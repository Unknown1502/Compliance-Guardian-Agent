"""API Gateway — the single public entry point (Cloud Run, stateless).

Implements the exact API contract. Every endpoint verifies a Firebase Auth JWT
and derives tenant_id from the verified claims — never from client-supplied
input (query params / bodies). Async agent work is dispatched via the
Orchestrator's TaskService (Cloud Tasks in prod, inline locally).

    POST   /api/documents               multipart upload -> ingestion task
    GET    /api/documents/{id}
    POST   /api/compliance/checks       trigger a check on a document_id
    GET    /api/compliance/checks/{id}
    PATCH  /api/compliance/checks/{id}  reviewer approve/reject (role: reviewer)
    GET    /api/audit-logs              tenant-scoped audit query
    POST   /api/reports                 (Phase 4 — reporting agent)
    GET    /api/reports/{id}            (Phase 4)
    GET    /api/tasks/{id}              poll task status
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from auth_middleware import AuthContext, create_tenant_owner, require_auth, require_role
from escalation_service.decisions import apply_decision
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from firebase_admin.auth import EmailAlreadyExistsError
from gcp_clients import audit_dataset, audit_table, project_id
from gcp_clients.firestore_repo import (
    DecisionConflictError,
    NotFoundError,
    TenantMismatchError,
)
from google.cloud import bigquery
from pydantic import BaseModel, Field
from schema_validators import (
    Document,
    DocumentStatus,
    PlanTier,
    RulesetNotFoundError,
    TaskType,
    Tenant,
    load_ruleset,
)

from api_gateway.composition import RULESETS_ROOT, Gateway
from api_gateway.rate_limit import TokenBucketRateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.gateway")

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MiB
ALLOWED_UPLOAD_TYPES = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/json",
    "image/png",
    "image/jpeg",
}
CORS_ORIGINS = os.environ.get("CG_CORS_ORIGINS", "http://localhost:5173").split(",")

# Swagger/OpenAPI is off unless explicitly enabled — this is a compliance
# product; the API surface should not be publicly browsable by default.
_DOCS_ENABLED = os.environ.get("CG_ENABLE_DOCS") == "1"

app = FastAPI(
    title="ComplianceGuardian API Gateway",
    version="0.1.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_gateway: Gateway | None = None
_upload_limiter = TokenBucketRateLimiter(capacity=20, refill_per_second=0.5)
# Signup is public and creates real Firebase Auth users + tenants — keep it
# tight (5 attempts, refilling 1 every 2 min) since there's no tenant_id yet
# to key on; keyed by client IP instead.
_signup_limiter = TokenBucketRateLimiter(capacity=5, refill_per_second=1 / 120)


def gw() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway()
    return _gateway


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=4096)
    business_name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="healthcare_ndis")
    jurisdiction: str = Field(default="AU")


class SignupResponse(BaseModel):
    tenant_id: str
    uid: str
    email: str


class UploadResponse(BaseModel):
    document_id: str
    task_id: str
    status: str


class DocumentResponse(BaseModel):
    document_id: str
    tenant_id: str
    source: str
    storage_ref: str
    extracted_fields: dict
    status: str


class TriggerCheckRequest(BaseModel):
    document_id: str = Field(min_length=1)


class TaskResponse(BaseModel):
    task_id: str
    tenant_id: str
    task_type: str
    target_ref: str
    status: str
    result: dict
    error: str | None


class CheckResponse(BaseModel):
    check_id: str
    document_id: str
    tenant_id: str
    rule_set_version: str
    risk_score: int
    justification: str
    citations: list[str]
    decision: str
    reviewer_id: str | None
    rule_verdicts: list[dict]


class DecisionRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")


class CreateReportRequest(BaseModel):
    period_start: datetime
    period_end: datetime


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


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(oneoff|subscription)$")


class CheckoutResponse(BaseModel):
    checkout_url: str


class RuleResponse(BaseModel):
    id: str
    description: str
    check_type: str
    severity: str


class RulesetResponse(BaseModel):
    rule_set_version: str
    industry: str
    jurisdiction: str
    required_fields: list[str]
    rules: list[RuleResponse]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "api-gateway"}


# ---------------------------------------------------------------------------
# Signup — the only public (unauthenticated) write endpoint. Everything else
# requires a bearer token because it acts on an existing tenant; this one
# creates the tenant.
# ---------------------------------------------------------------------------


@app.post("/api/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, request: Request) -> SignupResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _signup_limiter.allow(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many signup attempts; try again shortly",
        )
    # Fail before creating any account/tenant state if we don't have a
    # ruleset for this industry/jurisdiction — there'd be nothing to check
    # documents against.
    try:
        load_ruleset(RULESETS_ROOT, req.industry, req.jurisdiction)
    except (RulesetNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"no ruleset for industry={req.industry!r} jurisdiction={req.jurisdiction!r}",
        ) from exc

    tenant_id = f"tenant-{uuid.uuid4().hex[:12]}"
    try:
        uid = create_tenant_owner(email=req.email, password=req.password, tenant_id=tenant_id)
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    g = gw()
    tenant = Tenant(
        tenant_id=tenant_id,
        name=req.business_name,
        industry=req.industry,
        jurisdiction=req.jurisdiction,
        plan_tier=PlanTier.FREE,
    )
    g.repo.upsert_tenant(tenant)
    g.auditor.log(
        tenant_id=tenant_id,
        actor=uid,
        action="tenant.signed_up",
        dedup_key=f"{tenant_id}:signed_up",
        before_state=None,
        after_state={
            "name": req.business_name,
            "industry": req.industry,
            "jurisdiction": req.jurisdiction,
        },
    )
    return SignupResponse(tenant_id=tenant_id, uid=uid, email=req.email)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@app.post("/api/documents", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    source: str = Form(default="upload"),
    auth: AuthContext = Depends(require_auth),
) -> UploadResponse:
    # Rate-limit uploads per tenant.
    if not _upload_limiter.allow(auth.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="upload rate limit exceeded; try again shortly",
        )
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported content type: {file.content_type}",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    g = gw()
    # Server-generated document_id — never client-supplied.
    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    safe_name = os.path.basename(file.filename or "upload.bin").replace("/", "_")
    blob_path = f"{auth.tenant_id}/{document_id}/{safe_name}"
    bucket = g.storage.bucket(g.raw_bucket)
    bucket.blob(blob_path).upload_from_string(
        data, content_type=file.content_type or "application/octet-stream"
    )
    storage_ref = f"gs://{g.raw_bucket}/{blob_path}"

    document = Document(
        document_id=document_id,
        tenant_id=auth.tenant_id,
        source=source,
        storage_ref=storage_ref,
        extracted_fields={},
        status=DocumentStatus.PENDING,
    )
    g.repo.upsert_document(document)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="document.uploaded",
        dedup_key=f"{document_id}:uploaded",
        before_state=None,
        after_state={"document_id": document_id, "storage_ref": storage_ref, "source": source},
    )

    # Dispatch ingestion. In inline mode this runs Gemini synchronously; surface
    # a clear 503 if no key is configured rather than failing opaquely.
    try:
        svc = g.task_service()
    except Exception as exc:  # GeminiConfigError etc.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ingestion pipeline unavailable: {exc}",
        ) from exc
    task = svc.create_and_dispatch(
        task_type=TaskType.INGEST, target_ref=document_id, tenant_id=auth.tenant_id
    )
    return UploadResponse(document_id=document_id, task_id=task.task_id, status=task.status.value)


@app.get("/api/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, auth: AuthContext = Depends(require_auth)) -> DocumentResponse:
    try:
        doc = gw().repo.get_document(document_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc
    return DocumentResponse(
        document_id=doc.document_id,
        tenant_id=doc.tenant_id,
        source=doc.source,
        storage_ref=doc.storage_ref,
        extracted_fields=doc.extracted_fields,
        status=doc.status.value,
    )


# ---------------------------------------------------------------------------
# Compliance checks
# ---------------------------------------------------------------------------


@app.post("/api/compliance/checks", response_model=TaskResponse)
def trigger_check(
    req: TriggerCheckRequest, auth: AuthContext = Depends(require_auth)
) -> TaskResponse:
    g = gw()
    # Verify the document exists and belongs to this tenant before dispatch.
    try:
        g.repo.get_document(req.document_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None
    try:
        svc = g.task_service()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"compliance pipeline unavailable: {exc}",
        ) from exc
    task = svc.create_and_dispatch(
        task_type=TaskType.CHECK, target_ref=req.document_id, tenant_id=auth.tenant_id
    )
    return TaskResponse(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        task_type=task.task_type.value,
        target_ref=task.target_ref,
        status=task.status.value,
        result=task.result,
        error=task.error,
    )


@app.get("/api/compliance/checks/{check_id}", response_model=CheckResponse)
def get_check(check_id: str, auth: AuthContext = Depends(require_auth)) -> CheckResponse:
    try:
        c = gw().repo.get_check(check_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None
    return _check_to_response(c)


@app.patch("/api/compliance/checks/{check_id}", response_model=CheckResponse)
def decide_check(
    check_id: str,
    req: DecisionRequest,
    auth: AuthContext = Depends(require_role("reviewer")),
) -> CheckResponse:
    g = gw()
    try:
        result = apply_decision(
            repo=g.repo,
            auditor=g.auditor,
            check_id=check_id,
            tenant_id=auth.tenant_id,
            reviewer_id=auth.uid,
            approve=(req.action == "approve"),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None
    except DecisionConflictError as exc:
        # The losing side of a concurrent two-reviewer race.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _check_to_response(result.check)


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------


@app.get("/api/audit-logs")
def get_audit_logs(
    auth: AuthContext = Depends(require_auth),
    tenant_id: str | None = None,  # accepted for spec shape; IGNORED (see below)
    from_: str | None = None,
    to: str | None = None,
    limit: int = 100,
) -> dict:
    # SECURITY: the client-supplied tenant_id query param is deliberately
    # ignored; the tenant is always the verified JWT claim. Cross-tenant reads
    # are impossible regardless of what the client passes.
    if tenant_id and tenant_id != auth.tenant_id:
        logger.warning(
            "ignoring client tenant_id=%s; using claim %s", tenant_id, auth.tenant_id
        )
    limit = max(1, min(limit, 500))
    g = gw()
    clauses = ["tenant_id = @tenant"]
    params = [bigquery.ScalarQueryParameter("tenant", "STRING", auth.tenant_id)]
    if from_:
        clauses.append("created_at >= @from_ts")
        params.append(bigquery.ScalarQueryParameter("from_ts", "TIMESTAMP", from_))
    if to:
        clauses.append("created_at < @to_ts")
        params.append(bigquery.ScalarQueryParameter("to_ts", "TIMESTAMP", to))
    where = " AND ".join(clauses)
    query = (
        f"SELECT event_id, tenant_id, actor, action, "
        f"TO_JSON_STRING(before_state) AS before_state, "
        f"TO_JSON_STRING(after_state) AS after_state, "
        f"CAST(created_at AS STRING) AS created_at "
        f"FROM `{project_id()}.{audit_dataset()}.{audit_table()}` "
        f"WHERE {where} ORDER BY created_at DESC LIMIT {limit}"
    )
    job = g.bq.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
    rows = [dict(r) for r in job.result()]
    return {"tenant_id": auth.tenant_id, "count": len(rows), "events": rows}


# ---------------------------------------------------------------------------
# Reports — Reporting Agent (real Gemini or fixture when no key)
# ---------------------------------------------------------------------------


@app.post("/api/reports", response_model=ReportResponse)
def create_report(
    req: CreateReportRequest, auth: AuthContext = Depends(require_auth)
) -> ReportResponse:
    from reporting_agent.reporter import generate_report
    from gcp_clients import audit_dataset, audit_table, bigquery_client, firestore_client, project_id as pid, reports_table, storage_client as sc
    from gemini_client import GeminiClient, GeminiConfigError

    if req.period_start >= req.period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_start must be before period_end",
        )
    g = gw()
    try:
        gemini = g.gemini()
    except GeminiConfigError:
        gemini = None

    outcome = generate_report(
        tenant_id=auth.tenant_id,
        period_start=req.period_start,
        period_end=req.period_end,
        db=g.db,
        bq_client=g.bq,
        storage_client=g.storage,
        auditor=g.auditor,
        gemini=gemini,
        bq_dataset=audit_dataset(),
        bq_reports_table=reports_table(),
        bq_project=project_id(),
        generated_by=auth.uid,
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


@app.get("/api/reports/{report_id}", response_class=HTMLResponse)
def get_report(
    report_id: str, auth: AuthContext = Depends(require_auth)
) -> HTMLResponse:
    from gcp_clients import reports_bucket

    g = gw()
    blob_path = f"{auth.tenant_id}/{report_id}/report.html"
    bucket = g.storage.bucket(reports_bucket())
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return HTMLResponse(content=blob.download_as_text())


# ---------------------------------------------------------------------------
# Billing
#
# Card collection is entirely Stripe-hosted (Checkout) — no card data ever
# reaches this service, so there is no PCI scope here. tenant_id for the
# webhook comes ONLY from the Checkout Session's client_reference_id/
# metadata, which we set ourselves from the authenticated session when
# creating it — never trusted from client-supplied request bodies.
# ---------------------------------------------------------------------------


@app.post("/api/billing/checkout", response_model=CheckoutResponse)
def create_checkout(
    req: CheckoutRequest, auth: AuthContext = Depends(require_auth)
) -> CheckoutResponse:
    from billing import BillingConfigError

    try:
        session = gw().billing().create_checkout_session(
            tenant_id=auth.tenant_id, plan=req.plan, customer_email=auth.email
        )
    except BillingConfigError as exc:
        # Stripe isn't configured yet (no account/keys). Fails as a normal
        # 503, not a crash — every other endpoint keeps working.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return CheckoutResponse(checkout_url=session.checkout_url)


@app.post("/api/billing/webhook", status_code=status.HTTP_200_OK)
async def billing_webhook(request: Request) -> dict:
    from billing import BillingConfigError, WebhookSignatureError

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    g = gw()
    try:
        event = g.billing().parse_webhook(payload=payload, signature_header=signature)
    except WebhookSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid signature: {exc}"
        ) from exc
    except BillingConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if event.event_type != "checkout.session.completed" or not event.tenant_id:
        # Ignore every other event type (e.g. later subscription lifecycle
        # events) for now — acknowledge with 200 so Stripe doesn't retry.
        return {"received": True, "handled": False}

    tenant = g.repo.get_tenant(event.tenant_id)
    new_tier = PlanTier.PRO if event.mode == "subscription" else PlanTier.STARTER
    tenant.plan_tier = new_tier
    g.repo.upsert_tenant(tenant)
    g.auditor.log(
        tenant_id=event.tenant_id,
        actor="stripe-webhook",
        action="billing.subscribed" if event.mode == "subscription" else "billing.purchased",
        dedup_key=f"stripe:{event.stripe_event_id}",
        before_state=None,
        after_state={
            "plan_tier": new_tier.value,
            "amount_total": event.amount_total,
            "currency": event.currency,
            "stripe_customer_id": event.stripe_customer_id,
            "stripe_event_id": event.stripe_event_id,
        },
    )
    return {"received": True, "handled": True}


# ---------------------------------------------------------------------------
# Ruleset — read-only. Lets a tenant see exactly what they're being checked
# against, by industry/jurisdiction resolved from their own tenant record
# (never client-supplied), same trust posture as everything else here.
# ---------------------------------------------------------------------------


@app.get("/api/ruleset", response_model=RulesetResponse)
def get_active_ruleset(auth: AuthContext = Depends(require_auth)) -> RulesetResponse:
    g = gw()
    tenant = g.repo.get_tenant(auth.tenant_id)
    try:
        ruleset = load_ruleset(RULESETS_ROOT, tenant.industry, tenant.jurisdiction)
    except (RulesetNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no ruleset for industry={tenant.industry!r} jurisdiction={tenant.jurisdiction!r}",
        ) from exc
    return RulesetResponse(
        rule_set_version=ruleset.rule_set_version,
        industry=ruleset.industry,
        jurisdiction=ruleset.jurisdiction,
        required_fields=ruleset.required_fields,
        rules=[
            RuleResponse(
                id=r.id,
                description=r.description,
                check_type=r.check_type.value,
                severity=r.severity.value,
            )
            for r in ruleset.rules
        ],
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, auth: AuthContext = Depends(require_auth)) -> TaskResponse:
    try:
        task = gw().task_service().get_task(task_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return TaskResponse(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        task_type=task.task_type.value,
        target_ref=task.target_ref,
        status=task.status.value,
        result=task.result,
        error=task.error,
    )


def _check_to_response(c) -> CheckResponse:
    return CheckResponse(
        check_id=c.check_id,
        document_id=c.document_id,
        tenant_id=c.tenant_id,
        rule_set_version=c.rule_set_version,
        risk_score=c.risk_score,
        justification=c.justification,
        citations=c.citations,
        decision=c.decision.value,
        reviewer_id=c.reviewer_id,
        rule_verdicts=[
            {
                "rule_id": v.rule_id,
                "status": v.status.value,
                "confidence": v.confidence,
                "explanation": v.explanation,
                "triggering_data_point": v.triggering_data_point,
            }
            for v in c.rule_verdicts
        ],
    )
