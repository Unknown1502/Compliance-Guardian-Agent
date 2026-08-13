"""POST /api/reports queues work and reports durable state — it never waits.

The old endpoint ran Gemini and BigQuery inside the request and answered 200
when the function returned. These tests pin the replacement's contract: 202
with a status, one report per logical request however many times it is asked
for, and a status that only says READY when an artifact has been verified.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from schema_validators import ReportRecord, ReportStatus, TaskStatus, TaskType

START = "2026-07-01T00:00:00+00:00"
END = "2026-08-01T00:00:00+00:00"


def _hdr(uid="u1", tenant="tenant-a", role="owner") -> dict:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer dev:{raw}"}


class FakeRepo:
    def __init__(self):
        self.records: dict[str, ReportRecord] = {}
        self.claims = 0

    def claim_report(self, record: ReportRecord):
        self.claims += 1
        existing = self.records.get(record.report_id)
        if existing:
            return existing, False
        self.records[record.report_id] = record
        return record, True

    def get_report_record(self, report_id, tenant_id):
        from gcp_clients.firestore_repo import NotFoundError, TenantMismatchError

        rec = self.records.get(report_id)
        if rec is None:
            raise NotFoundError(report_id)
        if rec.tenant_id != tenant_id:
            raise TenantMismatchError(report_id)
        return rec

    def update_report_record(self, report_id, tenant_id, updates):
        rec = self.get_report_record(report_id, tenant_id)
        patched = rec.model_copy(update=updates)
        self.records[report_id] = patched
        return patched

    def list_report_records(self, tenant_id, limit=100):
        return [r for r in self.records.values() if r.tenant_id == tenant_id]


class FakeTask:
    def __init__(self, task_id):
        self.task_id = task_id
        self.status = TaskStatus.QUEUED


class RecordingTasks:
    def __init__(self, fail=False):
        self.dispatched = []
        self.fail = fail

    def create_and_dispatch(self, *, task_type, target_ref, tenant_id):
        if self.fail:
            raise RuntimeError("cloud tasks unavailable")
        self.dispatched.append((task_type, target_ref))
        return FakeTask(f"task-{target_ref[:8]}")


class FakeStorage:
    def list_blobs(self, *_a, **_k):
        return []


class FakeGateway:
    def __init__(self, tasks=None):
        self.repo = FakeRepo()
        self.storage = FakeStorage()
        self._tasks = tasks or RecordingTasks()

    def task_service(self):
        return self._tasks


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware
    from api_gateway.rate_limit import TokenBucketRateLimiter

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    monkeypatch.setattr(
        main, "_expensive_limiter", TokenBucketRateLimiter(capacity=100, refill_per_second=10)
    )
    return TestClient(main.app, raise_server_exceptions=False), fake


def _post(c, start=START, end=END, **kw):
    return c.post(
        "/api/reports", headers=_hdr(**kw), json={"period_start": start, "period_end": end}
    )


class TestTheRequestQueuesRatherThanWaits:
    def test_returns_202_not_200(self, client):
        c, _ = client
        assert _post(c).status_code == 202

    def test_the_report_starts_queued_and_not_downloadable(self, client):
        c, _ = client
        body = _post(c).json()
        assert body["status"] == ReportStatus.QUEUED.value
        assert body["downloadable"] is False

    def test_a_report_task_is_dispatched(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        assert fake._tasks.dispatched == [(TaskType.REPORT, report_id)]

    def test_the_task_id_is_recorded_on_the_record(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        assert fake.repo.records[report_id].task_id


class TestIdempotency:
    def test_the_same_period_twice_is_one_report(self, client):
        """A double-clicked Generate button."""
        c, fake = client
        first = _post(c).json()["report_id"]
        second = _post(c).json()["report_id"]
        assert first == second
        assert len(fake.repo.records) == 1

    def test_a_repeat_request_does_not_queue_a_second_task(self, client):
        """The expensive half: a second task means a second Gemini bill."""
        c, fake = client
        _post(c)
        _post(c)
        assert len(fake._tasks.dispatched) == 1

    def test_a_different_period_is_a_different_report(self, client):
        c, fake = client
        _post(c)
        _post(c, end="2026-09-01T00:00:00+00:00")
        assert len(fake.repo.records) == 2

    def test_asking_again_for_a_finished_report_returns_it(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        fake.repo.records[report_id] = fake.repo.records[report_id].model_copy(
            update={"status": ReportStatus.READY, "format": "pdf", "size_bytes": 4096}
        )
        body = _post(c).json()
        assert body["status"] == ReportStatus.READY.value
        assert body["downloadable"] is True
        # And it was not regenerated.
        assert len(fake._tasks.dispatched) == 1


class TestStatusPolling:
    def test_status_reflects_the_durable_record(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        fake.repo.records[report_id] = fake.repo.records[report_id].model_copy(
            update={"status": ReportStatus.GENERATING}
        )
        body = c.get(f"/api/reports/{report_id}/status", headers=_hdr()).json()
        assert body["status"] == "generating"
        assert body["downloadable"] is False

    def test_only_ready_is_downloadable(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        for s in ReportStatus:
            fake.repo.records[report_id] = fake.repo.records[report_id].model_copy(
                update={"status": s}
            )
            body = c.get(f"/api/reports/{report_id}/status", headers=_hdr()).json()
            assert body["downloadable"] is (s is ReportStatus.READY), s

    def test_a_failure_does_not_leak_the_internal_reason(self, client):
        c, fake = client
        report_id = _post(c).json()["report_id"]
        fake.repo.records[report_id] = fake.repo.records[report_id].model_copy(
            update={"status": ReportStatus.FAILED, "error": "bigquery quota exceeded for project"}
        )
        body = c.get(f"/api/reports/{report_id}/status", headers=_hdr()).json()
        assert "bigquery" not in body["error"].lower()
        assert body["error"]

    def test_unknown_report_is_404(self, client):
        c, _ = client
        assert c.get("/api/reports/no-such-report/status", headers=_hdr()).status_code == 404


class TestTenantIsolation:
    def test_another_tenant_cannot_read_the_status(self, client):
        c, _ = client
        report_id = _post(c, tenant="tenant-a").json()["report_id"]
        r = c.get(f"/api/reports/{report_id}/status", headers=_hdr(tenant="tenant-b"))
        assert r.status_code == 404

    def test_the_same_period_in_two_tenants_is_two_reports(self, client):
        c, fake = client
        a = _post(c, tenant="tenant-a").json()["report_id"]
        b = _post(c, tenant="tenant-b").json()["report_id"]
        assert a != b


class TestDispatchFailure:
    def test_a_queue_outage_is_recorded_not_silently_swallowed(self, monkeypatch):
        monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
        import api_gateway.main as main
        import auth_middleware
        from api_gateway.rate_limit import TokenBucketRateLimiter

        monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
        fake = FakeGateway(tasks=RecordingTasks(fail=True))
        monkeypatch.setattr(main, "_gateway", fake)
        monkeypatch.setattr(main, "gw", lambda: fake)
        monkeypatch.setattr(
            main, "_expensive_limiter", TokenBucketRateLimiter(capacity=100, refill_per_second=10)
        )
        c = TestClient(main.app, raise_server_exceptions=False)

        r = _post(c)
        assert r.status_code == 503
        # The record exists and says FAILED rather than sitting QUEUED forever
        # behind a task that was never created.
        record = next(iter(fake.repo.records.values()))
        assert record.status is ReportStatus.FAILED


class TestValidation:
    def test_an_inverted_period_is_rejected(self, client):
        c, _ = client
        assert _post(c, start=END, end=START).status_code == 400

    def test_unauthenticated_is_refused(self, client):
        c, _ = client
        assert c.post("/api/reports", json={"period_start": START, "period_end": END}).status_code == 401
