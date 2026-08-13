"""The product guarantee: ComplianceGuardian controls ACCESS, never RECORDS.

Suspension is the one write on the operator console, so it is the one place
that guarantee can be broken. The test is a before/after snapshot: suspend a
tenant, then compare every compliance record byte for byte.

A compliance product whose operator console can quietly edit a customer's
history has nothing to sell. This is the regression test for that claim, and
it is deliberately blunt — it compares whole records rather than named fields,
so a future change that starts touching evidence fails here even if nobody
thought to update the assertion.
"""

from __future__ import annotations

import base64
import copy
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import (
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    GeminiCallMetadata,
    ScanStatus,
    Tenant,
    TenantStatus,
)

OPERATOR = "operator@example.com"
TENANT = "tenant-a"


def _hdr(email=OPERATOR, uid="op1", tenant="tenant-ops", role="owner") -> dict:
    claims = {"uid": uid, "tenant_id": tenant, "role": role, "email": email}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer dev:{raw}"}


def _tenant(status=TenantStatus.ACTIVE) -> Tenant:
    return Tenant(
        tenant_id=TENANT,
        name="Sunrise Community Care",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier="starter",
        status=status,
    )


def _document() -> Document:
    return Document(
        document_id="doc-1",
        tenant_id=TENANT,
        source="upload",
        storage_ref="gs://raw/tenant-a/doc-1/record.txt",
        status=DocumentStatus.PROCESSED,
        scan_status=ScanStatus.CLEAN,
        content_hash="a" * 64,
        extracted_fields={"participant": "R. Okafor"},
    )


def _check() -> ComplianceCheck:
    return ComplianceCheck(
        check_id="chk-1",
        document_id="doc-1",
        tenant_id=TENANT,
        rule_set_version="1.1.0",
        risk_score=72,
        justification="Incident lodged outside the 24-hour window.",
        citations=["NDIS Practice Standards — incident management"],
        decision=CheckDecision.ESCALATED,
        rule_verdicts=[],
        gemini_metadata=GeminiCallMetadata(
            prompt_version="compliance_v1", model_name="gemini-3.1-flash-lite", model_version="001"
        ),
    )


class Repo:
    """Records live here. Any mutation by the console shows up in the snapshot."""

    def __init__(self):
        self.tenant = _tenant()
        self.documents = {"doc-1": _document()}
        self.checks = {"chk-1": _check()}

    def get_tenant(self, tenant_id):
        return self.tenant

    def upsert_tenant(self, tenant):
        self.tenant = tenant

    def snapshot(self) -> dict:
        return {
            "documents": {k: v.model_dump(mode="json") for k, v in self.documents.items()},
            "checks": {k: v.model_dump(mode="json") for k, v in self.checks.items()},
        }


class Auditor:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)
        return kw


class Gateway:
    def __init__(self):
        self.repo = Repo()
        self.auditor = Auditor()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", OPERATOR)
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = Gateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app, raise_server_exceptions=False), fake


def _set_status(c, status, reason="Non-payment: invoice 41 overdue."):
    return c.put(
        f"/api/platform/tenants/{TENANT}/status",
        headers=_hdr(),
        json={"status": status, "reason": reason},
    )


class TestSuspensionChangesAccess:
    def test_the_tenant_becomes_suspended(self, client):
        c, fake = client
        assert _set_status(c, "suspended").status_code == 200
        assert fake.repo.tenant.status is TenantStatus.SUSPENDED

    def test_a_reason_is_recorded_for_the_customer(self, client):
        c, fake = client
        _set_status(c, "suspended", reason="Non-payment: invoice 41 overdue.")
        assert "invoice 41" in fake.repo.tenant.status_reason

    def test_suspension_is_audited_with_the_operator_identity(self, client):
        c, fake = client
        _set_status(c, "suspended")
        assert fake.auditor.events, "suspending a workspace must not be possible quietly"
        assert OPERATOR in str(fake.auditor.events[0].get("actor", ""))

    def test_restoring_clears_the_reason(self, client):
        c, fake = client
        _set_status(c, "suspended")
        _set_status(c, "active", reason="Payment received, reinstated.")
        assert fake.repo.tenant.status is TenantStatus.ACTIVE
        assert fake.repo.tenant.status_reason == ""


class TestRecordsAreNeverTouched:
    """The invariant. Whole-record comparison, not per-field."""

    def test_suspension_does_not_alter_any_record(self, client):
        c, fake = client
        before = copy.deepcopy(fake.repo.snapshot())
        _set_status(c, "suspended")
        assert fake.repo.snapshot() == before

    def test_restoration_does_not_alter_any_record(self, client):
        c, fake = client
        before = copy.deepcopy(fake.repo.snapshot())
        _set_status(c, "suspended")
        _set_status(c, "active", reason="Payment received, reinstated.")
        assert fake.repo.snapshot() == before

    def test_a_full_suspend_restore_cycle_leaves_evidence_identical(self, client):
        c, fake = client
        before = copy.deepcopy(fake.repo.snapshot())
        for _ in range(3):
            assert _set_status(c, "suspended").status_code == 200
            assert fake.repo.tenant.status is TenantStatus.SUSPENDED
            assert _set_status(c, "active", reason="Reinstated after review.").status_code == 200
            assert fake.repo.tenant.status is TenantStatus.ACTIVE
        after = fake.repo.snapshot()
        assert after == before
        # And specifically the things an auditor would ask about.
        assert after["checks"]["chk-1"]["risk_score"] == 72
        assert after["checks"]["chk-1"]["decision"] == CheckDecision.ESCALATED.value
        assert after["documents"]["doc-1"]["content_hash"] == "a" * 64

    def test_no_document_or_check_is_deleted(self, client):
        c, fake = client
        _set_status(c, "suspended")
        assert set(fake.repo.documents) == {"doc-1"}
        assert set(fake.repo.checks) == {"chk-1"}


class TestOnlyOperatorsCanChangeStatus:
    def test_a_customer_cannot_suspend_a_workspace(self, client):
        c, fake = client
        r = c.put(
            f"/api/platform/tenants/{TENANT}/status",
            headers=_hdr(email="customer@acme.test"),
            json={"status": "suspended", "reason": "nope"},
        )
        # 404 rather than 403: the platform surface does not confirm it exists.
        assert r.status_code == 404
        assert fake.repo.tenant.status is TenantStatus.ACTIVE

    def test_an_unauthenticated_caller_cannot(self, client):
        c, fake = client
        r = c.put(
            f"/api/platform/tenants/{TENANT}/status",
            json={"status": "suspended", "reason": "nope"},
        )
        assert r.status_code == 401
        assert fake.repo.tenant.status is TenantStatus.ACTIVE
