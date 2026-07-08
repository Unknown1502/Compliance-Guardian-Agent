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
