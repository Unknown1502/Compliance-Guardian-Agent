"""Billing client — the single choke point for every Stripe call.

Mirrors the gemini_client pattern: constructed lazily so the gateway serves
every other endpoint fine with no Stripe key configured, fails loudly and
specifically (BillingConfigError) rather than crashing at import time, and
never lets tenant_id come from anywhere but the verified server-side session
— client_reference_id on the Checkout Session is set from the authenticated
tenant, never trusted back from Stripe without also checking the signature
on the webhook that reports it.

Two things intentionally live outside this module:
  - Card collection: Stripe Checkout is hosted by Stripe. No card data ever
    touches our frontend or backend, so there is no PCI scope to manage.
  - Plan enforcement (blocking uploads past a free-tier quota): not built.
    This module only makes "buy an audit" / "subscribe" possible and records
    the outcome — deciding when to *require* payment is a product decision
    for once real usage data exists, not a default to guess at now.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import stripe

_RETRYABLE = True  # stripe-python has built-in retry; kept explicit for clarity


class BillingConfigError(RuntimeError):
    """Raised when a billing operation is attempted without required config."""


class WebhookSignatureError(RuntimeError):
    """Raised when a webhook payload fails Stripe signature verification."""


@dataclass
class CheckoutSession:
    session_id: str
    checkout_url: str


@dataclass
class WebhookEvent:
    """The subset of a verified Stripe event this app acts on."""

    event_type: str
    tenant_id: str | None
    mode: str | None  # "payment" | "subscription"
    amount_total: int | None  # minor units (cents), None for subscription-only events
    currency: str | None
    stripe_customer_id: str | None
    stripe_event_id: str


@dataclass
class BillingClient:
    """Construct once per process, same lifecycle as GeminiClient."""

    api_key: str | None = None
    webhook_secret: str | None = None
    price_id_oneoff: str = field(
        default_factory=lambda: os.environ.get("STRIPE_PRICE_ID_ONEOFF", "")
    )
    price_id_subscription: str = field(
        default_factory=lambda: os.environ.get("STRIPE_PRICE_ID_SUBSCRIPTION", "")
    )
    success_url: str = field(
        default_factory=lambda: os.environ.get(
            "STRIPE_CHECKOUT_SUCCESS_URL", "http://localhost:5173/billing?status=success"
        )
    )
    cancel_url: str = field(
        default_factory=lambda: os.environ.get(
            "STRIPE_CHECKOUT_CANCEL_URL", "http://localhost:5173/billing?status=cancelled"
        )
    )

    def __post_init__(self) -> None:
        key = self.api_key or os.environ.get("STRIPE_SECRET_KEY")
        if not key:
            raise BillingConfigError(
                "STRIPE_SECRET_KEY is not set. Provide it via env var or "
                "BillingClient(api_key=...)."
            )
        self._key = key
        self.webhook_secret = self.webhook_secret or os.environ.get("STRIPE_WEBHOOK_SECRET")

    # -- checkout -------------------------------------------------------

    def create_checkout_session(
        self, *, tenant_id: str, plan: str, customer_email: str | None = None
    ) -> CheckoutSession:
        """Create a Stripe-hosted Checkout Session for one tenant.

        plan is "oneoff" (single audit, mode=payment) or "subscription"
        (unlimited audits, mode=subscription). tenant_id is set as
        client_reference_id — the ONLY way the webhook maps a completed
        payment back to a tenant, and it always comes from the server-side
        authenticated session, never from a client-supplied body field.
        """
        if plan == "oneoff":
            mode, price_id = "payment", self.price_id_oneoff
        elif plan == "subscription":
            mode, price_id = "subscription", self.price_id_subscription
        else:
            raise ValueError(f"unknown plan {plan!r}; expected 'oneoff' or 'subscription'")

        if not price_id:
            raise BillingConfigError(
                f"no Stripe price configured for plan={plan!r} "
                f"(set STRIPE_PRICE_ID_{'ONEOFF' if plan == 'oneoff' else 'SUBSCRIPTION'})"
            )

        session = stripe.checkout.Session.create(
            api_key=self._key,
            mode=mode,
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=tenant_id,
            customer_email=customer_email,
            success_url=self.success_url,
            cancel_url=self.cancel_url,
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
        return CheckoutSession(session_id=session.id, checkout_url=session.url)

    # -- webhook ----------------------------------------------------------

    def parse_webhook(self, *, payload: bytes, signature_header: str) -> WebhookEvent:
        """Verify the Stripe-Signature header and parse a checkout event.

        Raises WebhookSignatureError on any verification failure — the caller
        must return 400 without acting on the payload. This is the only
        trust boundary: everything else in this module treats Stripe as an
        authenticated source of truth once the signature checks out.
        """
        if not self.webhook_secret:
            raise BillingConfigError("STRIPE_WEBHOOK_SECRET is not set.")
        try:
            event = stripe.Webhook.construct_event(
                payload, signature_header, self.webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WebhookSignatureError(str(exc)) from exc

        obj: dict[str, Any] = event["data"]["object"]
        return WebhookEvent(
            event_type=event["type"],
            tenant_id=(obj.get("metadata") or {}).get("tenant_id")
            or obj.get("client_reference_id"),
            mode=obj.get("mode"),
            amount_total=obj.get("amount_total"),
            currency=obj.get("currency"),
            stripe_customer_id=obj.get("customer"),
            stripe_event_id=event["id"],
        )
