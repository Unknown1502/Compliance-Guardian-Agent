"""Orchestrator Service — FastAPI (Cloud Run, stateless).

    POST /tasks                       create + dispatch a task (internal)
    GET  /tasks/{task_id}             poll task status
    POST /internal/tasks/{id}/status  status callback for deployed agents

In the local composition (API Gateway + InlineDispatcher) the gateway uses the
TaskService directly; this HTTP surface is what a fully-distributed deployment
uses so the orchestrator is a standalone Cloud Run service too.
"""

from __future__ import annotations

import logging
import os

from audit_logger import AuditLogger
from fastapi import FastAPI, Header, HTTPException, status
from gcp_clients import audit_dataset, audit_table, bigquery_client, firestore_client
from gcp_clients.firestore_repo import FirestoreRepo, NotFoundError, TenantMismatchError
from pydantic import BaseModel, Field
from schema_validators import TaskStatus, TaskType

from orchestrator.tasks import TaskService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cg.orchestrator.api")

app = FastAPI(title="ComplianceGuardian Orchestrator", version="0.1.0")

_state: dict = {}


def _service() -> TaskService:
    if "svc" not in _state:
        # In a distributed deploy the orchestrator uses the CloudTasksDispatcher;
        # constructing it requires target URLs from env. Built lazily here.
        from task_dispatch import CloudTasksDispatcher

        repo = FirestoreRepo(firestore_client())
        auditor = AuditLogger(bigquery_client(), audit_dataset(), audit_table())
        dispatcher = CloudTasksDispatcher(
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("CLOUD_TASKS_LOCATION", "us-central1"),
            queue=os.environ.get("CLOUD_TASKS_QUEUE", "cg-task-queue"),
            target_urls={
                "ingest": os.environ.get("INGESTION_URL", ""),
                "check": os.environ.get("COMPLIANCE_URL", ""),
            },
            invoker_service_account=os.environ.get("INVOKER_SA", ""),
            internal_token=os.environ.get("INTERNAL_TASK_TOKEN"),
        )
        _state["svc"] = TaskService(repo=repo, dispatcher=dispatcher, auditor=auditor)
    return _state["svc"]


def _check_internal_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TASK_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid internal token")


class CreateTaskRequest(BaseModel):
    task_type: TaskType
    target_ref: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)


class TaskResponse(BaseModel):
    task_id: str
    tenant_id: str
    task_type: str
    target_ref: str
    status: str
    result: dict
    error: str | None


class StatusCallback(BaseModel):
    tenant_id: str = Field(min_length=1)
    status: TaskStatus
    result: dict = Field(default_factory=dict)
    error: str | None = None


def _to_response(task) -> "TaskResponse":
    return TaskResponse(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        task_type=task.task_type.value,
        target_ref=task.target_ref,
        status=task.status.value,
        result=task.result,
        error=task.error,
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "orchestrator"}


@app.post("/tasks", response_model=TaskResponse)
def create_task(req: CreateTaskRequest, x_internal_token: str | None = Header(default=None)) -> TaskResponse:
    _check_internal_token(x_internal_token)
    task = _service().create_and_dispatch(
        task_type=req.task_type, target_ref=req.target_ref, tenant_id=req.tenant_id
    )
    return _to_response(task)


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, tenant_id: str, x_internal_token: str | None = Header(default=None)) -> TaskResponse:
    _check_internal_token(x_internal_token)
    try:
        task = _service().get_task(task_id, tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _to_response(task)


@app.post("/internal/tasks/{task_id}/status", response_model=TaskResponse)
def update_status(
    task_id: str, cb: StatusCallback, x_internal_token: str | None = Header(default=None)
) -> TaskResponse:
    _check_internal_token(x_internal_token)
    svc = _service()
    try:
        if cb.status is TaskStatus.RUNNING:
            task = svc.mark_running(task_id, cb.tenant_id)
        elif cb.status is TaskStatus.SUCCEEDED:
            task = svc.mark_succeeded(task_id, cb.tenant_id, cb.result)
        elif cb.status is TaskStatus.FAILED:
            task = svc.mark_failed(task_id, cb.tenant_id, cb.error or "unknown error")
        else:
            task = svc.get_task(task_id, cb.tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TenantMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _to_response(task)
