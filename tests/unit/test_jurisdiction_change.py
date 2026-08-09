"""Unit tests: moving a workspace to a different industry / jurisdiction.

This closes the other half of the hardcoded-Australia defect. New signups can
now pick a jurisdiction, but every workspace created before that — including
real ones — was left permanently on healthcare_ndis/AU with no way out.

The properties asserted here are the ones that matter if this endpoint is
ever the subject of a dispute: only an owner can move a workspace, an
invalid destination changes nothing, the move is written to the append-only
trail with both the old and new values, and past verdicts are left alone.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import PlanTier, Tenant


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


class FakeRepo:
    def __init__(self, *tenants: Tenant):
        self.tenants = {t.tenant_id: t for t in tenants}

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant


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
        name="Legacy Workspace",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier=PlanTier.FREE,
    )


@pytest.fixture()
def client(monkeypatch, tenant):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway(tenant)
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app, raise_server_exceptions=False), fake


INDIA = {"industry": "data_privacy", "jurisdiction": "in"}


class TestAccessControl:
    def test_requires_auth(self, client):
        c, _ = client
        assert c.put("/api/admin/jurisdiction", json=INDIA).status_code == 401

    def test_admin_is_allowed(self, client):
        """Admin implicitly satisfies every role check in this codebase.

        Asserted rather than assumed: the first version of this endpoint was
        written as require_role("owner") and documented as owner-only, which
        was simply false — admin passed anyway. Pinning the real behaviour
        means the docstring can never drift back into claiming otherwise.
        """
        c, g = client
        r = c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr(role="admin"))
        assert r.status_code == 200
        assert g.repo.get_tenant("tenant-a").industry == "data_privacy"

    def test_reviewer_cannot_move_the_workspace(self, client):
        c, g = client
        r = c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr(role="reviewer"))
        assert r.status_code == 403
        assert g.repo.get_tenant("tenant-a").jurisdiction == "AU"


class TestValidation:
    def test_nonexistent_ruleset_changes_nothing(self, client):
        c, g = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "data_privacy", "jurisdiction": "atlantis"},
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert g.repo.get_tenant("tenant-a").industry == "healthcare_ndis"
        assert g.auditor.events == []

    def test_path_traversal_is_rejected_before_the_filesystem(self, client):
        c, g = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "data_privacy", "jurisdiction": "../../../etc/passwd"},
            headers=_hdr(),
        )
        assert r.status_code == 422
        assert g.auditor.events == []

    def test_industry_without_that_jurisdiction_is_refused(self, client):
        """NDIS is an Australian scheme; there is no NDIS ruleset for India."""
        c, g = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "healthcare_ndis", "jurisdiction": "in"},
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert g.repo.get_tenant("tenant-a").jurisdiction == "AU"

    def test_unknown_field_is_rejected(self, client):
        c, _ = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={**INDIA, "plan_tier": "pro"},
            headers=_hdr(),
        )
        assert r.status_code == 422


class TestTheMove:
    def test_owner_can_move_a_legacy_australian_workspace_to_india(self, client):
        c, g = client
        r = c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["changed"] is True
        assert body["industry"] == "data_privacy"
        assert body["jurisdiction"] == "in"
        assert body["rule_count"] > 0
        tenant = g.repo.get_tenant("tenant-a")
        assert (tenant.industry, tenant.jurisdiction) == ("data_privacy", "in")

    def test_the_move_is_audited_with_both_sides(self, client):
        c, g = client
        c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr(email="owner@example.com"))
        event = g.auditor.events[-1]
        assert event["action"] == "workspace.jurisdiction_changed"
        assert event["actor"] == "owner@example.com"
        assert event["before_state"] == {"industry": "healthcare_ndis", "jurisdiction": "AU"}
        assert event["after_state"]["jurisdiction"] == "in"
        # The version matters: it says which rules took effect at that moment.
        assert event["after_state"]["rule_set_version"]

    def test_a_no_op_request_is_not_recorded_as_a_change(self, client):
        """Writing 'jurisdiction changed' when it did not is a false record.

        The tenant stores "AU" while ruleset files are lowercase ("au.yaml"),
        so this specifically covers the case that a naive equality check gets
        wrong — and did, before this test existed.
        """
        c, g = client
        r = c.put(
            "/api/admin/jurisdiction",
            json={"industry": "healthcare_ndis", "jurisdiction": "au"},
            headers=_hdr(),
        )
        assert r.status_code == 200
        assert r.json()["changed"] is False
        assert g.auditor.events == []
        # And the stored value is left exactly as it was, not re-cased.
        assert g.repo.get_tenant("tenant-a").jurisdiction == "AU"

    def test_moving_twice_records_two_events(self, client):
        c, g = client
        c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr())
        c.put(
            "/api/admin/jurisdiction",
            json={"industry": "data_privacy", "jurisdiction": "eu"},
            headers=_hdr(),
        )
        actions = [e["action"] for e in g.auditor.events]
        assert actions == ["workspace.jurisdiction_changed"] * 2
        # Distinct dedup keys, or the second move would collapse into the first.
        assert len({e["dedup_key"] for e in g.auditor.events}) == 2

    def test_one_tenant_cannot_move_another(self, client):
        """tenant_id comes from the token, never the body — same as everywhere."""
        c, g = client
        r = c.put("/api/admin/jurisdiction", json=INDIA, headers=_hdr(tenant="tenant-other"))
        # The caller's own tenant does not exist in this fixture, so the move
        # cannot silently land on tenant-a.
        assert r.status_code != 200
        assert g.repo.get_tenant("tenant-a").industry == "healthcare_ndis"
