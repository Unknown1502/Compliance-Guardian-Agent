"""Unit tests: API Gateway routes — RBAC, tenant scoping, decision conflict.

Uses the local dev-auth mode (CG_AUTH_DEV_MODE=1) with base64 claim tokens and a
FakeGateway injected in place of real GCP clients. No emulators, no network.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import CheckDecision, ComplianceCheck, Document, DocumentStatus


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeRepo:
    def __init__(self):
        self.tenants = {}
        self.docs = {
            "doc-a": Document(
                document_id="doc-a", tenant_id="tenant-a", source="upload",
                storage_ref="gs://b/doc-a/x.txt", extracted_fields={"k": "v"},
                status=DocumentStatus.PROCESSED,
            )
        }
        self.checks = {
            "check-a": ComplianceCheck(
                check_id="check-a", document_id="doc-a", tenant_id="tenant-a",
                rule_set_version="1.0.0", risk_score=85, justification="Needs review.",
                citations=["consent_documentation"], decision=CheckDecision.ESCALATED,
                reviewer_id=None,
            )
        }

    def get_document(self, document_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        d = self.docs.get(document_id)
        if d is None:
            raise NotFoundError(document_id)
        if d.tenant_id != tenant_id:
            raise TenantMismatchError(document_id)
        return d

    def get_check(self, check_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        c = self.checks.get(check_id)
        if c is None:
            raise NotFoundError(check_id)
        if c.tenant_id != tenant_id:
            raise TenantMismatchError(check_id)
        return c

    def apply_reviewer_decision(self, *, check_id, tenant_id, reviewer_id, decision):
        from gcp_clients.firestore_repo import DecisionConflictError

        c = self.get_check(check_id, tenant_id)
        if c.decision is not CheckDecision.ESCALATED or c.reviewer_id is not None:
            raise DecisionConflictError(check_id)
        updated = c.model_copy(update={"decision": decision, "reviewer_id": reviewer_id})
        self.checks[check_id] = updated
        return updated

    def upsert_tenant(self, tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app), fake


class TestAuthAndRbac:
    def test_unauthenticated_rejected(self, client):
        c, _ = client
        assert c.get("/api/documents/doc-a").status_code == 401

    def test_get_document_tenant_scoped(self, client):
        c, _ = client
        ok = c.get("/api/documents/doc-a", headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"})
        assert ok.status_code == 200
        assert ok.json()["document_id"] == "doc-a"

    def test_cross_tenant_document_is_404(self, client):
        c, _ = client
        r = c.get("/api/documents/doc-a", headers={"Authorization": f"Bearer {_dev_token('u2','tenant-b','owner')}"})
        assert r.status_code == 404  # not leaked as 403

    def test_owner_cannot_decide(self, client):
        c, _ = client
        r = c.patch(
            "/api/compliance/checks/check-a",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','owner')}"},
        )
        assert r.status_code == 403

    def test_reviewer_can_approve(self, client):
        c, fake = client
        r = c.patch(
            "/api/compliance/checks/check-a",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {_dev_token('rev1','tenant-a','reviewer')}"},
        )
        assert r.status_code == 200
        assert r.json()["decision"] == "auto_approved"
        assert r.json()["reviewer_id"] == "rev1"
        assert any(e["action"] == "check.approved" for e in fake.auditor.events)

    def test_second_reviewer_gets_409(self, client):
        c, _ = client
        hdr = {"Authorization": f"Bearer {_dev_token('rev1','tenant-a','reviewer')}"}
        assert c.patch("/api/compliance/checks/check-a", json={"action": "approve"}, headers=hdr).status_code == 200
        hdr2 = {"Authorization": f"Bearer {_dev_token('rev2','tenant-a','reviewer')}"}
        r = c.patch("/api/compliance/checks/check-a", json={"action": "reject"}, headers=hdr2)
        assert r.status_code == 409

    def test_reports_endpoint_requires_auth(self, client):
        """POST /api/reports is now live (Phase 4) and must require auth."""
        c, _ = client
        r = c.post("/api/reports", json={"period_start": "2026-06-01T00:00:00Z", "period_end": "2026-07-01T00:00:00Z"})
        assert r.status_code == 401


class TestSignup:
    """POST /api/signup — the only public write endpoint (it creates the tenant)."""

    def _payload(self, **overrides):
        payload = {
            "email": "owner@sunrisecare.example",
            "password": "correct-horse-battery-staple",
            "business_name": "Sunrise Community Care Pty Ltd",
            "industry": "healthcare_ndis",
            "jurisdiction": "AU",
        }
        payload.update(overrides)
        return payload

    def test_signup_creates_tenant_and_owner(self, client, monkeypatch):
        c, fake = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_owner", lambda **kw: "uid-new-owner")

        r = c.post("/api/signup", json=self._payload())
        assert r.status_code == 201
        body = r.json()
        assert body["uid"] == "uid-new-owner"
        assert body["tenant_id"].startswith("tenant-")
        assert body["tenant_id"] in fake.repo.tenants
        assert fake.repo.tenants[body["tenant_id"]].name == "Sunrise Community Care Pty Ltd"
        assert any(e["action"] == "tenant.signed_up" for e in fake.auditor.events)

    def test_signup_no_auth_required(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "create_tenant_owner", lambda **kw: "uid-x")
        r = c.post("/api/signup", json=self._payload())  # no Authorization header
        assert r.status_code == 201

    def test_signup_rejects_unknown_ruleset(self, client):
        c, _ = client
        r = c.post("/api/signup", json=self._payload(industry="astrology", jurisdiction="ZZ"))
        assert r.status_code == 400

    def test_signup_duplicate_email_is_409(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main
        from firebase_admin.auth import EmailAlreadyExistsError

        def _raise(**kw):
            raise EmailAlreadyExistsError("email already exists", None, None)

        monkeypatch.setattr(main, "create_tenant_owner", _raise)
        r = c.post("/api/signup", json=self._payload())
        assert r.status_code == 409

    def test_signup_short_password_rejected(self, client):
        c, _ = client
        r = c.post("/api/signup", json=self._payload(password="short"))
        assert r.status_code == 422  # pydantic min_length validation
