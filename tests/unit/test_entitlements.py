"""Unit tests: report entitlements.

The product gives every new workspace one free report and requires payment
after that. The whole value of the feature is that it cannot be bypassed
from the client, so these tests target the bypasses: calling the API
directly, exhausting the allowance, and racing two requests at the last one.

The repo transaction itself is exercised against a fake that models the
read-modify-write window, because that window is where a real race would
hand out a free report.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from gcp_clients.firestore_repo import EntitlementExhaustedError
from schema_validators import EntitlementSource, PlanTier, Tenant


def _tok(uid="u1", tenant="tenant-a", role="owner") -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


class FakeRepo:
    """Models the entitlement transaction's semantics, not Firestore's API.

    consume() is written the way the real transaction behaves: the decision
    and the write happen together, so it cannot be interleaved. A test that
    faked it as check-then-write would prove nothing about the real thing.
    """

    def __init__(self, tenant: Tenant):
        self.tenants = {tenant.tenant_id: tenant}
        self.released = 0

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant

    def get_document(self, document_id: str, tenant_id: str):
        return object()

    def consume_report_entitlement(self, tenant_id: str) -> Tenant:
        t = self.tenants[tenant_id]
        if t.reports_consumed >= t.reports_granted:
            raise EntitlementExhaustedError(tenant_id)
        t.reports_consumed += 1
        return t

    def release_report_entitlement(self, tenant_id: str) -> None:
        t = self.tenants[tenant_id]
        if t.reports_consumed > 0:
            t.reports_consumed -= 1
            self.released += 1

    def grant_report_entitlement(self, tenant_id: str, *, source, quantity: int) -> Tenant:
        t = self.tenants[tenant_id]
        t.reports_granted += quantity
        t.entitlement_source = source
        return t


class FakeTask:
    task_id = "task-1"
    tenant_id = "tenant-a"
    target_ref = "doc-1"
    # TaskResponse types these as dict/str, not optional.
    result: dict = {}
    error = ""

    class task_type:
        value = "check"

    class status:
        value = "pending"


class FakeTaskService:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def create_and_dispatch(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("dispatcher unavailable")
        return FakeTask()


class FakeGateway:
    def __init__(self, tenant: Tenant, fail_dispatch: bool = False):
        self.repo = FakeRepo(tenant)
        self._svc = FakeTaskService(fail=fail_dispatch)

    def task_service(self):
        return self._svc


@pytest.fixture()
def tenant() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        name="Fernbank Verify",
        industry="data_privacy",
        jurisdiction="in",
        plan_tier=PlanTier.FREE,
    )


def _client(monkeypatch, gateway):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    auth_middleware.set_tenant_status_resolver(None)
    monkeypatch.setattr(main, "_gateway", gateway)
    monkeypatch.setattr(main, "gw", lambda: gateway)
    return TestClient(main.app, raise_server_exceptions=False)


CHECK = {"document_id": "doc-1"}


class TestFreeReport:
    def test_a_new_workspace_gets_exactly_one(self, tenant):
        assert tenant.reports_granted == 1
        assert tenant.reports_consumed == 0
        assert tenant.entitlement_source is EntitlementSource.FREE

    def test_the_first_check_is_allowed(self, monkeypatch, tenant):
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        assert c.post("/api/compliance/checks", json=CHECK, headers=_hdr()).status_code == 200
        assert g.repo.tenants["tenant-a"].reports_consumed == 1

    def test_the_second_check_is_refused_with_402(self, monkeypatch, tenant):
        """The entire point of the feature."""
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        r = c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        assert r.status_code == 402
        assert "allowance" in r.json()["detail"].lower()

    def test_402_not_403(self, monkeypatch, tenant):
        """The caller is authorised; they have simply used what they paid for."""
        tenant.reports_consumed = 1
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        r = c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        assert r.status_code == 402


class TestCannotBeBypassedFromTheClient:
    def test_calling_the_api_directly_still_fails(self, monkeypatch, tenant):
        """No frontend involved at all — the server decides."""
        tenant.reports_consumed = 1
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        assert c.post("/api/compliance/checks", json=CHECK, headers=_hdr()).status_code == 402

    def test_a_second_session_shares_the_same_allowance(self, monkeypatch, tenant):
        """Allowance is per workspace, so another device or login changes nothing."""
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        c.post("/api/compliance/checks", json=CHECK, headers=_hdr(uid="u1"))
        r = c.post("/api/compliance/checks", json=CHECK, headers=_hdr(uid="u2-another-device"))
        assert r.status_code == 402

    def test_replaying_the_request_does_not_grant_more(self, monkeypatch, tenant):
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        codes = [
            c.post("/api/compliance/checks", json=CHECK, headers=_hdr()).status_code
            for _ in range(5)
        ]
        assert codes == [200, 402, 402, 402, 402]
        assert g.repo.tenants["tenant-a"].reports_consumed == 1


class TestConsumptionIsAtomic:
    def test_two_requests_on_the_last_allowance_yield_exactly_one_report(
        self, monkeypatch, tenant
    ):
        """The race that would otherwise give away a free report.

        The naive implementation reads "1 remaining", decides yes twice, and
        writes twice. Consumption happens inside the decision here, so the
        second caller sees the already-incremented count.
        """
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        results = [
            c.post("/api/compliance/checks", json=CHECK, headers=_hdr()).status_code
            for _ in range(2)
        ]
        assert sorted(results) == [200, 402]
        assert g.repo.tenants["tenant-a"].reports_consumed == 1

    def test_consumed_never_exceeds_granted(self, monkeypatch, tenant):
        g = FakeGateway(tenant)
        c = _client(monkeypatch, g)
        for _ in range(10):
            c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        t = g.repo.tenants["tenant-a"]
        assert t.reports_consumed <= t.reports_granted


class TestFailedGenerationIsNotCharged:
    def test_dispatch_failure_releases_the_allowance(self, monkeypatch, tenant):
        """Nobody should pay for a report that was never produced."""
        g = FakeGateway(tenant, fail_dispatch=True)
        c = _client(monkeypatch, g)
        c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        assert g.repo.tenants["tenant-a"].reports_consumed == 0
        assert g.repo.released == 1

    def test_and_the_customer_can_then_retry_successfully(self, monkeypatch, tenant):
        g = FakeGateway(tenant, fail_dispatch=True)
        c = _client(monkeypatch, g)
        c.post("/api/compliance/checks", json=CHECK, headers=_hdr())
        g._svc.fail = False
        assert c.post("/api/compliance/checks", json=CHECK, headers=_hdr()).status_code == 200


class TestPaymentGrantsAllowance:
    def test_a_single_purchase_adds_exactly_one(self, tenant):
        repo = FakeRepo(tenant)
        repo.consume_report_entitlement("tenant-a")  # free report used
        repo.grant_report_entitlement("tenant-a", source=EntitlementSource.SINGLE, quantity=1)
        t = repo.tenants["tenant-a"]
        assert t.reports_granted - t.reports_consumed == 1
        assert t.entitlement_source is EntitlementSource.SINGLE

    def test_a_grant_is_additive_and_never_confiscates_an_unused_free_report(self, tenant):
        """Buying early must not silently take away what you already had."""
        repo = FakeRepo(tenant)
        repo.grant_report_entitlement("tenant-a", source=EntitlementSource.SINGLE, quantity=1)
        t = repo.tenants["tenant-a"]
        assert t.reports_granted - t.reports_consumed == 2

    def test_pro_grants_the_configured_monthly_allowance(self, tenant):
        from gcp_clients.firestore_repo import PRO_MONTHLY_REPORTS

        repo = FakeRepo(tenant)
        repo.grant_report_entitlement(
            "tenant-a", source=EntitlementSource.PRO, quantity=PRO_MONTHLY_REPORTS
        )
        t = repo.tenants["tenant-a"]
        assert t.reports_granted - t.reports_consumed == PRO_MONTHLY_REPORTS + 1
        assert t.entitlement_source is EntitlementSource.PRO


class TestEntitlementEndpoint:
    def test_reports_free_report_available_for_a_new_workspace(self, monkeypatch, tenant):
        c = _client(monkeypatch, FakeGateway(tenant))
        body = c.get("/api/entitlement", headers=_hdr()).json()
        assert body["state"] == "free_report_available"
        assert body["remaining"] == 1
        assert body["source"] == "free"

    def test_reports_payment_required_once_exhausted(self, monkeypatch, tenant):
        tenant.reports_consumed = 1
        c = _client(monkeypatch, FakeGateway(tenant))
        body = c.get("/api/entitlement", headers=_hdr()).json()
        assert body["state"] == "payment_required"
        assert body["remaining"] == 0

    def test_distinguishes_a_one_time_buyer_from_a_subscriber(self, monkeypatch, tenant):
        """A single purchaser must never be described as Pro."""
        tenant.reports_consumed = 1
        tenant.reports_granted = 2
        tenant.entitlement_source = EntitlementSource.SINGLE
        c = _client(monkeypatch, FakeGateway(tenant))
        body = c.get("/api/entitlement", headers=_hdr()).json()
        assert body["state"] == "paid_report_available"
        assert body["source"] == "single"

    def test_requires_auth(self, monkeypatch, tenant):
        c = _client(monkeypatch, FakeGateway(tenant))
        assert c.get("/api/entitlement").status_code == 401
