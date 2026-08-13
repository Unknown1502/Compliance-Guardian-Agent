"""Uploads land in quarantine, and the queue is told to scan — not to ingest.

The scan gate in the ingestion worker is the backstop. This is the front door:
if the gateway wrote to approved storage, or queued an ingest directly, the
backstop would be the only thing standing between an upload and a worker. Two
independent controls is the point.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import ScanStatus, TaskStatus, TaskType

RAW = "test-raw-bucket"
QUARANTINE = "test-quarantine-bucket"


def _hdr(uid="u1", tenant="tenant-a", role="owner") -> dict:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer dev:{raw}"}


class FakeBlob:
    def __init__(self):
        self.content = b""

    def upload_from_string(self, data, content_type=None):
        self.content = data


class FakeBucket:
    def __init__(self, name):
        self.name = name
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, path):
        return self.blobs.setdefault(path, FakeBlob())


class FakeStorage:
    def __init__(self):
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))


class FakeRepo:
    def __init__(self):
        self.documents = {}

    def upsert_document(self, document):
        self.documents[document.document_id] = document


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)
        return kw


class FakeTask:
    def __init__(self, task_id):
        self.task_id = task_id
        self.status = TaskStatus.QUEUED


class RecordingTaskService:
    def __init__(self):
        self.dispatched = []

    def create_and_dispatch(self, *, task_type, target_ref, tenant_id):
        self.dispatched.append(task_type)
        return FakeTask(f"task-{target_ref}")


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.storage = FakeStorage()
        self.raw_bucket = RAW
        self.quarantine_bucket = QUARANTINE
        self._svc = RecordingTaskService()

    def task_service(self):
        return self._svc


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
        main, "_upload_limiter", TokenBucketRateLimiter(capacity=50, refill_per_second=5)
    )
    return TestClient(main.app), fake


def _upload(c):
    return c.post(
        "/api/documents",
        headers=_hdr(),
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4\n" + b"x" * 200), "application/pdf")},
    )


class TestUploadsAreQuarantined:
    def test_bytes_go_to_the_quarantine_bucket(self, client):
        c, fake = client
        assert _upload(c).status_code == 200
        assert QUARANTINE in fake.storage.buckets
        assert fake.storage.buckets[QUARANTINE].blobs

    def test_nothing_is_written_to_approved_storage(self, client):
        """The single most important assertion in this file."""
        c, fake = client
        _upload(c)
        assert RAW not in fake.storage.buckets

    def test_document_starts_scan_pending(self, client):
        c, fake = client
        _upload(c)
        doc = next(iter(fake.repo.documents.values()))
        assert doc.scan_status is ScanStatus.SCAN_PENDING

    def test_storage_ref_points_at_quarantine(self, client):
        c, fake = client
        _upload(c)
        doc = next(iter(fake.repo.documents.values()))
        assert doc.storage_ref.startswith(f"gs://{QUARANTINE}/")
        assert doc.quarantine_ref == doc.storage_ref


class TestTheQueueIsToldToScan:
    def test_a_scan_task_is_dispatched(self, client):
        c, fake = client
        _upload(c)
        assert fake._svc.dispatched == [TaskType.SCAN]

    def test_ingest_is_never_dispatched_from_upload(self, client):
        """Ingestion is reachable only via the scanner, after a clean verdict."""
        c, fake = client
        _upload(c)
        assert TaskType.INGEST not in fake._svc.dispatched


class TestTheAuditTrailRecordsTheTrustState:
    def test_upload_event_records_scan_pending(self, client):
        c, fake = client
        _upload(c)
        uploaded = [e for e in fake.auditor.events if e["action"] == "document.uploaded"]
        assert uploaded[0]["after_state"]["scan_status"] == ScanStatus.SCAN_PENDING.value
