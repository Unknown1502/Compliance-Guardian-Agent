"""Unit tests: billing checkout + webhook routes.

Hermetic — the real `stripe` SDK calls (Session.create, Webhook.construct_event)
are monkeypatched, never hitting the network. No real Stripe account or keys
are needed to run this suite.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from billing import BillingClient, CheckoutSession, WebhookEvent, WebhookSignatureError
from schema_validators import PlanTier, Tenant


def _dev_token(uid: str, tenant_id: str, role: str) -> str:
    claims = {"uid": uid, "tenant_id": tenant_id, "role": role}
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


class FakeRepo:
    def __init__(self, tenant: Tenant):
        self.tenants = {tenant.tenant_id: tenant}

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant


class FakeAuditor:
    def __init__(self):
        self.events = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeBilling:
    """Stands in for BillingClient — no real Stripe API key required."""

    def __init__(self, *, checkout: CheckoutSession | None = None, webhook_event=None, webhook_error=None):
        self._checkout = checkout
        self._webhook_event = webhook_event
        self._webhook_error = webhook_error
        self.checkout_calls: list[dict] = []

    def create_checkout_session(self, *, tenant_id, plan, customer_email=None):
        self.checkout_calls.append(
            {"tenant_id": tenant_id, "plan": plan, "customer_email": customer_email}
        )
        return self._checkout

    def parse_webhook(self, *, payload, signature_header):
        if self._webhook_error:
            raise self._webhook_error
        return self._webhook_event


class FakeGateway:
    def __init__(self, tenant: Tenant, billing: FakeBilling):
        self.repo = FakeRepo(tenant)
        self.auditor = FakeAuditor()
        self._billing = billing

    def billing(self):
        return self._billing


def _client(monkeypatch, gateway: FakeGateway):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    monkeypatch.setattr(main, "_gateway", gateway)
    monkeypatch.setattr(main, "gw", lambda: gateway)
    return TestClient(main.app)


@pytest.fixture()
def tenant():
    return Tenant(
        tenant_id="tenant-a",
        name="Fernbank Verify",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier=PlanTier.FREE,
    )


class TestCheckout:
    def test_requires_auth(self, monkeypatch, tenant):
        gateway = FakeGateway(tenant, FakeBilling())
        c = _client(monkeypatch, gateway)
        r = c.post("/api/billing/checkout", json={"plan": "oneoff"})
        assert r.status_code == 401

    def test_oneoff_checkout_returns_url(self, monkeypatch, tenant):
        checkout = CheckoutSession(session_id="cs_test_1", checkout_url="https://checkout.stripe.com/cs_test_1")
        billing = FakeBilling(checkout=checkout)
        gateway = FakeGateway(tenant, billing)
        c = _client(monkeypatch, gateway)
        r = c.post(
            "/api/billing/checkout",
            json={"plan": "oneoff"},
            headers={"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"},
        )
        assert r.status_code == 200
        assert r.json()["checkout_url"] == "https://checkout.stripe.com/cs_test_1"
        # tenant_id must come from the verified session, never the request body.
        assert billing.checkout_calls == [
            {"tenant_id": "tenant-a", "plan": "oneoff", "customer_email": None}
        ]

    def test_rejects_unknown_plan(self, monkeypatch, tenant):
        gateway = FakeGateway(tenant, FakeBilling())
        c = _client(monkeypatch, gateway)
        r = c.post(
            "/api/billing/checkout",
            json={"plan": "lifetime"},
            headers={"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"},
        )
        assert r.status_code == 422  # fails the pydantic pattern constraint

    def test_unconfigured_stripe_is_503_not_crash(self, monkeypatch, tenant):
        from billing import BillingConfigError

        class BrokenBilling(FakeBilling):
            def create_checkout_session(self, **kwargs):
                raise BillingConfigError("STRIPE_SECRET_KEY is not set.")

        gateway = FakeGateway(tenant, BrokenBilling())
        c = _client(monkeypatch, gateway)
        r = c.post(
            "/api/billing/checkout",
            json={"plan": "oneoff"},
            headers={"Authorization": f"Bearer {_dev_token('u1', 'tenant-a', 'owner')}"},
        )
        assert r.status_code == 503


class TestWebhook:
    def test_invalid_signature_is_400_and_does_not_touch_tenant(self, monkeypatch, tenant):
        billing = FakeBilling(webhook_error=WebhookSignatureError("bad sig"))
        gateway = FakeGateway(tenant, billing)
        c = _client(monkeypatch, gateway)
        r = c.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"})
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_oneoff_purchase_upgrades_to_starter_and_logs(self, monkeypatch, tenant):
        event = WebhookEvent(
            event_type="checkout.session.completed",
            tenant_id="tenant-a",
            mode="payment",
            amount_total=29900,
            currency="aud",
            stripe_customer_id="cus_test_1",
            stripe_event_id="evt_test_1",
        )
        gateway = FakeGateway(tenant, FakeBilling(webhook_event=event))
        c = _client(monkeypatch, gateway)
        r = c.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})
        assert r.status_code == 200
        assert r.json()["handled"] is True
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.STARTER
        assert any(
            e["action"] == "billing.purchased" and e["after_state"]["amount_total"] == 29900
            for e in gateway.auditor.events
        )

    def test_subscription_upgrades_to_pro(self, monkeypatch, tenant):
        event = WebhookEvent(
            event_type="checkout.session.completed",
            tenant_id="tenant-a",
            mode="subscription",
            amount_total=9900,
            currency="aud",
            stripe_customer_id="cus_test_2",
            stripe_event_id="evt_test_2",
        )
        gateway = FakeGateway(tenant, FakeBilling(webhook_event=event))
        c = _client(monkeypatch, gateway)
        r = c.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})
        assert r.status_code == 200
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.PRO
        assert any(e["action"] == "billing.subscribed" for e in gateway.auditor.events)

    def test_unrelated_event_type_is_ignored_not_errored(self, monkeypatch, tenant):
        event = WebhookEvent(
            event_type="customer.updated",
            tenant_id="tenant-a",
            mode=None,
            amount_total=None,
            currency=None,
            stripe_customer_id="cus_test_3",
            stripe_event_id="evt_test_3",
        )
        gateway = FakeGateway(tenant, FakeBilling(webhook_event=event))
        c = _client(monkeypatch, gateway)
        r = c.post("/api/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})
        assert r.status_code == 200
        assert r.json()["handled"] is False
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE  # untouched
        assert gateway.auditor.events == []


class TestBillingClientConfig:
    """BillingClient itself — the pieces that don't need the FastAPI app."""

    def test_missing_secret_key_fails_loudly(self, monkeypatch):
        from billing import BillingConfigError

        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        with pytest.raises(BillingConfigError):
            BillingClient()

    def test_unknown_plan_rejected(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
        client = BillingClient()
        with pytest.raises(ValueError):
            client.create_checkout_session(tenant_id="tenant-a", plan="lifetime")

    def test_missing_price_id_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
        monkeypatch.delenv("STRIPE_PRICE_ID_ONEOFF", raising=False)
        from billing import BillingConfigError

        client = BillingClient()
        with pytest.raises(BillingConfigError):
            client.create_checkout_session(tenant_id="tenant-a", plan="oneoff")
