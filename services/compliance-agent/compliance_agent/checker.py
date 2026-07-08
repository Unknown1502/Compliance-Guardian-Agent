"""Compliance Agent core — evaluate extracted data against a ruleset via Gemini.

HTTP/Cloud-Tasks-agnostic, like the ingestion core. Exposes `run_compliance_check()`.

Key safeguards (Phase 2 Thinking Protocol):

  Anti-fabricated-citation: every rule_id Gemini returns is validated against
  the ruleset's real rule ids. Hallucinated ids are dropped and recorded in the
  audit trail; citations attached to the check are ONLY validated ids.

  Score reconciliation: Gemini's holistic risk_score is trusted but cannot
  under-score a serious violation. A severity floor derived from actually-failed
  (or uncertain-on-important) rules can only raise the score, never lower it.
  Both the raw Gemini score and the final score are audit-logged, so the
  adjustment is fully traceable.

  Idempotency: check_id is deterministic (uuid5 over document_id +
  rule_set_version). Cloud Task redelivery overwrites the same check rather than
  creating duplicates; the audit dedup_key includes the check_id + revision.

  Missing-verdict handling: if Gemini omits a rule, that rule is injected as an
  'uncertain' verdict (confidence 0) so the check always covers every rule.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from audit_logger import AuditLogger
from gcp_clients.firestore_repo import FirestoreRepo
from schema_validators import (
    CheckDecision,
    ComplianceCheck,
    DocumentStatus,
    GeminiCallMetadata,
    RuleSet,
    RuleVerdict,
    RuleVerdictStatus,
    load_ruleset,
)

from compliance_agent.prompts import (
    COMPLIANCE_PROMPT_VERSION,
    COMPLIANCE_SYSTEM_INSTRUCTION,
    build_compliance_user_prompt,
)

logger = logging.getLogger("cg.compliance")

# Stable namespace for deterministic check IDs.
_CHECK_NAMESPACE = uuid.UUID("7c1d3e2b-9a44-4f16-8c0e-2b7a9d6f1e05")

# Severity → minimum risk floor when a rule of that severity FAILS.
_FAIL_FLOOR = {"critical": 80, "high": 60, "medium": 40, "low": 20}
# Severity → floor when a rule of that severity is UNCERTAIN (needs a human).
_UNCERTAIN_FLOOR = {"critical": 60, "high": 60, "medium": 25, "low": 10}


class DocumentNotProcessedError(RuntimeError):
    """Raised when a compliance check is requested before extraction succeeded."""


def deterministic_check_id(document_id: str, rule_set_version: str) -> str:
    return str(uuid.uuid5(_CHECK_NAMESPACE, f"{document_id}|{rule_set_version}"))


@dataclass(frozen=True)
class ComplianceOutcome:
    check: ComplianceCheck
    gemini_raw_risk_score: int
    dropped_citations: list[str]


def _coerce_status(value: str) -> RuleVerdictStatus:
    try:
        return RuleVerdictStatus(str(value).lower().strip())
    except ValueError:
        return RuleVerdictStatus.UNCERTAIN


def _severity_of(ruleset: RuleSet, rule_id: str) -> str:
    for r in ruleset.rules:
        if r.id == rule_id:
            return r.severity.value
    return "medium"


def _reconcile_score(
    gemini_score: int, verdicts: list[RuleVerdict], ruleset: RuleSet
) -> int:
    """Final score = max(gemini_score, severity floor from failed/uncertain rules)."""
    floor = 0
    for v in verdicts:
        sev = _severity_of(ruleset, v.rule_id)
        if v.status is RuleVerdictStatus.FAIL:
            floor = max(floor, _FAIL_FLOOR.get(sev, 40))
        elif v.status is RuleVerdictStatus.UNCERTAIN:
            floor = max(floor, _UNCERTAIN_FLOOR.get(sev, 25))
    return max(0, min(100, max(gemini_score, floor)))


def _build_verdicts(
    raw_verdicts: list, ruleset: RuleSet
) -> tuple[list[RuleVerdict], list[str]]:
    """Validate Gemini verdicts against the ruleset; inject missing rules.

    Returns (verdicts, dropped_citation_ids).
    """
    valid_ids = ruleset.rule_ids()
    by_id: dict[str, RuleVerdict] = {}
    dropped: list[str] = []

    for item in raw_verdicts or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("rule_id", "")).strip()
        if rid not in valid_ids:
            if rid:
                dropped.append(rid)  # fabricated / unknown id
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        verdict = RuleVerdict(
            rule_id=rid,
            status=_coerce_status(item.get("status", "uncertain")),
            confidence=confidence,
            explanation=str(item.get("explanation") or "No explanation provided.").strip()
            or "No explanation provided.",
            triggering_data_point=item.get("triggering_data_point"),
        )
        by_id[rid] = verdict  # last wins if duplicated

    # Inject any rule Gemini failed to address as uncertain (never silently skip).
    for r in ruleset.rules:
        if r.id not in by_id:
            by_id[r.id] = RuleVerdict(
                rule_id=r.id,
                status=RuleVerdictStatus.UNCERTAIN,
                confidence=0.0,
                explanation="Model did not return a verdict for this rule; flagged for review.",
                triggering_data_point=None,
            )

    # Preserve ruleset order for stable output.
    ordered = [by_id[r.id] for r in ruleset.rules]
    return ordered, dropped


def run_compliance_check(
    *,
    document_id: str,
    tenant_id: str,
    repo: FirestoreRepo,
    gemini,  # GeminiClient
    auditor: AuditLogger,
    rulesets_root: str,
    escalation_threshold: int,
) -> ComplianceOutcome:
    """Evaluate one processed document against its ruleset. Tenant-scoped, idempotent."""
    document = repo.get_document(document_id, tenant_id)  # tenant check
    if document.status is not DocumentStatus.PROCESSED:
        raise DocumentNotProcessedError(
            f"document {document_id} is {document.status.value}, expected processed"
        )
    tenant = repo.get_tenant(tenant_id)
    ruleset = load_ruleset(rulesets_root, tenant.industry, tenant.jurisdiction)

    check_id = deterministic_check_id(document_id, ruleset.rule_set_version)

    try:
        user_prompt = build_compliance_user_prompt(
            ruleset=ruleset, extracted_fields=document.extracted_fields
        )
        result = gemini.generate_json(
            prompt_version=COMPLIANCE_PROMPT_VERSION,
            system_instruction=COMPLIANCE_SYSTEM_INSTRUCTION,
            user_content=user_prompt,
        )

        raw_score_val = result.data.get("risk_score", 0)
        try:
            gemini_raw_score = int(round(float(raw_score_val)))
        except (TypeError, ValueError):
            gemini_raw_score = 0
        gemini_raw_score = max(0, min(100, gemini_raw_score))

        verdicts, dropped = _build_verdicts(result.data.get("rule_verdicts"), ruleset)
        final_score = _reconcile_score(gemini_raw_score, verdicts, ruleset)

        # Citations: real rule ids that failed or were uncertain (the ones that
        # drove risk). All are guaranteed to be in the ruleset by construction.
        citations = [
            v.rule_id
            for v in verdicts
            if v.status in (RuleVerdictStatus.FAIL, RuleVerdictStatus.UNCERTAIN)
        ]

        justification = str(
            result.data.get("justification") or "No justification provided by the model."
        ).strip() or "No justification provided by the model."
        if dropped:
            justification += (
                f" [Note: {len(dropped)} unrecognized rule citation(s) returned by "
                f"the model were discarded and not used.]"
            )

        decision = (
            CheckDecision.ESCALATED
            if final_score >= escalation_threshold
            else CheckDecision.AUTO_APPROVED
        )

        check = ComplianceCheck(
            check_id=check_id,
            document_id=document_id,
            tenant_id=tenant_id,
            rule_set_version=ruleset.rule_set_version,
            risk_score=final_score,
            justification=justification,
            citations=citations,
            decision=decision,
            reviewer_id=None,
            rule_verdicts=verdicts,
            gemini_metadata=GeminiCallMetadata(
                prompt_version=result.prompt_version,
                model_name=result.model_name,
                model_version=result.model_version,
                response_id=result.response_id,
            ),
        )
        repo.upsert_check(check)

        auditor.log(
            tenant_id=tenant_id,
            actor="compliance-agent",
            action="compliance.checked",
            dedup_key=f"{check_id}:{result.prompt_version}",
            before_state={"document_id": document_id, "document_status": document.status.value},
            after_state={
                "check_id": check_id,
                "risk_score": final_score,
                "gemini_raw_risk_score": gemini_raw_score,
                "decision": decision.value,
                "citations": citations,
                "dropped_citations": dropped,
                "prompt_version": result.prompt_version,
                "model_name": result.model_name,
                "model_version": result.model_version,
            },
        )

        return ComplianceOutcome(
            check=check,
            gemini_raw_risk_score=gemini_raw_score,
            dropped_citations=dropped,
        )

    except Exception as exc:
        logger.exception("compliance check failed for document %s", document_id)
        auditor.log(
            tenant_id=tenant_id,
            actor="compliance-agent",
            action="compliance.check_failed",
            dedup_key=f"{check_id}:failure",
            before_state=None,
            after_state={"error": str(exc)[:500]},
        )
        raise
