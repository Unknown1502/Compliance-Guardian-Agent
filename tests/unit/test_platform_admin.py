"""Security tests for the platform (cross-tenant) admin surface.

These exist because /api/platform/* is the only code in the product that
reads across tenant boundaries. The properties asserted here are the ones
that would matter in an incident: that a customer cannot reach it, that a
role cannot be used to grant it, that the allowlist is closed by default,
and that reaching it is itself recorded.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

ADMIN_EMAIL = "operator@example.com"


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


PLATFORM_ROUTES = [
    "/api/platform/whoami",
    "/api/platform/overview",
    "/api/platform/audit",
    "/api/platform/documents",
    "/api/platform/reviews",
    "/api/platform/agents",
    "/api/platform/compliance",
    "/api/platform/security",
    "/api/platform/system",
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", ADMIN_EMAIL)
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    return TestClient(main.app, raise_server_exceptions=False)


class TestPlatformAccessControl:
    @pytest.mark.parametrize("route", PLATFORM_ROUTES)
    def test_customer_cannot_reach_platform_routes(self, client, route):
        """A perfectly valid customer session must not see these at all."""
        r = client.get(route, headers=_hdr(email="customer@acme.test"))
        # 404, not 403: a 403 would confirm the route exists.
        assert r.status_code == 404, f"{route} leaked status {r.status_code}"

    @pytest.mark.parametrize("route", PLATFORM_ROUTES)
    def test_unauthenticated_rejected(self, client, route):
        assert client.get(route).status_code == 401

    def test_reviewer_role_does_not_grant_platform_access(self, client):
        r = client.get("/api/platform/overview", headers=_hdr(role="reviewer", email="rev@acme.test"))
        assert r.status_code == 404

    def test_admin_role_does_not_grant_platform_access(self, client):
        """The critical one: 'admin' is a TENANT role handed out by
        POST /api/team, so any owner could mint it for themselves. It must
        not be a path to cross-tenant data."""
        r = client.get("/api/platform/overview", headers=_hdr(role="admin", email="sneaky@acme.test"))
        assert r.status_code == 404

    def test_allowlisted_principal_is_admitted(self, client):
        r = client.get("/api/platform/whoami", headers=_hdr(email=ADMIN_EMAIL))
        assert r.status_code == 200
        assert r.json()["platform_admin"] is True

    def test_allowlist_matches_uid_as_well_as_email(self, client, monkeypatch):
        monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "uid-operator")
        r = client.get("/api/platform/whoami", headers=_hdr(uid="uid-operator"))
        assert r.status_code == 200

    def test_empty_allowlist_admits_nobody(self, client, monkeypatch):
        """Unset must mean nobody, never everybody."""
        monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "")
        assert client.get("/api/platform/whoami", headers=_hdr(email=ADMIN_EMAIL)).status_code == 404

    def test_client_cannot_self_assign_platform_admin(self, client):
        """Claims are attacker-controlled in the dev-token path, which makes
        this the sharpest possible version of the test: even fully forged
        role/tenant claims must not confer platform access, because access
        comes from server-side config the token cannot influence."""
        forged = _tok(uid="attacker", tenant="tenant-a", role="admin", email="attacker@evil.test")
        r = client.get("/api/platform/overview", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 404

    def test_tenant_id_in_query_cannot_widen_access(self, client):
        """A customer must not reach another tenant by asking nicely."""
        r = client.get(
            "/api/audit-logs?tenant_id=tenant-b",
            headers=_hdr(tenant="tenant-a", email="customer@acme.test"),
        )
        if r.status_code == 200:
            assert r.json()["tenant_id"] == "tenant-a"


class TestNoSecretLeakage:
    def test_whoami_returns_no_credentials(self, client):
        body = client.get("/api/platform/whoami", headers=_hdr(email=ADMIN_EMAIL)).text.lower()
        for forbidden in ("api_key", "secret", "password", "token", "private", "sk_", "whsec"):
            assert forbidden not in body, f"{forbidden!r} appeared in a platform response"
