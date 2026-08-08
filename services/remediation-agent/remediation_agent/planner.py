"""Remediation Agent core — turn failed rules into an ordered list of fixes.

Design decisions:

  Runs for ANY document with a failed rule, not only escalated ones. A check
  that auto-approves can still carry minor violations worth fixing, and gating
  remediation behind "a human was needed" hides exactly the small problems a
  business could clear itself.

  Ordering is ours, not the model's. Items are sorted blocking-first, then by
  severity, then by shortest job. A model asked to rank its own output ranks it
  differently run to run; a deterministic sort means two identical checks
  produce the same plan, which matters for a product whose promise is
  reproducibility.

  Rule ids are validated against the check's own citations before an item is
  kept. The model is instructed not to invent rules, but "instructed not to" is
  not a guarantee — an item citing a rule that never failed would be a
  fabricated obligation shown to a customer, so it is dropped.

  Gemini failure is not fatal. A deterministic fallback derives one item per
  failed rule from the rule text already on hand, marked used_fixture, so a
  provider still gets a checklist and the pipeline still completes.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from audit_logger import AuditLogger
from gcp_clients.firestore_repo import FirestoreRepo
from schema_validators import (
    ComplianceCheck,
    GeminiCallMetadata,
    RemediationItem,
    RemediationPlan,
    RuleVerdictStatus,
    load_ruleset,
)

from remediation_agent.prompts import (
    REMEDIATION_PROMPT_VERSION,
    REMEDIATION_SYSTEM_INSTRUCTION,
    build_remediation_user_prompt,
)

logger = logging.getLogger("cg.remediation")

# Lower sorts first. Anything unrecognised sorts last rather than crashing.
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# A plan longer than this stops being a checklist and starts being homework.
MAX_ITEMS = 25


@dataclass(frozen=True)
class RemediationOutcome:
    plan: RemediationPlan
    used_fixture: bool


def deterministic_plan_id(check_id: str) -> str:
    """Same check → same plan id, so a redelivered task overwrites rather than duplicates."""
    return f"plan-{uuid.uuid5(uuid.NAMESPACE_URL, check_id).hex[:16]}"


def _sort_key(item: RemediationItem) -> tuple:
    return (
        0 if item.blocking else 1,
        _SEVERITY_ORDER.get(item.severity, 99),
        item.estimated_minutes,
        item.rule_id,
    )


def order_items(items: list[RemediationItem]) -> list[RemediationItem]:
    """Blocking first, then most severe, then quickest — a work order, not a list."""
    return sorted(items, key=_sort_key)


def _collect_failures(check: ComplianceCheck, ruleset) -> list[dict]:
    """Failed and uncertain verdicts, enriched with the rule text and severity.

    Uncertain counts as needing action: "we could not tell" is precisely the
    case a human should resolve, and silently dropping it would let a real gap
    pass unmentioned.
    """
    by_id = {r.id: r for r in ruleset.rules}
    out: list[dict] = []
    for verdict in check.rule_verdicts:
        if verdict.status not in (RuleVerdictStatus.FAIL, RuleVerdictStatus.UNCERTAIN):
            continue
        rule = by_id.get(verdict.rule_id)
        if rule is None:
            # Cannot cite a rule that is not in the ruleset.
            continue
        out.append(
            {
                "rule_id": verdict.rule_id,
                "severity": getattr(rule.severity, "value", str(rule.severity)),
                "description": rule.description,
                "explanation": verdict.explanation,
                "triggering_data_point": verdict.triggering_data_point,
            }
        )
    return out


def _fallback_items(failures: list[dict]) -> list[RemediationItem]:
    """One item per failure, built from the rule text without a model call."""
    items: list[RemediationItem] = []
    for f in failures:
        severity = f.get("severity", "medium")
        items.append(
            RemediationItem(
                rule_id=f["rule_id"],
                title=f"Address: {f['description'][:120]}",
                action=(
                    f"This document did not satisfy the requirement \"{f['description']}\". "
                    f"Reported reason: {f.get('explanation') or 'not specified'}. "
                    "Correct the record so the requirement is met, then re-run the check."
                ),
                blocking=severity in ("critical", "high"),
                estimated_minutes=30 if severity in ("critical", "high") else 15,
                severity=severity,
            )
        )
    return items


def _items_from_model(data: dict, failures: list[dict]) -> list[RemediationItem]:
    """Validate model output into items, dropping anything not grounded in a real failure."""
    allowed = {f["rule_id"]: f for f in failures}
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("model response has no 'items' list")

    items: list[RemediationItem] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        rule_id = str(raw.get("rule_id", "")).strip()
        # A fabricated rule id would present a customer with an obligation that
        # no rule actually imposes.
        if rule_id not in allowed or rule_id in seen:
            continue
        seen.add(rule_id)

        try:
            minutes = int(round(float(raw.get("estimated_minutes", 15))))
        except (TypeError, ValueError):
            minutes = 15
        minutes = max(1, min(10080, minutes))

        title = str(raw.get("title") or "").strip() or allowed[rule_id]["description"][:120]
        action = str(raw.get("action") or "").strip()
        if not action:
            continue  # an item with no action is not remediation

        items.append(
            RemediationItem(
                rule_id=rule_id,
                title=title[:200],
                action=action[:2000],
                blocking=bool(raw.get("blocking", False)),
                estimated_minutes=minutes,
                severity=allowed[rule_id].get("severity", "medium"),
            )
        )

    if not items:
        raise ValueError("model returned no usable items")
    return items


def build_remediation_plan(
    *,
    check: ComplianceCheck,
    repo: FirestoreRepo,
    gemini,  # GeminiClient | None
    auditor: AuditLogger,
    rulesets_root: str,
    document_extract: str = "",
) -> RemediationOutcome:
    """Produce and persist the remediation plan for one compliance check."""
    tenant = repo.get_tenant(check.tenant_id)
    ruleset = load_ruleset(rulesets_root, tenant.industry, tenant.jurisdiction)
    failures = _collect_failures(check, ruleset)

    plan_id = deterministic_plan_id(check.check_id)

    # A clean document is a valid outcome, not an error: an empty plan says
    # "nothing to do" far more clearly than an exception does.
    if not failures:
        plan = RemediationPlan(
            plan_id=plan_id,
            check_id=check.check_id,
            document_id=check.document_id,
            tenant_id=check.tenant_id,
            items=[],
            used_fixture=False,
        )
        _persist(plan, repo=repo, auditor=auditor, model_name="none")
        return RemediationOutcome(plan=plan, used_fixture=False)

    used_fixture = False
    metadata: GeminiCallMetadata | None = None
    try:
        if gemini is None:
            raise RuntimeError("no Gemini client available")
        result = gemini.generate_json(
            prompt_version=REMEDIATION_PROMPT_VERSION,
            system_instruction=REMEDIATION_SYSTEM_INSTRUCTION,
            user_content=build_remediation_user_prompt(
                failures=failures,
                document_extract=document_extract,
                industry=tenant.industry,
                jurisdiction=tenant.jurisdiction,
            ),
        )
        items = _items_from_model(result.data, failures)
        metadata = GeminiCallMetadata(
            prompt_version=result.prompt_version,
            model_name=result.model_name,
            model_version=result.model_version,
            response_id=result.response_id,
        )
        model_name = result.model_name
    except Exception as exc:
        # Includes malformed JSON that survived gemini_client's repair pass.
        logger.warning("remediation via Gemini failed (%s) — using derived plan", exc)
        items = _fallback_items(failures)
        used_fixture = True
        model_name = "fixture"

    plan = RemediationPlan(
        plan_id=plan_id,
        check_id=check.check_id,
        document_id=check.document_id,
        tenant_id=check.tenant_id,
        items=order_items(items)[:MAX_ITEMS],
        gemini_metadata=metadata,
        used_fixture=used_fixture,
    )
    _persist(plan, repo=repo, auditor=auditor, model_name=model_name)
    return RemediationOutcome(plan=plan, used_fixture=used_fixture)


def _persist(
    plan: RemediationPlan, *, repo: FirestoreRepo, auditor: AuditLogger, model_name: str
) -> None:
    """Write the plan, then audit it. Storage first so the trail never claims
    a plan that does not exist."""
    repo.upsert_remediation_plan(plan)
    auditor.log(
        tenant_id=plan.tenant_id,
        actor="remediation-agent",
        action="remediation_plan_generated",
        dedup_key=f"{plan.check_id}:remediation",
        before_state=None,
        after_state={
            "plan_id": plan.plan_id,
            "check_id": plan.check_id,
            "document_id": plan.document_id,
            "item_count": len(plan.items),
            "blocking_count": sum(1 for i in plan.items if i.blocking),
            "estimated_minutes": plan.total_estimated_minutes,
            "gemini_model": model_name,
            "used_fixture": plan.used_fixture,
        },
    )
