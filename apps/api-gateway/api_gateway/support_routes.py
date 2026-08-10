"""Support tickets — customer side and operator side.

Two audiences, one thread, and the boundary between them is the whole point of
this file:

  * /api/support/*          the customer's own tickets, tenant-scoped exactly
                            like every other customer endpoint.
  * /api/platform/support/* every ticket, for whoever operates the service.

Three rules hold everywhere here:

  1. INTERNAL NOTES NEVER REACH A CUSTOMER. Filtering happens in
     SupportTicket.customer_view() and every customer response is built from
     it, so a new endpoint cannot forget. A triage note leaking to the
     customer it is about would be worse than having no notes at all.
  2. TENANT SCOPE IS ENFORCED IN THE REPO, not by the caller. get_ticket
     raises the same not-found error for another workspace's ticket as for a
     missing one, so an id cannot be probed.
  3. REPLYING IS A SEPARATE PERMISSION. Being able to read the support inbox
     is not the same as being able to speak to customers in the company's
     name, and CG_SUPPORT_AGENTS is what separates them.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Callable

from auth_middleware import AuthContext, require_auth, require_platform_admin
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from schema_validators import (
    MessageSender,
    SupportMessage,
    SupportTicket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

logger = logging.getLogger("cg.gateway.support")

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$"


def _support_agents() -> set[str]:
    """Operators permitted to reply to customers.

    An environment allowlist for the same reason platform admin is one: roles
    are handed out inside tenants, so anything derived from a role could be
    minted by a customer inviting themselves. Empty means nobody can reply —
    closed by default, which is the right failure mode for a permission that
    lets someone speak as the company.
    """
    raw = os.environ.get("CG_SUPPORT_AGENTS", "")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _can_reply(auth: AuthContext) -> bool:
    agents = _support_agents()
    if not agents:
        return False
    return (auth.email or "").lower() in agents or auth.uid.lower() in agents


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- schemas


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class CreateTicketRequest(_Strict):
    first_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320, pattern=_EMAIL_PATTERN)
    # Optional, and stays optional. Demanding a phone number for a written
    # question is friction with no purpose.
    phone: str = Field(default="", max_length=40)
    message: str = Field(min_length=10, max_length=8000)
    category: str = Field(default="other")
    subject: str = Field(default="", max_length=200)


class ReplyRequest(_Strict):
    body: str = Field(min_length=1, max_length=8000)


class OperatorReplyRequest(_Strict):
    body: str = Field(min_length=1, max_length=8000)
    # An internal note stays on the thread but never leaves the console.
    internal: bool = False


class UpdateTicketRequest(_Strict):
    status: str | None = Field(default=None, pattern="^(new|open|in_progress|waiting_for_user|resolved|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    assigned_to: str = Field(default="", max_length=320)


class MessageOut(BaseModel):
    message_id: str
    sender: str
    author_email: str
    body: str
    internal: bool
    created_at: str


class TicketOut(BaseModel):
    reference: str
    ticket_id: str
    tenant_id: str
    first_name: str
    email: str
    phone: str
    category: str
    subject: str
    status: str
    priority: str
    assigned_to: str
    created_at: str
    updated_at: str
    messages: list[MessageOut]


def _to_out(t: SupportTicket) -> TicketOut:
    return TicketOut(
        reference=t.reference,
        ticket_id=t.ticket_id,
        tenant_id=t.tenant_id,
        first_name=t.first_name,
        email=t.email,
        phone=t.phone,
        category=t.category.value,
        subject=t.subject,
        status=t.status.value,
        priority=t.priority.value,
        assigned_to=t.assigned_to,
        created_at=t.created_at.isoformat(),
        updated_at=t.updated_at.isoformat(),
        messages=[
            MessageOut(
                message_id=m.message_id,
                sender=m.sender.value,
                author_email=m.author_email,
                body=m.body,
                internal=m.internal,
                created_at=m.created_at.isoformat(),
            )
            for m in t.messages
        ],
    )


# --------------------------------------------------------------- router


def build_support_router(
    gw,
    *,
    enforce_standard: Callable[[str, str], None],
) -> APIRouter:
    router = APIRouter(tags=["support"])

    def _notifier():
        from support_notify import EmailNotifier

        return EmailNotifier()

    def _audit(g, *, tenant_id: str, actor: str, action: str, ticket: SupportTicket, extra=None):
        """Every ticket event lands in the append-only trail.

        Written before any notification is attempted, so a mail failure can
        never mean the event is lost. Message bodies are NOT recorded — the
        trail says what happened and who did it, not what a customer wrote
        about their own compliance problems.
        """
        try:
            g.auditor.log(
                tenant_id=tenant_id,
                actor=actor,
                action=action,
                dedup_key=f"{ticket.reference}:{action}:{_utcnow().isoformat()}",
                before_state=None,
                after_state={"reference": ticket.reference, "status": ticket.status.value, **(extra or {})},
            )
        except Exception:
            logger.exception("failed to audit %s for %s", action, ticket.reference)

    # ---------------------------------------------------------- customer

    @router.post("/support/tickets", response_model=TicketOut, status_code=201)
    def create_ticket(
        req: CreateTicketRequest, auth: AuthContext = Depends(require_auth)
    ) -> TicketOut:
        """File a support request.

        tenant_id and the author's uid come from the verified session, never
        from the body — a ticket cannot be filed against another workspace.
        """
        enforce_standard(auth.tenant_id, "support tickets")
        g = gw()

        try:
            category = TicketCategory(req.category)
        except ValueError:
            category = TicketCategory.OTHER

        # Security and privacy requests start higher: a slow reply on either
        # is a materially worse outcome than a slow reply about billing.
        priority = (
            TicketPriority.HIGH
            if category in (TicketCategory.SECURITY, TicketCategory.PRIVACY)
            else TicketPriority.NORMAL
        )

        ticket = SupportTicket(
            ticket_id=str(uuid.uuid4()),
            reference=g.repo.next_ticket_reference(),
            tenant_id=auth.tenant_id,
            created_by_uid=auth.uid,
            first_name=req.first_name.strip(),
            email=req.email.strip(),
            phone=req.phone.strip(),
            category=category,
            subject=req.subject.strip(),
            priority=priority,
            messages=[
                SupportMessage(
                    message_id=str(uuid.uuid4()),
                    sender=MessageSender.CUSTOMER,
                    body=req.message,
                )
            ],
        )
        g.repo.upsert_ticket(ticket)
        _audit(
            g,
            tenant_id=auth.tenant_id,
            actor=auth.email or auth.uid,
            action="support.ticket_created",
            ticket=ticket,
            extra={"category": category.value},
        )

        # Best-effort. The ticket exists whether or not this sends.
        from support_notify import notify_new_ticket

        notify_new_ticket(_notifier(), reference=ticket.reference, to=ticket.email)

        return _to_out(ticket.customer_view())

    @router.get("/support/tickets", response_model=list[TicketOut])
    def list_my_tickets(auth: AuthContext = Depends(require_auth)) -> list[TicketOut]:
        return [_to_out(t.customer_view()) for t in gw().repo.list_tickets(auth.tenant_id)]

    @router.get("/support/tickets/{ticket_id}", response_model=TicketOut)
    def get_my_ticket(
        ticket_id: str = Path(min_length=1, max_length=128),
        auth: AuthContext = Depends(require_auth),
    ) -> TicketOut:
        from gcp_clients.firestore_repo import NotFoundError

        try:
            ticket = gw().repo.get_ticket(ticket_id, auth.tenant_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="not found") from None
        return _to_out(ticket.customer_view())

    @router.post("/support/tickets/{ticket_id}/messages", response_model=TicketOut)
    def reply_as_customer(
        req: ReplyRequest,
        ticket_id: str = Path(min_length=1, max_length=128),
        auth: AuthContext = Depends(require_auth),
    ) -> TicketOut:
        from gcp_clients.firestore_repo import NotFoundError

        enforce_standard(auth.tenant_id, "support messages")
        g = gw()
        try:
            g.repo.get_ticket(ticket_id, auth.tenant_id)  # scope check before write
            ticket = g.repo.append_ticket_message(
                ticket_id,
                SupportMessage(
                    message_id=str(uuid.uuid4()),
                    sender=MessageSender.CUSTOMER,
                    body=req.body,
                ),
                status=TicketStatus.OPEN.value,
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="not found") from None

        _audit(
            g,
            tenant_id=auth.tenant_id,
            actor=auth.email or auth.uid,
            action="support.customer_replied",
            ticket=ticket,
        )
        return _to_out(ticket.customer_view())

    # ---------------------------------------------------------- operator

    @router.get("/platform/support", response_model=list[TicketOut])
    def list_all_tickets(
        limit: int = Query(default=200, ge=1, le=500),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> list[TicketOut]:
        """Every ticket across every workspace.

        Full view including internal notes — this is the operator surface. The
        access itself is audited, like every other platform read.
        """
        g = gw()
        try:
            g.auditor.log(
                tenant_id="__platform__",
                actor=auth.email or auth.uid,
                action="platform.support_viewed",
                dedup_key=f"support:{_utcnow().isoformat()}",
                before_state=None,
                after_state={"limit": limit},
            )
        except Exception:
            logger.exception("failed to audit support inbox access")
        return [_to_out(t) for t in g.repo.list_all_tickets(limit=limit)]

    @router.get("/platform/support/permissions")
    def my_support_permissions(auth: AuthContext = Depends(require_platform_admin)) -> dict:
        """What this operator may do, so the console can hide what they cannot."""
        return {
            "can_reply": _can_reply(auth),
            "agents_configured": bool(_support_agents()),
            "me": auth.email or auth.uid,
        }

    @router.post("/platform/support/{ticket_id}/reply", response_model=TicketOut)
    def reply_as_support(
        req: OperatorReplyRequest,
        ticket_id: str = Path(min_length=1, max_length=128),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> TicketOut:
        """Reply to a customer, or add an internal note.

        Gated on CG_SUPPORT_AGENTS rather than platform admin: reading the
        inbox and speaking to customers as the company are different powers,
        and conflating them means every operator can send mail on the
        company's behalf by accident.
        """
        from gcp_clients.firestore_repo import NotFoundError

        if not _can_reply(auth):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the support reply permission.",
            )

        g = gw()
        try:
            ticket = g.repo.append_ticket_message(
                ticket_id,
                SupportMessage(
                    message_id=str(uuid.uuid4()),
                    sender=MessageSender.SUPPORT,
                    author_email=auth.email or auth.uid,
                    body=req.body,
                    internal=req.internal,
                ),
                # An internal note is not a reply, so it must not move the
                # ticket into a state that tells the customer to look.
                status=None if req.internal else TicketStatus.WAITING_FOR_USER.value,
            )
        except NotFoundError:
            raise HTTPException(status_code=404, detail="not found") from None

        _audit(
            g,
            tenant_id=ticket.tenant_id,
            actor=f"operator:{auth.email or auth.uid}",
            action="support.internal_note_added" if req.internal else "support.support_replied",
            ticket=ticket,
        )

        if not req.internal:
            from support_notify import notify_reply

            notify_reply(_notifier(), reference=ticket.reference, to=ticket.email)

        return _to_out(ticket)

    @router.put("/platform/support/{ticket_id}", response_model=TicketOut)
    def update_ticket(
        req: UpdateTicketRequest,
        ticket_id: str = Path(min_length=1, max_length=128),
        auth: AuthContext = Depends(require_platform_admin),
    ) -> TicketOut:
        """Assign, prioritise or move a ticket's status.

        Assignment is an operator decision. A customer never chooses who
        handles their ticket, which is why there is no customer route for it.
        """
        from gcp_clients.firestore_repo import NotFoundError

        g = gw()
        try:
            ticket = g.repo.get_ticket(ticket_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="not found") from None

        before = {
            "status": ticket.status.value,
            "priority": ticket.priority.value,
            "assigned_to": ticket.assigned_to,
        }
        if req.status:
            ticket.status = TicketStatus(req.status)
        if req.priority:
            ticket.priority = TicketPriority(req.priority)
        if req.assigned_to != "":
            ticket.assigned_to = req.assigned_to
        ticket.updated_at = _utcnow()
        g.repo.upsert_ticket(ticket)

        _audit(
            g,
            tenant_id=ticket.tenant_id,
            actor=f"operator:{auth.email or auth.uid}",
            action="support.ticket_updated",
            ticket=ticket,
            extra={"before": before, "assigned_to": ticket.assigned_to},
        )
        return _to_out(ticket)

    return router
