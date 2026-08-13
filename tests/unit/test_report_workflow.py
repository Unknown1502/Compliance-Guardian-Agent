"""READY must mean the artifact is there. Everything else is the point.

Report generation used to run inside the HTTP request and answer 200 when the
function returned — so a Cloud Run instance replaced mid-generation, or an
upload that failed after the summary was produced, both ended as "your report
is ready" with nothing to download.

These tests drive the state machine through each way that can go wrong and
assert the same thing every time: the record did not reach READY. The happy
path is one test; the other nine are failures, because the failures are what
the old design got wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reporting_agent.workflow import (
    ReportGenerationError,
    report_id_for,
    run_report_workflow,
)
from schema_validators import ReportRecord, ReportStatus

START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 8, 1, tzinfo=timezone.utc)
TENANT = "tenant-a"
BUCKET = "cg-reports"


class Outcome:
    def __init__(self, content_ref=f"gs://{BUCKET}/tenant-a/rep/report.html", pdf_ref="", **kw):
        self.content_ref = content_ref
        self.pdf_ref = pdf_ref
        self.stats = kw.get("stats", {"total_checks": 12, "auto_approved": 9, "rejected": 1, "escalated": 2})
        self.gemini_executive_summary = kw.get("summary", "Two escalations, both consent-related.")
        self.model_name = "gemini-3.1-flash-lite"
        self.used_fixture = False


class FakeBlob:
    def __init__(self, data: bytes | None):
        self._data = data

    def exists(self) -> bool:
        return self._data is not None

    def download_as_bytes(self) -> bytes:
        return self._data or b""


class FakeStorage:
    def __init__(self, objects: dict[str, bytes | None]):
        self.objects = objects

    def bucket(self, _name):
        outer = self

        class _B:
            def blob(self, path):
                return FakeBlob(outer.objects.get(path))

        return _B()


class FakeRepo:
    def __init__(self, record: ReportRecord):
        self.record = record
        self.history: list[ReportStatus] = []

    def update_report_record(self, report_id, tenant_id, updates):
        if "status" in updates:
            self.history.append(updates["status"])
        self.record = self.record.model_copy(update=updates)
        return self.record


def _record(status=ReportStatus.QUEUED, **kw) -> ReportRecord:
    return ReportRecord(
        report_id=report_id_for(TENANT, START, END),
        tenant_id=TENANT,
        period_start=START,
        period_end=END,
        status=status,
        **kw,
    )


def _run(repo, storage, generate):
    return run_report_workflow(
        record=repo.record, repo=repo, generate=generate, storage_client=storage
    )


HTML_PATH = "tenant-a/rep/report.html"
PDF_PATH = "tenant-a/rep/report.pdf"


class TestIdentityIsDeterministic:
    def test_same_period_is_the_same_report(self):
        assert report_id_for(TENANT, START, END) == report_id_for(TENANT, START, END)

    def test_a_different_period_is_a_different_report(self):
        other = report_id_for(TENANT, START, END + timedelta(days=1))
        assert other != report_id_for(TENANT, START, END)

    def test_another_tenant_is_a_different_report(self):
        assert report_id_for("tenant-b", START, END) != report_id_for(TENANT, START, END)


class TestTheHappyPath:
    def test_report_reaches_ready(self):
        repo = FakeRepo(_record())
        storage = FakeStorage({HTML_PATH: b"<html>report</html>"})
        final = _run(repo, storage, lambda: Outcome())
        assert final.status is ReportStatus.READY

    def test_it_passes_through_every_state_in_order(self):
        repo = FakeRepo(_record())
        storage = FakeStorage({HTML_PATH: b"<html>report</html>"})
        _run(repo, storage, lambda: Outcome())
        assert repo.history == [
            ReportStatus.GENERATING,
            ReportStatus.VALIDATING,
            ReportStatus.PERSISTING,
            ReportStatus.VERIFYING,
            ReportStatus.READY,
        ]

    def test_artifact_metadata_is_recorded(self):
        body = b"<html>report</html>"
        repo = FakeRepo(_record())
        final = _run(repo, FakeStorage({HTML_PATH: body}), lambda: Outcome())
        assert final.size_bytes == len(body)
        assert final.checksum and len(final.checksum) == 64
        assert final.mime_type == "text/html"
        assert final.storage_key == HTML_PATH
        assert final.expires_at is not None

    def test_a_pdf_is_preferred_over_the_html(self):
        """The PDF is what an auditor files, so it is what gets verified."""
        repo = FakeRepo(_record())
        storage = FakeStorage({HTML_PATH: b"<html>x</html>", PDF_PATH: b"%PDF-1.4 body"})
        final = _run(repo, storage, lambda: Outcome(pdf_ref=f"gs://{BUCKET}/{PDF_PATH}"))
        assert final.format == "pdf"
        assert final.mime_type == "application/pdf"

    def test_summary_stats_are_carried_onto_the_record(self):
        repo = FakeRepo(_record())
        final = _run(repo, FakeStorage({HTML_PATH: b"x"}), lambda: Outcome())
        assert (final.total_checks, final.pass_count, final.fail_count, final.escalated_count) == (
            12, 9, 1, 2
        )


class TestNoFailureReachesReady:
    """Each of these was previously capable of ending as a 200."""

    def _assert_not_ready(self, repo):
        assert repo.record.status is not ReportStatus.READY
        assert ReportStatus.READY not in repo.history

    def test_generation_failure(self):
        """Gemini or BigQuery unavailable."""
        repo = FakeRepo(_record())

        def boom():
            raise RuntimeError("gemini 503")

        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), boom)
        self._assert_not_ready(repo)
        assert repo.record.status is ReportStatus.RETRYING

    def test_artifact_never_reached_storage(self):
        """The exact production failure: generation 'succeeded', file absent."""
        repo = FakeRepo(_record())
        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), lambda: Outcome())
        self._assert_not_ready(repo)

    def test_artifact_is_present_but_empty(self):
        """A zero-byte object exists. It is not a report."""
        repo = FakeRepo(_record())
        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({HTML_PATH: b""}), lambda: Outcome())
        self._assert_not_ready(repo)

    def test_generation_returned_no_artifact_reference(self):
        repo = FakeRepo(_record())
        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), lambda: Outcome(content_ref=""))
        self._assert_not_ready(repo)
        assert repo.record.status is ReportStatus.FAILED

    def test_a_failure_records_why(self):
        repo = FakeRepo(_record())

        def boom():
            raise RuntimeError("bigquery timeout")

        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), boom)
        assert "bigquery timeout" in repo.record.error

    def test_a_retryable_failure_is_marked_retrying_not_failed(self):
        """Cloud Tasks will redeliver; the record should not look dead."""
        repo = FakeRepo(_record())
        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), lambda: Outcome())
        assert repo.record.status is ReportStatus.RETRYING


class TestRedeliveryAndRecovery:
    def test_a_report_already_ready_is_not_regenerated(self):
        """A redelivered Cloud Task must not spend a second Gemini call."""
        repo = FakeRepo(_record(status=ReportStatus.READY))
        called = []

        def generate():
            called.append(1)
            return Outcome()

        final = _run(repo, FakeStorage({HTML_PATH: b"x"}), generate)
        assert called == []
        assert final.status is ReportStatus.READY
        assert repo.history == []

    def test_a_retry_resumes_from_a_failed_attempt(self):
        """Worker died mid-generation; the next delivery finishes the job."""
        repo = FakeRepo(_record(status=ReportStatus.RETRYING, attempts=1))
        final = _run(repo, FakeStorage({HTML_PATH: b"<html>x</html>"}), lambda: Outcome())
        assert final.status is ReportStatus.READY
        assert final.attempts == 2

    def test_attempts_increment_so_a_loop_is_visible(self):
        repo = FakeRepo(_record())
        with pytest.raises(ReportGenerationError):
            _run(repo, FakeStorage({}), lambda: Outcome())
        assert repo.record.attempts == 1
