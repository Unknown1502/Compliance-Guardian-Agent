"""Audit Writer — the only path by which the gateway reaches the audit trail.

Exists for one reason: to hold the append permission that the gateway must not
have. A BigQuery streaming insert needs `bigquery.tables.updateData`; a DML
statement needs that plus `bigquery.jobs.create`. The gateway needs
jobs.create for six read paths, so leaving it the append permission as well
would leave it able to UPDATE or DELETE historical compliance evidence — not
through any endpoint that exists, but the guarantee has to be "cannot", not
"does not".

So the permissions are split across two identities that each hold half:

    cg-gateway        jobs.create + read      → can SELECT, cannot append
    cg-audit-writer   append only             → can insert, cannot run a statement

Neither can rewrite history, and no single compromised identity gains the
ability to.

This service takes an already-formed event. It deliberately does NOT
re-derive event_id: that id is a function of the logical event and is what
BigQuery dedupes replays on, so computing it here from request data would
break idempotency for Cloud Task redelivery.
"""

from __future__ import annotations

import logging
import os

from audit_logger import AuditWriteError
from fastapi import FastAPI, Header, HTTPException, status
from gcp_clients import audit_dataset, audit_table, bigquery_client, project_id
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.audit.writer")

app = FastAPI(title="ComplianceGuardian Audit Writer", version="0.1.0")

_state: dict = {}


def _client():
    if "bq" not in _state:
        _state["bq"] = bigquery_client()
        _state["table"] = f"{project_id()}.{audit_dataset()}.{audit_table()}"
    return _state["bq"], _state["table"]


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token"
        )


class AuditEvent(BaseModel):
    """Pre-formed row. event_id is supplied, never generated here."""

    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    before_state: str | None = None
    after_state: str | None = None
    created_at: str = Field(min_length=1)


@app.get("/internal/healthz")
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "audit-writer"}


@app.post("/internal/audit", status_code=status.HTTP_201_CREATED)
def write_audit(
    event: AuditEvent,
    x_internal_token: str | None = Header(default=None),
) -> dict:
    _check_internal_token(x_internal_token)
    client, table = _client()

    payload = event.model_dump()
    try:
        # row_ids carries event_id as the streaming insertId, so a redelivered
        # event dedupes inside BigQuery's window exactly as it did when the
        # gateway inserted directly.
        errors = client.insert_rows_json(table, [payload], row_ids=[event.event_id])
    except Exception as exc:  # noqa: BLE001
        logger.exception("audit insert raised for %s", event.event_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="audit insert failed"
        ) from exc

    if errors:
        logger.error("audit insert returned row errors for %s: %s", event.event_id, errors)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="audit insert rejected"
        )
    return {"event_id": event.event_id, "written": True}


__all__ = ["app", "AuditWriteError"]
