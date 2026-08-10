"""Unit tests: what an API key may and may not do.

API keys authenticated as `owner` until this was found. That gave a key
created for a CI pipeline the ability to change the workspace's jurisdiction,
add and remove team members, alter retention, and — worst — mint further API
keys, so revoking a leaked key would not end the compromise.

Keys sit in CI config and env files and leak far more readily than passwords,
so the boundary is asserted here rather than left to a code comment.

Two properties:
  * A key CAN do the work it exists for: upload, check, read results.
  * A key CANNOT manage the workspace or decide an escalation. Management is a
    human action, and approving a compliance escalation is a human judgement —
    the product's human-review guarantee is worth nothing if a machine
    credential satisfies it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auth_middleware import SERVICE_ROLE, AuthContext, VALID_ROLES
from schema_validators import PlanTier, Tenant

KEY = "cg_live_testkey_0123456789abcdef"


class FakeRepo:
    def __init__(self, tenant: Tenant):
        self.tenants = {tenant.tenant_id: tenant}

    def get_tenant(self, tenant_id):
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant):
        self.tenants[tenant.tenant_id] = tenant

    def list_users(self, tenant_id, limit=100):
        return []

    def list_api_keys(self, tenant_id, limit=200):
        return []


class FakeGateway:
    def __init__(self, tenant: Tenant):
        self.repo = FakeRepo(tenant)
        self.auditor = type("A", (), {"log": lambda self, **kw: kw})()


@pytest.fixture()
def tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        name="Fernbank Verify",
        industry="data_privacy",
        jurisdiction="in",
        plan_tier=PlanTier.PRO,
    )


@pytest.fixture()
def client(monkeypatch, tenant):
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    auth_middleware.set_tenant_status_resolver(None)

    # Stand in for the real resolver, returning the same identity it does.
    auth_middleware.set_api_key_resolver(
        lambda presented: (
            AuthContext(
                uid="api_key:k1", tenant_id="tenant-a", role=SERVICE_ROLE, email=None
            )
            if presented == KEY
            else None
        )
    )
    fake = FakeGateway(tenant)
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    yield TestClient(main.app, raise_server_exceptions=False), fake
    auth_middleware.set_api_key_resolver(None)


HDR = {"X-API-Key": KEY}


class TestTheIdentityItself:
    def test_service_is_not_a_role_a_person_can_be_given(self):
        """It must not be assignable via POST /api/team."""
        assert SERVICE_ROLE not in VALID_ROLES

    def test_an_unknown_key_is_refused(self, client):
        c, _ = client
        r = c.get("/api/team", headers={"X-API-Key": "cg_live_wrong_key_value_here"})
        assert r.status_code == 401


class TestWhatAKeyCanDo:
    def test_it_can_read_within_its_own_workspace(self, client):
        """The work keys exist for still has to function."""
        c, _ = client
        assert c.get("/api/team", headers=HDR).status_code == 200

    def test_it_can_read_the_entitlement(self, client):
        c, _ = client
        assert c.get("/api/entitlement", headers=HDR).status_code == 200


class TestWhatAKeyCannotDo:
    """Management is a human action. A leaked key must not be able to do it."""

    def test_it_cannot_invite_a_team_member(self, client):
        c, _ = client
        r = c.post(
            "/api/team", json={"email": "x@example.com", "role": "admin"}, headers=HDR
        )
        assert r.status_code == 403
        assert "API keys cannot" in r.json()["detail"]

    def test_it_cannot_change_the_jurisdiction(self, client):
        """This decides which law every future check is judged against."""
        c, g = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "data_privacy", "jurisdiction": "eu"},
            headers=HDR,
        )
        assert r.status_code == 403
        assert g.repo.tenants["tenant-a"].jurisdiction == "in"

    def test_it_cannot_mint_another_api_key(self, client):
        """The one that turns a leak into persistence."""
        c, _ = client
        r = c.post("/api/keys", json={"name": "second key"}, headers=HDR)
        assert r.status_code == 403

    def test_it_cannot_change_retention(self, client):
        c, _ = client
        r = c.put("/api/settings/retention", json={"retention_days": 0}, headers=HDR)
        assert r.status_code == 403

    def test_the_refusal_explains_what_to_do_instead(self, client):
        c, _ = client
        detail = c.post(
            "/api/team", json={"email": "x@example.com", "role": "admin"}, headers=HDR
        ).json()["detail"]
        assert "Sign in as a person" in detail


class TestPeopleAreUnaffected:
    def test_an_owner_can_still_manage_the_workspace(self, client, monkeypatch):
        """The fix must not break the humans it is protecting."""
        import base64
        import json

        monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
        c, g = client
        claims = {"uid": "u1", "tenant_id": "tenant-a", "role": "owner"}
        raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "data_privacy", "jurisdiction": "eu"},
            headers={"Authorization": f"Bearer dev:{raw}"},
        )
        assert r.status_code == 200
        assert g.repo.tenants["tenant-a"].jurisdiction == "eu"
