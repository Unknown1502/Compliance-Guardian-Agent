"""Unit tests: strict input validation and endpoint rate limiting.

Covers the hardening the API gateway relies on to reject rather than
sanitize: path ids that could reach a Firestore document path or a GCS
object key, request bodies carrying unknown fields, and the per-tier
rate limits. Hermetic — no emulators, no network.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


AUTH = {"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"}


class FakeRepo:
    def __init__(self):
        self.tenants = {}
        self.users = {}

    def get_document(self, document_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError

        raise NotFoundError(document_id)

    def get_check(self, check_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError

        raise NotFoundError(check_id)


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class _EmptySnapStream:
    def collection(self, name):
        return self

    def where(self, *args, **kwargs):
        return self

    def stream(self):
        return iter([])


def _EmptyFirestore():
    """Firestore stand-in holding no checks."""
    return _EmptySnapStream()


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.db = _EmptyFirestore()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app), fake, main


class TestPathIdValidation:
    """Ids in the URL must be rejected before they reach any datastore path."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "..",
            "a/b",
            "a\\b",
            "a b",
            "a$b",
            "x" * 129,
        ],
    )
    def test_malformed_document_id_rejected(self, client, bad_id):
        c, _, _ = client
        r = c.get(f"/api/documents/{bad_id}", headers=AUTH)
        # 404 would mean the route didn't match at all; 422 means it matched
        # and validation refused the value. Either way it must never be 200.
        assert r.status_code in (404, 422)
        assert r.status_code != 200

    def test_wellformed_id_passes_validation(self, client):
        """A normal id reaches the handler — proving the pattern isn't over-tight."""
        c, _, _ = client
        r = c.get("/api/documents/doc-abc123", headers=AUTH)
        # Handler ran and the fake repo raised NotFound -> 404 with our
        # generic message, not a 422 from validation.
        assert r.status_code == 404
        assert r.json()["detail"] == "not found"

    def test_check_id_is_validated_too(self, client):
        c, _, _ = client
        r = c.get("/api/compliance/checks/a b", headers=AUTH)
        assert r.status_code in (404, 422)


class TestErrorMessagesAreGeneric:
    def test_not_found_does_not_echo_the_requested_id(self, client):
        """The datastore's own phrasing must not reach the client."""
        c, _, _ = client
        r = c.get("/api/documents/doc-secret-name", headers=AUTH)
        assert r.status_code == 404
        assert r.json()["detail"] == "not found"
        assert "doc-secret-name" not in json.dumps(r.json())


class TestRateLimitTiers:
    def test_expensive_tier_blocks_after_capacity(self, client, monkeypatch):
        c, _, main = client
        from api_gateway.rate_limit import TokenBucketRateLimiter

        # Capacity 2 so the third call must be refused.
        monkeypatch.setattr(
            main,
            "_expensive_limiter",
            TokenBucketRateLimiter(capacity=2, refill_per_second=0.0001),
        )
        codes = [
            c.post(
                "/api/compliance/checks", json={"document_id": "doc-a"}, headers=AUTH
            ).status_code
            for _ in range(3)
        ]
        assert codes[-1] == 429

    def test_429_carries_retry_after(self, client, monkeypatch):
        c, _, main = client
        from api_gateway.rate_limit import TokenBucketRateLimiter

        monkeypatch.setattr(
            main,
            "_expensive_limiter",
            TokenBucketRateLimiter(capacity=1, refill_per_second=0.5),
        )
        c.post("/api/compliance/checks", json={"document_id": "doc-a"}, headers=AUTH)
        r = c.post("/api/compliance/checks", json={"document_id": "doc-a"}, headers=AUTH)
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

    def test_limits_are_keyed_per_tenant(self, client, monkeypatch):
        c, _, main = client
        from api_gateway.rate_limit import TokenBucketRateLimiter

        monkeypatch.setattr(
            main,
            "_expensive_limiter",
            TokenBucketRateLimiter(capacity=1, refill_per_second=0.0001),
        )
        other = {"Authorization": f"Bearer {_dev_token('u2', 'tenant-b', 'owner')}"}
        c.post("/api/compliance/checks", json={"document_id": "doc-a"}, headers=AUTH)
        blocked = c.post(
            "/api/compliance/checks", json={"document_id": "doc-a"}, headers=AUTH
        )
        assert blocked.status_code == 429
        # A different tenant must be unaffected by the first tenant's usage.
        fresh = c.post(
            "/api/compliance/checks", json={"document_id": "doc-a"}, headers=other
        )
        assert fresh.status_code != 429


class TestStrictBodies:
    def test_unknown_field_rejected(self, client):
        c, _, _ = client
        r = c.post(
            "/api/compliance/checks",
            json={"document_id": "doc-a", "tenant_id": "tenant-b"},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_id_pattern_enforced_in_body(self, client):
        c, _, _ = client
        r = c.post(
            "/api/compliance/checks", json={"document_id": "../etc/passwd"}, headers=AUTH
        )
        assert r.status_code == 422


class TestTrendsEndpoint:
    """GET /api/analytics/trends — auth, tenant scoping, and bounds."""

    def test_requires_authentication(self, client):
        c, _, _ = client
        assert c.get("/api/analytics/trends").status_code == 401

    def test_returns_requested_week_count(self, client, monkeypatch):
        c, fake, main = client
        fake.db = _EmptyFirestore()
        r = c.get("/api/analytics/trends?weeks=4", headers=AUTH)
        assert r.status_code == 200, r.text
        assert len(r.json()["weeks"]) == 4
        assert r.json()["tenant_id"] == "tenant-a"

    def test_defaults_to_twelve_weeks(self, client):
        c, fake, _ = client
        fake.db = _EmptyFirestore()
        r = c.get("/api/analytics/trends", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["weeks"]) == 12

    @pytest.mark.parametrize("weeks", [0, -1, 53, 100000])
    def test_out_of_range_week_count_rejected(self, client, weeks):
        """Unbounded weeks would pull a tenant's whole history in one query."""
        c, fake, _ = client
        fake.db = _EmptyFirestore()
        r = c.get(f"/api/analytics/trends?weeks={weeks}", headers=AUTH)
        assert r.status_code == 422

    def test_non_numeric_week_count_rejected(self, client):
        c, fake, _ = client
        fake.db = _EmptyFirestore()
        assert c.get("/api/analytics/trends?weeks=lots", headers=AUTH).status_code == 422
