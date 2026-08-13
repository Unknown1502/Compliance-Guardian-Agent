"""Scanner Agent core — scan a quarantined upload, promote it only if clean.

HTTP-agnostic like the ingestion agent's extractor, so the same code path runs
under a Cloud Task and under a local runner.

The one rule this module exists to enforce:

    a document leaves quarantine only by being scanned and found clean.

Everything else follows from it. There is no branch that writes CLEAN without a
scanner having said so, no exception handler that falls through to a pass, and
no path that copies bytes into approved storage before the verdict is known.

Idempotent: Cloud Tasks redelivers, and a redelivered scan of an already-clean
document is a no-op rather than a second copy or a second audit event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from schema_validators import DocumentStatus, ScanStatus

logger = logging.getLogger("cg.scanner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ScanOutcome:
    document_id: str
    tenant_id: str
    scan_status: ScanStatus
    threat_name: str = ""
    promoted: bool = False
    already_resolved: bool = False

    @property
    def may_process(self) -> bool:
        return self.scan_status is ScanStatus.CLEAN


class QuarantineReadError(Exception):
    """The quarantined bytes could not be read. Never treated as clean."""


def _split_gs(ref: str) -> tuple[str, str]:
    parsed = urlparse(ref)
    if parsed.scheme != "gs":
        raise QuarantineReadError(f"not a gs:// URI: {ref!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def scan_document(
    *,
    document_id: str,
    tenant_id: str,
    repo,
    storage_client,
    scanner,
    auditor,
    approved_bucket: str,
) -> ScanOutcome:
    """Scan one quarantined document and promote it if — and only if — clean."""
    document = repo.get_document(document_id, tenant_id)  # raises on tenant mismatch

    # Redelivery of a scan that already succeeded. Returning early keeps the
    # copy and the audit event single, and avoids re-reading a quarantine
    # object that promotion has already deleted.
    if document.scan_status is ScanStatus.CLEAN:
        return ScanOutcome(
            document_id=document_id,
            tenant_id=tenant_id,
            scan_status=ScanStatus.CLEAN,
            already_resolved=True,
        )

    started = _utcnow()
    repo.update_document_fields(
        document_id,
        tenant_id,
        {"scan_status": ScanStatus.SCANNING, "scan_started_at": started},
    )

    source_ref = document.quarantine_ref or document.storage_ref
    try:
        bucket_name, blob_path = _split_gs(source_ref)
        blob = storage_client.bucket(bucket_name).blob(blob_path)
        data = blob.download_as_bytes()
    except Exception as exc:
        # Cannot read it, so cannot clear it. The record is marked failed and
        # the bytes stay exactly where they are.
        logger.exception("could not read quarantined object for %s", document_id)
        return _resolve(
            repo=repo,
            auditor=auditor,
            document=document,
            status=ScanStatus.SCAN_FAILED,
            started=started,
            scanner_name=getattr(scanner, "name", "unknown"),
            scanner_version="",
            threat_name="",
            detail=f"quarantine read failed: {exc}",
        )

    scanner_version = ""
    try:
        scanner_version = scanner.version()
    except Exception:  # a missing version must not fail the scan
        logger.warning("could not read scanner version", exc_info=True)

    try:
        verdict = scanner.scan(data)
    except Exception as exc:
        logger.exception("scanner raised for %s", document_id)
        return _resolve(
            repo=repo,
            auditor=auditor,
            document=document,
            status=ScanStatus.SCAN_FAILED,
            started=started,
            scanner_name=getattr(scanner, "name", "unknown"),
            scanner_version=scanner_version,
            threat_name="",
            detail=f"scanner error: {exc}",
        )

    if not verdict.is_clean:
        # Infected, failed or timed out. The object is deliberately left in
        # quarantine rather than deleted: an infected upload is evidence, and
        # deleting it would destroy the only copy an incident review has.
        return _resolve(
            repo=repo,
            auditor=auditor,
            document=document,
            status=verdict.status,
            started=started,
            scanner_name=getattr(scanner, "name", "unknown"),
            scanner_version=scanner_version,
            threat_name=verdict.threat_name,
            detail=verdict.detail,
        )

    # Clean. Copy into approved storage first, and only then record CLEAN —
    # if the copy fails the document stays untrusted, which is the safe way
    # round. The reverse order would leave a record claiming a readable file
    # that does not exist.
    approved_path = blob_path
    try:
        source_bucket = storage_client.bucket(bucket_name)
        storage_client.bucket(approved_bucket).blob(approved_path).upload_from_string(
            data, content_type=document.content_type or "application/octet-stream"
        )
    except Exception as exc:
        logger.exception("promotion copy failed for %s", document_id)
        return _resolve(
            repo=repo,
            auditor=auditor,
            document=document,
            status=ScanStatus.SCAN_FAILED,
            started=started,
            scanner_name=getattr(scanner, "name", "unknown"),
            scanner_version=scanner_version,
            threat_name="",
            detail=f"promotion failed: {exc}",
        )

    approved_ref = f"gs://{approved_bucket}/{approved_path}"
    finished = _utcnow()
    repo.update_document_fields(
        document_id,
        tenant_id,
        {
            "scan_status": ScanStatus.CLEAN,
            "scanner": getattr(scanner, "name", "unknown"),
            "scanner_version": scanner_version,
            "scan_completed_at": finished,
            "threat_name": "",
            # storage_ref now points at approved storage, so every downstream
            # reader is reading the copy that was cleared.
            "storage_ref": approved_ref,
            "quarantine_ref": "",
        },
    )

    # Best-effort: the promoted copy is authoritative from here, and a
    # leftover quarantine object is a lifecycle-rule problem, not a
    # correctness one.
    try:
        source_bucket.blob(blob_path).delete()
    except Exception:
        logger.warning("could not delete quarantine object %s", source_ref, exc_info=True)

    _audit(
        auditor,
        document=document,
        action="document.scan_cleared",
        after={
            "scan_status": ScanStatus.CLEAN.value,
            "scanner": getattr(scanner, "name", "unknown"),
            "scanner_version": scanner_version,
            "storage_ref": approved_ref,
            "content_hash": document.content_hash,
        },
    )
    return ScanOutcome(
        document_id=document_id,
        tenant_id=tenant_id,
        scan_status=ScanStatus.CLEAN,
        promoted=True,
    )


def _resolve(
    *,
    repo,
    auditor,
    document,
    status: ScanStatus,
    started: datetime,
    scanner_name: str,
    scanner_version: str,
    threat_name: str,
    detail: str,
) -> ScanOutcome:
    """Record a non-clean outcome. The bytes are not moved and not deleted."""
    updates = {
        "scan_status": status,
        "scanner": scanner_name,
        "scanner_version": scanner_version,
        "scan_started_at": started,
        "scan_completed_at": _utcnow(),
        "threat_name": threat_name[:200],
    }
    if status is ScanStatus.INFECTED:
        # A rejected upload is terminal; nothing will ever process it.
        updates["status"] = DocumentStatus.FAILED
    repo.update_document_fields(document.document_id, document.tenant_id, updates)

    _audit(
        auditor,
        document=document,
        action="document.scan_rejected"
        if status is ScanStatus.INFECTED
        else "document.scan_failed",
        after={
            "scan_status": status.value,
            "scanner": scanner_name,
            "scanner_version": scanner_version,
            # Recorded for operators. The API never returns threat_name to the
            # uploader — naming the signature tells an attacker which sample
            # got through and which did not.
            "threat_name": threat_name,
            "detail": detail[:300],
            "content_hash": document.content_hash,
        },
    )
    logger.warning(
        "document %s not cleared: %s %s", document.document_id, status.value, threat_name
    )
    return ScanOutcome(
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        scan_status=status,
        threat_name=threat_name,
    )


def _audit(auditor, *, document, action: str, after: dict) -> None:
    if auditor is None:
        return
    try:
        auditor.log(
            tenant_id=document.tenant_id,
            actor="scanner-agent",
            action=action,
            dedup_key=f"{document.document_id}:{action}",
            before_state=None,
            after_state={"document_id": document.document_id, **after},
        )
    except Exception:
        # An audit write must not turn a correct rejection into a crash that
        # a retry might resolve differently.
        logger.exception("could not write scan audit event for %s", document.document_id)
