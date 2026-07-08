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


class Tenant(StrictModel):
    tenant_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    plan_tier: PlanTier = PlanTier.FREE
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

    @field_validator("citations")
    @classmethod
    def _no_blank_citations(cls, v: list[str]) -> list[str]:
        if any(not c.strip() for c in v):
            raise ValueError("citations must not contain blank entries")
        return v


# ---------------------------------------------------------------------------
# BigQuery: audit_logs (append-only)
# ---------------------------------------------------------------------------


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
