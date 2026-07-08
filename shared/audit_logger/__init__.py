"""Append-only audit logger for BigQuery.

Design decisions (Phase 1 Thinking Protocol):

  Idempotency / dedup — Cloud Tasks redelivery means the same logical event can
  be written twice. Every audit event therefore gets a DETERMINISTIC event_id
  (uuid5 over tenant + actor + action + logical dedup key supplied by the
  caller), and that event_id doubles as the BigQuery streaming `insertId`,
  which BigQuery uses for best-effort dedup within its dedup window. Replays
  produce the same insertId → deduped, not duplicated.

  Append-only — enforced at the IAM layer (see infra/terraform/iam.tf): the
  runtime service account holds a custom role with dataEditor-style INSERT
  permission but no bigquery.jobs.create, so it cannot run UPDATE/DELETE DML.
  App code contains no update/delete path at all.

  Failure visibility — audit logging must never crash the business flow, but
  it must also never fail silently: on insert failure we log loudly and expose
  the failure to the caller via AuditWriteError so agents can route the event
  to their Gemini-failure branch (which itself audits to a fallback path).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from google.cloud import bigquery

from schema_validators import AuditLogRow

logger = logging.getLogger("cg.audit")

# Stable namespace for deterministic event IDs (uuid5). Do not change once live.
_AUDIT_NAMESPACE = uuid.UUID("2f9b6a54-8f0e-4d7c-9be1-5f1a2b3c4d5e")


class AuditWriteError(RuntimeError):
    """Raised when the audit row could not be inserted after retries."""


def deterministic_event_id(tenant_id: str, actor: str, action: str, dedup_key: str) -> str:
    """Same logical event → same event_id → BigQuery insertId dedup on replay."""
    return str(uuid.uuid5(_AUDIT_NAMESPACE, f"{tenant_id}|{actor}|{action}|{dedup_key}"))


def _json_safe(state: dict[str, Any] | None) -> str | None:
    if state is None:
        return None
    return json.dumps(state, default=str, ensure_ascii=False, sort_keys=True)


class AuditLogger:
    """Writes validated AuditLogRow records to BigQuery via streaming inserts."""

    def __init__(
        self,
        client: bigquery.Client,
        dataset: str,
        table: str,
        max_attempts: int = 3,
    ) -> None:
        self._client = client
        self._table_ref = f"{client.project}.{dataset}.{table}"
        self._max_attempts = max_attempts

    def log(
        self,
        *,
        tenant_id: str,
        actor: str,
        action: str,
        dedup_key: str,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> AuditLogRow:
        """Validate and insert one audit event. Returns the row as written.

        dedup_key must identify the logical event (e.g. document_id for an
        ingestion event, check_id+revision for a decision) so that Cloud Task
        redelivery reproduces the same event_id.
        """
        row = AuditLogRow(
            event_id=deterministic_event_id(tenant_id, actor, action, dedup_key),
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            before_state=before_state,
            after_state=after_state,
            **({"created_at": created_at} if created_at is not None else {}),
        )
        payload = {
            "event_id": row.event_id,
            "tenant_id": row.tenant_id,
            "actor": row.actor,
            "action": row.action,
            "before_state": _json_safe(row.before_state),
            "after_state": _json_safe(row.after_state),
            "created_at": row.created_at.isoformat(),
        }

        last_errors: Any = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                errors = self._client.insert_rows_json(
                    self._table_ref,
                    [payload],
                    row_ids=[row.event_id],  # streaming insertId → replay dedup
                )
            except Exception as exc:  # network/API failure — retry
                last_errors = exc
                logger.warning(
                    "audit insert attempt %d/%d failed: %s",
                    attempt,
                    self._max_attempts,
                    exc,
                )
                continue
            if not errors:
                return row
            last_errors = errors
            logger.warning(
                "audit insert attempt %d/%d returned row errors: %s",
                attempt,
                self._max_attempts,
                errors,
            )

        logger.error("audit insert FAILED after %d attempts: %s", self._max_attempts, last_errors)
        raise AuditWriteError(f"failed to write audit event {row.event_id}: {last_errors}")
