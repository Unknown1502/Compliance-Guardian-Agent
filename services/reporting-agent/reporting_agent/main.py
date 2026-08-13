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
from schema_validators import EntitlementSource, ReportRecord, ReportStatus, TenantStatus

from reporting_agent.reporter import generate_report
from reporting_agent.workflow import (
    ReportGenerationError,
    report_id_for,
    run_report_workflow,
)

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


class DurableReportResponse(BaseModel):
    """What is actually true of this report right now.

    `status` is the contract: only READY means an artifact exists and has been
    read back. storage_key is deliberately absent — a client never needs the
    bucket path, and the download endpoint builds its own from the caller's
    verified tenant claim.
    """

    report_id: str
    tenant_id: str
    status: str
    period_start: str
    period_end: str
    format: str
    size_bytes: int
    checksum: str
    total_checks: int
    pass_count: int
    fail_count: int
    escalated_count: int
    executive_summary: str
    model_name: str
    used_fixture: bool
    attempts: int


def _to_response(r: ReportRecord) -> "DurableReportResponse":
    return DurableReportResponse(
        report_id=r.report_id,
        tenant_id=r.tenant_id,
        status=r.status.value,
        period_start=r.period_start.isoformat(),
        period_end=r.period_end.isoformat(),
        format=r.format,
        size_bytes=r.size_bytes,
        checksum=r.checksum,
        total_checks=r.total_checks,
        pass_count=r.pass_count,
        fail_count=r.fail_count,
        escalated_count=r.escalated_count,
        executive_summary=r.executive_summary,
        model_name=r.model_name,
        used_fixture=r.used_fixture,
        attempts=r.attempts,
    )


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


@app.post("/internal/report", response_model=DurableReportResponse)
def create_report(
    req: ReportRequest, x_internal_token: str | None = Header(default=None)
) -> DurableReportResponse:
    """Generate one report through the durable lifecycle.

    Drives the state machine rather than generating inline, so the response
    describes what is actually true of storage. The scheduled weekly workflow
    calls this with the same body it always has and now gets the same
    guarantees — previously a failed weekly run left no record it had been
    attempted.

    A report already READY is returned untouched, so Cloud Task redelivery and
    a re-run of the weekly workflow are both no-ops rather than a second
    Gemini call.
    """
    _check_internal_token(x_internal_token)
    if req.period_start >= req.period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_start must be before period_end",
        )
    deps = _deps()
    repo = deps["repo"]

    record = ReportRecord(
        report_id=report_id_for(req.tenant_id, req.period_start, req.period_end),
        tenant_id=req.tenant_id,
        period_start=req.period_start,
        period_end=req.period_end,
        status=ReportStatus.QUEUED,
        requested_by=req.generated_by,
    )
    # Whoever wins this is the one that generates; everyone else resumes the
    # record that already exists.
    record, _created = repo.claim_report(record)

    def _generate():
        return generate_report(
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
            report_id=record.report_id,
        )

    try:
        final = run_report_workflow(
            record=record,
            repo=repo,
            generate=_generate,
            storage_client=deps["storage"],
        )
    except ReportGenerationError as exc:
        # 502 so Cloud Tasks retries per the queue policy. The durable record
        # already says RETRYING or FAILED, so the state is not lost with the
        # response.
        logger.error("report %s did not complete: %s", record.report_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="report generation failed"
        ) from exc

    return _to_response(final)


class ReportTaskRequest(BaseModel):
    """Cloud Tasks payload. The queue carries an id, not a period."""

    tenant_id: str = Field(min_length=1)
    # The dispatcher names it target_ref; document_id is the same value and is
    # sent alongside for the other agents. Either is accepted so the worker
    # does not depend on which field the dispatcher happens to fill.
    target_ref: str = Field(default="", max_length=128)
    document_id: str = Field(default="", max_length=128)
    task_id: str = Field(default="", max_length=128)

    @property
    def report_id(self) -> str:
        return self.target_ref or self.document_id


@app.post("/internal/report-task", response_model=DurableReportResponse)
def run_report_task(
    req: ReportTaskRequest, x_internal_token: str | None = Header(default=None)
) -> DurableReportResponse:
    """Cloud Tasks entry point: finish the report this id names.

    The period is read from the durable record rather than the payload, so a
    replayed task cannot generate a different period under an id that already
    means something. A record already READY returns immediately, which is what
    makes redelivery free.
    """
    _check_internal_token(x_internal_token)
    if not req.report_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="report id missing from task payload"
        )
    deps = _deps()
    repo = deps["repo"]

    try:
        record = repo.get_report_record(req.report_id, req.tenant_id)
    except Exception as exc:
        # Includes the tenant-mismatch case, which is a 404 for the same
        # reason it is everywhere else: existence is not disclosed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
        ) from exc

    def _generate():
        return generate_report(
            tenant_id=record.tenant_id,
            period_start=record.period_start,
            period_end=record.period_end,
            db=deps["db"],
            bq_client=deps["bq"],
            storage_client=deps["storage"],
            auditor=deps["auditor"],
            gemini=deps["gemini"],
            bq_dataset=audit_dataset(),
            bq_reports_table=reports_table(),
            bq_project=project_id(),
            generated_by=record.requested_by or "reporting-agent",
            report_id=record.report_id,
        )

    try:
        final = run_report_workflow(
            record=record, repo=repo, generate=_generate, storage_client=deps["storage"]
        )
    except ReportGenerationError as exc:
        logger.error("report task %s did not complete: %s", req.report_id, exc)
        # 502 so Cloud Tasks retries. The durable record already records why.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="report generation failed"
        ) from exc

    return _to_response(final)


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
