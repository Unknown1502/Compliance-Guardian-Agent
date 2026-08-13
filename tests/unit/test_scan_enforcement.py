"""The untrusted-file invariant: no unscanned document reaches processing.

The property under test is not "ingestion returns an error" — it is that the
bytes are never fetched at all. A check that ran after the download would still
have handed a malicious file to the parser. So the storage client here refuses
to be touched, and any read is a test failure rather than a mock return value.

Only CLEAN proceeds. SCAN_FAILED and SCAN_TIMEOUT are pinned alongside INFECTED
on purpose: an unavailable scanner must fail closed, and the single most likely
way this invariant regresses is someone treating "scan errored" as benign.
"""

from __future__ import annotations

import pytest

from schema_validators import Document, DocumentStatus, ScanStatus


class ExplodingStorage:
    """Any access at all fails the test."""

    def __init__(self):
        self.touched = False

    def bucket(self, *_a, **_k):
        self.touched = True
        raise AssertionError("storage was read for a document that is not CLEAN")


class Repo:
    def __init__(self, document: Document):
        self._doc = document
        self.tenant_reads = 0

    def get_document(self, document_id, tenant_id):
        return self._doc

    def get_tenant(self, tenant_id):
        # Reached only if the trust gate let the request through.
        self.tenant_reads += 1
        raise AssertionError("ingestion continued past the scan gate")


def _doc(scan_status: ScanStatus) -> Document:
    return Document(
        document_id="doc-1",
        tenant_id="tenant-a",
        source="upload",
        storage_ref="gs://quarantine/tenant-a/doc-1/x.pdf",
        status=DocumentStatus.PENDING,
        scan_status=scan_status,
    )


def _ingest(document: Document, storage):
    from ingestion_agent.extractor import ingest_document

    return ingest_document(
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        repo=Repo(document),
        storage_client=storage,
        gemini=None,
        auditor=None,
        rulesets_root="/nonexistent",
    )


BLOCKED = [
    ScanStatus.UNSCANNED,
    ScanStatus.SCAN_PENDING,
    ScanStatus.SCANNING,
    ScanStatus.INFECTED,
    ScanStatus.SCAN_FAILED,
    ScanStatus.SCAN_TIMEOUT,
]


class TestUnscannedFilesCannotBeProcessed:
    @pytest.mark.parametrize("scan_status", BLOCKED, ids=lambda s: s.value)
    def test_processing_is_refused(self, scan_status):
        from ingestion_agent.extractor import UnscannedDocumentError

        with pytest.raises(UnscannedDocumentError) as exc:
            _ingest(_doc(scan_status), ExplodingStorage())
        assert exc.value.scan_status == scan_status.value

    @pytest.mark.parametrize("scan_status", BLOCKED, ids=lambda s: s.value)
    def test_the_bytes_are_never_fetched(self, scan_status):
        from ingestion_agent.extractor import UnscannedDocumentError

        storage = ExplodingStorage()
        with pytest.raises(UnscannedDocumentError):
            _ingest(_doc(scan_status), storage)
        assert storage.touched is False

    def test_a_scanner_failure_is_not_treated_as_clean(self):
        """The rule most likely to be 'simplified' away later."""
        from ingestion_agent.extractor import UnscannedDocumentError

        with pytest.raises(UnscannedDocumentError):
            _ingest(_doc(ScanStatus.SCAN_FAILED), ExplodingStorage())

    def test_clean_passes_the_gate(self):
        """A CLEAN document must get past the trust check — proven by the
        failure coming from the *next* step (tenant load) rather than the gate."""
        from ingestion_agent.extractor import UnscannedDocumentError

        with pytest.raises(AssertionError, match="past the scan gate"):
            _ingest(_doc(ScanStatus.CLEAN), ExplodingStorage())

        # And specifically not the trust error.
        try:
            _ingest(_doc(ScanStatus.CLEAN), ExplodingStorage())
        except UnscannedDocumentError:  # pragma: no cover
            pytest.fail("CLEAN was refused by the scan gate")
        except AssertionError:
            pass


class TestDefaultsFailClosed:
    def test_a_document_with_no_scan_field_is_unscanned(self):
        """Records written before scanning existed, or restored from a backup,
        must not inherit trust they never earned."""
        doc = Document(
            document_id="doc-legacy",
            tenant_id="tenant-a",
            source="upload",
            storage_ref="gs://raw/tenant-a/doc-legacy/x.pdf",
        )
        assert doc.scan_status is ScanStatus.UNSCANNED

    def test_only_clean_is_processable(self):
        from schema_validators import PROCESSABLE_SCAN_STATUSES

        assert PROCESSABLE_SCAN_STATUSES == frozenset({ScanStatus.CLEAN})
