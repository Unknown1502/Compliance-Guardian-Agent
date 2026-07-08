"""Escalation decision logic — approve/reject an escalated compliance check.

This is the human-in-the-loop write path. It is deliberately small and pure
(operates on an injected repo + auditor) so both the Escalation Service HTTP
endpoint and the API Gateway's PATCH handler execute the exact same,
concurrency-safe logic.

Decision mapping (flagged spec interpretation):
  The spec fixes decision ∈ {auto_approved, escalated, rejected}. A human
  reviewer action on an escalated check therefore resolves to:
     approve -> auto_approved   (reviewer_id set)
     reject  -> rejected        (reviewer_id set)
  The human nature + exact timestamp are captured immutably in the audit_logs
  row (actor = reviewer_id, action = check.approved / check.rejected,
  created_at = decision time), satisfying "logs decision + reviewer ID +
  timestamp to BigQuery" without adding non-spec fields to ComplianceCheck.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from audit_logger import AuditLogger
from gcp_clients.firestore_repo import FirestoreRepo
from schema_validators import CheckDecision, ComplianceCheck

logger = logging.getLogger("cg.escalation.decisions")


@dataclass(frozen=True)
class DecisionResult:
    check: ComplianceCheck
    action: str  # check.approved | check.rejected


def apply_decision(
    *,
    repo: FirestoreRepo,
    auditor: AuditLogger,
    check_id: str,
    tenant_id: str,
    reviewer_id: str,
    approve: bool,
) -> DecisionResult:
    """Approve or reject an escalated check, transactionally + audited.

    Raises DecisionConflictError (from the repo transaction) if the check is no
    longer awaiting review — the losing side of a two-reviewer race.
    """
    decision = CheckDecision.AUTO_APPROVED if approve else CheckDecision.REJECTED
    action = "check.approved" if approve else "check.rejected"

    # Capture the prior state for the audit before/after, tenant-scoped.
    before = repo.get_check(check_id, tenant_id)

    updated = repo.apply_reviewer_decision(
        check_id=check_id,
        tenant_id=tenant_id,
        reviewer_id=reviewer_id,
        decision=decision,
    )

    # Immutable audit row carries reviewer_id (actor) + timestamp (created_at).
    # dedup_key ties the event to this specific resolution so a Cloud Task
    # redelivery of the same decision is deduped rather than double-logged.
    auditor.log(
        tenant_id=tenant_id,
        actor=reviewer_id,
        action=action,
        dedup_key=f"{check_id}:decision",
        before_state={"decision": before.decision.value, "reviewer_id": before.reviewer_id},
        after_state={"decision": updated.decision.value, "reviewer_id": updated.reviewer_id},
    )
    logger.info("%s applied to check %s by reviewer %s", action, check_id, reviewer_id)
    return DecisionResult(check=updated, action=action)
