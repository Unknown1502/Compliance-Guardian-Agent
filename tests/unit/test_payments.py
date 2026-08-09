"""Unit tests: Razorpay and PayPal payment routes.

Hermetic. Every provider HTTP call is monkeypatched at payments._get_json /
payments._post_json, so no network, no real keys, no real money.

What these assert is deliberately narrow and adversarial: the ways someone
could get a paid plan without paying. Signatures are computed for real (not
stubbed) so the HMAC path is genuinely exercised — a test that stubs the
verifier proves only that the stub works.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from schema_validators import PlanTier, Tenant

KEY_ID = "rzp_test_fake"
KEY_SECRET = "razorpay-secret-not-real"
WEBHOOK_SECRET = "razorpay-webhook-secret-not-real"

# Matches payments._DEFAULT_PRICES so the underpayment guard has a baseline.
ONEOFF_INR = 199900
SUB_INR = 830000


def _tok(uid="u1", tenant="tenant-a", role="owner", email=None) -> str:
    claims = {"uid": uid, "tenant_id": tenant, "role": role}
    if email:
        claims["email"] = email
    raw = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"dev:{raw}"


def _hdr(**kw) -> dict:
    return {"Authorization": f"Bearer {_tok(**kw)}"}


def _checkout_sig(order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
    return hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def _webhook_sig(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class FakeRepo:
    def __init__(self, *tenants: Tenant):
        self.tenants = {t.tenant_id: t for t in tenants}

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenants[tenant_id]

    def upsert_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.tenant_id] = tenant


class FakeAuditor:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


class FakeGateway:
    def __init__(self, *tenants: Tenant):
        self.repo = FakeRepo(*tenants)
        self.auditor = FakeAuditor()


@pytest.fixture()
def tenant_a() -> Tenant:
    return Tenant(
        tenant_id="tenant-a",
        name="Fernbank Verify",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier=PlanTier.FREE,
    )


@pytest.fixture()
def tenant_b() -> Tenant:
    return Tenant(
        tenant_id="tenant-b",
        name="Other Provider",
        industry="healthcare_ndis",
        jurisdiction="AU",
        plan_tier=PlanTier.FREE,
    )


@pytest.fixture()
def gateway(tenant_a, tenant_b) -> FakeGateway:
    return FakeGateway(tenant_a, tenant_b)


@pytest.fixture()
def client(monkeypatch, gateway):
    monkeypatch.setenv("CG_AUTH_DEV_MODE", "1")
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)

    import api_gateway.main as main
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "_ensure_firebase_app", lambda: None)
    # The router closes over main.gw from import time, and that function reads
    # the module global — so replacing _gateway is what actually swaps it out.
    monkeypatch.setattr(main, "_gateway", gateway)
    monkeypatch.setattr(main, "gw", lambda: gateway)
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture()
def no_network(monkeypatch):
    """Fail loudly if a test forgets to stub a provider call."""
    import payments

    def boom(*args, **kwargs):  # pragma: no cover - only fires on a test bug
        raise AssertionError("unstubbed provider HTTP call")

    monkeypatch.setattr(payments, "_get_json", boom)
    monkeypatch.setattr(payments, "_post_json", boom)
    return monkeypatch


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class TestPricing:
    def test_price_comes_from_the_server_not_the_request(self, client, gateway, monkeypatch):
        """An amount in the body is a 422, not a discount."""
        r = client.post(
            "/api/billing/razorpay/order",
            json={"plan": "subscription", "amount_minor": 100},
            headers=_hdr(),
        )
        assert r.status_code == 422

    def test_env_override_applies(self, monkeypatch):
        from payments import price_for

        monkeypatch.setenv("CG_PRICE_RAZORPAY_ONEOFF", "500000")
        monkeypatch.setenv("CG_CURRENCY_RAZORPAY", "inr")
        price = price_for("razorpay", "oneoff")
        assert price.amount_minor == 500000
        assert price.currency == "INR"

    def test_unparseable_price_fails_loudly_rather_than_becoming_free(self, monkeypatch):
        from payments import PaymentConfigError, price_for

        monkeypatch.setenv("CG_PRICE_RAZORPAY_ONEOFF", "four thousand")
        with pytest.raises(PaymentConfigError):
            price_for("razorpay", "oneoff")

    def test_paypal_major_units_formatting(self):
        from payments import price_for

        assert price_for("paypal", "oneoff").major == "25.00"


# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------


class TestRazorpayOrder:
    def test_requires_auth(self, client):
        r = client.post("/api/billing/razorpay/order", json={"plan": "oneoff"})
        assert r.status_code == 401

    def test_order_uses_server_price_and_session_tenant(self, client, no_network):
        import payments

        seen: dict = {}

        def fake_post(url, *, data, headers):
            seen["url"] = url
            seen["data"] = data
            return {"id": "order_ABC", "amount": data["amount"], "currency": data["currency"]}

        no_network.setattr(payments, "_post_json", fake_post)

        r = client.post(
            "/api/billing/razorpay/order", json={"plan": "subscription"}, headers=_hdr()
        )
        assert r.status_code == 200
        body = r.json()
        assert body["order_id"] == "order_ABC"
        assert body["amount"] == SUB_INR
        assert body["key_id"] == KEY_ID
        # tenant_id rides in notes and comes from the verified session.
        assert seen["data"]["notes"] == {"tenant_id": "tenant-a", "plan": "subscription"}

    def test_secret_is_never_returned(self, client, no_network):
        import payments

        no_network.setattr(
            payments,
            "_post_json",
            lambda url, *, data, headers: {
                "id": "order_ABC",
                "amount": data["amount"],
                "currency": data["currency"],
            },
        )
        r = client.post("/api/billing/razorpay/order", json={"plan": "oneoff"}, headers=_hdr())
        assert KEY_SECRET not in r.text

    def test_unconfigured_is_503_not_a_crash(self, client, monkeypatch):
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
        r = client.post("/api/billing/razorpay/order", json={"plan": "oneoff"}, headers=_hdr())
        assert r.status_code == 503


class TestRazorpayVerify:
    def _captured(self, *, amount=ONEOFF_INR, plan="oneoff", tenant="tenant-a", order="order_1"):
        return {
            "id": "pay_1",
            "status": "captured",
            "order_id": order,
            "amount": amount,
            "currency": "INR",
            "notes": {"tenant_id": tenant, "plan": plan},
        }

    def test_forged_signature_is_rejected_and_plan_untouched(self, client, gateway, no_network):
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": "deadbeef" * 8,
            },
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE
        assert gateway.auditor.events == []

    def test_signature_from_the_wrong_secret_is_rejected(self, client, gateway, no_network):
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1", secret="guessed"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_valid_payment_upgrades_and_audits(self, client, gateway, no_network):
        import payments

        no_network.setattr(payments, "_get_json", lambda url, *, headers: self._captured())

        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["plan_tier"] == "starter"
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.STARTER
        event = gateway.auditor.events[-1]
        assert event["action"] == "billing.purchased"
        assert event["dedup_key"] == "razorpay:pay_1"
        assert event["after_state"]["provider"] == "razorpay"

    def test_subscription_upgrades_to_pro(self, client, gateway, no_network):
        import payments

        no_network.setattr(
            payments,
            "_get_json",
            lambda url, *, headers: self._captured(amount=SUB_INR, plan="subscription"),
        )
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 200
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.PRO

    def test_uncaptured_payment_does_not_upgrade(self, client, gateway, no_network):
        """A valid signature on a failed payment is still not a payment."""
        import payments

        failed = self._captured() | {"status": "failed"}
        no_network.setattr(payments, "_get_json", lambda url, *, headers: failed)

        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_payment_for_another_order_is_rejected(self, client, gateway, no_network):
        """Signature is over order|payment, so a mismatch means a spliced pair."""
        import payments

        no_network.setattr(
            payments, "_get_json", lambda url, *, headers: self._captured(order="order_OTHER")
        )
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_cannot_claim_another_tenants_payment(self, client, gateway, no_network):
        """tenant-b pays; tenant-a replays the callback. Nobody gets upgraded."""
        import payments

        no_network.setattr(
            payments, "_get_json", lambda url, *, headers: self._captured(tenant="tenant-b")
        )
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(tenant="tenant-a"),
        )
        assert r.status_code == 403
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE
        assert gateway.repo.get_tenant("tenant-b").plan_tier is PlanTier.FREE

    def test_underpayment_is_refused(self, client, gateway, no_network):
        """A subscription-tagged payment for the one-off amount buys nothing."""
        import payments

        no_network.setattr(
            payments,
            "_get_json",
            lambda url, *, headers: self._captured(amount=100, plan="subscription"),
        )
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": _checkout_sig("order_1", "pay_1"),
            },
            headers=_hdr(),
        )
        assert r.status_code == 402
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_error_body_does_not_leak_why_verification_failed(self, client, no_network):
        r = client.post(
            "/api/billing/razorpay/verify",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": "00" * 32,
            },
            headers=_hdr(),
        )
        assert "signature" not in r.text.lower()


class TestRazorpayWebhook:
    def _event(self, *, tenant="tenant-a", plan="oneoff", amount=ONEOFF_INR) -> bytes:
        return json.dumps(
            {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_wh_1",
                            "amount": amount,
                            "currency": "INR",
                            "notes": {"tenant_id": tenant, "plan": plan},
                        }
                    }
                },
            }
        ).encode()

    def test_forged_signature_is_400_and_changes_nothing(self, client, gateway):
        payload = self._event()
        r = client.post(
            "/api/billing/razorpay/webhook",
            content=payload,
            headers={"x-razorpay-signature": "00" * 32},
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_missing_signature_header_is_400(self, client, gateway):
        r = client.post("/api/billing/razorpay/webhook", content=self._event())
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_valid_webhook_upgrades_without_a_browser(self, client, gateway):
        payload = self._event(plan="subscription", amount=SUB_INR)
        r = client.post(
            "/api/billing/razorpay/webhook",
            content=payload,
            headers={"x-razorpay-signature": _webhook_sig(payload)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["handled"] is True
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.PRO

    def test_tampered_body_invalidates_the_signature(self, client, gateway):
        """Signature is over the exact bytes, so editing the amount breaks it."""
        payload = self._event()
        signature = _webhook_sig(payload)
        tampered = payload.replace(b'"tenant-a"', b'"tenant-b"')
        r = client.post(
            "/api/billing/razorpay/webhook",
            content=tampered,
            headers={"x-razorpay-signature": signature},
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-b").plan_tier is PlanTier.FREE

    def test_unrelated_event_is_acknowledged_not_acted_on(self, client, gateway):
        payload = json.dumps({"event": "payment.failed", "payload": {}}).encode()
        r = client.post(
            "/api/billing/razorpay/webhook",
            content=payload,
            headers={"x-razorpay-signature": _webhook_sig(payload)},
        )
        assert r.status_code == 200
        assert r.json()["handled"] is False
        assert gateway.auditor.events == []

    def test_payment_without_tenant_notes_is_ignored(self, client, gateway):
        payload = json.dumps(
            {
                "event": "payment.captured",
                "payload": {"payment": {"entity": {"id": "pay_x", "amount": 100, "notes": {}}}},
            }
        ).encode()
        r = client.post(
            "/api/billing/razorpay/webhook",
            content=payload,
            headers={"x-razorpay-signature": _webhook_sig(payload)},
        )
        assert r.status_code == 200
        assert r.json()["handled"] is False
        assert gateway.auditor.events == []


# ---------------------------------------------------------------------------
# PayPal
# ---------------------------------------------------------------------------


class TestPayPal:
    @pytest.fixture()
    def paypal_client(self, client, monkeypatch):
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client-fake")
        monkeypatch.setenv("PAYPAL_SECRET", "paypal-secret-fake")
        return client

    def test_unconfigured_is_503(self, client):
        r = client.post("/api/billing/paypal/order", json={"plan": "oneoff"}, headers=_hdr())
        assert r.status_code == 503

    def test_sandbox_is_the_default_environment(self, monkeypatch):
        from payments import PayPal

        monkeypatch.delenv("PAYPAL_LIVE", raising=False)
        assert "sandbox" in PayPal().api

    def test_order_returns_paypals_approval_link(self, paypal_client, monkeypatch):
        """The redirect flow needs this link; without it the client cannot proceed."""
        import payments

        monkeypatch.setattr(
            payments,
            "_post_json",
            lambda url, *, data, headers: {
                "id": "ORDER1",
                "status": "CREATED",
                "links": [
                    {"rel": "self", "href": "https://api/x"},
                    {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"},
                ],
            },
        )
        monkeypatch.setattr(payments.PayPal, "_token", lambda self: "fake-token")

        r = paypal_client.post(
            "/api/billing/paypal/order", json={"plan": "oneoff"}, headers=_hdr()
        )
        assert r.status_code == 200, r.text
        assert r.json()["approve_url"].startswith("https://www.sandbox.paypal.com/")

    def test_order_amount_is_the_server_price_in_major_units(self, paypal_client, monkeypatch):
        import payments

        seen: dict = {}

        def fake_post(url, *, data, headers):
            seen.update(data)
            return {"id": "ORDER1", "status": "CREATED", "links": []}

        monkeypatch.setattr(payments, "_post_json", fake_post)
        monkeypatch.setattr(payments.PayPal, "_token", lambda self: "fake-token")

        paypal_client.post(
            "/api/billing/paypal/order", json={"plan": "subscription"}, headers=_hdr()
        )
        unit = seen["purchase_units"][0]
        assert unit["amount"] == {"currency_code": "USD", "value": "99.00"}
        # custom_id is how the capture maps back to a tenant, set server-side.
        assert unit["custom_id"] == "tenant-a|subscription"

    def test_capture_completed_upgrades(self, paypal_client, gateway, monkeypatch):
        import payments

        def fake_post(url, *, data, headers):
            if url.endswith("/oauth2/token"):  # pragma: no cover - token uses urlopen
                raise AssertionError("token path is separate")
            return {
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "custom_id": "tenant-a|oneoff",
                        "payments": {
                            "captures": [
                                {"id": "cap_1", "amount": {"value": "50.00", "currency_code": "USD"}}
                            ]
                        },
                    }
                ],
            }

        monkeypatch.setattr(payments, "_post_json", fake_post)
        monkeypatch.setattr(payments.PayPal, "_token", lambda self: "fake-token")

        r = paypal_client.post(
            "/api/billing/paypal/capture", json={"order_id": "ORDER1"}, headers=_hdr()
        )
        assert r.status_code == 200, r.text
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.STARTER
        assert gateway.auditor.events[-1]["dedup_key"] == "paypal:cap_1"

    def test_uncompleted_capture_does_not_upgrade(self, paypal_client, gateway, monkeypatch):
        import payments

        monkeypatch.setattr(
            payments, "_post_json", lambda url, *, data, headers: {"status": "PENDING"}
        )
        monkeypatch.setattr(payments.PayPal, "_token", lambda self: "fake-token")

        r = paypal_client.post(
            "/api/billing/paypal/capture", json={"order_id": "ORDER1"}, headers=_hdr()
        )
        assert r.status_code == 400
        assert gateway.repo.get_tenant("tenant-a").plan_tier is PlanTier.FREE

    def test_cannot_capture_another_tenants_order(self, paypal_client, gateway, monkeypatch):
        import payments

        monkeypatch.setattr(
            payments,
            "_post_json",
            lambda url, *, data, headers: {
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "custom_id": "tenant-b|subscription",
                        "payments": {
                            "captures": [
                                {"id": "cap_2", "amount": {"value": "99.00", "currency_code": "USD"}}
                            ]
                        },
                    }
                ],
            },
        )
        monkeypatch.setattr(payments.PayPal, "_token", lambda self: "fake-token")

        r = paypal_client.post(
            "/api/billing/paypal/capture", json={"order_id": "ORDER1"}, headers=_hdr(tenant="tenant-a")
        )
        assert r.status_code == 403
        assert gateway.repo.get_tenant("tenant-b").plan_tier is PlanTier.FREE


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestProviderDiscovery:
    def test_requires_auth(self, client):
        assert client.get("/api/billing/providers").status_code == 401

    def test_unconfigured_provider_is_reported_unavailable(self, client):
        r = client.get("/api/billing/providers", headers=_hdr())
        assert r.status_code == 200
        paypal = [p for p in r.json()["oneoff"] if p["provider"] == "paypal"][0]
        assert paypal["available"] is False
        assert paypal["amount_minor"] is None

    def test_only_razorpay_and_paypal_are_offered(self, client):
        """Exactly the two providers — no Stripe, no operator-only path."""
        for plan in ("oneoff", "subscription"):
            names = {p["provider"] for p in client.get("/api/billing/providers", headers=_hdr()).json()[plan]}
            assert names == {"razorpay", "paypal"}

    def test_configured_provider_quotes_the_server_price(self, client):
        r = client.get("/api/billing/providers", headers=_hdr())
        razorpay = [p for p in r.json()["subscription"] if p["provider"] == "razorpay"][0]
        assert razorpay["available"] is True
        assert razorpay["amount_minor"] == SUB_INR
        assert razorpay["currency"] == "INR"

    def test_no_secrets_in_the_response(self, client):
        r = client.get("/api/billing/providers", headers=_hdr())
        assert KEY_SECRET not in r.text
        assert WEBHOOK_SECRET not in r.text
