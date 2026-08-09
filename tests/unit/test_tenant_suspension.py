"""Unit tests: suspending and restoring a workspace's access.

This is the only cross-tenant write in the product, so the properties that
matter are the ones that would be argued about afterwards: that a customer
cannot reach it, that a reason is mandatory and recorded against the operator
who acted, that suspension actually stops requests whichever credential they
carry, and — most importantly — that it touches access and never records.

A console able to rewrite compliance history would be a liability in a
product whose entire claim is that history cannot be rewritten. These tests
are what keep that line where it is.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import PlanTier, Tenant, TenantStatus

ADMIN_EMAIL = "operator@example.com"
REASON = "Payment failed on three consecutive attempts."


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


def _admin() -> dict:
    return _hdr(uid="admin", email=ADMIN_EMAIL)


class FakeRepo:
    def __init__(self, *tenants: Tenant):
        self.tenants = {t.tenant_id: t for t in tenants}
        self.writes = 0

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant
        self.writes += 1


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeGateway:
    def __init__(self, *tenants: Tenant):
        self.repo = FakeRepo(*tenants)
        self.auditor = FakeAuditor()


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
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", ADMIN_EMAIL)
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway(tenant)
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)

    # No TTL cache in tests: a suspension must be observable on the very next
    # request, otherwise these assertions would pass for the wrong reason.
    def resolve(tenant_id: str) -> str:
        t = fake.repo.tenants.get(tenant_id)
        if t is None or t.status is not TenantStatus.SUSPENDED:
            return ""
        return t.status_reason or "Contact support."

    auth_middleware.set_tenant_status_resolver(resolve)
    yield TestClient(main.app, raise_server_exceptions=False), fake
    auth_middleware.set_tenant_status_resolver(None)


URL = "/api/platform/tenants/tenant-a/status"
SUSPEND = {"status": "suspended", "reason": REASON}


class TestAccessControl:
    def test_customer_gets_404_not_403(self, client):
        """404 so the route's existence is not confirmed to a prober."""
        c, g = client
        r = c.put(URL, json=SUSPEND, headers=_hdr())
        assert r.status_code == 404
        assert g.repo.tenants["tenant-a"].status is TenantStatus.ACTIVE

    def test_owner_role_does_not_grant_it(self, client):
        """Roles are minted by tenant owners, so they must not open this."""
        c, _ = client
        r = c.put(URL, json=SUSPEND, headers=_hdr(role="owner", email="attacker@example.com"))
        assert r.status_code == 404

    def test_requires_auth(self, client):
        c, _ = client
        assert c.put(URL, json=SUSPEND).status_code == 401


class TestReasonIsMandatory:
    def test_missing_reason_is_rejected(self, client):
        c, g = client
        r = c.put(URL, json={"status": "suspended"}, headers=_admin())
        assert r.status_code == 422
        assert g.repo.writes == 0

    def test_token_reason_is_rejected(self, client):
        """'policy' is not a reason a customer can act on."""
        c, _ = client
        r = c.put(URL, json={"status": "suspended", "reason": "policy"}, headers=_admin())
        assert r.status_code == 422

    def test_unknown_status_is_rejected(self, client):
        c, _ = client
        r = c.put(URL, json={"status": "deleted", "reason": REASON}, headers=_admin())
        assert r.status_code == 422


class TestSuspension:
    def test_suspends_and_records_the_operator(self, client):
        c, g = client
        r = c.put(URL, json=SUSPEND, headers=_admin())
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
        assert g.repo.tenants["tenant-a"].status is TenantStatus.SUSPENDED

        event = g.auditor.events[-1]
        assert event["action"] == "tenant.suspended"
        assert ADMIN_EMAIL in event["actor"]
        assert event["before_state"] == {"status": "active"}
        assert event["after_state"]["reason"] == REASON

    def test_suspended_workspace_is_refused(self, client):
        """The point of the whole feature."""
        c, _ = client
        assert c.get("/api/team", headers=_hdr()).status_code != 403
        c.put(URL, json=SUSPEND, headers=_admin())
        r = c.get("/api/team", headers=_hdr())
        assert r.status_code == 403
        assert "suspended" in r.json()["detail"].lower()

    def test_the_reason_reaches_the_customer(self, client):
        """A blocked user needs to know what to do, not just that they are blocked."""
        c, _ = client
        c.put(URL, json=SUSPEND, headers=_admin())
        assert REASON in c.get("/api/team", headers=_hdr()).json()["detail"]

    def test_reactivation_restores_access_and_clears_the_reason(self, client):
        c, g = client
        c.put(URL, json=SUSPEND, headers=_admin())
        r = c.put(URL, json={"status": "active", "reason": "Payment received and cleared."},
                  headers=_admin())
        assert r.status_code == 200
        assert g.repo.tenants["tenant-a"].status is TenantStatus.ACTIVE
        assert g.repo.tenants["tenant-a"].status_reason == ""
        assert c.get("/api/team", headers=_hdr()).status_code != 403
        assert g.auditor.events[-1]["action"] == "tenant.reactivated"

    def test_repeating_the_current_status_is_not_recorded_as_a_change(self, client):
        """An audit entry claiming a change that did not happen is a false record."""
        c, g = client
        r = c.put(URL, json={"status": "active", "reason": "Confirming nothing changed."},
                  headers=_admin())
        assert r.status_code == 200
        assert r.json()["changed"] is False
        assert g.auditor.events == []
        assert g.repo.writes == 0

    def test_suspending_twice_records_two_distinct_events(self, client):
        c, g = client
        c.put(URL, json=SUSPEND, headers=_admin())
        c.put(URL, json={"status": "active", "reason": "Restored after review."}, headers=_admin())
        c.put(URL, json=SUSPEND, headers=_admin())
        actions = [e["action"] for e in g.auditor.events]
        assert actions == ["tenant.suspended", "tenant.reactivated", "tenant.suspended"]
        # Distinct dedup keys, or the second suspension would collapse away.
        assert len({e["dedup_key"] for e in g.auditor.events}) == 3


class TestItTouchesAccessNeverRecords:
    """The line this feature is not allowed to cross."""

    def test_no_document_check_or_audit_field_is_writable(self, client, tenant):
        c, g = client
        before = tenant.model_dump()
        c.put(URL, json=SUSPEND, headers=_admin())
        after = g.repo.tenants["tenant-a"].model_dump()

        changed = {k for k in after if before.get(k) != after.get(k)}
        # Access fields only. Anything else appearing here means the write
        # widened beyond what it is permitted to touch.
        assert changed == {"status", "status_reason"}

    def test_suspension_appends_to_the_trail_rather_than_editing_it(self, client):
        c, g = client
        c.put(URL, json=SUSPEND, headers=_admin())
        c.put(URL, json={"status": "active", "reason": "Restored after review."}, headers=_admin())
        # Both events survive; the trail only ever grows.
        assert len(g.auditor.events) == 2
        assert g.auditor.events[0]["action"] == "tenant.suspended"


class TestFailureModes:
    def test_a_datastore_error_does_not_lock_everyone_out(self, monkeypatch, client):
        """Failing closed here would take the product down for every customer."""
        c, _ = client
        import auth_middleware

        def boom(_tenant_id: str) -> str:
            raise RuntimeError("firestore unavailable")

        auth_middleware.set_tenant_status_resolver(boom)
        assert c.get("/api/team", headers=_hdr()).status_code != 403

    def test_no_resolver_configured_means_nobody_is_suspended(self, monkeypatch, client):
        c, _ = client
        import auth_middleware

        auth_middleware.set_tenant_status_resolver(None)
        assert c.get("/api/team", headers=_hdr()).status_code != 403


class TestOperatorCannotLockThemselvesOut:
    """Found by the tests above before it ever shipped.

    require_platform_admin originally depended on require_auth, so it
    inherited the suspension check. An operator is normally a member of some
    workspace — suspending that one locked them out of the console that
    suspends, with no route back in. Platform administration is orthogonal to
    membership of any single workspace.
    """

    def test_admin_keeps_console_access_after_suspending_their_own_workspace(self, client):
        c, g = client
        # The operator here belongs to tenant-a, the workspace being suspended.
        assert c.put(URL, json=SUSPEND, headers=_admin()).status_code == 200
        assert g.repo.tenants["tenant-a"].status is TenantStatus.SUSPENDED

        # Still able to read the console...
        assert c.get("/api/platform/whoami", headers=_admin()).status_code == 200
        # ...and, critically, able to undo it.
        r = c.put(URL, json={"status": "active", "reason": "Reversing the suspension."},
                  headers=_admin())
        assert r.status_code == 200
        assert g.repo.tenants["tenant-a"].status is TenantStatus.ACTIVE

    def test_but_their_customer_facing_access_is_still_suspended(self, client):
        """Console access is exempt. Product access is not — no back door."""
        c, _ = client
        c.put(URL, json=SUSPEND, headers=_admin())
        assert c.get("/api/team", headers=_admin()).status_code == 403
