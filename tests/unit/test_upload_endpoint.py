"""Unit tests: POST /api/documents — content validation + bounded read (hermetic)."""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import TaskStatus


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeBlob:
    def __init__(self):
        self.content = b""
        self.content_type = None

    def upload_from_string(self, data, content_type=None):
        self.content = data
        self.content_type = content_type


class FakeBucket:
    def __init__(self):
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, path):
        if path not in self.blobs:
            self.blobs[path] = FakeBlob()
        return self.blobs[path]


class FakeStorage:
    def __init__(self):
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name):
        if name not in self.buckets:
            self.buckets[name] = FakeBucket()
        return self.buckets[name]


class FakeRepo:
    def __init__(self):
        self.documents = {}

    def upsert_document(self, document):
        self.documents[document.document_id] = document


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeTask:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = TaskStatus.QUEUED


class FakeTaskService:
    """Stands in for the real TaskService (Firestore + Cloud Tasks) so the
    happy path can reach a response without any real infra. Not under test
    here — Task 2 only wires content validation ahead of this dispatch."""

    def create_and_dispatch(self, *, task_type, target_ref, tenant_id):
        return FakeTask(task_id=f"task-{target_ref}")


class FakeGateway:
    def __init__(self):
        self.repo = FakeRepo()
        self.auditor = FakeAuditor()
        self.storage = FakeStorage()
        self.raw_bucket = "test-raw-bucket"

    def task_service(self):
        return FakeTaskService()


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
    # Fresh rate-limit bucket per test — the real one is module-level state.
    monkeypatch.setattr(
        main, "_upload_limiter", TokenBucketRateLimiter(capacity=20, refill_per_second=0.5)
    )
    return TestClient(main.app), fake


AUTH_HEADER = {"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"}


class TestUploadValidation:
    def test_valid_pdf_accepted(self, client):
        c, fake = client
        pdf_bytes = b"%PDF-1.4\n" + b"x" * 100
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert r.status_code == 200
        assert len(fake.repo.documents) == 1

    def test_valid_text_file_accepted(self, client):
        c, fake = client
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.txt", io.BytesIO(b"plain text content"), "text/plain")},
        )
        assert r.status_code == 200
        assert len(fake.repo.documents) == 1

    def test_exe_disguised_as_pdf_rejected(self, client):
        c, fake = client
        exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00" + b"x" * 100
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("doc.pdf", io.BytesIO(exe_bytes), "application/pdf")},
        )
        assert r.status_code == 415
        assert len(fake.repo.documents) == 0
        assert any(e["action"] == "document.upload_rejected" for e in fake.auditor.events)

    def test_oversized_upload_rejected(self, client, monkeypatch):
        c, _ = client
        import api_gateway.main as main

        monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024)
        big = b"%PDF-1.4\n" + b"x" * 2048
        r = c.post(
            "/api/documents",
            headers=AUTH_HEADER,
            files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        )
        assert r.status_code == 413
