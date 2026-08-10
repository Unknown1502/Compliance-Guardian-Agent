"""API Gateway composition root — builds and holds shared dependencies.

Keeps client construction (and the inline-vs-cloud dispatch choice) out of the
route handlers. Gemini is built lazily so the gateway can serve the reviewer
decision / read endpoints even when GEMINI_API_KEY is absent (the ingestion and
compliance trigger endpoints then return 503 until a key is configured).
"""

from __future__ import annotations

import logging
import os

import time

from audit_logger import AuditLogger
from auth_middleware import (
    SERVICE_ROLE,
    AuthContext,
    set_api_key_resolver,
    set_tenant_status_resolver,
)
from escalation_service.notifications import AuditNotifier
from notifications import SlackNotifier
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
# Used to build the "Review" deep link in Slack escalation alerts.
DASHBOARD_BASE_URL = os.environ.get("CG_DASHBOARD_BASE_URL", "")


class Gateway:
    def __init__(self) -> None:
        self.db = firestore_client()
        self.repo = FirestoreRepo(self.db)
        self.storage = storage_client()
        self.bq = bigquery_client()
        self.auditor = AuditLogger(self.bq, audit_dataset(), audit_table())
        # Slack wraps the audit notifier rather than replacing it: the audit
        # record is the guarantee, Slack is the convenience on top.
        self.notifier = SlackNotifier(
            AuditNotifier(self.db, self.auditor),
            self.repo,
            dashboard_base_url=DASHBOARD_BASE_URL,
        )
        self.raw_bucket = raw_docs_bucket()
        self._gemini = None
        self._task_service = None
        self._register_api_key_auth()
        self._register_tenant_status()

    def _register_api_key_auth(self) -> None:
        """Teach auth_middleware how to resolve an X-API-Key header.

        Injected here so the middleware itself has no datastore dependency,
        and so the tenant on the resolved context comes from the stored key
        record — the caller never supplies it.
        """
        from api_keys import hash_api_key, looks_like_api_key

        repo = self.repo

        def resolve(plaintext: str):
            if not looks_like_api_key(plaintext):
                return None
            record = repo.find_api_key_by_hash(hash_api_key(plaintext))
            if record is None:
                return None
            repo.touch_api_key(record.key_id)
            # A machine identity, NOT an owner. Scoping still comes from the
            # key's own tenant_id so cross-tenant access remains impossible,
            # and SERVICE_ROLE additionally means the key cannot manage the
            # workspace or decide escalations — see auth_middleware.
            return AuthContext(
                uid=f"api_key:{record.key_id}",
                tenant_id=record.tenant_id,
                role=SERVICE_ROLE,
                email=None,
            )

        set_api_key_resolver(resolve)

    def _register_tenant_status(self) -> None:
        """Teach auth_middleware to refuse suspended workspaces.

        Cached for a short window because this runs on EVERY authenticated
        request and would otherwise add a Firestore read to each one. The
        trade is explicit: a suspension takes up to TTL seconds to bite. For
        stopping abuse or chasing a failed payment that is fine; if it ever
        needs to be instant, the answer is a push invalidation, not a longer
        hot path.

        Fails open on a datastore error — see _enforce_tenant_status. A blip
        in Firestore must not lock every customer out of the product.
        """
        repo = self.repo
        ttl = float(os.environ.get("CG_TENANT_STATUS_TTL_SECONDS", "30"))
        cache: dict[str, tuple[float, str]] = {}

        def resolve(tenant_id: str) -> str:
            now = time.monotonic()
            hit = cache.get(tenant_id)
            if hit and now - hit[0] < ttl:
                return hit[1]
            tenant = repo.get_tenant(tenant_id)
            reason = ""
            if getattr(tenant, "status", None) == "suspended" or (
                getattr(getattr(tenant, "status", None), "value", None) == "suspended"
            ):
                reason = tenant.status_reason or "Contact support to restore access."
            cache[tenant_id] = (now, reason)
            return reason

        set_tenant_status_resolver(resolve)

    # Lazy Gemini so read/decision paths work without a key.
    def gemini(self):
        if self._gemini is None:
            from gemini_client import GeminiClient

            self._gemini = GeminiClient()
        return self._gemini

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
