"""Schema validators for ComplianceGuardian.

Pydantic models implementing the EXACT data model from the spec:

Firestore:
  - tenants:            tenant_id, name, industry, jurisdiction, plan_tier, created_at
  - documents:          document_id, tenant_id, source, storage_ref, extracted_fields (map),
                        status (pending/processed/failed), created_at
  - compliance_checks:  check_id, document_id, tenant_id, rule_set_version, risk_score,
                        justification, citations (array), decision
                        (auto_approved/escalated/rejected), reviewer_id (nullable), created_at

BigQuery:
  - audit_logs (append-only): event_id, tenant_id, actor, action, before_state (json),
                              after_state (json), created_at
  - reports:                  report_id, tenant_id, period_start, period_end, generated_by,
                              content_ref, created_at

Plus the versioned YAML ruleset format and Gemini response envelopes used from Phase 2 on.
"""

from schema_validators.models import (
    AuditLogRow,
    CheckDecision,
    ComplianceCheck,
    Document,
    DocumentStatus,
    EntitlementSource,
    GeminiCallMetadata,
    PlanTier,
    RemediationItem,
    RemediationPlan,
    ReportRow,
    Rule,
    RuleSet,
    ReviewComment,
    MessageSender,
    SupportMessage,
    SupportTicket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    RuleVerdict,
    RuleVerdictStatus,
    Task,
    TaskStatus,
    TaskType,
    ApiKeyRecord,
    Tenant,
    TenantStatus,
    TenantUser,
)
from schema_validators.rulesets import (
    RulesetNotFoundError,
    RulesetOption,
    available_rulesets,
    load_ruleset,
    load_ruleset_file,
)

__all__ = [
    "AuditLogRow",
    "CheckDecision",
    "ComplianceCheck",
    "Document",
    "DocumentStatus",
    "EntitlementSource",
    "GeminiCallMetadata",
    "PlanTier",
    "RemediationItem",
    "RemediationPlan",
    "ReportRow",
    "Rule",
    "RuleSet",
    "ReviewComment",
    "MessageSender",
    "SupportMessage",
    "SupportTicket",
    "TicketCategory",
    "TicketPriority",
    "TicketStatus",
    "RuleVerdict",
    "RuleVerdictStatus",
    "Task",
    "TaskStatus",
    "TaskType",
    "ApiKeyRecord",
    "Tenant",
    "TenantStatus",
    "TenantUser",
    "RulesetNotFoundError",
    "RulesetOption",
    "available_rulesets",
    "load_ruleset",
    "load_ruleset_file",
]
