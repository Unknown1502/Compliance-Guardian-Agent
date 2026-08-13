"""Scanner Agent — FastAPI service (Cloud Run, stateless).

Exposes an INTERNAL endpoint invoked by the Orchestrator via Cloud Tasks:

    POST /internal/scan   { "document_id": "...", "tenant_id": "..." }

Protected the same two ways as the other agents: Cloud Run IAM
(--no-allow-unauthenticated, only the runtime service account holds
roles/run.invoker) plus the shared INTERNAL_TASK_TOKEN header.

This service is the only writer that may set scan_status=CLEAN, and the only
identity granted read on the quarantine bucket. Both halves matter: the first
means the application layer cannot mark its own uploads safe, and the second
means a bug elsewhere cannot hand a worker unscanned bytes, because no other
service account can read them.

On a non-clean verdict this returns 200, not an error. The scan *succeeded* —
it found the file unfit to process — and a 5xx would make Cloud Tasks retry a
decision that will not change, eventually landing the task in the dead-letter
queue as though the system had malfunctioned.
"""

from __future__ import annotations

import logging
import os

from audit_logger import AuditLogger
from fastapi import FastAPI, Header, HTTPException, status
from gcp_clients import (
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    raw_docs_bucket,
    storage_client,
)
from gcp_clients.firestore_repo import (
    FirestoreRepo,
    NotFoundError,
    TenantMismatchError,
)
from orchestrator.tasks import TaskService
from pydantic import BaseModel, Field
from schema_validators import TaskType
from task_dispatch import CloudTasksDispatcher

from scanner_agent.clamav import ClamAVScanner
from scanner_agent.scanner import scan_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.scanner.api")

CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "127.0.0.1")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))
CLAMAV_TIMEOUT = float(os.environ.get("CLAMAV_TIMEOUT_SECONDS", "120"))

app = FastAPI(title="ComplianceGuardian Scanner Agent", version="0.1.0")

_state: dict = {}


def _deps():
    if not _state:
        repo = FirestoreRepo(firestore_client())
        auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
        _state["repo"] = repo
        _state["storage"] = storage_client()
        _state["auditor"] = auditor
        _state["scanner"] = ClamAVScanner(CLAMAV_HOST, CLAMAV_PORT, CLAMAV_TIMEOUT)
        _state["tasks"] = TaskService(
            repo=repo,
            dispatcher=CloudTasksDispatcher(
                project=os.environ["GOOGLE_CLOUD_PROJECT"],
                location=os.environ.get("CLOUD_TASKS_LOCATION", "us-central1"),
                queue=os.environ.get("CLOUD_TASKS_QUEUE", "cg-task-queue"),
                # Only ingest: the scanner never dispatches a scan, so a
                # misconfiguration cannot produce a scan loop.
                target_urls={"ingest": os.environ.get("INGESTION_URL", "")},
                invoker_service_account=os.environ.get("INVOKER_SA", ""),
                internal_token=os.environ.get("INTERNAL_TASK_TOKEN"),
            ),
            auditor=auditor,
        )
    return _state


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token"
        )


class ScanRequest(BaseModel):
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class ScanResponse(BaseModel):
    document_id: str
    tenant_id: str
    scan_status: str
    promoted: bool
    # Deliberately no threat_name: the signature that matched goes to the audit
    # trail and the operator console, never to an API response an uploader can
    # read. Naming it tells an attacker which sample evaded detection.


@app.get("/healthz")
@app.get("/internal/healthz")
def healthz() -> dict:
    """Liveness only.

    Registered on both paths because a bare /healthz on this project is
    answered by a Google frontend 404 before it ever reaches the container —
    a probe on it reports a permanent fake outage. /internal/healthz gets
    through. Same trap already documented for the gateway's /api/healthz.

    Does NOT probe clamd. If the signature daemon is down this service must
    stay up and keep answering — it will return SCAN_FAILED for each document
    and hold them in quarantine, which is the behaviour we want. Reporting
    itself unhealthy would take the container out of rotation and turn a
    contained failure into a silent backlog with no record of why.
    """
    return {"status": "ok", "service": "scanner-agent"}


@app.get("/internal/scanner-status")
def scanner_status(x_internal_token: str | None = Header(default=None)) -> dict:
    """Operational view of the signature daemon, for alerting.

    Separate from /healthz precisely because a down scanner is an operational
    emergency but not a reason to restart this container.
    """
    _check_internal_token(x_internal_token)
    scanner = _deps()["scanner"]
    reachable = scanner.ping()
    return {
        "scanner": scanner.name,
        "reachable": reachable,
        "version": scanner.version() if reachable else "",
    }


@app.post("/internal/scan", response_model=ScanResponse)
def scan(
    req: ScanRequest,
    x_internal_token: str | None = Header(default=None),
) -> ScanResponse:
    _check_internal_token(x_internal_token)
    deps = _deps()
    try:
        outcome = scan_document(
            document_id=req.document_id,
            tenant_id=req.tenant_id,
            repo=deps["repo"],
            storage_client=deps["storage"],
            scanner=deps["scanner"],
            auditor=deps["auditor"],
            approved_bucket=raw_docs_bucket(),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # An unexpected fault here left the document in whatever state it was
        # in — never CLEAN, since only the success path writes that. A 502
        # lets Cloud Tasks retry.
        logger.exception("scan failed for %s", req.document_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"scan failed: {exc}"
        ) from exc

    # Only a freshly-promoted file continues to ingestion. `already_resolved`
    # is excluded so a redelivered scan does not queue a second ingest.
    if outcome.promoted:
        _dispatch_ingest(req.document_id, req.tenant_id)

    return ScanResponse(
        document_id=outcome.document_id,
        tenant_id=outcome.tenant_id,
        scan_status=outcome.scan_status.value,
        promoted=outcome.promoted,
    )


def _dispatch_ingest(document_id: str, tenant_id: str) -> None:
    """Hand a cleared document to ingestion.

    Failure here is logged, not raised. The file is already promoted and
    recorded CLEAN, so raising would make Cloud Tasks retry the whole scan —
    which would find the document already clean, return early, and never
    dispatch the ingest anyway. A stuck-but-clean document is visible in the
    task list and recoverable by re-triggering; a retry storm is not.
    """
    try:
        _deps()["tasks"].create_and_dispatch(
            task_type=TaskType.INGEST, target_ref=document_id, tenant_id=tenant_id
        )
    except Exception:
        logger.exception(
            "document %s cleared but ingest dispatch failed; needs re-trigger", document_id
        )
