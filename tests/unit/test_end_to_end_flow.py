"""End-to-end flow through the real API gateway, one tenant's whole journey.

Every other test file checks one endpoint in isolation. This one drives the
actual FastAPI app over HTTP in sequence — signup, upload, check, review,
report, audit — so that a change which passes every unit test but breaks the
handoff between two steps still fails here.

Hermetic: GCP clients and Firebase Auth are replaced with in-memory fakes.
Routing, request validation, auth middleware, rate limiting, and error
handling are all the real implementations.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import (
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    PlanTier,
    Tenant,
)


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


# --- in-memory stand-ins for the GCP surface -------------------------------


class FakeBlob:
    def __init__(self, store: dict, path: str):
        self._store = store
        self._path = path

    def upload_from_string(self, data, content_type=None):
        self._store[self._path] = data if isinstance(data, bytes) else data.encode()

    def exists(self):
        return self._path in self._store

    def download_as_bytes(self):
        return self._store[self._path]

    def download_as_text(self):
        return self._store[self._path].decode("utf-8")


class FakeBucket:
    def __init__(self, store: dict):
        self._store = store

    def blob(self, path):
        return FakeBlob(self._store, path)


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def bucket(self, _name):
        return FakeBucket(self.objects)


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs

    def actions(self) -> list[str]:
        return [e["action"] for e in self.events]


class FakeTask:
    def __init__(self, task_id, tenant_id, task_type, target_ref):
        from schema_validators import TaskStatus

        self.task_id = task_id
        self.tenant_id = tenant_id
        self.task_type = task_type
        self.target_ref = target_ref
        self.status = TaskStatus.QUEUED
        self.result: dict = {}
        self.error = None


class FakeTaskService:
    def __init__(self):
        self.dispatched: list[FakeTask] = []

    def create_and_dispatch(self, *, task_type, target_ref, tenant_id):
        task = FakeTask(
            f"task-{len(self.dispatched) + 1}", tenant_id, task_type, target_ref
        )
        self.dispatched.append(task)
        return task

    def get_task(self, task_id, tenant_id):
        for t in self.dispatched:
            if t.task_id == task_id and t.tenant_id == tenant_id:
                return t
        from gcp_clients.firestore_repo import NotFoundError

        raise NotFoundError(task_id)


class FakeRepo:
    """Tenant-scoping semantics matching FirestoreRepo's contract."""

    def __init__(self):
        self.tenants: dict[str, Tenant] = {}
        self.users: dict[str, object] = {}
        self.documents: dict[str, Document] = {}
        self.checks: dict[str, ComplianceCheck] = {}

    # tenants / users
    def upsert_tenant(self, tenant):
        self.tenants[tenant.tenant_id] = tenant

    def get_tenant(self, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError

        if tenant_id not in self.tenants:
            raise NotFoundError(tenant_id)
        return self.tenants[tenant_id]

    def upsert_user(self, user):
        self.users[user.uid] = user

    # Entitlements. The journey this file walks is signup -> upload -> check,
    # and a check now spends the workspace's free report — so the fake models
    # that, and the flow proves the free report actually carries a new user
    # through their first analysis end to end.
    def consume_report_entitlement(self, tenant_id):
        from gcp_clients.firestore_repo import EntitlementExhaustedError

        t = self.get_tenant(tenant_id)
        if t.reports_consumed >= t.reports_granted:
            raise EntitlementExhaustedError(tenant_id)
        t.reports_consumed += 1
        return t

    def release_report_entitlement(self, tenant_id):
        t = self.get_tenant(tenant_id)
        t.reports_consumed = max(0, t.reports_consumed - 1)

    def grant_report_entitlement(self, tenant_id, *, source, quantity):
        t = self.get_tenant(tenant_id)
        t.reports_granted += quantity
        t.entitlement_source = source
        return t

    def list_users(self, tenant_id, limit=100):
        return [u for u in self.users.values() if u.tenant_id == tenant_id]

    # documents
    def upsert_document(self, document):
        self.documents[document.document_id] = document

    def get_document(self, document_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        if document_id not in self.documents:
            raise NotFoundError(document_id)
        doc = self.documents[document_id]
        if doc.tenant_id != tenant_id:
            raise TenantMismatchError(document_id)
        return doc

    # checks
    def upsert_check(self, check):
        self.checks[check.check_id] = check

    def get_check(self, check_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        if check_id not in self.checks:
            raise NotFoundError(check_id)
        c = self.checks[check_id]
        if c.tenant_id != tenant_id:
            raise TenantMismatchError(check_id)
        return c

    def list_escalated_checks(self, tenant_id, limit=200):
        return [
            c
            for c in self.checks.values()
            if c.tenant_id == tenant_id and c.decision is CheckDecision.ESCALATED
        ]

    def apply_reviewer_decision(self, *, check_id, tenant_id, reviewer_id, decision):
        from gcp_clients.firestore_repo import DecisionConflictError

        c = self.get_check(check_id, tenant_id)
        if c.decision is not CheckDecision.ESCALATED or c.reviewer_id is not None:
            raise DecisionConflictError(check_id)
        updated = c.model_copy(update={"decision": decision, "reviewer_id": reviewer_id})
        self.checks[check_id] = updated
        return updated


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.storage = FakeStorage()
        self.raw_bucket = "cg-test-raw"
        self._svc = FakeTaskService()

    def task_service(self):
        return self._svc


@pytest.fixture()
def app_client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware
    from api_gateway.rate_limit import TokenBucketRateLimiter

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    # Fresh limiter state per test — the real ones are module-level.
    for name in ("_upload_limiter", "_expensive_limiter", "_standard_limiter", "_auth_limiter"):
        monkeypatch.setattr(
            main, name, TokenBucketRateLimiter(capacity=50, refill_per_second=5.0)
        )
    return TestClient(main.app), fake, main


OWNER = {"Authorization": f"Bearer {_dev_token('owner-1', 'tenant-x', 'owner')}"}
REVIEWER = {"Authorization": f"Bearer {_dev_token('rev-1', 'tenant-x', 'reviewer')}"}
OTHER_TENANT = {"Authorization": f"Bearer {_dev_token('o-2', 'tenant-y', 'owner')}"}


class TestFullJourney:
    def test_upload_check_review_flow(self, app_client):
        """The complete path a real customer takes, in order."""
        c, fake, _ = app_client
        fake.repo.upsert_tenant(
            Tenant(
                tenant_id="tenant-x",
                name="Fernbank Care",
                industry="healthcare_ndis",
                jurisdiction="AU",
                plan_tier=PlanTier.FREE,
            )
        )

        # 1. Upload a document.
        up = c.post(
            "/api/documents",
            headers=OWNER,
            files={
                "file": (
                    "record.txt",
                    io.BytesIO(b"Client consent recorded 2026-01-05."),
                    "text/plain",
                )
            },
        )
        assert up.status_code == 200, up.text
        document_id = up.json()["document_id"]

        # 2. The document is readable back, tenant-scoped.
        got = c.get(f"/api/documents/{document_id}", headers=OWNER)
        assert got.status_code == 200
        assert got.json()["tenant_id"] == "tenant-x"

        # ...and invisible to another tenant.
        assert c.get(f"/api/documents/{document_id}", headers=OTHER_TENANT).status_code == 404

        # 3. Trigger a compliance check on it.
        chk = c.post(
            "/api/compliance/checks", json={"document_id": document_id}, headers=OWNER
        )
        assert chk.status_code == 200, chk.text

        # 4. An escalated check reaches the reviewer queue.
        fake.repo.upsert_check(
            ComplianceCheck(
                check_id="check-1",
                document_id=document_id,
                tenant_id="tenant-x",
                rule_set_version="1.1.0",
                risk_score=82,
                justification="Consent record predates the service date.",
                citations=["consent_documentation"],
                decision=CheckDecision.ESCALATED,
            )
        )
        queue = c.get("/api/compliance/queue", headers=REVIEWER)
        assert queue.status_code == 200
        assert [x["check_id"] for x in queue.json()] == ["check-1"]

        # 5. The reviewer decides, and the decision sticks.
        dec = c.patch(
            "/api/compliance/checks/check-1", json={"action": "approve"}, headers=REVIEWER
        )
        assert dec.status_code == 200, dec.text
        assert dec.json()["reviewer_id"] == "rev-1"

        # 6. A second reviewer loses the race rather than overwriting.
        again = c.patch(
            "/api/compliance/checks/check-1", json={"action": "reject"}, headers=REVIEWER
        )
        assert again.status_code == 409
        assert again.json()["detail"] == "this check was already decided by another reviewer"

        # 7. Every step left an audit trail.
        actions = fake.auditor.actions()
        assert "document.uploaded" in actions
        assert "check.approved" in actions

    def test_owner_cannot_make_reviewer_decisions(self, app_client):
        c, fake, _ = app_client
        fake.repo.upsert_check(
            ComplianceCheck(
                check_id="check-2",
                document_id="doc-1",
                tenant_id="tenant-x",
                rule_set_version="1.1.0",
                risk_score=90,
                justification="x",
                citations=["a"],
                decision=CheckDecision.ESCALATED,
            )
        )
        r = c.patch(
            "/api/compliance/checks/check-2", json={"action": "approve"}, headers=OWNER
        )
        assert r.status_code == 403


class TestHardeningHoldsInTheRealFlow:
    """The security work must not have broken the journey, and must still bite."""

    def test_disguised_upload_is_refused_mid_flow(self, app_client):
        c, fake, _ = app_client
        r = c.post(
            "/api/documents",
            headers=OWNER,
            files={
                "file": (
                    "invoice.pdf",
                    io.BytesIO(b"MZ\x90\x00\x03" + b"\x00" * 200),
                    "application/pdf",
                )
            },
        )
        assert r.status_code == 415
        assert fake.repo.documents == {}
        assert "document.upload_rejected" in fake.auditor.actions()

    def test_upload_rate_limit_stops_a_flood(self, app_client, monkeypatch):
        c, _, main = app_client
        from api_gateway.rate_limit import TokenBucketRateLimiter

        monkeypatch.setattr(
            main, "_upload_limiter", TokenBucketRateLimiter(capacity=2, refill_per_second=0.0001)
        )
        codes = []
        for _ in range(4):
            r = c.post(
                "/api/documents",
                headers=OWNER,
                files={"file": ("a.txt", io.BytesIO(b"hello there"), "text/plain")},
            )
            codes.append(r.status_code)
        assert codes[:2] == [200, 200]
        assert codes[-1] == 429

    def test_errors_stay_generic_across_the_flow(self, app_client):
        c, _, _ = app_client
        r = c.get("/api/documents/doc-does-not-exist", headers=OWNER)
        assert r.status_code == 404
        body = json.dumps(r.json())
        assert "doc-does-not-exist" not in body

    def test_unauthenticated_request_is_refused_everywhere(self, app_client):
        c, _, _ = app_client
        for path in ("/api/documents/doc-a", "/api/compliance/queue", "/api/team"):
            assert c.get(path).status_code == 401, path
