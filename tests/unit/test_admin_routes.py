"""Unit tests: tenant admin and platform admin surfaces.

The platform routes are the only cross-tenant code in the product, so most of
this file is about who is refused. Hermetic — no emulators, no network.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from schema_validators import PlanTier, Tenant


def _dev_token(uid: str, tenant_id: str, role: str, email: str = "") -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


OWNER = {"Authorization": f"Bearer {_dev_token('owner-1', 'tenant-a', 'owner')}"}
REVIEWER = {"Authorization": f"Bearer {_dev_token('rev-1', 'tenant-a', 'reviewer')}"}
FOUNDER = {"Authorization": f"Bearer {_dev_token('founder-uid', 'tenant-a', 'owner')}"}


def _tenant(tid: str, name: str) -> Tenant:
    return Tenant(
        tenant_id=tid,
        name=name,
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier=PlanTier.FREE,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


class FakeRepo:
    def __init__(self):
        self.tenants = {
            "tenant-a": _tenant("tenant-a", "Fernbank Care"),
            "tenant-b": _tenant("tenant-b", "Other Business"),
        }

    def get_tenant(self, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError

        if tenant_id not in self.tenants:
            raise NotFoundError(tenant_id)
        return self.tenants[tenant_id]

    def list_all_tenants(self, limit=1000):
        return list(self.tenants.values())[:limit]

    def list_documents(self, tenant_id, limit=50):
        return []

    def list_users(self, tenant_id, limit=100):
        return []

    def list_api_keys(self, tenant_id, limit=100):
        return []

    def list_escalated_checks(self, tenant_id, limit=200):
        return []


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class _EmptyFirestore:
    def collection(self, name):
        return self

    def where(self, *a, **k):
        return self

    def stream(self):
        return iter([])


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.db = _EmptyFirestore()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    # Only this uid is a platform admin. Everyone else must be refused.
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "founder-uid")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app), fake


class TestRoutesAreActuallyMounted:
    """Behavioural, not introspective: FastAPI hides included routes from
    app.routes behind a wrapper object, so checking .path proves nothing."""

    def test_tenant_admin_route_exists(self, client):
        c, _ = client
        assert c.get("/api/admin/overview", headers=OWNER).status_code == 200

    def test_platform_route_exists(self, client):
        c, _ = client
        assert c.get("/api/platform/whoami", headers=FOUNDER).status_code == 200


class TestTenantAdminOverview:
    def test_requires_authentication(self, client):
        c, _ = client
        assert c.get("/api/admin/overview").status_code == 401

    def test_reviewer_is_refused(self, client):
        c, _ = client
        assert c.get("/api/admin/overview", headers=REVIEWER).status_code == 403

    def test_owner_sees_own_workspace_only(self, client):
        c, _ = client
        r = c.get("/api/admin/overview", headers=OWNER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenant_id"] == "tenant-a"
        assert body["name"] == "Fernbank Care"
        # Nothing from the other tenant leaks into a tenant-scoped view.
        assert "tenant-b" not in json.dumps(body)
        assert "Other Business" not in json.dumps(body)


class TestPlatformAdminAccess:
    """The allowlist is the whole security boundary — test it from every angle."""

    PLATFORM_ROUTES = [
        "/api/platform/overview",
        "/api/platform/audit",
        "/api/platform/whoami",
    ]

    @pytest.mark.parametrize("path", PLATFORM_ROUTES)
    def test_unauthenticated_refused(self, client, path):
        c, _ = client
        assert c.get(path).status_code == 401

    @pytest.mark.parametrize("path", PLATFORM_ROUTES)
    def test_ordinary_owner_refused(self, client, path):
        """A tenant owner is not a platform admin, however senior in their org."""
        c, _ = client
        r = c.get(path, headers=OWNER)
        # 404, not 403: a 403 confirms the route exists to anyone probing.
        assert r.status_code == 404, f"{path} leaked to a non-admin: {r.status_code}"

    @pytest.mark.parametrize("path", PLATFORM_ROUTES)
    def test_reviewer_refused(self, client, path):
        c, _ = client
        assert c.get(path, headers=REVIEWER).status_code == 404

    def test_admin_role_does_not_grant_platform_access(self, client):
        """'admin' is a tenant role and must not imply platform access."""
        c, _ = client
        hdr = {"Authorization": f"Bearer {_dev_token('someone', 'tenant-a', 'admin')}"}
        assert c.get("/api/platform/overview", headers=hdr).status_code == 404

    def test_allowlisted_uid_is_admitted(self, client):
        c, _ = client
        r = c.get("/api/platform/whoami", headers=FOUNDER)
        assert r.status_code == 200
        assert r.json()["platform_admin"] is True

    def test_empty_allowlist_admits_nobody(self, client, monkeypatch):
        """Unset must mean nobody, never everybody."""
        monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "")
        c, _ = client
        assert c.get("/api/platform/whoami", headers=FOUNDER).status_code == 404

    def test_email_allowlisting_works(self, client, monkeypatch):
        monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "boss@example.com")
        c, _ = client
        hdr = {
            "Authorization": f"Bearer {_dev_token('any-uid', 'tenant-a', 'owner', 'boss@example.com')}"
        }
        assert c.get("/api/platform/whoami", headers=hdr).status_code == 200

    def test_allowlist_match_is_case_insensitive(self, client, monkeypatch):
        monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", "BOSS@Example.COM")
        c, _ = client
        hdr = {
            "Authorization": f"Bearer {_dev_token('u', 'tenant-a', 'owner', 'boss@example.com')}"
        }
        assert c.get("/api/platform/whoami", headers=hdr).status_code == 200


class TestPlatformOverviewData:
    def test_aggregates_across_every_tenant(self, client):
        c, _ = client
        r = c.get("/api/platform/overview", headers=FOUNDER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenants_total"] == 2
        names = {t["name"] for t in body["tenants"]}
        assert names == {"Fernbank Care", "Other Business"}

    def test_cross_tenant_read_is_audited(self, client):
        """The operator's own access is accountable too."""
        c, fake = client
        c.get("/api/platform/overview", headers=FOUNDER)
        actions = [e["action"] for e in fake.auditor.events]
        assert "platform.overview_viewed" in actions
        event = next(e for e in fake.auditor.events if e["action"] == "platform.overview_viewed")
        assert event["actor"] == "founder-uid"

    def test_refused_access_writes_no_audit_event(self, client):
        """A rejected probe must not be able to spam the audit trail."""
        c, fake = client
        c.get("/api/platform/overview", headers=OWNER)
        assert fake.auditor.events == []

    def test_limit_is_bounded(self, client):
        c, _ = client
        assert c.get("/api/platform/overview?limit=9999", headers=FOUNDER).status_code == 422
        assert c.get("/api/platform/overview?limit=0", headers=FOUNDER).status_code == 422

    def test_no_write_methods_exist(self, client):
        """The platform surface is read-only by construction."""
        c, _ = client
        for method in ("post", "put", "patch", "delete"):
            r = getattr(c, method)("/api/platform/overview", headers=FOUNDER)
            assert r.status_code in (404, 405), f"{method.upper()} unexpectedly allowed"
