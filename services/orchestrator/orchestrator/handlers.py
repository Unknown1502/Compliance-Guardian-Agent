"""Inline dispatch handlers — the local composition root.

Wires the logical task targets ('ingest', 'check') to the agent core functions
from Phase 2, updating task status around each run and firing the escalation
notification when a check comes back escalated. This is what makes the whole
pipeline run in-process against local emulators without Cloud Tasks.

In production the CloudTasksDispatcher posts to each agent's Cloud Run URL
instead, and the agents call the orchestrator's status-callback endpoint — these
inline handlers are not used there.
"""

from __future__ import annotations

import logging

from compliance_agent.checker import run_compliance_check
from escalation_service.notifications import Notifier
from ingestion_agent.extractor import ingest_document
from schema_validators import CheckDecision
from task_dispatch import InlineDispatcher

from orchestrator.tasks import TaskService

logger = logging.getLogger("cg.orchestrator.handlers")


def build_inline_dispatcher(
    *,
    task_service: TaskService,
    repo,
    storage_client,
    gemini,
    auditor,
    notifier: Notifier,
    rulesets_root: str,
    escalation_threshold: int,
) -> InlineDispatcher:
    def handle_ingest(payload: dict) -> None:
        task_id = payload["task_id"]
        tenant_id = payload["tenant_id"]
        document_id = payload["document_id"]
        task_service.mark_running(task_id, tenant_id)
        try:
            outcome = ingest_document(
                document_id=document_id,
                tenant_id=tenant_id,
                repo=repo,
                storage_client=storage_client,
                gemini=gemini,
                auditor=auditor,
                rulesets_root=rulesets_root,
            )
            task_service.mark_succeeded(
                task_id,
                tenant_id,
                result={
                    "status": outcome.status.value,
                    "missing_required_fields": outcome.missing_required_fields,
                },
            )
        except Exception as exc:
            task_service.mark_failed(task_id, tenant_id, str(exc)[:500])
            raise

    def _build_remediation(*, check, document_id: str) -> None:
        """Generate and store the fix list for a completed check."""
        from remediation_agent.planner import build_remediation_plan

        # A short extract gives the model context without paying to send the
        # whole document a second time; the failure reasons carry the substance.
        extract = ""
        try:
            doc = repo.get_document(document_id, check.tenant_id)
            extract = str(doc.extracted_fields)[:2000]
        except Exception:
            logger.warning("could not load extract for %s; planning without it", document_id)

        build_remediation_plan(
            check=check,
            repo=repo,
            gemini=gemini,
            auditor=auditor,
            rulesets_root=rulesets_root,
            document_extract=extract,
        )

    def handle_check(payload: dict) -> None:
        task_id = payload["task_id"]
        tenant_id = payload["tenant_id"]
        document_id = payload["document_id"]
        task_service.mark_running(task_id, tenant_id)
        try:
            outcome = run_compliance_check(
                document_id=document_id,
                tenant_id=tenant_id,
                repo=repo,
                gemini=gemini,
                auditor=auditor,
                rulesets_root=rulesets_root,
                escalation_threshold=escalation_threshold,
            )
            check = outcome.check
            # Fire the escalation notification when a human is needed.
            if check.decision is CheckDecision.ESCALATED:
                notifier.notify_escalation(
                    tenant_id=tenant_id,
                    check_id=check.check_id,
                    document_id=document_id,
                    risk_score=check.risk_score,
                )

            # Remediation runs for ANY document with a failed or uncertain
            # rule, not only escalated ones. A check can auto-approve and still
            # carry minor violations worth fixing, and gating the fix list
            # behind "a human was needed" hides exactly the small problems a
            # business could clear itself.
            #
            # Never allowed to fail the check: the compliance verdict is the
            # product's guarantee, the fix list is help on top of it. A
            # remediation problem must not cost a customer their verdict.
            try:
                _build_remediation(check=check, document_id=document_id)
            except Exception:
                logger.exception(
                    "remediation planning failed for check %s (verdict unaffected)",
                    check.check_id,
                )
            task_service.mark_succeeded(
                task_id,
                tenant_id,
                result={
                    "check_id": check.check_id,
                    "risk_score": check.risk_score,
                    "decision": check.decision.value,
                },
            )
        except Exception as exc:
            task_service.mark_failed(task_id, tenant_id, str(exc)[:500])
            raise

    return InlineDispatcher({"ingest": handle_ingest, "check": handle_check})
