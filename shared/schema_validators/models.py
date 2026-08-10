"""Core Pydantic models — the single source of truth for entity shapes.

Every Firestore write and BigQuery insert in the codebase round-trips through
these models so that a malformed record can never reach storage silently.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def utcnow() -> datetime:
    """Timezone-aware UTC now (Firestore & BigQuery both want aware datetimes)."""
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base: reject unknown fields so schema drift fails loudly, not silently."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Firestore: tenants
# ---------------------------------------------------------------------------


class PlanTier(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"


class TenantStatus(str, Enum):
    """Whether a workspace may use the platform.

    Access control only. Suspending a workspace stops its people signing in
    and its API keys working; it never alters a document, a verdict, or an
    audit record. That distinction is the whole design: the operator console
    can control access and can never rewrite history.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"


class EntitlementSource(str, Enum):
    """Where a workspace's current report allowance came from.

    Kept distinct from PlanTier because they answer different questions.
    plan_tier is what the customer bought; this is what they can currently
    DO. A one-time buyer is not a subscriber, and the console must never
    describe them as one.
    """

    FREE = "free"           # the one report every new workspace gets
    SINGLE = "single"       # one-time purchase, one report
    PRO = "pro"             # monthly subscription allowance


class Tenant(StrictModel):
    tenant_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    plan_tier: PlanTier = PlanTier.FREE
    created_at: datetime = Field(default_factory=utcnow)

    # Slack incoming-webhook URL for escalation alerts. Empty = notifications
    # off. Validated as a Slack host on write (see api_gateway) because this
    # is a tenant-supplied URL the server itself fetches.
    slack_webhook_url: str = Field(default="", max_length=500)

    # Days to keep uploaded documents before the retention sweep deletes them.
    # 0 means keep indefinitely, and is the default — retention deletion is
    # destructive, so it never happens unless a tenant explicitly opts in.
    # The append-only audit trail is NEVER affected by this setting.
    retention_days: int = Field(default=0, ge=0, le=3650)

    # --- Report entitlement --------------------------------------------
    # Deliberately counters rather than a boolean. "free_report_used" cannot
    # express a Pro allowance, a top-up, or a refund, and every one of those
    # is a real case. Remaining = granted - consumed, and consumption is
    # applied inside a Firestore transaction so two concurrent requests
    # cannot both spend the last one.
    #
    # Defaults to 1 granted / 0 consumed, so a workspace created before this
    # existed reads back with its free report intact rather than locked out.
    reports_granted: int = Field(default=1, ge=0)
    reports_consumed: int = Field(default=0, ge=0)
    entitlement_source: EntitlementSource = EntitlementSource.FREE
    # Set only for a Pro subscription: when the current allowance lapses and
    # the next period's grant is due. None for free and one-time purchases,
    # which never expire.
    entitlement_expires_at: datetime | None = None

    # Defaults to ACTIVE so every workspace written before this field existed
    # reads back as active rather than needing a migration.
    status: TenantStatus = TenantStatus.ACTIVE
    # Why a workspace was suspended, shown to its users at sign-in. Kept short
    # and operator-written: "payment failed" is actionable, "policy" is not.
    status_reason: str = Field(default="", max_length=300)


class ApiKeyRecord(StrictModel):
    """A programmatic API key. The plaintext key is NEVER stored here.

    key_hash is a SHA-256 of the key; display_prefix is the first few
    characters so a human can tell keys apart in a list without the secret
    being recoverable from this record.
    """

    key_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    name: str = Field(default="", max_length=120)
    key_hash: str = Field(min_length=64, max_length=64)
    display_prefix: str = Field(min_length=1, max_length=32)
    created_by: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    revoked: bool = False


class TenantUser(StrictModel):
    """A person inside a tenant.

    Mirrors the Firebase Auth user (uid is the Firebase uid) but adds the
    profile fields Firebase doesn't carry — notably job_title, which is what
    lets an owner see who actually reviews their compliance decisions.
    Firebase remains the source of truth for authentication; this record is
    the source of truth for display.
    """

    uid: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    role: str = Field(min_length=1)
    job_title: str = Field(default="", max_length=120)
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Firestore: documents
# ---------------------------------------------------------------------------


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class Document(StrictModel):
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    source: str = Field(min_length=1, description="upload | email | integration name")
    storage_ref: str = Field(min_length=1, description="gs://bucket/path to the raw file")
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    status: DocumentStatus = DocumentStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)

    # SHA-256 of the exact bytes received, computed once at upload. This is
    # what makes "the document that was assessed" verifiable: anyone holding
    # the original file can recompute this and prove the assessed content was
    # not altered. Empty on records created before hashing existed.
    content_hash: str = Field(default="", max_length=64)
    content_type: str = Field(default="", max_length=100)
    size_bytes: int = Field(default=0, ge=0)
    filename: str = Field(default="", max_length=260)


# ---------------------------------------------------------------------------
# Firestore: compliance_checks
# ---------------------------------------------------------------------------


class CheckDecision(str, Enum):
    AUTO_APPROVED = "auto_approved"
    ESCALATED = "escalated"
    REJECTED = "rejected"


class RuleVerdictStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class RuleVerdict(StrictModel):
    """Per-rule result returned by the Compliance Agent's Gemini call."""

    rule_id: str = Field(min_length=1)
    status: RuleVerdictStatus
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1)
    triggering_data_point: str | None = None

    @field_validator("triggering_data_point", mode="before")
    @classmethod
    def _coerce_trigger(cls, v: Any) -> Any:
        # Gemini may return a non-string data point (number, object); keep it lossless.
        if v is None or isinstance(v, str):
            return v
        return str(v)


class GeminiCallMetadata(StrictModel):
    """Reproducibility metadata stored alongside every Gemini output."""

    prompt_version: str = Field(min_length=1, description="e.g. compliance_v1")
    model_name: str = Field(min_length=1, description="e.g. gemini-2.5-flash")
    model_version: str | None = Field(
        default=None, description="modelVersion echoed by the API response, when present"
    )
    response_id: str | None = None


class ReviewComment(StrictModel):
    """One reviewer's note on a compliance check.

    Carries author identity and time so the reasoning behind a human
    decision stays attributable long after the person has moved on.
    """

    comment_id: str = Field(min_length=1)
    author_uid: str = Field(min_length=1)
    author_email: str = Field(default="", max_length=320)
    body: str = Field(min_length=1, max_length=4000)
    created_at: datetime = Field(default_factory=utcnow)


class ComplianceCheck(StrictModel):
    check_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    rule_set_version: str = Field(min_length=1)
    risk_score: int = Field(ge=0, le=100)
    justification: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
    decision: CheckDecision
    reviewer_id: str | None = None
    rule_verdicts: list[RuleVerdict] = Field(default_factory=list)
    gemini_metadata: GeminiCallMetadata | None = None
    created_at: datetime = Field(default_factory=utcnow)

    # Human oversight. assigned_to names who is expected to decide; comments
    # are the reviewer's own reasoning. Both are append-only in practice: a
    # comment is never edited or removed, because the point of the record is
    # that you can reconstruct why a human decided what they decided.
    assigned_to: str | None = None
    comments: list[ReviewComment] = Field(default_factory=list)

    @field_validator("citations")
    @classmethod
    def _no_blank_citations(cls, v: list[str]) -> list[str]:
        if any(not c.strip() for c in v):
            raise ValueError("citations must not contain blank entries")
        return v


# ---------------------------------------------------------------------------
# Firestore: remediation plans (one per compliance check)
# ---------------------------------------------------------------------------


class RemediationItem(StrictModel):
    """One concrete thing a business should do about one failed rule.

    Deliberately actionable rather than descriptive: a compliance check tells
    a provider what is wrong, and this tells them what to do about it. The
    rule_id ties every item back to a real rule in the ruleset, so an item
    can never float free of the citation that justifies it.
    """

    rule_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=2000, description="What to actually do")
    blocking: bool = Field(
        default=False,
        description="True when this must be fixed before the document can be relied on",
    )
    estimated_minutes: int = Field(default=15, ge=1, le=10080)
    severity: str = Field(default="medium")


class RemediationPlan(StrictModel):
    """The ordered set of fixes for one compliance check."""

    plan_id: str = Field(min_length=1)
    check_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    items: list[RemediationItem] = Field(default_factory=list)
    gemini_metadata: GeminiCallMetadata | None = None
    used_fixture: bool = Field(
        default=False,
        description="True when items were derived without a live model call",
    )
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def total_estimated_minutes(self) -> int:
        return sum(i.estimated_minutes for i in self.items)


# ---------------------------------------------------------------------------
# BigQuery: audit_logs (append-only)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Support
#
# New collections rather than fields on Tenant, deliberately: Tenant is a
# StrictModel parsed by every service, so extending it forces all five to be
# redeployed together. Support tickets are only ever touched by the gateway.
# ---------------------------------------------------------------------------


class TicketStatus(str, Enum):
    NEW = "new"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_USER = "waiting_for_user"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(str, Enum):
    ACCOUNT = "account"
    REPORT = "report"
    BILLING = "billing"
    SUBSCRIPTION = "subscription"
    REFUND = "refund"
    TECHNICAL = "technical"
    SECURITY = "security"
    PRIVACY = "privacy"
    OTHER = "other"


class MessageSender(str, Enum):
    CUSTOMER = "customer"
    SUPPORT = "support"


class SupportMessage(StrictModel):
    """One turn in a ticket conversation.

    `internal` marks an operator-only note. It lives on the same thread so the
    context stays with the ticket, and is filtered out server-side before any
    customer-facing response is built — never by the client, which would be one
    forgotten condition away from leaking triage notes to the customer they are
    about.
    """

    message_id: str = Field(min_length=1)
    sender: MessageSender
    # Empty for a customer message: the ticket already carries their identity,
    # and support replies are attributed to the operator who wrote them.
    author_email: str = Field(default="", max_length=320)
    body: str = Field(min_length=1, max_length=8000)
    internal: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class SupportTicket(StrictModel):
    """A customer support request.

    Tenant-scoped like everything else: tenant_id comes from the verified
    session, never from the request body, so a ticket cannot be filed against
    somebody else's workspace.
    """

    ticket_id: str = Field(min_length=1)          # internal id
    reference: str = Field(min_length=1)          # CG-SUP-000123, shown to people
    tenant_id: str = Field(min_length=1)
    created_by_uid: str = Field(min_length=1)

    first_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    phone: str = Field(default="", max_length=40)  # optional by design

    category: TicketCategory = TicketCategory.OTHER
    subject: str = Field(default="", max_length=200)
    status: TicketStatus = TicketStatus.NEW
    priority: TicketPriority = TicketPriority.NORMAL

    # Operator email rather than uid: the console shows people, and an email is
    # legible in the audit trail years later where a uid is not.
    assigned_to: str = Field(default="", max_length=320)

    messages: list[SupportMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def customer_view(self) -> "SupportTicket":
        """A copy with internal notes removed.

        Used for every customer-facing response. Filtering here rather than at
        each call site means a new endpoint cannot forget to do it.
        """
        return self.model_copy(
            update={"messages": [m for m in self.messages if not m.internal]}
        )


class AuditLogRow(StrictModel):
    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    actor: str = Field(min_length=1, description="agent_name or reviewer_id")
    action: str = Field(min_length=1)
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# BigQuery: reports
# ---------------------------------------------------------------------------


class ReportRow(StrictModel):
    report_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    period_start: datetime
    period_end: datetime
    generated_by: str = Field(min_length=1, description="reporting-agent version or user id")
    content_ref: str = Field(min_length=1, description="gs:// path to rendered report")
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Firestore: tasks (orchestrator lifecycle; backs GET /api/tasks/:id)
# ---------------------------------------------------------------------------


class TaskType(str, Enum):
    INGEST = "ingest"
    CHECK = "check"
    REPORT = "report"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Task(StrictModel):
    task_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    task_type: TaskType
    target_ref: str = Field(min_length=1, description="document_id or report period key")
    status: TaskStatus = TaskStatus.QUEUED
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Rulesets (versioned YAML under /rulesets/{industry}/{jurisdiction}.yaml)
# ---------------------------------------------------------------------------


class RuleSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleCheckType(str, Enum):
    DATE_COMPARISON = "date_comparison"
    FIELD_PRESENCE = "field_presence"
    VALUE_RANGE = "value_range"
    PATTERN_MATCH = "pattern_match"
    CROSS_FIELD = "cross_field"


class Rule(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    check_type: RuleCheckType
    severity: RuleSeverity
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="check_type-specific parameters (e.g. min_years for date_comparison)",
    )


class RuleSet(StrictModel):
    rule_set_version: str
    industry: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    required_fields: list[str] = Field(
        default_factory=list,
        description="Fields the Ingestion Agent must extract; missing ones are flagged",
    )
    rules: list[Rule] = Field(min_length=1)

    @field_validator("rule_set_version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"rule_set_version must be semver (X.Y.Z), got {v!r}")
        return v

    @field_validator("rules")
    @classmethod
    def _unique_rule_ids(cls, rules: list[Rule]) -> list[Rule]:
        ids = [r.id for r in rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids in ruleset: {sorted(dupes)}")
        return rules

    def rule_ids(self) -> set[str]:
        return {r.id for r in self.rules}
