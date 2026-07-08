"""Ingestion Agent — FastAPI service (Cloud Run, stateless).

Exposes an INTERNAL endpoint invoked by the Orchestrator via Cloud Tasks:

    POST /internal/ingest   { "document_id": "...", "tenant_id": "..." }

This endpoint is not public. In production it is protected two ways:
  1. Cloud Run IAM: the service is deployed --no-allow-unauthenticated and only
     the runtime service account (which Cloud Tasks acts as via OIDC) holds
     roles/run.invoker.
  2. Defense in depth: a shared internal token header checked here, sourced
     from Secret Manager (INTERNAL_TASK_TOKEN).

tenant_id arrives in the task payload, which the Orchestrator populated from
the authenticated user's verified JWT claims — never from raw client input.
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
    storage_client,
)
from gcp_clients.firestore_repo import (
    FirestoreRepo,
    NotFoundError,
    TenantMismatchError,
)
from gemini_client import GeminiClient
from pydantic import BaseModel, Field

from ingestion_agent.extractor import ingest_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.ingestion.api")

RULESETS_ROOT = os.environ.get("RULESETS_ROOT", "/app/rulesets")

app = FastAPI(title="ComplianceGuardian Ingestion Agent", version="0.1.0")

# Lazily-initialized singletons so the module imports without credentials
# (e.g. during unit-test collection). Real clients are built on first request.
_state: dict = {}


def _deps():
    if not _state:
        _state["repo"] = FirestoreRepo(firestore_client())
        _state["storage"] = storage_client()
        _state["gemini"] = GeminiClient()
        _state["auditor"] = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
    return _state


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    # If no token is configured (local/dev), skip — Cloud Run IAM is the gate in prod.
    if expected and token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token"
        )


class IngestRequest(BaseModel):
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class IngestResponse(BaseModel):
    document_id: str
    tenant_id: str
    status: str
    extracted_fields: dict
    missing_required_fields: list[str]
    prompt_version: str
    model_name: str
    model_version: str | None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "ingestion-agent"}


@app.post("/internal/ingest", response_model=IngestResponse)
def ingest(
    req: IngestRequest,
    x_internal_token: str | None = Header(default=None),
) -> IngestResponse:
    _check_internal_token(x_internal_token)
    deps = _deps()
    try:
        outcome = ingest_document(
            document_id=req.document_id,
            tenant_id=req.tenant_id,
            repo=deps["repo"],
            storage_client=deps["storage"],
            gemini=deps["gemini"],
            auditor=deps["auditor"],
            rulesets_root=RULESETS_ROOT,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Already audited + marked failed inside ingest_document; surface 502 so
        # Cloud Tasks retries per the queue policy.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"ingestion failed: {exc}"
        ) from exc

    return IngestResponse(
        document_id=outcome.document_id,
        tenant_id=outcome.tenant_id,
        status=outcome.status.value,
        extracted_fields=outcome.extracted_fields,
        missing_required_fields=outcome.missing_required_fields,
        prompt_version=outcome.prompt_version,
        model_name=outcome.model_name,
        model_version=outcome.model_version,
    )
