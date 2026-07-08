"""Firestore data-access helpers shared by the agents.

Centralizes the tenant-scoped read/write patterns so no service re-implements
(and no service forgets) tenant scoping. Every read that returns tenant data
requires the caller to pass the trusted tenant_id; a document whose stored
tenant_id doesn't match is treated as not-found (defense in depth against ID
guessing even though IDs are server-generated).
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore

from schema_validators import CheckDecision, ComplianceCheck, Document, Task, Tenant

COLLECTION_TENANTS = "tenants"
COLLECTION_DOCUMENTS = "documents"
COLLECTION_CHECKS = "compliance_checks"
COLLECTION_TASKS = "tasks"


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
