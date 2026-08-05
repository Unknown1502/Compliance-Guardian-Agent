"""API Gateway composition root — builds and holds shared dependencies.

Keeps client construction (and the inline-vs-cloud dispatch choice) out of the
route handlers. Gemini is built lazily so the gateway can serve the reviewer
decision / read endpoints even when GEMINI_API_KEY is absent (the ingestion and
compliance trigger endpoints then return 503 until a key is configured).
"""

from __future__ import annotations

import logging
import os

from audit_logger import AuditLogger
from escalation_service.notifications import AuditNotifier
from gcp_clients import (
    audit_dataset,
    audit_table,
    bigquery_client,
    firestore_client,
    raw_docs_bucket,
    storage_client,
)
from gcp_clients.firestore_repo import FirestoreRepo
from orchestrator.tasks import TaskService

logger = logging.getLogger("cg.gateway.composition")

RULESETS_ROOT = os.environ.get("RULESETS_ROOT", "rulesets")
ESCALATION_THRESHOLD = int(os.environ.get("RISK_ESCALATION_THRESHOLD", "60"))
DISPATCH_MODE = os.environ.get("CG_DISPATCH_MODE", "inline")  # inline | cloud


class Gateway:
    def __init__(self) -> None:
        self.db = firestore_client()
        self.repo = FirestoreRepo(self.db)
        self.storage = storage_client()
        self.bq = bigquery_client()
        self.auditor = AuditLogger(self.bq, audit_dataset(), audit_table())
        self.notifier = AuditNotifier(self.db, self.auditor)
        self.raw_bucket = raw_docs_bucket()
        self._gemini = None
        self._task_service = None
        self._billing = None

    # Lazy Gemini so read/decision paths work without a key.
    def gemini(self):
        if self._gemini is None:
            from gemini_client import GeminiClient

            self._gemini = GeminiClient()
        return self._gemini

    # Lazy billing so every other endpoint works with no Stripe key
    # configured; only /api/billing/* routes need this to succeed.
    def billing(self):
        if self._billing is None:
            from billing import BillingClient

            self._billing = BillingClient()
        return self._billing

    def task_service(self) -> TaskService:
        """Build the task service + dispatcher on first use.

        inline mode wires the agent cores in-process (needs Gemini); cloud mode
        builds a CloudTasksDispatcher that posts to the agents' Cloud Run URLs.
        """
        if self._task_service is not None:
            return self._task_service

        if DISPATCH_MODE == "cloud":
            from task_dispatch import CloudTasksDispatcher

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
            self._task_service = TaskService(
                repo=self.repo, dispatcher=dispatcher, auditor=self.auditor
            )
            return self._task_service

        # inline (local/dev)
        from orchestrator.handlers import build_inline_dispatcher

        svc = TaskService(repo=self.repo, dispatcher=_Deferred(), auditor=self.auditor)
        dispatcher = build_inline_dispatcher(
            task_service=svc,
            repo=self.repo,
            storage_client=self.storage,
            gemini=self.gemini(),  # inline needs Gemini
            auditor=self.auditor,
            notifier=self.notifier,
            rulesets_root=RULESETS_ROOT,
            escalation_threshold=ESCALATION_THRESHOLD,
        )
        # Late-bind the real dispatcher now that handlers can reference svc.
        svc._dispatcher = dispatcher  # type: ignore[attr-defined]
        self._task_service = svc
        return self._task_service


class _Deferred:
    """Placeholder dispatcher swapped out immediately after TaskService build."""

    def dispatch(self, *, target: str, payload: dict) -> str:  # pragma: no cover
        raise RuntimeError("dispatcher not yet bound")
