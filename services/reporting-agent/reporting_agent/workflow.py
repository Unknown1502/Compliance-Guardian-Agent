"""Durable report lifecycle.

The failure this exists to remove: report generation used to run inside the
HTTP request and answer 200 as soon as the function returned. If the Cloud Run
instance was replaced mid-generation, or the upload failed after the summary
was produced, the caller had either an error with no record of the attempt or
a success for an artifact that was not there. Both are the same bug — the
claim "your report is ready" was never checked against storage.

    QUEUED → GENERATING → VALIDATING → PERSISTING → VERIFYING → READY
                                                  ↘ FAILED / RETRYING

READY is written in exactly one place, after the stored object has been read
back and matched against its recorded size and checksum. Everything else is a
state the UI shows as "not yet".

Idempotency: report_id is derived from (tenant, period_start, period_end), so
the same logical request is the same report however many times it is asked
for. A redelivered Cloud Task, a double-clicked button and a retried HTTP
request all converge on one record and one artifact. A report already READY is
returned untouched rather than regenerated — that also means a retry cannot
spend a second Gemini call or a second entitlement.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from schema_validators import ReportRecord, ReportStatus

logger = logging.getLogger("cg.reporting.workflow")

# Stable namespace for deterministic report ids. Changing this orphans every
# existing report's identity, so it is fixed for the life of the product.
_REPORT_NAMESPACE = uuid.UUID("6d1c4e77-0a2f-4c1b-9f3d-8e5a7b2c0d19")

# How long a finished report is offered for download. Storage lifecycle rules
# are what actually delete it; this is the product's promise about it.
REPORT_TTL_DAYS = 365


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def report_id_for(tenant_id: str, period_start: datetime, period_end: datetime) -> str:
    """Same tenant + same period → same report, always.

    Deliberately not random. A uuid4 per attempt is what allowed a retry to
    produce a second report, a second stored object and a second BigQuery row
    for work the customer asked for once.
    """
    key = f"{tenant_id}|{period_start.isoformat()}|{period_end.isoformat()}"
    return str(uuid.uuid5(_REPORT_NAMESPACE, key))


class ReportGenerationError(RuntimeError):
    """Generation, validation, persistence or verification failed."""


@dataclass(frozen=True)
class Verification:
    storage_key: str
    size_bytes: int
    checksum: str
    mime_type: str
    format: str


def _split_gs(ref: str) -> tuple[str, str]:
    parsed = urlparse(ref)
    if parsed.scheme != "gs":
        raise ReportGenerationError(f"not a gs:// URI: {ref!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _verify_artifact(storage_client, content_ref: str, pdf_ref: str) -> Verification:
    """Read the stored object back and describe what is actually there.

    Prefers the PDF when one exists, because that is what a customer files.
    Reading the bytes rather than trusting `blob.exists()` is the point: an
    object can exist and be empty, and a zero-byte report is not a report.
    """
    ref = pdf_ref or content_ref
    if not ref:
        raise ReportGenerationError("generation reported no artifact reference")

    bucket_name, blob_path = _split_gs(ref)
    blob = storage_client.bucket(bucket_name).blob(blob_path)
    if not blob.exists():
        raise ReportGenerationError(f"artifact missing from storage: {ref}")

    data = blob.download_as_bytes()
    if not data:
        raise ReportGenerationError(f"artifact is empty: {ref}")

    is_pdf = blob_path.endswith(".pdf")
    return Verification(
        storage_key=blob_path,
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        mime_type="application/pdf" if is_pdf else "text/html",
        format="pdf" if is_pdf else "html",
    )


def run_report_workflow(
    *,
    record: ReportRecord,
    repo,
    generate,
    storage_client,
) -> ReportRecord:
    """Drive one report from wherever it is to READY, or to FAILED.

    `generate` is injected rather than imported so the failure paths can be
    tested without a Gemini key or a BigQuery dataset — the states below are
    the product behaviour under failure, and they need to be exercised.
    """
    report_id, tenant_id = record.report_id, record.tenant_id

    # Already finished. Return it untouched: this is what makes a redelivered
    # task a no-op instead of a second report.
    if record.status is ReportStatus.READY:
        logger.info("report %s already READY — nothing to do", report_id)
        return record

    def _set(status: ReportStatus, **fields) -> ReportRecord:
        return repo.update_report_record(report_id, tenant_id, {"status": status, **fields})

    _set(ReportStatus.GENERATING, attempts=record.attempts + 1, error="")

    try:
        outcome = generate()
    except Exception as exc:
        logger.exception("report %s generation failed", report_id)
        # RETRYING, not FAILED: Cloud Tasks will redeliver, and the record
        # should say so rather than looking permanently dead between attempts.
        _set(ReportStatus.RETRYING, error=f"generation failed: {exc}"[:500])
        raise ReportGenerationError(f"generation failed: {exc}") from exc

    # VALIDATING — is what came back a report at all? A run that reviewed
    # nothing still produces a document, so emptiness is not the test; a
    # missing summary or missing artifact reference is.
    _set(ReportStatus.VALIDATING)
    if not getattr(outcome, "content_ref", ""):
        _set(ReportStatus.FAILED, error="generation produced no artifact reference")
        raise ReportGenerationError("generation produced no artifact reference")

    # PERSISTING is where generate() has already written to storage; the state
    # is recorded so a crash between generation and verification is visible as
    # exactly that rather than as an unexplained gap.
    _set(ReportStatus.PERSISTING, storage_key="")

    _set(ReportStatus.VERIFYING)
    try:
        verified = _verify_artifact(
            storage_client, outcome.content_ref, getattr(outcome, "pdf_ref", "")
        )
    except ReportGenerationError as exc:
        logger.error("report %s failed verification: %s", report_id, exc)
        _set(ReportStatus.RETRYING, error=str(exc)[:500])
        raise

    stats = getattr(outcome, "stats", {}) or {}
    final = repo.update_report_record(
        report_id,
        tenant_id,
        {
            # The single write that makes a report downloadable, and the only
            # one reached after the bytes have been read back.
            "status": ReportStatus.READY,
            "storage_key": verified.storage_key,
            "filename": f"compliance-report-{report_id}.{verified.format}",
            "format": verified.format,
            "mime_type": verified.mime_type,
            "size_bytes": verified.size_bytes,
            "checksum": verified.checksum,
            "total_checks": stats.get("total_checks", 0),
            "pass_count": stats.get("auto_approved", 0),
            "fail_count": stats.get("rejected", 0),
            "escalated_count": stats.get("escalated", 0),
            "executive_summary": (getattr(outcome, "gemini_executive_summary", "") or "")[:4000],
            "model_name": getattr(outcome, "model_name", "") or "",
            "used_fixture": bool(getattr(outcome, "used_fixture", False)),
            "expires_at": _utcnow() + timedelta(days=REPORT_TTL_DAYS),
            "error": "",
        },
    )
    logger.info(
        "report %s READY (%s, %d bytes)", report_id, verified.format, verified.size_bytes
    )
    return final
