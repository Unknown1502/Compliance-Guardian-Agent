"""Orchestrator task lifecycle.

TaskService owns the Task records that back GET /api/tasks/:id. It creates a
task, dispatches the work through the injected TaskDispatcher (Cloud Tasks in
prod, inline locally), and exposes status transitions used both by the inline
handler and by the internal status-callback endpoint that deployed agents call
when they finish.

Tasks are intentionally NOT idempotent units (each request is a new task_id) —
idempotency lives in the agents (deterministic document/check IDs from Phase 2),
so duplicate Cloud Task delivery cannot corrupt state regardless of task rows.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from audit_logger import AuditLogger
from gcp_clients.firestore_repo import FirestoreRepo
from schema_validators import Task, TaskStatus, TaskType
from task_dispatch import TaskDispatcher

logger = logging.getLogger("cg.orchestrator")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskService:
    def __init__(
        self,
        *,
        repo: FirestoreRepo,
        dispatcher: TaskDispatcher,
        auditor: AuditLogger,
    ) -> None:
        self._repo = repo
        self._dispatcher = dispatcher
        self._auditor = auditor

    def create_and_dispatch(
        self, *, task_type: TaskType, target_ref: str, tenant_id: str
    ) -> Task:
        task = Task(
            task_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            task_type=task_type,
            target_ref=target_ref,
            status=TaskStatus.QUEUED,
        )
        self._repo.upsert_task(task)
        self._auditor.log(
            tenant_id=tenant_id,
            actor="orchestrator",
            action="task.created",
            dedup_key=f"{task.task_id}:created",
            before_state=None,
            after_state={"task_type": task_type.value, "target_ref": target_ref},
        )
        payload = {
            "task_id": task.task_id,
            "tenant_id": tenant_id,
            "document_id": target_ref,
            "target_ref": target_ref,
        }
        try:
            self._dispatcher.dispatch(target=task_type.value, payload=payload)
        except Exception as exc:  # dispatch failure is terminal for this task
            logger.exception("dispatch failed for task %s", task.task_id)
            self.mark_failed(task.task_id, tenant_id, f"dispatch failed: {exc}")
            raise
        # For inline dispatch the handler has already driven the task to a
        # terminal state; re-read so callers see the final status.
        return self._repo.get_task(task.task_id, tenant_id)

    def get_task(self, task_id: str, tenant_id: str) -> Task:
        return self._repo.get_task(task_id, tenant_id)

    def mark_running(self, task_id: str, tenant_id: str) -> Task:
        return self._transition(task_id, tenant_id, TaskStatus.RUNNING)

    def mark_succeeded(self, task_id: str, tenant_id: str, result: dict) -> Task:
        return self._transition(task_id, tenant_id, TaskStatus.SUCCEEDED, result=result)

    def mark_failed(self, task_id: str, tenant_id: str, error: str) -> Task:
        return self._transition(task_id, tenant_id, TaskStatus.FAILED, error=error)

    def _transition(
        self,
        task_id: str,
        tenant_id: str,
        status: TaskStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> Task:
        task = self._repo.get_task(task_id, tenant_id)
        updates = {"status": status, "updated_at": _now()}
        if result is not None:
            updates["result"] = result
        if error is not None:
            updates["error"] = error
        updated = task.model_copy(update=updates)
        self._repo.upsert_task(updated)
        return updated
