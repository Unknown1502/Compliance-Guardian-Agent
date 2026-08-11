"""Reporting Agent — FastAPI service (Cloud Run, stateless).

Endpoints:
    POST /internal/report   { tenant_id, period_start, period_end }
        Generates a report for the period and writes HTML to GCS + BQ row.
        Invoked by the API Gateway (on-demand) or Cloud Workflows (scheduled).

    GET  /internal/report-tenants
        Which tenants the weekly workflow should generate for. Exists so the
        scheduled run follows the real customer list instead of a hardcoded
        one; see the endpoint for why the filter lives here and not in YAML.

    GET  /reports/{report_id}/html
        Proxies the report HTML from GCS for dashboard display.

Both endpoints protected by the internal token header; the public surface
(`GET /api/reports/{id}`) lives in the API Gateway with full Firebase Auth.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from audit_logger import AuditLogger
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from gcp_clients import (
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    project_id,
    reports_table,
    storage_client,
)
from gcp_clients.firestore_repo import FirestoreRepo
from gemini_client import GeminiClient, GeminiConfigError
from pydantic import BaseModel, Field
from schema_validators import EntitlementSource, TenantStatus

from reporting_agent.reporter import generate_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.reporting.api")

app = FastAPI(title="ComplianceGuardian Reporting Agent", version="0.1.0")

_state: dict = {}


def _deps() -> dict:
    if not _state:
        _state["db"] = firestore_client()
        _state["repo"] = FirestoreRepo(_state["db"])
        _state["bq"] = bigquery_client()
        _state["storage"] = storage_client()
        _state["auditor"] = AuditLogger(_state["bq"], audit_dataset(), audit_table())
        try:
            _state["gemini"] = GeminiClient()
        except GeminiConfigError:
            logger.warning("GEMINI_API_KEY not set — reports will use fixture summaries")
            _state["gemini"] = None
    return _state


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token")


class ReportRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    period_start: datetime
    period_end: datetime
    generated_by: str = Field(default="reporting-agent")


class ReportResponse(BaseModel):
    report_id: str
    tenant_id: str
    period_start: str
    period_end: str
    content_ref: str
    total_checks: int
    pass_count: int
    fail_count: int
    escalated_count: int
    executive_summary: str
    prompt_version: str
    model_name: str
    model_version: str | None
    used_fixture: bool


class ReportTenantsResponse(BaseModel):
    tenant_ids: list[str]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "reporting-agent"}


@app.get("/internal/report-tenants", response_model=ReportTenantsResponse)
def list_report_tenants(
    x_internal_token: str | None = Header(default=None),
) -> ReportTenantsResponse:
    """Tenants the weekly workflow should generate a scheduled report for.

    Narrower than "every tenant", on purpose:

      * SUSPENDED workspaces are excluded. Suspension stops a workspace being
        used; quietly continuing to produce its reports would contradict that.
      * Only PRO workspaces are included. A recurring report is the thing a
        subscription buys — a FREE or one-time workspace has not bought it,
        and generating one anyway spends Gemini quota to give away the paid
        feature.

    The filter lives here rather than in the workflow YAML because Cloud
    Workflows cannot see the Tenant model, and a rule this close to billing
    belongs in code that can be tested. Scheduled generation deliberately does
    not touch consume_report_entitlement: that counter meters what a customer
    asks for, and an automated run they did not request must not spend it.
    """
    _check_internal_token(x_internal_token)
    tenants = _deps()["repo"].list_all_tenants()
    return ReportTenantsResponse(
        tenant_ids=[
            t.tenant_id
            for t in tenants
            if t.status is TenantStatus.ACTIVE
            and t.entitlement_source is EntitlementSource.PRO
        ]
    )


@app.post("/internal/report", response_model=ReportResponse)
def create_report(
    req: ReportRequest, x_internal_token: str | None = Header(default=None)
) -> ReportResponse:
    _check_internal_token(x_internal_token)
    if req.period_start >= req.period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_start must be before period_end",
        )
    deps = _deps()
    outcome = generate_report(
        tenant_id=req.tenant_id,
        period_start=req.period_start,
        period_end=req.period_end,
        db=deps["db"],
        bq_client=deps["bq"],
        storage_client=deps["storage"],
        auditor=deps["auditor"],
        gemini=deps["gemini"],
        bq_dataset=audit_dataset(),
        bq_reports_table=reports_table(),
        bq_project=project_id(),
        generated_by=req.generated_by,
    )
    s = outcome.stats
    return ReportResponse(
        report_id=outcome.report_id,
        tenant_id=outcome.tenant_id,
        period_start=outcome.period_start.isoformat(),
        period_end=outcome.period_end.isoformat(),
        content_ref=outcome.content_ref,
        total_checks=s.get("total_checks", 0),
        pass_count=s.get("auto_approved", 0),
        fail_count=s.get("rejected", 0),
        escalated_count=s.get("escalated", 0),
        executive_summary=outcome.gemini_executive_summary,
        prompt_version=outcome.prompt_version,
        model_name=outcome.model_name,
        model_version=outcome.model_version,
        used_fixture=outcome.used_fixture,
    )


@app.get("/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(
    report_id: str,
    tenant_id: str,
    x_internal_token: str | None = Header(default=None),
) -> HTMLResponse:
    """Proxies the report HTML from GCS for dashboard rendering."""
    _check_internal_token(x_internal_token)
    from gcp_clients import reports_bucket

    deps = _deps()
    blob_path = f"{tenant_id}/{report_id}/report.html"
    bucket = deps["storage"].bucket(reports_bucket())
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return HTMLResponse(content=blob.download_as_text())
