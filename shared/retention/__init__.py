"""Document retention sweep.

This is the only code in the system that deletes customer data, so it is
written defensively:

  * Opt-in only. retention_days defaults to 0, which means keep forever.
    A tenant that never touches the setting never loses anything.
  * A floor on the configured value. Retention shorter than MIN_RETENTION_DAYS
    is refused at the API, so a typo like "1" cannot wipe a tenant's active
    working set.
  * The audit trail is NEVER touched. Deleting compliance history is exactly
    what this product promises is impossible; retention applies to uploaded
    documents and their extracted fields only. Each deletion is itself
    APPENDED to that trail, so the record of what was deleted survives the
    deletion.
  * Dry-run first. sweep_tenant(dry_run=True) reports what would be removed
    without removing it, and the scheduled caller can be pointed at either.
  * Bounded per run, tenant by tenant, so a bug cannot cascade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("cg.retention")

# Refuse retention windows shorter than this. Chosen to be clearly longer
# than any plausible review cycle, so the setting cannot be used (or
# mistyped) as an instant-delete switch.
MIN_RETENTION_DAYS = 30
MAX_DOCS_PER_TENANT_PER_RUN = 500


@dataclass
class SweepResult:
    tenant_id: str
    retention_days: int
    cutoff: datetime | None = None
    considered: int = 0
    deleted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "retention_days": self.retention_days,
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "considered": self.considered,
            "deleted_count": len(self.deleted),
            "deleted": self.deleted[:50],
            "errors": self.errors[:10],
            "skipped_reason": self.skipped_reason,
            "dry_run": self.dry_run,
        }


def _delete_blob_for(storage_client, storage_ref: str) -> None:
    """Delete the GCS object behind a gs:// reference, if it still exists."""
    if not storage_ref.startswith("gs://"):
        return
    without_scheme = storage_ref[len("gs://") :]
    bucket_name, _, blob_path = without_scheme.partition("/")
    if not bucket_name or not blob_path:
        return
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    if blob.exists():
        blob.delete()


def sweep_tenant(
    *,
    tenant,
    repo,
    storage_client,
    auditor,
    now: datetime | None = None,
    dry_run: bool = False,
) -> SweepResult:
    """Apply one tenant's retention policy. Returns what happened."""
    retention_days = int(getattr(tenant, "retention_days", 0) or 0)
    result = SweepResult(
        tenant_id=tenant.tenant_id, retention_days=retention_days, dry_run=dry_run
    )

    if retention_days <= 0:
        result.skipped_reason = "retention not configured (keep forever)"
        return result
    if retention_days < MIN_RETENTION_DAYS:
        # Defensive: the API refuses these, so reaching here means a value
        # was written by some other path. Refuse rather than delete.
        result.skipped_reason = (
            f"retention_days={retention_days} below floor {MIN_RETENTION_DAYS}; refusing to sweep"
        )
        logger.warning("refusing sweep for %s: %s", tenant.tenant_id, result.skipped_reason)
        return result

    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=retention_days)
    result.cutoff = cutoff

    stale = repo.list_documents_created_before(
        tenant.tenant_id, cutoff, limit=MAX_DOCS_PER_TENANT_PER_RUN
    )
    result.considered = len(stale)

    for doc in stale:
        if dry_run:
            result.deleted.append(doc.document_id)
            continue
        try:
            _delete_blob_for(storage_client, doc.storage_ref)
            repo.delete_document(doc.document_id, tenant.tenant_id)
            result.deleted.append(doc.document_id)
            # The deletion is itself an audit event. The trail is append-only,
            # so this record cannot later be removed — deleting a document
            # never erases the evidence that it existed and was deleted.
            auditor.log(
                tenant_id=tenant.tenant_id,
                actor="retention-service",
                action="document.retention_deleted",
                dedup_key=f"{doc.document_id}:retention_deleted",
                before_state={
                    "document_id": doc.document_id,
                    "storage_ref": doc.storage_ref,
                    "created_at": doc.created_at.isoformat(),
                },
                after_state={"retention_days": retention_days, "cutoff": cutoff.isoformat()},
            )
        except Exception as exc:  # keep going; one bad doc shouldn't stop the sweep
            logger.exception("retention delete failed for %s", doc.document_id)
            result.errors.append(f"{doc.document_id}: {str(exc)[:200]}")

    return result


def sweep_all_tenants(
    *, repo, storage_client, auditor, now: datetime | None = None, dry_run: bool = False
) -> list[SweepResult]:
    """Run the sweep for every tenant that has opted in."""
    results: list[SweepResult] = []
    for tenant in repo.list_all_tenants():
        results.append(
            sweep_tenant(
                tenant=tenant,
                repo=repo,
                storage_client=storage_client,
                auditor=auditor,
                now=now,
                dry_run=dry_run,
            )
        )
    return results
