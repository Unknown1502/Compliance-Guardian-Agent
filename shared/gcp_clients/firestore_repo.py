"""Firestore data-access helpers shared by the agents.

Centralizes the tenant-scoped read/write patterns so no service re-implements
(and no service forgets) tenant scoping. Every read that returns tenant data
requires the caller to pass the trusted tenant_id; a document whose stored
tenant_id doesn't match is treated as not-found (defense in depth against ID
guessing even though IDs are server-generated).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from schema_validators import (
    ApiKeyRecord,
    CheckDecision,
    ComplianceCheck,
    Document,
    Task,
    Tenant,
    TenantUser,
)

COLLECTION_TENANTS = "tenants"
COLLECTION_DOCUMENTS = "documents"
COLLECTION_CHECKS = "compliance_checks"
COLLECTION_TASKS = "tasks"
COLLECTION_REMEDIATION = "remediation_plans"
COLLECTION_USERS = "users"
COLLECTION_API_KEYS = "api_keys"


class TenantMismatchError(PermissionError):
    """Raised when a fetched record's tenant_id != the caller's tenant_id."""


class NotFoundError(LookupError):
    """Raised when a document/check does not exist."""


class DecisionConflictError(RuntimeError):
    """Raised when a reviewer decision loses a race (check already decided)."""


class FirestoreRepo:
    def __init__(self, client: firestore.Client) -> None:
        self._db = client

    # -- tenants ------------------------------------------------------------

    def get_tenant(self, tenant_id: str) -> Tenant:
        snap = self._db.collection(COLLECTION_TENANTS).document(tenant_id).get()
        if not snap.exists:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return Tenant.model_validate(snap.to_dict())

    def upsert_tenant(self, tenant: Tenant) -> None:
        self._db.collection(COLLECTION_TENANTS).document(tenant.tenant_id).set(
            tenant.model_dump(mode="json")
        )

    # -- users --------------------------------------------------------------

    def upsert_user(self, user: TenantUser) -> None:
        self._db.collection(COLLECTION_USERS).document(user.uid).set(
            user.model_dump(mode="json")
        )

    def list_users(self, tenant_id: str, limit: int = 100) -> list[TenantUser]:
        q = (
            self._db.collection(COLLECTION_USERS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        return [TenantUser.model_validate(s.to_dict()) for s in q.stream()]

    def get_user(self, uid: str, tenant_id: str) -> TenantUser:
        snap = self._db.collection(COLLECTION_USERS).document(uid).get()
        if not snap.exists:
            raise NotFoundError(f"user {uid} not found")
        user = TenantUser.model_validate(snap.to_dict())
        if user.tenant_id != tenant_id:
            raise TenantMismatchError(f"user {uid} belongs to another tenant")
        return user

    def delete_user(self, uid: str, tenant_id: str) -> None:
        # Read-then-delete so a caller can never remove a user outside their
        # own tenant by guessing a uid.
        self.get_user(uid, tenant_id)
        self._db.collection(COLLECTION_USERS).document(uid).delete()

    # -- api keys -----------------------------------------------------------

    def upsert_api_key(self, key: ApiKeyRecord) -> None:
        self._db.collection(COLLECTION_API_KEYS).document(key.key_id).set(
            key.model_dump(mode="json")
        )

    def list_api_keys(self, tenant_id: str, limit: int = 100) -> list[ApiKeyRecord]:
        q = (
            self._db.collection(COLLECTION_API_KEYS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        return [ApiKeyRecord.model_validate(s.to_dict()) for s in q.stream()]

    def find_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        """Look a key up by its hash. Returns None if absent or revoked.

        Queried by hash, never by plaintext — the plaintext is not stored
        anywhere, so there is nothing to match against even in principle.
        """
        q = (
            self._db.collection(COLLECTION_API_KEYS)
            .where(filter=firestore.FieldFilter("key_hash", "==", key_hash))
            .limit(1)
        )
        for snap in q.stream():
            record = ApiKeyRecord.model_validate(snap.to_dict())
            return None if record.revoked else record
        return None

    def revoke_api_key(self, key_id: str, tenant_id: str) -> ApiKeyRecord:
        snap = self._db.collection(COLLECTION_API_KEYS).document(key_id).get()
        if not snap.exists:
            raise NotFoundError(f"api key {key_id} not found")
        record = ApiKeyRecord.model_validate(snap.to_dict())
        if record.tenant_id != tenant_id:
            raise TenantMismatchError(f"api key {key_id} belongs to another tenant")
        revoked = record.model_copy(update={"revoked": True})
        self.upsert_api_key(revoked)
        return revoked

    def touch_api_key(self, key_id: str) -> None:
        """Record last use. Best-effort: never fail a request over telemetry."""
        try:
            self._db.collection(COLLECTION_API_KEYS).document(key_id).update(
                {"last_used_at": datetime.now(timezone.utc).isoformat()}
            )
        except Exception:  # pragma: no cover - telemetry only
            pass

    # -- retention ----------------------------------------------------------

    def list_documents_created_before(
        self, tenant_id: str, cutoff: datetime, limit: int = 500
    ) -> list[Document]:
        """Documents older than `cutoff`, for the retention sweep.

        Deliberately tenant-scoped and bounded: the sweep processes one
        tenant at a time so a bug cannot run away across the whole dataset.
        """
        q = (
            self._db.collection(COLLECTION_DOCUMENTS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        out: list[Document] = []
        for snap in q.stream():
            doc = Document.model_validate(snap.to_dict())
            if doc.created_at < cutoff:
                out.append(doc)
        return out

    def delete_document(self, document_id: str, tenant_id: str) -> None:
        self.get_document(document_id, tenant_id)  # tenant check before delete
        self._db.collection(COLLECTION_DOCUMENTS).document(document_id).delete()

    def list_all_tenants(self, limit: int = 1000) -> list[Tenant]:
        """All tenants. Used only by the scheduled retention sweep."""
        return [
            Tenant.model_validate(s.to_dict())
            for s in self._db.collection(COLLECTION_TENANTS).limit(limit).stream()
        ]

    # -- documents ----------------------------------------------------------

    def get_document(self, document_id: str, tenant_id: str) -> Document:
        snap = self._db.collection(COLLECTION_DOCUMENTS).document(document_id).get()
        if not snap.exists:
            raise NotFoundError(f"document {document_id} not found")
        doc = Document.model_validate(snap.to_dict())
        if doc.tenant_id != tenant_id:
            raise TenantMismatchError(
                f"document {document_id} belongs to another tenant"
            )
        return doc

    def upsert_document(self, document: Document) -> None:
        self._db.collection(COLLECTION_DOCUMENTS).document(document.document_id).set(
            document.model_dump(mode="json")
        )

    def update_document_fields(
        self, document_id: str, tenant_id: str, updates: dict[str, Any]
    ) -> Document:
        """Read-verify-write: confirm tenant ownership, then patch fields."""
        doc = self.get_document(document_id, tenant_id)  # raises on mismatch
        patched = doc.model_copy(update=updates)
        self.upsert_document(patched)
        return patched

    # -- compliance checks --------------------------------------------------

    def get_check(self, check_id: str, tenant_id: str) -> ComplianceCheck:
        snap = self._db.collection(COLLECTION_CHECKS).document(check_id).get()
        if not snap.exists:
            raise NotFoundError(f"compliance check {check_id} not found")
        check = ComplianceCheck.model_validate(snap.to_dict())
        if check.tenant_id != tenant_id:
            raise TenantMismatchError(f"check {check_id} belongs to another tenant")
        return check

    def upsert_check(self, check: ComplianceCheck) -> None:
        self._db.collection(COLLECTION_CHECKS).document(check.check_id).set(
            check.model_dump(mode="json")
        )

    def list_checks(self, tenant_id: str, limit: int = 200) -> list[ComplianceCheck]:
        """All checks for one tenant, regardless of decision."""
        q = (
            self._db.collection(COLLECTION_CHECKS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        return [ComplianceCheck.model_validate(s.to_dict()) for s in q.stream()]

    def list_escalated_checks(self, tenant_id: str, limit: int = 200) -> list[ComplianceCheck]:
        """Checks still awaiting a human decision, for the review queue."""
        q = (
            self._db.collection(COLLECTION_CHECKS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .where(filter=firestore.FieldFilter("decision", "==", CheckDecision.ESCALATED.value))
            .limit(limit)
        )
        return [ComplianceCheck.model_validate(s.to_dict()) for s in q.stream()]

    def list_documents(self, tenant_id: str, limit: int = 50) -> list[Document]:
        query = (
            self._db.collection(COLLECTION_DOCUMENTS)
            .where("tenant_id", "==", tenant_id)
            .limit(limit)
        )
        return [Document.model_validate(s.to_dict()) for s in query.stream()]

    # -- tasks --------------------------------------------------------------

    def upsert_task(self, task: Task) -> None:
        self._db.collection(COLLECTION_TASKS).document(task.task_id).set(
            task.model_dump(mode="json")
        )

    def get_task(self, task_id: str, tenant_id: str) -> Task:
        snap = self._db.collection(COLLECTION_TASKS).document(task_id).get()
        if not snap.exists:
            raise NotFoundError(f"task {task_id} not found")
        task = Task.model_validate(snap.to_dict())
        if task.tenant_id != tenant_id:
            raise TenantMismatchError(f"task {task_id} belongs to another tenant")
        return task

    # -- reviewer decision (concurrency-safe) -------------------------------

    def apply_reviewer_decision(
        self,
        *,
        check_id: str,
        tenant_id: str,
        reviewer_id: str,
        decision: CheckDecision,
    ) -> ComplianceCheck:
        """Apply an approve/reject decision inside a Firestore transaction.

        Concurrency guarantee: the transaction re-reads the check and refuses to
        act unless it is still ESCALATED and unclaimed (reviewer_id is None). If
        two reviewers act at once, exactly one transaction commits; the other
        sees the now-decided state and raises DecisionConflictError -> HTTP 409.
        This is what prevents a double-decision write race on one escalation.

        The decision timestamp is recorded on the immutable audit_logs row
        (created_at) by the caller, keeping ComplianceCheck's fields exactly as
        the spec defines them.
        """
        db = self._db
        check_ref = db.collection(COLLECTION_CHECKS).document(check_id)

        @firestore.transactional
        def _txn(transaction) -> ComplianceCheck:
            snap = check_ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFoundError(f"compliance check {check_id} not found")
            current = ComplianceCheck.model_validate(snap.to_dict())
            if current.tenant_id != tenant_id:
                raise TenantMismatchError(f"check {check_id} belongs to another tenant")
            if current.decision is not CheckDecision.ESCALATED or current.reviewer_id is not None:
                raise DecisionConflictError(
                    f"check {check_id} is not awaiting review "
                    f"(decision={current.decision.value}, reviewer_id={current.reviewer_id})"
                )
            updated = current.model_copy(
                update={"decision": decision, "reviewer_id": reviewer_id}
            )
            transaction.set(check_ref, updated.model_dump(mode="json"))
            return updated

        return _txn(db.transaction())

    # -- remediation plans --------------------------------------------------

    def upsert_remediation_plan(self, plan) -> None:
        """Write a plan. The id is deterministic per check, so a redelivered
        task overwrites its own plan instead of creating a duplicate."""
        self._db.collection(COLLECTION_REMEDIATION).document(plan.plan_id).set(
            plan.model_dump(mode="json")
        )

    def get_remediation_plan_for_check(self, check_id: str, tenant_id: str):
        """The plan for one check, or None. Tenant-scoped like every read here:
        a plan belonging to another tenant is indistinguishable from absent."""
        from schema_validators import RemediationPlan

        snaps = (
            self._db.collection(COLLECTION_REMEDIATION)
            .where("check_id", "==", check_id)
            .where("tenant_id", "==", tenant_id)
            .limit(1)
            .stream()
        )
        for snap in snaps:
            return RemediationPlan.model_validate(snap.to_dict())
        return None

    def list_remediation_plans(self, tenant_id: str, limit: int = 100) -> list:
        from schema_validators import RemediationPlan

        snaps = (
            self._db.collection(COLLECTION_REMEDIATION)
            .where("tenant_id", "==", tenant_id)
            .limit(limit)
            .stream()
        )
        return [RemediationPlan.model_validate(s.to_dict()) for s in snaps]
