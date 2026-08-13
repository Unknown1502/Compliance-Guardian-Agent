"""Scanner agent: what leaves quarantine, and what emphatically does not.

The invariant is one-directional — a document may only reach approved storage
by being scanned and found clean — so most of these tests assert a *negative*:
that nothing was copied, that the record was not marked CLEAN, that the bytes
are still where they were. A scanner subsystem fails safe or it is worthless,
and the failure paths are the ones that rot silently.
"""

from __future__ import annotations

import pytest

from schema_validators import Document, DocumentStatus, ScanStatus
from scanner_agent.clamav import ScanVerdict
from scanner_agent.scanner import scan_document

QUARANTINE = "cg-quarantine"
APPROVED = "cg-raw-docs"
PATH = "tenant-a/doc-1/report.pdf"


class FakeBlob:
    def __init__(self, bucket, path, data=b""):
        self.bucket = bucket
        self.path = path
        self.data = data

    def download_as_bytes(self):
        if self.data is None:
            raise OSError("object missing")
        return self.data

    def upload_from_string(self, data, content_type=None):
        self.bucket.store[self.path] = data
        if self.bucket.fail_upload:
            raise OSError("storage unavailable")

    def delete(self):
        self.bucket.store.pop(self.path, None)
        self.bucket.deleted.append(self.path)


class FakeBucket:
    def __init__(self, name):
        self.name = name
        self.store: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail_upload = False

    def blob(self, path):
        return FakeBlob(self, path, self.store.get(path, b"" if path in self.store else None))


class FakeStorage:
    def __init__(self):
        self.buckets = {QUARANTINE: FakeBucket(QUARANTINE), APPROVED: FakeBucket(APPROVED)}
        self.buckets[QUARANTINE].store[PATH] = b"%PDF-1.4 harmless"

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))


class FakeRepo:
    def __init__(self, document):
        self.doc = document
        self.updates: list[dict] = []

    def get_document(self, document_id, tenant_id):
        return self.doc

    def update_document_fields(self, document_id, tenant_id, updates):
        self.updates.append(updates)
        self.doc = self.doc.model_copy(update=updates)
        return self.doc

    @property
    def final(self) -> dict:
        merged: dict = {}
        for u in self.updates:
            merged.update(u)
        return merged


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kw):
        self.events.append(kw)


class StubScanner:
    name = "clamav"

    def __init__(self, verdict=None, raises=None):
        self._verdict = verdict or ScanVerdict(ScanStatus.CLEAN)
        self._raises = raises
        self.scanned = False

    def version(self):
        return "0.104.0/27000"

    def scan(self, data):
        self.scanned = True
        if self._raises:
            raise self._raises
        return self._verdict


def _doc(**kw) -> Document:
    base = dict(
        document_id="doc-1",
        tenant_id="tenant-a",
        source="upload",
        storage_ref=f"gs://{QUARANTINE}/{PATH}",
        quarantine_ref=f"gs://{QUARANTINE}/{PATH}",
        status=DocumentStatus.PENDING,
        scan_status=ScanStatus.SCAN_PENDING,
        content_type="application/pdf",
        content_hash="abc123",
    )
    base.update(kw)
    return Document(**base)


def _run(scanner, document=None, storage=None, auditor=None):
    storage = storage or FakeStorage()
    repo = FakeRepo(document or _doc())
    auditor = auditor or FakeAuditor()
    outcome = scan_document(
        document_id="doc-1",
        tenant_id="tenant-a",
        repo=repo,
        storage_client=storage,
        scanner=scanner,
        auditor=auditor,
        approved_bucket=APPROVED,
    )
    return outcome, repo, storage, auditor


class TestCleanFilesArePromoted:
    def test_clean_file_reaches_approved_storage(self):
        outcome, repo, storage, _ = _run(StubScanner())
        assert outcome.scan_status is ScanStatus.CLEAN
        assert outcome.promoted is True
        assert storage.buckets[APPROVED].store[PATH] == b"%PDF-1.4 harmless"

    def test_storage_ref_points_at_the_cleared_copy(self):
        """Downstream readers must read the copy that was scanned."""
        _, repo, _, _ = _run(StubScanner())
        assert repo.final["storage_ref"] == f"gs://{APPROVED}/{PATH}"
        assert repo.final["quarantine_ref"] == ""

    def test_scanner_identity_is_recorded(self):
        _, repo, _, _ = _run(StubScanner())
        assert repo.final["scanner"] == "clamav"
        assert repo.final["scanner_version"] == "0.104.0/27000"
        assert repo.final["scan_completed_at"] is not None

    def test_quarantine_copy_is_removed(self):
        _, _, storage, _ = _run(StubScanner())
        assert PATH in storage.buckets[QUARANTINE].deleted

    def test_clearing_is_audited(self):
        _, _, _, auditor = _run(StubScanner())
        assert [e["action"] for e in auditor.events] == ["document.scan_cleared"]


class TestInfectedFilesAreContained:
    def _infected(self):
        return _run(StubScanner(ScanVerdict(ScanStatus.INFECTED, threat_name="Eicar-Test")))

    def test_nothing_is_copied_to_approved_storage(self):
        _, _, storage, _ = self._infected()
        assert storage.buckets[APPROVED].store == {}

    def test_document_is_marked_infected_and_failed(self):
        _, repo, _, _ = self._infected()
        assert repo.final["scan_status"] is ScanStatus.INFECTED
        assert repo.final["status"] is DocumentStatus.FAILED
        assert repo.final["threat_name"] == "Eicar-Test"

    def test_the_sample_is_kept_for_investigation(self):
        """Deleting an infected upload destroys the only evidence."""
        _, _, storage, _ = self._infected()
        assert storage.buckets[QUARANTINE].deleted == []
        assert PATH in storage.buckets[QUARANTINE].store

    def test_rejection_is_audited(self):
        _, _, _, auditor = self._infected()
        assert auditor.events[0]["action"] == "document.scan_rejected"
        assert auditor.events[0]["after_state"]["threat_name"] == "Eicar-Test"

    def test_outcome_refuses_processing(self):
        outcome, _, _, _ = self._infected()
        assert outcome.may_process is False


class TestScannerFailuresFailClosed:
    @pytest.mark.parametrize(
        "verdict",
        [
            ScanVerdict(ScanStatus.SCAN_FAILED, detail="scanner unreachable"),
            ScanVerdict(ScanStatus.SCAN_TIMEOUT, detail="scanner timed out"),
        ],
        ids=["unreachable", "timeout"],
    )
    def test_a_scanner_that_could_not_answer_never_promotes(self, verdict):
        outcome, repo, storage, _ = _run(StubScanner(verdict))
        assert outcome.scan_status is verdict.status
        assert outcome.may_process is False
        assert storage.buckets[APPROVED].store == {}
        assert repo.final["scan_status"] is not ScanStatus.CLEAN

    def test_a_scanner_that_raises_is_not_a_pass(self):
        outcome, _, storage, _ = _run(StubScanner(raises=RuntimeError("boom")))
        assert outcome.scan_status is ScanStatus.SCAN_FAILED
        assert storage.buckets[APPROVED].store == {}

    def test_unreadable_quarantine_object_is_not_a_pass(self):
        storage = FakeStorage()
        del storage.buckets[QUARANTINE].store[PATH]
        scanner = StubScanner()
        outcome, _, storage, _ = _run(scanner, storage=storage)
        assert outcome.scan_status is ScanStatus.SCAN_FAILED
        assert scanner.scanned is False

    def test_a_failed_promotion_copy_leaves_the_file_untrusted(self):
        """The record must never claim CLEAN for a copy that isn't there."""
        storage = FakeStorage()
        storage.buckets[APPROVED].fail_upload = True
        outcome, repo, _, _ = _run(StubScanner(), storage=storage)
        assert outcome.scan_status is ScanStatus.SCAN_FAILED
        assert outcome.promoted is False
        assert repo.final["scan_status"] is not ScanStatus.CLEAN

    def test_failures_are_audited(self):
        _, _, _, auditor = _run(StubScanner(ScanVerdict(ScanStatus.SCAN_FAILED)))
        assert auditor.events[0]["action"] == "document.scan_failed"


class TestRedelivery:
    def test_rescanning_a_cleared_document_is_a_no_op(self):
        """Cloud Tasks redelivers; a second scan must not re-copy or re-audit."""
        scanner = StubScanner()
        outcome, repo, storage, auditor = _run(
            scanner, document=_doc(scan_status=ScanStatus.CLEAN)
        )
        assert outcome.already_resolved is True
        assert scanner.scanned is False
        assert storage.buckets[APPROVED].store == {}
        assert auditor.events == []


class TestClamdReplyParsing:
    """Unknown scanner output must never be read as a pass."""

    @staticmethod
    def _interpret(raw):
        from scanner_agent.clamav import ClamAVScanner

        return ClamAVScanner._interpret(raw)

    def test_ok_is_clean(self):
        assert self._interpret("stream: OK").status is ScanStatus.CLEAN

    def test_found_is_infected_with_the_signature_name(self):
        v = self._interpret("stream: Win.Test.EICAR_HDB-1 FOUND")
        assert v.status is ScanStatus.INFECTED
        assert v.threat_name == "Win.Test.EICAR_HDB-1"

    @pytest.mark.parametrize(
        "raw",
        ["INSTREAM size limit exceeded. ERROR", "", "stream: ", "garbage", "OK"],
    )
    def test_anything_unrecognised_is_a_failure(self, raw):
        assert self._interpret(raw).status is ScanStatus.SCAN_FAILED
