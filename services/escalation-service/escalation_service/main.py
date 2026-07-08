"""Escalation Service — FastAPI (Cloud Run, stateless).

Internal endpoints (invoked by the Orchestrator via Cloud Tasks, or by the API
Gateway for the reviewer decision path):

    POST /internal/escalate   { check_id, tenant_id, document_id, risk_score }
        Records a reviewer notification for an escalated check.

    POST /internal/decisions  { check_id, tenant_id, reviewer_id, approve }
        Applies a concurrency-safe approve/reject and audits it.

Both are protected by Cloud Run IAM + the internal token header, like the other
agents. tenant_id always arrives from a trusted upstream (JWT claims), never raw
client input.
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
)
from gcp_clients.firestore_repo import (
    DecisionConflictError,
    FirestoreRepo,
    NotFoundError,
    TenantMismatchError,
)
from pydantic import BaseModel, Field

from escalation_service.decisions import apply_decision
from escalation_service.notifications import AuditNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.escalation.api")

app = FastAPI(title="ComplianceGuardian Escalation Service", version="0.1.0")

_state: dict = {}


def _deps():
    if not _state:
        db = firestore_client()
        auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
        _state["repo"] = FirestoreRepo(db)
        _state["auditor"] = auditor
        _state["notifier"] = AuditNotifier(db, auditor)
    return _state


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token")


class EscalateRequest(BaseModel):
    check_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    risk_score: int = Field(ge=0, le=100)


class DecisionRequest(BaseModel):
    check_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    approve: bool


class DecisionResponse(BaseModel):
    check_id: str
    decision: str
    reviewer_id: str | None
    action: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "escalation-service"}


@app.post("/internal/escalate")
def escalate(req: EscalateRequest, x_internal_token: str | None = Header(default=None)) -> dict:
    _check_internal_token(x_internal_token)
    deps = _deps()
    deps["notifier"].notify_escalation(
        tenant_id=req.tenant_id,
        check_id=req.check_id,
        document_id=req.document_id,
        risk_score=req.risk_score,
    )
    return {"status": "notified", "check_id": req.check_id}


@app.post("/internal/decisions", response_model=DecisionResponse)
def decide(req: DecisionRequest, x_internal_token: str | None = Header(default=None)) -> DecisionResponse:
    _check_internal_token(x_internal_token)
    deps = _deps()
    try:
        result = apply_decision(
            repo=deps["repo"],
            auditor=deps["auditor"],
            check_id=req.check_id,
            tenant_id=req.tenant_id,
            reviewer_id=req.reviewer_id,
            approve=req.approve,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DecisionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return DecisionResponse(
        check_id=result.check.check_id,
        decision=result.check.decision.value,
        reviewer_id=result.check.reviewer_id,
        action=result.action,
    )
