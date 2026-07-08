"""Compliance Agent — FastAPI service (Cloud Run, stateless).

Internal endpoint invoked by the Orchestrator via Cloud Tasks:

    POST /internal/check   { "document_id": "...", "tenant_id": "..." }

Protection identical to the ingestion agent: Cloud Run IAM (primary) plus an
internal token header (defense in depth). tenant_id comes from the task
payload, which the Orchestrator populated from verified JWT claims.
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
    FirestoreRepo,
    NotFoundError,
    TenantMismatchError,
)
from gemini_client import GeminiClient
from pydantic import BaseModel, Field

from compliance_agent.checker import (
    DocumentNotProcessedError,
    run_compliance_check,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.compliance.api")

RULESETS_ROOT = os.environ.get("RULESETS_ROOT", "/app/rulesets")
ESCALATION_THRESHOLD = int(os.environ.get("RISK_ESCALATION_THRESHOLD", "60"))

app = FastAPI(title="ComplianceGuardian Compliance Agent", version="0.1.0")

_state: dict = {}


def _deps():
    if not _state:
        _state["repo"] = FirestoreRepo(firestore_client())
        _state["gemini"] = GeminiClient()
        _state["auditor"] = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
    return _state


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token"
        )


class CheckRequest(BaseModel):
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class RuleVerdictOut(BaseModel):
    rule_id: str
    status: str
    confidence: float
    explanation: str
    triggering_data_point: str | None


class CheckResponse(BaseModel):
    check_id: str
    document_id: str
    tenant_id: str
    rule_set_version: str
    risk_score: int
    gemini_raw_risk_score: int
    justification: str
    citations: list[str]
    decision: str
    rule_verdicts: list[RuleVerdictOut]
    prompt_version: str
    model_name: str
    model_version: str | None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "compliance-agent"}


@app.post("/internal/check", response_model=CheckResponse)
def check(
    req: CheckRequest,
    x_internal_token: str | None = Header(default=None),
) -> CheckResponse:
    _check_internal_token(x_internal_token)
    deps = _deps()
    try:
        outcome = run_compliance_check(
            document_id=req.document_id,
            tenant_id=req.tenant_id,
            repo=deps["repo"],
            gemini=deps["gemini"],
            auditor=deps["auditor"],
            rulesets_root=RULESETS_ROOT,
            escalation_threshold=ESCALATION_THRESHOLD,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DocumentNotProcessedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"compliance check failed: {exc}"
        ) from exc

    c = outcome.check
    return CheckResponse(
        check_id=c.check_id,
        document_id=c.document_id,
        tenant_id=c.tenant_id,
        rule_set_version=c.rule_set_version,
        risk_score=c.risk_score,
        gemini_raw_risk_score=outcome.gemini_raw_risk_score,
        justification=c.justification,
        citations=c.citations,
        decision=c.decision.value,
        rule_verdicts=[
            RuleVerdictOut(
                rule_id=v.rule_id,
                status=v.status.value,
                confidence=v.confidence,
                explanation=v.explanation,
                triggering_data_point=v.triggering_data_point,
            )
            for v in c.rule_verdicts
        ],
        prompt_version=c.gemini_metadata.prompt_version if c.gemini_metadata else "",
        model_name=c.gemini_metadata.model_name if c.gemini_metadata else "",
        model_version=c.gemini_metadata.model_version if c.gemini_metadata else None,
    )
