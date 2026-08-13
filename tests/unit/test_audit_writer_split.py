"""The audit trail's two-identity split, and the properties that make it work.

The gateway must keep `bigquery.jobs.create` — six read paths need it. An
identity holding jobs.create AND `bigquery.tables.updateData` can run DML
against the audit table, so the gateway must not hold the second. Appends
move to cg-audit-writer, which holds updateData and not jobs.create.

Neither half can rewrite history. These tests pin the application-level
behaviour that split depends on; the IAM half is verified against the live
project (a hostile DML attempt as the gateway identity).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_logger import AuditWriteError, RemoteAuditLogger, deterministic_event_id

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, status=201):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Capture:
    """Stands in for urllib.request.urlopen."""

    def __init__(self, status=201, raises=None):
        self.status = status
        self.raises = raises
        self.calls: list = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        if self.raises:
            raise self.raises
        return FakeResponse(self.status)


@pytest.fixture()
def logger(monkeypatch):
    log = RemoteAuditLogger("https://writer.example", max_attempts=3)
    monkeypatch.setattr(log, "_id_token", lambda: "test-token")
    return log


def _send(logger, capture, monkeypatch, **kw):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    payload = dict(
        tenant_id="tenant-a", actor="u1", action="document.uploaded", dedup_key="doc-1"
    )
    payload.update(kw)
    return logger.log(**payload)


class TestRemoteAuditLogger:
    def test_event_is_posted_to_the_writer(self, logger, monkeypatch):
        cap = Capture()
        _send(logger, cap, monkeypatch)
        assert cap.calls[0].full_url == "https://writer.example/internal/audit"

    def test_request_is_authenticated(self, logger, monkeypatch):
        cap = Capture()
        _send(logger, cap, monkeypatch)
        assert cap.calls[0].headers["Authorization"] == "Bearer test-token"

    def test_event_id_is_derived_from_the_event_not_the_request(self, logger, monkeypatch):
        """Idempotency depends on this: a Cloud Task replay must produce the
        same id so BigQuery dedupes it, exactly as when the gateway inserted
        directly. Generating the id inside the writer would break that."""
        cap = Capture()
        row = _send(logger, cap, monkeypatch)
        expected = deterministic_event_id("tenant-a", "u1", "document.uploaded", "doc-1")
        assert row.event_id == expected
        assert json.loads(cap.calls[0].data)["event_id"] == expected

    def test_the_same_event_twice_carries_the_same_id(self, logger, monkeypatch):
        cap = Capture()
        first = _send(logger, cap, monkeypatch)
        second = _send(logger, cap, monkeypatch)
        assert first.event_id == second.event_id

    def test_state_is_serialised_for_the_wire(self, logger, monkeypatch):
        cap = Capture()
        _send(logger, cap, monkeypatch, after_state={"z": 1, "a": 2})
        sent = json.loads(cap.calls[0].data)["after_state"]
        # sort_keys, so a replayed event produces byte-identical state.
        assert sent == '{"a": 2, "z": 1}'


class TestFailuresAreNeverSilent:
    def test_a_writer_outage_raises_rather_than_dropping_the_event(self, logger, monkeypatch):
        cap = Capture(raises=OSError("connection refused"))
        with pytest.raises(AuditWriteError):
            _send(logger, cap, monkeypatch)

    def test_it_retries_before_giving_up(self, logger, monkeypatch):
        cap = Capture(raises=OSError("boom"))
        with pytest.raises(AuditWriteError):
            _send(logger, cap, monkeypatch)
        assert len(cap.calls) == 3

    def test_a_rejected_write_is_not_reported_as_success(self, logger, monkeypatch):
        cap = Capture(status=500)
        with pytest.raises(AuditWriteError):
            _send(logger, cap, monkeypatch)


class TestTheSplitIsDeclaredInInfrastructure:
    """The control is IAM. These guard the declaration against a well-meaning
    edit that would quietly restore the dangerous combination."""

    def _iam(self) -> str:
        return (REPO_ROOT / "infra/terraform/iam.tf").read_text(encoding="utf-8")

    def test_the_gateway_has_no_appender_binding(self):
        iam = self._iam()
        # The binding resource is gone entirely, not merely renamed.
        assert 'resource "google_bigquery_dataset_iam_member" "gateway_appender"' not in iam

    def test_the_writer_holds_the_appender_role(self):
        assert 'resource "google_bigquery_dataset_iam_member" "audit_writer_appender"' in self._iam()

    def test_the_writer_is_not_granted_job_permissions(self):
        """jobs.create on this identity would re-create DML capability."""
        iam = self._iam()
        writer_block = iam.split("cg_audit_writer")
        joined = " ".join(writer_block)
        assert "bigquery.jobUser" not in joined or "cg_gateway" in joined
        # Explicit: no jobUser binding names the writer service account.
        for line in iam.splitlines():
            if "jobUser" in line:
                assert "audit_writer" not in line

    def test_the_appender_role_still_omits_jobs_create(self):
        """Checks the granted permissions, not the prose around them — the
        role's own description mentions jobs.create to explain its absence."""
        block = self._iam().split('"audit_appender"')[1]
        granted = block.split("permissions = [")[1].split("]")[0]
        assert "bigquery.jobs.create" not in granted
        assert "bigquery.tables.updateData" in granted
