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

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone

from auth_middleware import (
    VALID_ROLES,
    AuthContext,
    create_tenant_member,
    create_tenant_owner,
    delete_tenant_member,
    require_auth,
    require_role,
    set_api_key_resolver,
)
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
    ApiKeyRecord,
    Document,
    DocumentStatus,
    PlanTier,
    ReviewComment,
    RulesetNotFoundError,
    TaskType,
    Tenant,
    TenantUser,
    load_ruleset,
)

from api_gateway.composition import RULESETS_ROOT, Gateway
from api_gateway.rate_limit import TokenBucketRateLimiter
from api_gateway.upload_validation import ContentMismatchError, validate_upload

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
    job_title: str = Field(default="", max_length=120)
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
    content_hash: str = ""
    content_type: str = ""
    size_bytes: int = 0
    filename: str = ""
    created_at: str = ""


class DocumentContentResponse(BaseModel):
    document_id: str
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str
    # Text when the file is text-like; otherwise base64 so the client can
    # render or download it without a second round trip.
    text: str | None = None
    base64: str | None = None
    hash_verified: bool = False


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
    assigned_to: str | None = None
    comments: list[dict] = []
    created_at: str = ""


class AddCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class AssignRequest(BaseModel):
    # None / empty clears the assignment.
    assignee_uid: str | None = None


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


class NotificationSettingsResponse(BaseModel):
    slack_configured: bool
    slack_webhook_masked: str


class NotificationSettingsRequest(BaseModel):
    slack_webhook_url: str = Field(default="", max_length=500)


class RetentionSettingsResponse(BaseModel):
    retention_days: int
    minimum_days: int
    enabled: bool


class RetentionSettingsRequest(BaseModel):
    retention_days: int = Field(ge=0, le=3650)


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    display_prefix: str
    created_at: str
    last_used_at: str | None
    revoked: bool


class ApiKeyCreatedResponse(ApiKeyResponse):
    # Present exactly once, in the creation response, and never again.
    plaintext_key: str


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="", max_length=120)


class TeamMemberResponse(BaseModel):
    uid: str
    email: str
    role: str
    job_title: str
    created_at: str


class InviteMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=4096)
    role: str = Field(default="reviewer")
    job_title: str = Field(default="", max_length=120)


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
    # Record the person, not just the business — job_title is the only place
    # we learn who actually operates compliance inside the customer.
    g.repo.upsert_user(
        TenantUser(
            uid=uid,
            tenant_id=tenant_id,
            email=req.email,
            role="owner",
            job_title=req.job_title,
        )
    )
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
            "job_title": req.job_title,
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

    # Bounded read: stop as soon as the limit is exceeded instead of
    # buffering an unbounded body into memory first.
    buf = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file exceeds {MAX_UPLOAD_BYTES} bytes",
            )
    data = bytes(buf)
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")

    g = gw()
    try:
        validate_upload(data, file.content_type)
    except ContentMismatchError:
        g.auditor.log(
            tenant_id=auth.tenant_id,
            actor=auth.uid,
            action="document.upload_rejected",
            # Stable key derived from the rejected bytes (not wall-clock time):
            # retries of the same rejected file dedupe via deterministic_event_id,
            # while different rejected files still get distinct events.
            dedup_key=f"{auth.tenant_id}:{hashlib.sha256(data).hexdigest()}",
            before_state=None,
            after_state={
                "declared_content_type": file.content_type,
                "size_bytes": len(data),
                "reason": "content_type_mismatch",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="file content does not match its declared type",
        )
    # Server-generated document_id — never client-supplied.
    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    safe_name = os.path.basename(file.filename or "upload.bin").replace("/", "_")
    blob_path = f"{auth.tenant_id}/{document_id}/{safe_name}"
    # Hash the exact bytes received, before anything else touches them, so the
    # hash provably describes what was assessed.
    content_hash = hashlib.sha256(data).hexdigest()
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
        content_hash=content_hash,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        filename=safe_name,
    )
    g.repo.upsert_document(document)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="document.uploaded",
        dedup_key=f"{document_id}:uploaded",
        before_state=None,
        after_state={
            "document_id": document_id,
            "storage_ref": storage_ref,
            "source": source,
            # Recorded in the immutable trail, so the integrity claim is
            # anchored to something that cannot later be rewritten.
            "content_hash": content_hash,
            "size_bytes": len(data),
            "filename": safe_name,
        },
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
        content_hash=getattr(doc, "content_hash", "") or "",
        content_type=getattr(doc, "content_type", "") or "",
        size_bytes=getattr(doc, "size_bytes", 0) or 0,
        filename=getattr(doc, "filename", "") or "",
        created_at=doc.created_at.isoformat(),
        document_id=doc.document_id,
        tenant_id=doc.tenant_id,
        source=doc.source,
        storage_ref=doc.storage_ref,
        extracted_fields=doc.extracted_fields,
        status=doc.status.value,
    )


@app.get("/api/documents/{document_id}/content", response_model=DocumentContentResponse)
def get_document_content(
    document_id: str, auth: AuthContext = Depends(require_auth)
) -> DocumentContentResponse:
    """Return the ACTUAL uploaded bytes for the review screen.

    Tenant-scoped through the same repo path as everything else, so a
    document id from another tenant is a 404, not a leak.

    The stored SHA-256 is recomputed from the bytes fetched back out of
    Cloud Storage and reported as hash_verified. That turns the integrity
    claim into something the reviewer can see rather than take on trust: if
    the stored object were ever altered, this would read false.
    """
    import base64 as _b64

    from gcp_clients import raw_docs_bucket

    g = gw()
    try:
        doc = g.repo.get_document(document_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None

    ref = doc.storage_ref
    if not ref.startswith("gs://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no stored file")
    without_scheme = ref[len("gs://") :]
    bucket_name, _, blob_path = without_scheme.partition("/")
    # Only ever read from our own raw-docs bucket, whatever the record says.
    if bucket_name != raw_docs_bucket():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    blob = g.storage.bucket(bucket_name).blob(blob_path)
    if not blob.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="stored file no longer available"
        )
    data = blob.download_as_bytes()

    stored_hash = getattr(doc, "content_hash", "") or ""
    actual_hash = hashlib.sha256(data).hexdigest()
    content_type = getattr(doc, "content_type", "") or "application/octet-stream"

    text: str | None = None
    b64: str | None = None
    if content_type.startswith("text/") or content_type == "application/json":
        text = data.decode("utf-8", errors="replace")
    else:
        b64 = _b64.b64encode(data).decode("ascii")

    return DocumentContentResponse(
        document_id=doc.document_id,
        filename=getattr(doc, "filename", "") or blob_path.rsplit("/", 1)[-1],
        content_type=content_type,
        size_bytes=len(data),
        content_hash=actual_hash,
        text=text,
        base64=b64,
        # Only meaningful when a hash was recorded at upload; older records
        # predate hashing and report false rather than a false positive.
        hash_verified=bool(stored_hash) and stored_hash == actual_hash,
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


@app.post("/api/compliance/checks/{check_id}/comments", response_model=CheckResponse)
def add_check_comment(
    check_id: str,
    req: AddCommentRequest,
    auth: AuthContext = Depends(require_auth),
) -> CheckResponse:
    """Append a reviewer note.

    Any member of the tenant may comment — an owner questioning a decision is
    as much a part of oversight as the reviewer making it. Comments are only
    ever appended; there is no edit or delete, because the value of the
    record is that it reconstructs what people actually thought at the time.
    """
    g = gw()
    try:
        check = g.repo.get_check(check_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None

    # min_length on the request only counts raw characters, so "   " gets
    # through and would then fail model validation as a 500. Reject it here
    # as the 400 it actually is.
    body = req.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="comment cannot be empty"
        )

    comment = ReviewComment(
        comment_id=str(uuid.uuid4()),
        author_uid=auth.uid,
        author_email=auth.email or "",
        body=body,
    )
    updated = check.model_copy(
        update={"comments": [*(getattr(check, "comments", None) or []), comment]}
    )
    g.repo.upsert_check(updated)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="check.comment_added",
        dedup_key=f"{check_id}:comment:{comment.comment_id}",
        before_state=None,
        after_state={"check_id": check_id, "comment_id": comment.comment_id},
    )
    return _check_to_response(updated)


@app.patch("/api/compliance/checks/{check_id}/assignee", response_model=CheckResponse)
def assign_check(
    check_id: str,
    req: AssignRequest,
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> CheckResponse:
    """Assign (or unassign) a reviewer.

    The assignee must already be a member of this tenant — verified against
    the user store rather than trusted from the request — so a check can
    never be assigned to someone outside the workspace.
    """
    g = gw()
    try:
        check = g.repo.get_check(check_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None

    assignee = (req.assignee_uid or "").strip() or None
    if assignee is not None:
        try:
            g.repo.get_user(assignee, auth.tenant_id)
        except (NotFoundError, TenantMismatchError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assignee is not a member of this workspace",
            ) from None

    previous = getattr(check, "assigned_to", None)
    updated = check.model_copy(update={"assigned_to": assignee})
    g.repo.upsert_check(updated)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="check.assigned" if assignee else "check.unassigned",
        dedup_key=f"{check_id}:assign:{assignee or 'none'}:{datetime.now(timezone.utc).isoformat()}",
        before_state={"assigned_to": previous},
        after_state={"assigned_to": assignee},
    )
    return _check_to_response(updated)


@app.get("/api/compliance/queue", response_model=list[CheckResponse])
def review_queue(auth: AuthContext = Depends(require_auth)) -> list[CheckResponse]:
    """Checks awaiting a human decision, highest risk first.

    This is the human-oversight surface: everything the AI declined to
    auto-approve and handed to a person.
    """
    checks = gw().repo.list_escalated_checks(auth.tenant_id)
    checks.sort(key=lambda c: c.risk_score, reverse=True)
    return [_check_to_response(c) for c in checks]


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
# Team — people inside one tenant. Listing is open to any member (you should
# be able to see who can approve your compliance decisions); mutating the
# roster is owner/admin only.
# ---------------------------------------------------------------------------


@app.get("/api/team", response_model=list[TeamMemberResponse])
def list_team(auth: AuthContext = Depends(require_auth)) -> list[TeamMemberResponse]:
    users = gw().repo.list_users(auth.tenant_id)
    users.sort(key=lambda u: u.created_at)
    return [
        TeamMemberResponse(
            uid=u.uid,
            email=u.email,
            role=u.role,
            job_title=u.job_title,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]


@app.post(
    "/api/team",
    response_model=TeamMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_team_member(
    req: InviteMemberRequest,
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> TeamMemberResponse:
    """Add a member to the caller's OWN tenant.

    NOTE: there is no email delivery in this system, so this creates the
    account directly with a password the owner sets and passes on out of
    band. It is deliberately not called an 'invite' in the UI, because no
    invite email is ever sent.
    """
    if req.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid role {req.role!r}; expected one of {sorted(VALID_ROLES)}",
        )
    try:
        uid = create_tenant_member(
            email=req.email,
            password=req.password,
            tenant_id=auth.tenant_id,  # never client-supplied
            role=req.role,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    g = gw()
    user = TenantUser(
        uid=uid,
        tenant_id=auth.tenant_id,
        email=req.email,
        role=req.role,
        job_title=req.job_title,
    )
    g.repo.upsert_user(user)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="team.member_added",
        dedup_key=f"{uid}:added",
        before_state=None,
        after_state={"uid": uid, "email": req.email, "role": req.role, "job_title": req.job_title},
    )
    return TeamMemberResponse(
        uid=user.uid,
        email=user.email,
        role=user.role,
        job_title=user.job_title,
        created_at=user.created_at.isoformat(),
    )


@app.delete("/api/team/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    uid: str, auth: AuthContext = Depends(require_role("owner", "admin"))
) -> None:
    if uid == auth.uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot remove your own account",
        )
    g = gw()
    try:
        existing = g.repo.get_user(uid, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from None

    try:
        delete_tenant_member(uid=uid, tenant_id=auth.tenant_id)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found") from None
    g.repo.delete_user(uid, auth.tenant_id)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="team.member_removed",
        dedup_key=f"{uid}:removed",
        before_state={"uid": uid, "email": existing.email, "role": existing.role},
        after_state=None,
    )


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
# Notification settings - Slack webhook for escalation alerts.
# ---------------------------------------------------------------------------


@app.get("/api/settings/notifications", response_model=NotificationSettingsResponse)
def get_notification_settings(
    auth: AuthContext = Depends(require_auth),
) -> NotificationSettingsResponse:
    from notifications import mask_webhook_url

    tenant = gw().repo.get_tenant(auth.tenant_id)
    url = getattr(tenant, "slack_webhook_url", "") or ""
    return NotificationSettingsResponse(
        slack_configured=bool(url), slack_webhook_masked=mask_webhook_url(url)
    )


@app.put("/api/settings/notifications", response_model=NotificationSettingsResponse)
def put_notification_settings(
    req: NotificationSettingsRequest,
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> NotificationSettingsResponse:
    """Set (or clear, with an empty string) the tenant's Slack webhook.

    The URL is validated against the Slack host allowlist because our server
    fetches it - an unvalidated value here would be a server-side request
    forgery primitive.
    """
    from notifications import (
        InvalidWebhookUrlError,
        mask_webhook_url,
        validate_slack_webhook_url,
    )

    g = gw()
    tenant = g.repo.get_tenant(auth.tenant_id)
    incoming = (req.slack_webhook_url or "").strip()

    if incoming:
        try:
            incoming = validate_slack_webhook_url(incoming)
        except InvalidWebhookUrlError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    updated = tenant.model_copy(update={"slack_webhook_url": incoming})
    g.repo.upsert_tenant(updated)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="settings.notifications_updated",
        dedup_key=f"{auth.tenant_id}:notifications:{datetime.now(timezone.utc).isoformat()}",
        before_state={"slack_configured": bool(getattr(tenant, "slack_webhook_url", ""))},
        after_state={"slack_configured": bool(incoming)},
    )
    return NotificationSettingsResponse(
        slack_configured=bool(incoming), slack_webhook_masked=mask_webhook_url(incoming)
    )


@app.post("/api/settings/notifications/test")
def test_notification_settings(
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> dict:
    """Send a real test message so the tenant can confirm delivery works."""
    from notifications import post_to_slack

    tenant = gw().repo.get_tenant(auth.tenant_id)
    url = getattr(tenant, "slack_webhook_url", "") or ""
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="no Slack webhook configured"
        )
    try:
        post_to_slack(
            url,
            {
                "text": (
                    f"ComplianceGuardian test message for {tenant.name}. "
                    f"Escalation alerts are working."
                )
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack rejected the message: {exc}",
        ) from exc
    return {"sent": True}


# ---------------------------------------------------------------------------
# Retention settings - the only destructive setting in the product.
# ---------------------------------------------------------------------------


@app.get("/api/settings/retention", response_model=RetentionSettingsResponse)
def get_retention_settings(
    auth: AuthContext = Depends(require_auth),
) -> RetentionSettingsResponse:
    from retention import MIN_RETENTION_DAYS

    tenant = gw().repo.get_tenant(auth.tenant_id)
    days = int(getattr(tenant, "retention_days", 0) or 0)
    return RetentionSettingsResponse(
        retention_days=days, minimum_days=MIN_RETENTION_DAYS, enabled=days > 0
    )


@app.put("/api/settings/retention", response_model=RetentionSettingsResponse)
def put_retention_settings(
    req: RetentionSettingsRequest,
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> RetentionSettingsResponse:
    """0 disables deletion entirely.

    Anything between 1 and the floor is refused rather than silently
    rounded, so a typo cannot delete a tenant's working set.
    """
    from retention import MIN_RETENTION_DAYS

    if 0 < req.retention_days < MIN_RETENTION_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"retention_days must be 0 (keep forever) or at least "
                f"{MIN_RETENTION_DAYS}; {req.retention_days} is too short to be safe"
            ),
        )
    g = gw()
    tenant = g.repo.get_tenant(auth.tenant_id)
    updated = tenant.model_copy(update={"retention_days": req.retention_days})
    g.repo.upsert_tenant(updated)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="settings.retention_updated",
        dedup_key=f"{auth.tenant_id}:retention:{datetime.now(timezone.utc).isoformat()}",
        before_state={"retention_days": int(getattr(tenant, "retention_days", 0) or 0)},
        after_state={"retention_days": req.retention_days},
    )
    return RetentionSettingsResponse(
        retention_days=req.retention_days,
        minimum_days=MIN_RETENTION_DAYS,
        enabled=req.retention_days > 0,
    )


@app.post("/api/settings/retention/preview")
def preview_retention(
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> dict:
    """Dry run: what WOULD be deleted under the current policy. Deletes nothing."""
    from retention import sweep_tenant

    g = gw()
    tenant = g.repo.get_tenant(auth.tenant_id)
    result = sweep_tenant(
        tenant=tenant,
        repo=g.repo,
        storage_client=g.storage,
        auditor=g.auditor,
        dry_run=True,
    )
    return result.as_dict()


# ---------------------------------------------------------------------------
# API keys - programmatic access. The plaintext key is shown exactly once.
# ---------------------------------------------------------------------------


def _api_key_to_response(k: ApiKeyRecord) -> ApiKeyResponse:
    return ApiKeyResponse(
        key_id=k.key_id,
        name=k.name,
        display_prefix=k.display_prefix,
        created_at=k.created_at.isoformat(),
        last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        revoked=k.revoked,
    )


@app.get("/api/keys", response_model=list[ApiKeyResponse])
def list_keys(
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> list[ApiKeyResponse]:
    keys = gw().repo.list_api_keys(auth.tenant_id)
    keys.sort(key=lambda k: k.created_at, reverse=True)
    return [_api_key_to_response(k) for k in keys]


@app.post("/api/keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_key(
    req: CreateApiKeyRequest,
    auth: AuthContext = Depends(require_role("owner", "admin")),
) -> ApiKeyCreatedResponse:
    from api_keys import generate_api_key

    generated = generate_api_key()
    record = ApiKeyRecord(
        key_id=str(uuid.uuid4()),
        tenant_id=auth.tenant_id,  # from the verified session, never the body
        name=req.name,
        key_hash=generated.key_hash,
        display_prefix=generated.display_prefix,
        created_by=auth.uid,
    )
    g = gw()
    g.repo.upsert_api_key(record)
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="api_key.created",
        dedup_key=f"{record.key_id}:created",
        before_state=None,
        # The key itself is deliberately absent from the audit record.
        after_state={
            "key_id": record.key_id,
            "name": record.name,
            "display_prefix": record.display_prefix,
        },
    )
    base = _api_key_to_response(record)
    return ApiKeyCreatedResponse(**base.model_dump(), plaintext_key=generated.plaintext)


@app.delete("/api/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(
    key_id: str, auth: AuthContext = Depends(require_role("owner", "admin"))
) -> None:
    g = gw()
    try:
        revoked = g.repo.revoke_api_key(key_id, auth.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="key not found"
        ) from exc
    except TenantMismatchError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="key not found"
        ) from None
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="api_key.revoked",
        dedup_key=f"{key_id}:revoked",
        before_state={"key_id": key_id, "revoked": False},
        after_state={
            "key_id": key_id,
            "revoked": True,
            "display_prefix": revoked.display_prefix,
        },
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
        assigned_to=getattr(c, "assigned_to", None),
        comments=[
            cm.model_dump(mode="json") if hasattr(cm, "model_dump") else dict(cm)
            for cm in (getattr(c, "comments", None) or [])
        ],
        created_at=c.created_at.isoformat() if getattr(c, "created_at", None) else "",
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
