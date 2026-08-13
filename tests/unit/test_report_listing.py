"""GET /api/reports — the index that makes a stored report reachable again.

Before this endpoint a report existed only in the React state of the page that
generated it. The artifact was durably in Cloud Storage the whole time, but one
reload and the tenant could not reach their own compliance evidence through the
product. These tests pin the two properties that matter: the listing is built
from artifacts that actually exist, and it cannot cross a tenant boundary.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def _hdr(uid="u1", tenant="tenant-a", role="owner") -> dict:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer dev:{raw}"}


class FakeBlob:
    def __init__(self, name: str, size: int, updated: datetime):
        self.name = name
        self.size = size
        self.updated = updated


def _dt(day: int) -> datetime:
    return datetime(2026, 8, day, 12, 0, tzinfo=timezone.utc)


# tenant-a: one report with both formats, one HTML-only (a pre-PDF report).
# tenant-b exists purely so a leak has something to leak.
BLOBS = [
    FakeBlob("tenant-a/rep-both/report.html", 100, _dt(1)),
    FakeBlob("tenant-a/rep-both/report.pdf", 900, _dt(1)),
    FakeBlob("tenant-a/rep-old/report.html", 50, _dt(5)),
    FakeBlob("tenant-a/rep-both/notes.txt", 7, _dt(1)),  # must be ignored
    FakeBlob("tenant-b/rep-secret/report.pdf", 400, _dt(2)),
]


class FakeStorage:
    def __init__(self):
        self.calls: list[str] = []

    def list_blobs(self, _bucket, prefix=""):
        self.calls.append(prefix)
        return [b for b in BLOBS if b.name.startswith(prefix)]


class FakeRepo:
    """No durable records — these tests cover the storage half of the listing,
    which is what carries reports generated before durable records existed."""

    def __init__(self, records=()):
        self._records = list(records)

    def list_report_records(self, tenant_id, limit=100):
        return [r for r in self._records if r.tenant_id == tenant_id]


class FakeGateway:
    def __init__(self, records=()):
        self.storage = FakeStorage()
        self.repo = FakeRepo(records)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    fake = FakeGateway()
    monkeypatch.setattr(main, "_gateway", fake)
    monkeypatch.setattr(main, "gw", lambda: fake)
    return TestClient(main.app, raise_server_exceptions=False), fake


class TestReportListing:
    def test_lists_the_tenants_reports(self, client):
        c, _ = client
        rows = c.get("/api/reports", headers=_hdr()).json()
        assert {r["report_id"] for r in rows} == {"rep-both", "rep-old"}

    def test_reports_advertise_only_formats_that_exist(self, client):
        c, _ = client
        rows = {r["report_id"]: r for r in c.get("/api/reports", headers=_hdr()).json()}
        assert rows["rep-both"]["has_pdf"] is True
        assert rows["rep-both"]["has_html"] is True
        # Generated before PDF rendering existed — offering a PDF download here
        # would 404 the customer.
        assert rows["rep-old"]["has_pdf"] is False
        assert rows["rep-old"]["has_html"] is True

    def test_newest_first(self, client):
        c, _ = client
        rows = c.get("/api/reports", headers=_hdr()).json()
        assert [r["report_id"] for r in rows] == ["rep-old", "rep-both"]

    def test_non_report_objects_are_ignored(self, client):
        c, _ = client
        rows = c.get("/api/reports", headers=_hdr()).json()
        assert all(r["report_id"] != "notes.txt" for r in rows)
        assert {r["report_id"] for r in rows} == {"rep-both", "rep-old"}

    def test_size_is_summed_across_formats(self, client):
        c, _ = client
        rows = {r["report_id"]: r for r in c.get("/api/reports", headers=_hdr()).json()}
        assert rows["rep-both"]["size_bytes"] == 1000


class TestReportListingIsolation:
    def test_another_tenants_reports_are_not_listed(self, client):
        c, _ = client
        body = c.get("/api/reports", headers=_hdr(tenant="tenant-a")).text
        assert "rep-secret" not in body

    def test_listing_is_scoped_by_the_jwt_tenant(self, client):
        """The prefix is derived server-side; nothing the client sends
        participates in building it."""
        c, fake = client
        c.get("/api/reports", headers=_hdr(tenant="tenant-b"))
        assert fake.storage.calls == ["tenant-b/"]

    def test_tenant_b_sees_only_its_own(self, client):
        c, _ = client
        rows = c.get("/api/reports", headers=_hdr(tenant="tenant-b")).json()
        assert [r["report_id"] for r in rows] == ["rep-secret"]

    def test_unauthenticated_is_refused(self, client):
        c, _ = client
        assert c.get("/api/reports").status_code == 401
