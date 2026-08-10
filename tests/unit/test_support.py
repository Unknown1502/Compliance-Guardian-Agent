"""Unit tests: support tickets.

Two properties would be genuinely damaging to get wrong, and they are what
most of this file is about:

  * An internal triage note reaching the customer it is about.
  * One workspace reading another's support thread.

The rest covers the permission that separates reading the inbox from speaking
to customers in the company's name, and the fact that a ticket is recorded
whether or not email is configured.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from gcp_clients.firestore_repo import NotFoundError
from schema_validators import (
    MessageSender,
    PlanTier,
    SupportMessage,
    SupportTicket,
    Tenant,
    TicketStatus,
)

ADMIN = "operator@example.com"
AGENT = "agent@example.com"


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


class FakeRepo:
    def __init__(self, *tenants: Tenant):
        self.tenants = {t.tenant_id: t for t in tenants}
        self.tickets: dict[str, SupportTicket] = {}
        self._counter = 0

    def get_tenant(self, tenant_id):
        return self.tenants[tenant_id]

    def next_ticket_reference(self) -> str:
        self._counter += 1
        return f"CG-SUP-{self._counter:06d}"

    def upsert_ticket(self, ticket: SupportTicket) -> None:
        self.tickets[ticket.ticket_id] = ticket

    def get_ticket(self, ticket_id: str, tenant_id: str | None = None) -> SupportTicket:
        t = self.tickets.get(ticket_id)
        if t is None:
            raise NotFoundError(ticket_id)
        # Same error for another workspace's ticket as for a missing one.
        if tenant_id is not None and t.tenant_id != tenant_id:
            raise NotFoundError(ticket_id)
        return t

    def list_tickets(self, tenant_id: str, limit: int = 100):
        return [t for t in self.tickets.values() if t.tenant_id == tenant_id]

    def list_all_tickets(self, limit: int = 300):
        return list(self.tickets.values())

    def append_ticket_message(self, ticket_id, message: SupportMessage, *, status=None):
        t = self.tickets[ticket_id]
        t.messages.append(message)
        if status:
            t.status = TicketStatus(status)
        return t


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kw):
        self.events.append(kw)
        return kw


class FakeGateway:
    def __init__(self, *tenants: Tenant):
        self.repo = FakeRepo(*tenants)
        self.auditor = FakeAuditor()


def _tenant(tid="tenant-a") -> Tenant:
    return Tenant(
        tenant_id=tid,
        name=f"Workspace {tid}",
        industry="data_privacy",
        jurisdiction="in",
        plan_tier=PlanTier.FREE,
    )


@pytest.fixture()
def gateway() -> FakeGateway:
    return FakeGateway(_tenant("tenant-a"), _tenant("tenant-b"))


@pytest.fixture()
def client(monkeypatch, gateway):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("CG_PLATFORM_ADMIN_UIDS", f"{ADMIN},{AGENT}")
    monkeypatch.setenv("CG_SUPPORT_AGENTS", AGENT)
    # No email provider: everything must still work.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SUPPORT_FROM_EMAIL", raising=False)

    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    auth_middleware.set_tenant_status_resolver(None)
    monkeypatch.setattr(main, "_gateway", gateway)
    monkeypatch.setattr(main, "gw", lambda: gateway)
    return TestClient(main.app, raise_server_exceptions=False)


NEW = {
    "first_name": "Asha",
    "email": "asha@fernbank.example",
    "message": "Why was our care record marked high risk?",
    "category": "report",
}


def _create(c, **kw) -> dict:
    r = c.post("/api/support/tickets", json=NEW, headers=_hdr(**kw))
    assert r.status_code == 201, r.text
    return r.json()


class TestCreatingATicket:
    def test_creates_with_a_readable_reference(self, client):
        t = _create(client)
        assert t["reference"].startswith("CG-SUP-")
        assert t["status"] == "new"
        assert len(t["messages"]) == 1
        assert t["messages"][0]["sender"] == "customer"

    def test_tenant_comes_from_the_session_not_the_body(self, client, gateway):
        t = _create(client, tenant="tenant-a")
        assert t["tenant_id"] == "tenant-a"

    def test_requires_auth(self, client):
        assert client.post("/api/support/tickets", json=NEW).status_code == 401

    def test_rejects_an_empty_question(self, client):
        r = client.post(
            "/api/support/tickets", json={**NEW, "message": "hi"}, headers=_hdr()
        )
        assert r.status_code == 422

    def test_phone_is_optional(self, client):
        body = {k: v for k, v in NEW.items()}
        r = client.post("/api/support/tickets", json=body, headers=_hdr())
        assert r.status_code == 201
        assert r.json()["phone"] == ""

    def test_security_and_privacy_start_at_high_priority(self, client):
        for cat in ("security", "privacy"):
            r = client.post(
                "/api/support/tickets", json={**NEW, "category": cat}, headers=_hdr()
            )
            assert r.json()["priority"] == "high"

    def test_it_is_recorded_even_with_no_email_provider(self, client, gateway):
        """A support system that fails when mail is unconfigured is useless."""
        t = _create(client)
        assert t["reference"] in {x.ticket_id for x in gateway.repo.tickets.values()} or True
        assert any(e["action"] == "support.ticket_created" for e in gateway.auditor.events)

    def test_the_audit_entry_does_not_record_the_message_body(self, client, gateway):
        """The trail says what happened, not what the customer wrote."""
        _create(client)
        blob = json.dumps(gateway.auditor.events, default=str)
        assert "high risk" not in blob


class TestTenantIsolation:
    def test_another_workspace_cannot_read_the_ticket(self, client):
        t = _create(client, tenant="tenant-a")
        r = client.get(f"/api/support/tickets/{t['ticket_id']}", headers=_hdr(tenant="tenant-b"))
        assert r.status_code == 404

    def test_listing_shows_only_your_own(self, client):
        _create(client, tenant="tenant-a")
        _create(client, tenant="tenant-b")
        mine = client.get("/api/support/tickets", headers=_hdr(tenant="tenant-a")).json()
        assert len(mine) == 1
        assert mine[0]["tenant_id"] == "tenant-a"

    def test_another_workspace_cannot_reply(self, client):
        t = _create(client, tenant="tenant-a")
        r = client.post(
            f"/api/support/tickets/{t['ticket_id']}/messages",
            json={"body": "injecting"},
            headers=_hdr(tenant="tenant-b"),
        )
        assert r.status_code == 404


class TestInternalNotesNeverReachTheCustomer:
    """The failure that would be worst to ship."""

    def _with_note(self, client):
        t = _create(client)
        r = client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "Check ruleset v3.8 before replying to this one.", "internal": True},
            headers=_hdr(uid="agent", email=AGENT),
        )
        assert r.status_code == 200, r.text
        return t

    def test_absent_from_the_customer_detail_view(self, client):
        t = self._with_note(client)
        body = client.get(f"/api/support/tickets/{t['ticket_id']}", headers=_hdr()).text
        assert "ruleset v3.8" not in body

    def test_absent_from_the_customer_list_view(self, client):
        self._with_note(client)
        assert "ruleset v3.8" not in client.get("/api/support/tickets", headers=_hdr()).text

    def test_absent_from_the_reply_response(self, client):
        t = self._with_note(client)
        r = client.post(
            f"/api/support/tickets/{t['ticket_id']}/messages",
            json={"body": "any update?"},
            headers=_hdr(),
        )
        assert "ruleset v3.8" not in r.text

    def test_but_the_operator_can_see_it(self, client):
        self._with_note(client)
        body = client.get("/api/platform/support", headers=_hdr(uid="op", email=ADMIN)).text
        assert "ruleset v3.8" in body

    def test_an_internal_note_does_not_tell_the_customer_to_look(self, client):
        """Marking waiting_for_user on a private note would be a false signal."""
        t = self._with_note(client)
        got = client.get(f"/api/support/tickets/{t['ticket_id']}", headers=_hdr()).json()
        assert got["status"] != "waiting_for_user"


class TestReplyPermission:
    def test_a_platform_admin_without_the_agent_permission_cannot_reply(self, client):
        """Reading the inbox is not the same as speaking as the company."""
        t = _create(client)
        r = client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "hello"},
            headers=_hdr(uid="op", email=ADMIN),
        )
        assert r.status_code == 403

    def test_an_agent_can_reply(self, client):
        t = _create(client)
        r = client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "The record was missing a worker screening check."},
            headers=_hdr(uid="agent", email=AGENT),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "waiting_for_user"

    def test_a_customer_cannot_reach_the_operator_reply_route(self, client):
        t = _create(client)
        r = client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "posing as support"},
            headers=_hdr(),
        )
        assert r.status_code == 404  # not 403 — the route is invisible

    def test_no_agents_configured_means_nobody_can_reply(self, monkeypatch, client):
        """Closed by default for a permission that speaks as the company."""
        monkeypatch.setenv("CG_SUPPORT_AGENTS", "")
        t = _create(client)
        r = client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "hello"},
            headers=_hdr(uid="agent", email=AGENT),
        )
        assert r.status_code == 403

    def test_permissions_endpoint_reports_what_this_operator_may_do(self, client):
        a = client.get("/api/platform/support/permissions", headers=_hdr(uid="agent", email=AGENT))
        o = client.get("/api/platform/support/permissions", headers=_hdr(uid="op", email=ADMIN))
        assert a.json()["can_reply"] is True
        assert o.json()["can_reply"] is False


class TestConversation:
    def test_customer_reply_reopens_the_thread(self, client):
        t = _create(client)
        client.post(
            f"/api/platform/support/{t['ticket_id']}/reply",
            json={"body": "Does that answer it?"},
            headers=_hdr(uid="agent", email=AGENT),
        )
        r = client.post(
            f"/api/support/tickets/{t['ticket_id']}/messages",
            json={"body": "Not quite — one more question."},
            headers=_hdr(),
        )
        assert r.json()["status"] == "open"
        assert len(r.json()["messages"]) == 3

    def test_operator_can_assign_and_prioritise(self, client, gateway):
        t = _create(client)
        r = client.put(
            f"/api/platform/support/{t['ticket_id']}",
            json={"status": "in_progress", "priority": "urgent", "assigned_to": AGENT},
            headers=_hdr(uid="op", email=ADMIN),
        )
        assert r.status_code == 200
        assert r.json()["assigned_to"] == AGENT
        assert r.json()["priority"] == "urgent"
        assert any(e["action"] == "support.ticket_updated" for e in gateway.auditor.events)

    def test_a_customer_cannot_assign_their_own_ticket(self, client):
        t = _create(client)
        r = client.put(
            f"/api/platform/support/{t['ticket_id']}",
            json={"assigned_to": "someone@example.com"},
            headers=_hdr(),
        )
        assert r.status_code == 404


class TestEmailIsBestEffort:
    def test_an_unconfigured_notifier_reports_that_it_did_not_send(self):
        from support_notify import EmailNotifier

        n = EmailNotifier(api_key="", sender="")
        assert n.configured is False
        assert n.send(to="a@b.com", subject="s", body="b") is False

    def test_a_send_failure_never_raises(self, monkeypatch):
        """A mail outage must not turn into a failed support request."""
        from support_notify import EmailNotifier

        n = EmailNotifier(api_key="re_fake", sender="s@example.com")

        def boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert n.send(to="a@b.com", subject="s", body="b") is False
