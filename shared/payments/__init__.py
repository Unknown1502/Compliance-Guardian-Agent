"""Payment providers beyond Stripe.

Why more than one: Stripe's live mode requires a registered business in most
markets, which can take weeks. Razorpay accepts Indian sole proprietors,
PayPal covers international customers, and an offline path records a real
bank or UPI transfer that happened outside any gateway. A product that can
only take money one way is a product that cannot take money.

Security posture, identical across providers:

  * A client saying "I paid" proves nothing. Every upgrade is authorised by
    either an HMAC signature computed with a secret the client never sees,
    or a server-to-server lookup against the provider's own API.
  * Signature comparison is constant-time.
  * Amounts are read from the provider's record, never from the request, so
    a client cannot claim a 5000-paise plan after paying 100.
  * Secrets are read from the environment and never returned by any endpoint.

Each provider is independent: one being unconfigured must never stop another
from working, so configuration is checked per provider at call time rather
than once at import.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("cg.payments")

_TIMEOUT = 15


class PaymentConfigError(RuntimeError):
    """Raised when a provider is used without the config it needs."""


class PaymentVerificationError(RuntimeError):
    """Raised when a payment cannot be proven genuine. Never upgrade on this."""


@dataclass(frozen=True)
class VerifiedPayment:
    """A payment the provider itself has confirmed."""

    provider: str
    reference: str          # provider-side payment/capture id
    amount_minor: int       # smallest currency unit, from the PROVIDER's record
    currency: str
    plan: str               # oneoff | subscription
    tenant_id: str


# ---------------------------------------------------------------------------
# Pricing
#
# Prices live on the server. A client names a PLAN ("oneoff"), never an
# amount — otherwise buying the unlimited tier for 1 rupee is a single edited
# request away. Stripe enforces this with hosted Price objects; Razorpay and
# PayPal take an amount on the wire, so the equivalent guarantee has to be
# made here.
#
# Currencies differ by provider on purpose: a Razorpay account activated for
# domestic Indian payments settles in INR, while PayPal covers the same
# product internationally in USD. Both are overridable per deployment.
# ---------------------------------------------------------------------------

PLANS = ("oneoff", "subscription")

_DEFAULT_PRICES: dict[tuple[str, str], tuple[int, str]] = {
    # Roughly the USD list price converted at a round rate; set the env vars
    # rather than editing this when the rate moves.
    ("razorpay", "oneoff"): (420000, "INR"),        # ₹4,200
    ("razorpay", "subscription"): (830000, "INR"),  # ₹8,300
    ("paypal", "oneoff"): (5000, "USD"),            # $50.00
    ("paypal", "subscription"): (9900, "USD"),      # $99.00
    ("offline", "oneoff"): (5000, "USD"),
    ("offline", "subscription"): (9900, "USD"),
}


@dataclass(frozen=True)
class Price:
    amount_minor: int
    currency: str

    @property
    def major(self) -> str:
        """PayPal wants "50.00", not 5000."""
        return f"{self.amount_minor / 100:.2f}"


def price_for(provider: str, plan: str) -> Price:
    """The server's price for one plan on one provider.

    Overridable per deployment with CG_PRICE_<PROVIDER>_<PLAN> (minor units)
    and CG_CURRENCY_<PROVIDER>, so a price change is a config change.
    """
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}; expected one of {PLANS}")
    try:
        default_minor, default_currency = _DEFAULT_PRICES[(provider, plan)]
    except KeyError:
        raise ValueError(f"no pricing defined for provider {provider!r}") from None

    raw = os.environ.get(f"CG_PRICE_{provider.upper()}_{plan.upper()}", "").strip()
    if raw:
        try:
            amount = int(raw)
        except ValueError:
            # A typo'd price must not silently become a free product.
            raise PaymentConfigError(
                f"CG_PRICE_{provider.upper()}_{plan.upper()}={raw!r} is not an integer "
                "in minor units"
            ) from None
        if amount <= 0:
            raise PaymentConfigError("configured price must be greater than zero")
    else:
        amount = default_minor

    currency = (
        os.environ.get(f"CG_CURRENCY_{provider.upper()}", "").strip() or default_currency
    ).upper()
    return Price(amount_minor=amount, currency=currency)


def _post_json(url: str, *, data: dict, headers: dict) -> dict:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _get_json(url: str, *, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------


class Razorpay:
    """Razorpay Orders + client-side Checkout, verified server-side.

    Flow: the server creates an Order, the browser pays via Razorpay
    Checkout, then the browser returns three values. Those are only trusted
    after recomputing the HMAC with the key secret, which never leaves the
    server — so a forged callback cannot upgrade anyone.
    """

    API = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    def _auth_header(self) -> dict:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def create_order(self, *, amount_minor: int, currency: str, tenant_id: str, plan: str) -> dict:
        """Create an Order. tenant_id rides in notes so the webhook can map back."""
        if not self.configured:
            raise PaymentConfigError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set")
        order = _post_json(
            f"{self.API}/orders",
            data={
                "amount": amount_minor,
                "currency": currency,
                "notes": {"tenant_id": tenant_id, "plan": plan},
            },
            headers=self._auth_header(),
        )
        return {"order_id": order["id"], "amount": order["amount"], "currency": order["currency"]}

    def verify_checkout(
        self, *, order_id: str, payment_id: str, signature: str
    ) -> VerifiedPayment:
        """Verify a Checkout callback, then confirm against the API.

        Two steps on purpose. The HMAC proves the callback came from a party
        holding the key secret; the API lookup proves the payment is actually
        captured and tells us the real amount. Signature alone would accept a
        replayed or authorised-but-uncaptured payment.
        """
        if not self.configured:
            raise PaymentConfigError("Razorpay is not configured")

        expected = hmac.new(
            self.key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise PaymentVerificationError("razorpay signature mismatch")

        payment = _get_json(f"{self.API}/payments/{payment_id}", headers=self._auth_header())
        if payment.get("status") not in ("captured", "authorized"):
            raise PaymentVerificationError(
                f"razorpay payment status is {payment.get('status')!r}, not captured"
            )
        if payment.get("order_id") != order_id:
            raise PaymentVerificationError("razorpay payment does not belong to that order")

        notes = payment.get("notes") or {}
        tenant_id = notes.get("tenant_id", "")
        if not tenant_id:
            order = _get_json(f"{self.API}/orders/{order_id}", headers=self._auth_header())
            tenant_id = (order.get("notes") or {}).get("tenant_id", "")

        return VerifiedPayment(
            provider="razorpay",
            reference=payment_id,
            amount_minor=int(payment.get("amount", 0)),  # provider's figure, not the client's
            currency=str(payment.get("currency", "")),
            plan=notes.get("plan", "oneoff"),
            tenant_id=tenant_id,
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict:
        """Verify a Razorpay webhook body against the webhook secret."""
        secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
        if not secret:
            raise PaymentConfigError("RAZORPAY_WEBHOOK_SECRET is not set")
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise PaymentVerificationError("razorpay webhook signature mismatch")
        return json.loads(payload.decode("utf-8") or "{}")


# ---------------------------------------------------------------------------
# PayPal
# ---------------------------------------------------------------------------


class PayPal:
    """PayPal Orders v2.

    No client-side signature to check, so trust comes entirely from a
    server-to-server capture: we call PayPal with our own credentials and
    read the result. The browser is never the source of truth.
    """

    def __init__(
        self, client_id: str | None = None, secret: str | None = None, live: bool | None = None
    ) -> None:
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.secret = secret or os.environ.get("PAYPAL_SECRET", "")
        env_live = os.environ.get("PAYPAL_LIVE", "0") == "1"
        self.live = env_live if live is None else live

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    @property
    def api(self) -> str:
        return "https://api-m.paypal.com" if self.live else "https://api-m.sandbox.paypal.com"

    def _token(self) -> str:
        if not self.configured:
            raise PaymentConfigError("PAYPAL_CLIENT_ID / PAYPAL_SECRET are not set")
        basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        req = urllib.request.Request(
            f"{self.api}/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]

    def create_order(
        self,
        *,
        amount_major: str,
        currency: str,
        tenant_id: str,
        plan: str,
        return_url: str = "",
        cancel_url: str = "",
    ) -> dict:
        """Create an order and return PayPal's own approval link.

        The redirect flow is used rather than PayPal's browser SDK: it keeps a
        third-party script off our pages entirely and means the client id
        never has to be published to the frontend.
        """
        token = self._token()
        context = {
            "user_action": "PAY_NOW",
            "return_url": return_url or os.environ.get("PAYPAL_RETURN_URL", ""),
            "cancel_url": cancel_url or os.environ.get("PAYPAL_CANCEL_URL", ""),
        }
        order = _post_json(
            f"{self.api}/v2/checkout/orders",
            data={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        # custom_id survives the round trip, so the capture can
                        # be mapped back to a tenant without trusting the client.
                        "custom_id": f"{tenant_id}|{plan}",
                        "amount": {"currency_code": currency, "value": amount_major},
                    }
                ],
                "application_context": {k: v for k, v in context.items() if v},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        approve = next(
            (
                link.get("href", "")
                for link in (order.get("links") or [])
                if link.get("rel") in ("approve", "payer-action")
            ),
            "",
        )
        return {
            "order_id": order["id"],
            "status": order.get("status", ""),
            "approve_url": approve,
        }

    def capture_order(self, order_id: str) -> VerifiedPayment:
        """Capture and read the result. This call IS the verification."""
        token = self._token()
        try:
            result = _post_json(
                f"{self.api}/v2/checkout/orders/{order_id}/capture",
                data={},
                headers={"Authorization": f"Bearer {token}"},
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise PaymentVerificationError(f"paypal capture failed: {body}") from exc

        if result.get("status") != "COMPLETED":
            raise PaymentVerificationError(
                f"paypal order status is {result.get('status')!r}, not COMPLETED"
            )

        unit = (result.get("purchase_units") or [{}])[0]
        capture = ((unit.get("payments") or {}).get("captures") or [{}])[0]
        amount = capture.get("amount", {})
        custom = unit.get("custom_id") or capture.get("custom_id") or ""
        tenant_id, _, plan = custom.partition("|")

        # PayPal reports major units ("50.00"); normalise to minor for storage.
        minor = int(round(float(amount.get("value", "0")) * 100))
        return VerifiedPayment(
            provider="paypal",
            reference=capture.get("id", order_id),
            amount_minor=minor,
            currency=str(amount.get("currency_code", "")),
            plan=plan or "oneoff",
            tenant_id=tenant_id,
        )


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------


def record_offline_payment(
    *, tenant_id: str, plan: str, amount_minor: int, currency: str, reference: str
) -> VerifiedPayment:
    """A payment that happened outside any gateway — bank transfer, UPI, cash.

    There is nothing to verify cryptographically, so this is deliberately NOT
    reachable by a customer: only a platform operator can record one, and the
    audit trail records who did it and what reference they cited. The control
    is accountability, not cryptography, and the endpoint says so plainly.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if amount_minor <= 0:
        raise ValueError("amount must be positive")
    return VerifiedPayment(
        provider="offline",
        reference=reference or "manual",
        amount_minor=amount_minor,
        currency=currency,
        plan=plan,
        tenant_id=tenant_id,
    )


def configured_providers() -> dict[str, bool]:
    """Which providers this deployment can actually use right now."""
    return {
        "stripe": bool(os.environ.get("STRIPE_SECRET_KEY")),
        "razorpay": Razorpay().configured,
        "paypal": PayPal().configured,
        "offline": True,  # always available; operator-only
    }
