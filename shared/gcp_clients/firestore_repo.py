"""Firestore data-access helpers shared by the agents.

Centralizes the tenant-scoped read/write patterns so no service re-implements
(and no service forgets) tenant scoping. Every read that returns tenant data
requires the caller to pass the trusted tenant_id; a document whose stored
tenant_id doesn't match is treated as not-found (defense in depth against ID
guessing even though IDs are server-generated).
"""

from __future__ import annotations

import logging
import os

from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore
from pydantic import ValidationError

from schema_validators import (
    EntitlementSource,
    SupportMessage,
    SupportTicket,
    ApiKeyRecord,
    CheckDecision,
    ComplianceCheck,
    Document,
    ReportRecord,
    Task,
    Tenant,
    TenantUser,
    validate_stored,
)

logger = logging.getLogger("cg.firestore_repo")

# A Pro subscription's monthly allowance. Config, not a magic number buried
# in a transaction — raising the plan's value should be one edit here.
PRO_MONTHLY_REPORTS = int(os.environ.get("CG_PRO_MONTHLY_REPORTS", "20"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


COLLECTION_TENANTS = "tenants"
COLLECTION_DOCUMENTS = "documents"
COLLECTION_CHECKS = "compliance_checks"
COLLECTION_TASKS = "tasks"
COLLECTION_REMEDIATION = "remediation_plans"
COLLECTION_USERS = "users"
COLLECTION_API_KEYS = "api_keys"
COLLECTION_TICKETS = "support_tickets"
COLLECTION_COUNTERS = "counters"
COLLECTION_REPORTS = "reports"


class TenantMismatchError(PermissionError):
    """Raised when a fetched record's tenant_id != the caller's tenant_id."""


class NotFoundError(LookupError):
    """Raised when a document/check does not exist."""


class DecisionConflictError(RuntimeError):
    """Raised when a reviewer decision loses a race (check already decided)."""



class EntitlementExhaustedError(RuntimeError):
    """Raised when a workspace has no report allowance left.

    Distinct from an authorization error on purpose: the caller is perfectly
    entitled to be here, they have simply used what they paid for. The
    gateway turns this into 402 Payment Required rather than 403.
    """


def _own_or_raise(snap, tenant_id: str, what: str) -> dict:
    """Confirm a fetched record belongs to the caller, BEFORE validating it.

    Ordering is the whole point. Validating first means a *malformed* record
    belonging to another tenant raises ValidationError → 500, while a record
    that simply does not exist → 404. That difference is an existence oracle:
    an unauthorised caller learns which ids are real by reading status codes.
    It is not hypothetical — a seeder wrote one unexpected field into this
    project's records and every affected read 500'd.

    Reading tenant_id straight off the raw dict makes both cases identical and
    means one tenant's bad data cannot produce errors for another tenant at
    all. Callers still convert the mismatch to 404, never 403.
    """
    if not snap.exists:
        raise NotFoundError(f"{what} not found")
    raw = snap.to_dict() or {}
    if raw.get("tenant_id") != tenant_id:
        raise TenantMismatchError(f"{what} belongs to another tenant")
    return raw


class FirestoreRepo:
    def __init__(self, client: firestore.Client) -> None:
        self._db = client

    # -- tenants ------------------------------------------------------------

    def get_tenant(self, tenant_id: str) -> Tenant:
        snap = self._db.collection(COLLECTION_TENANTS).document(tenant_id).get()
        if not snap.exists:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return validate_stored(Tenant, snap.to_dict())

    def consume_report_entitlement(self, tenant_id: str) -> Tenant:
        """Spend one report allowance, atomically.

        The naive version — read remaining, decide, write later — loses under
        concurrency: two requests both read "1 remaining", both decide yes,
        and the workspace gets two reports for one payment. Firestore
        transactions re-read inside the transaction and retry on contention,
        so exactly one of those commits and the other sees zero remaining.

        Also rolls a Pro subscription into its next period here rather than on
        a schedule. There is no cron in this system, so an allowance that
        renewed "monthly" via a background job would silently not renew at
        all; doing it lazily on the request that needs it means the renewal
        happens exactly when it matters and needs nothing else to be running.

        Raises EntitlementExhaustedError when nothing is left. Never returns a
        tenant with consumed > granted.
        """
        db = self._db
        ref = db.collection(COLLECTION_TENANTS).document(tenant_id)

        @firestore.transactional
        def _txn(transaction) -> Tenant:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFoundError(f"tenant {tenant_id} not found")
            tenant = validate_stored(Tenant, snap.to_dict())

            # Lazy Pro renewal: the period lapsed, so the next allowance is due.
            if (
                tenant.entitlement_source is EntitlementSource.PRO
                and tenant.entitlement_expires_at is not None
                and tenant.entitlement_expires_at <= utcnow()
            ):
                tenant.reports_granted = tenant.reports_consumed + PRO_MONTHLY_REPORTS
                tenant.entitlement_expires_at = utcnow() + timedelta(days=30)

            if tenant.reports_consumed >= tenant.reports_granted:
                raise EntitlementExhaustedError(
                    f"tenant {tenant_id} has no report allowance remaining"
                )

            tenant.reports_consumed += 1
            transaction.set(ref, tenant.model_dump(mode="json"))
            return tenant

        return _txn(db.transaction())

    def release_report_entitlement(self, tenant_id: str) -> None:
        """Give back an allowance spent on a report that never got produced.

        Called when generation fails after consumption. Clamped at zero so a
        double release cannot manufacture free reports, which would be the
        obvious way to abuse a refund path.
        """
        db = self._db
        ref = db.collection(COLLECTION_TENANTS).document(tenant_id)

        @firestore.transactional
        def _txn(transaction) -> None:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return
            tenant = validate_stored(Tenant, snap.to_dict())
            if tenant.reports_consumed <= 0:
                return
            tenant.reports_consumed -= 1
            transaction.set(ref, tenant.model_dump(mode="json"))

        _txn(db.transaction())

    def grant_report_entitlement(
        self, tenant_id: str, *, source: EntitlementSource, quantity: int
    ) -> Tenant:
        """Add allowance after a verified payment.

        Additive rather than absolute: a customer who buys a single report
        while still holding an unused free one keeps both. Setting the total
        instead would quietly confiscate what they already had.
        """
        db = self._db
        ref = db.collection(COLLECTION_TENANTS).document(tenant_id)

        @firestore.transactional
        def _txn(transaction) -> Tenant:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFoundError(f"tenant {tenant_id} not found")
            tenant = validate_stored(Tenant, snap.to_dict())
            tenant.reports_granted += quantity
            tenant.entitlement_source = source
            if source is EntitlementSource.PRO:
                tenant.entitlement_expires_at = utcnow() + timedelta(days=30)
            transaction.set(ref, tenant.model_dump(mode="json"))
            return tenant

        return _txn(db.transaction())

    # -- support ----------------------------------------------------------

    def next_ticket_reference(self) -> str:
        """Allocate a human-readable ticket reference, atomically.

        A count of existing tickets would collide the moment two arrive at
        once, and a random id is unusable over the phone. A transactional
        counter gives both: monotonic, readable, and safe under concurrency.
        """
        db = self._db
        ref = db.collection(COLLECTION_COUNTERS).document("support_tickets")

        @firestore.transactional
        def _txn(transaction) -> int:
            snap = ref.get(transaction=transaction)
            n = (snap.to_dict() or {}).get("value", 0) + 1 if snap.exists else 1
            transaction.set(ref, {"value": n})
            return n

        return f"CG-SUP-{_txn(db.transaction()):06d}"

    def upsert_ticket(self, ticket: SupportTicket) -> None:
        self._db.collection(COLLECTION_TICKETS).document(ticket.ticket_id).set(
            ticket.model_dump(mode="json")
        )

    def get_ticket(self, ticket_id: str, tenant_id: str | None = None) -> SupportTicket:
        """Fetch one ticket.

        tenant_id is required on the customer path and omitted on the operator
        path. When present it is enforced here rather than by the caller, so a
        customer cannot read another workspace's ticket by guessing an id.
        """
        snap = self._db.collection(COLLECTION_TICKETS).document(ticket_id).get()
        if not snap.exists:
            raise NotFoundError(f"ticket {ticket_id} not found")
        ticket = validate_stored(SupportTicket, snap.to_dict())
        if tenant_id is not None and ticket.tenant_id != tenant_id:
            # Same error as a missing ticket: distinguishing them would confirm
            # that somebody else's ticket exists.
            raise NotFoundError(f"ticket {ticket_id} not found")
        return ticket

    def list_tickets(self, tenant_id: str, limit: int = 100) -> list[SupportTicket]:
        q = (
            self._db.collection(COLLECTION_TICKETS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        out = [validate_stored(SupportTicket, d.to_dict()) for d in q.stream()]
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    def list_all_tickets(self, limit: int = 300) -> list[SupportTicket]:
        """Every ticket, for the operator console. Cross-tenant by design."""
        q = self._db.collection(COLLECTION_TICKETS).limit(limit)
        out = [validate_stored(SupportTicket, d.to_dict()) for d in q.stream()]
        out.sort(key=lambda t: t.updated_at, reverse=True)
        return out

    def append_ticket_message(
        self, ticket_id: str, message: SupportMessage, *, status: str | None = None
    ) -> SupportTicket:
        """Append a message, transactionally.

        A read-modify-write outside a transaction loses a message when a
        customer and an operator reply at the same moment — the second write
        overwrites a thread that no longer matches what it read.
        """
        db = self._db
        ref = db.collection(COLLECTION_TICKETS).document(ticket_id)

        @firestore.transactional
        def _txn(transaction) -> SupportTicket:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise NotFoundError(f"ticket {ticket_id} not found")
            ticket = validate_stored(SupportTicket, snap.to_dict())
            ticket.messages.append(message)
            ticket.updated_at = utcnow()
            if status:
                ticket.status = status
            transaction.set(ref, ticket.model_dump(mode="json"))
            return ticket

        return _txn(db.transaction())

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
        return [validate_stored(TenantUser, s.to_dict()) for s in q.stream()]

    def get_user(self, uid: str, tenant_id: str) -> TenantUser:
        snap = self._db.collection(COLLECTION_USERS).document(uid).get()
        raw = _own_or_raise(snap, tenant_id, f"user {uid}")
        return validate_stored(TenantUser, raw)

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
        return [validate_stored(ApiKeyRecord, s.to_dict()) for s in q.stream()]

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
            record = validate_stored(ApiKeyRecord, snap.to_dict())
            return None if record.revoked else record
        return None

    def revoke_api_key(self, key_id: str, tenant_id: str) -> ApiKeyRecord:
        snap = self._db.collection(COLLECTION_API_KEYS).document(key_id).get()
        raw = _own_or_raise(snap, tenant_id, f"api key {key_id}")
        record = validate_stored(ApiKeyRecord, raw)
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
            doc = validate_stored(Document, snap.to_dict())
            if doc.created_at < cutoff:
                out.append(doc)
        return out

    def delete_document(self, document_id: str, tenant_id: str) -> None:
        self.get_document(document_id, tenant_id)  # tenant check before delete
        self._db.collection(COLLECTION_DOCUMENTS).document(document_id).delete()

    def list_all_tenants(self, limit: int = 1000) -> list[Tenant]:
        """Every tenant, skipping any document that will not validate.

        Tenant is a StrictModel, so one document with an unexpected field
        raises. This list drives the retention sweep and the weekly report's
        tenant list, and failing the whole call would mean a single bad
        record silently stops deletions and reports for every other
        workspace. Skipping the bad one is the safer failure: the rest of the
        estate keeps working, and the exception is logged with the document
        id so it can actually be fixed.
        """
        out: list[Tenant] = []
        for snap in self._db.collection(COLLECTION_TENANTS).limit(limit).stream():
            try:
                out.append(validate_stored(Tenant, snap.to_dict()))
            except ValidationError:
                logger.exception("skipping malformed tenant document %s", snap.id)
        return out

    # -- documents ----------------------------------------------------------

    def get_document(self, document_id: str, tenant_id: str) -> Document:
        snap = self._db.collection(COLLECTION_DOCUMENTS).document(document_id).get()
        raw = _own_or_raise(snap, tenant_id, f"document {document_id}")
        return validate_stored(Document, raw)

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
        raw = _own_or_raise(snap, tenant_id, f"compliance check {check_id}")
        check = validate_stored(ComplianceCheck, raw)
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
        return [validate_stored(ComplianceCheck, s.to_dict()) for s in q.stream()]

    def list_escalated_checks(self, tenant_id: str, limit: int = 200) -> list[ComplianceCheck]:
        """Checks still awaiting a human decision, for the review queue."""
        q = (
            self._db.collection(COLLECTION_CHECKS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .where(filter=firestore.FieldFilter("decision", "==", CheckDecision.ESCALATED.value))
            .limit(limit)
        )
        return [validate_stored(ComplianceCheck, s.to_dict()) for s in q.stream()]

    def list_documents(self, tenant_id: str, limit: int = 50) -> list[Document]:
        query = (
            self._db.collection(COLLECTION_DOCUMENTS)
            .where("tenant_id", "==", tenant_id)
            .limit(limit)
        )
        return [validate_stored(Document, s.to_dict()) for s in query.stream()]

    # -- reports (durable lifecycle) ----------------------------------------

    def get_report_record(self, report_id: str, tenant_id: str) -> ReportRecord:
        snap = self._db.collection(COLLECTION_REPORTS).document(report_id).get()
        raw = _own_or_raise(snap, tenant_id, f"report {report_id}")
        return validate_stored(ReportRecord, raw)

    def claim_report(self, record: ReportRecord) -> tuple[ReportRecord, bool]:
        """Create the report record, or return the one already there.

        Returns (record, created). `created` is False when a record already
        existed, which is what stops a double-clicked Generate button, a
        retried HTTP request and a redelivered task from each producing their
        own report and their own Gemini bill.

        Transactional rather than get-then-set: two gateway instances can run
        this concurrently, and Cloud Run guarantees they will. The transaction
        makes exactly one of them the creator.
        """
        db = self._db
        ref = db.collection(COLLECTION_REPORTS).document(record.report_id)

        @firestore.transactional
        def _txn(transaction) -> tuple[ReportRecord, bool]:
            snap = ref.get(transaction=transaction)
            if snap.exists:
                existing = validate_stored(ReportRecord, snap.to_dict())
                if existing.tenant_id != record.tenant_id:
                    # A deterministic id collision across tenants should be
                    # impossible, but if it ever happened, answering with
                    # someone else's report would be the worst outcome.
                    raise TenantMismatchError(f"report {record.report_id} belongs to another tenant")
                return existing, False
            transaction.set(ref, record.model_dump(mode="json"))
            return record, True

        return _txn(db.transaction())

    def update_report_record(
        self, report_id: str, tenant_id: str, updates: dict[str, Any]
    ) -> ReportRecord:
        """Patch a report's durable state. Ownership is checked first."""
        current = self.get_report_record(report_id, tenant_id)
        patched = current.model_copy(update={**updates, "updated_at": utcnow()})
        self._db.collection(COLLECTION_REPORTS).document(report_id).set(
            patched.model_dump(mode="json")
        )
        return patched

    def list_report_records(self, tenant_id: str, limit: int = 100) -> list[ReportRecord]:
        q = (
            self._db.collection(COLLECTION_REPORTS)
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .limit(limit)
        )
        out: list[ReportRecord] = []
        for snap in q.stream():
            try:
                out.append(validate_stored(ReportRecord, snap.to_dict()))
            except ValidationError:
                # One malformed record must not cost the tenant the whole list.
                logger.exception("skipping malformed report record %s", snap.id)
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    # -- tasks --------------------------------------------------------------

    def upsert_task(self, task: Task) -> None:
        self._db.collection(COLLECTION_TASKS).document(task.task_id).set(
            task.model_dump(mode="json")
        )

    def get_task(self, task_id: str, tenant_id: str) -> Task:
        snap = self._db.collection(COLLECTION_TASKS).document(task_id).get()
        raw = _own_or_raise(snap, tenant_id, f"task {task_id}")
        return validate_stored(Task, raw)

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
            current = ComplianceCheck.model_validate(
                _own_or_raise(snap, tenant_id, f"compliance check {check_id}")
            )
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
            return validate_stored(RemediationPlan, snap.to_dict())
        return None

    def list_remediation_plans(self, tenant_id: str, limit: int = 100) -> list:
        from schema_validators import RemediationPlan

        snaps = (
            self._db.collection(COLLECTION_REMEDIATION)
            .where("tenant_id", "==", tenant_id)
            .limit(limit)
            .stream()
        )
        return [validate_stored(RemediationPlan, s.to_dict()) for s in snaps]
