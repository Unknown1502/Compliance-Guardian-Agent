"""Every payment route in the product.

Two ways to take money, neither requiring a registered business: Razorpay
(unregistered Indian sole proprietors, settles in INR) and PayPal, which
covers every customer outside India — Razorpay's domestic account rejects
international cards.

The trust model is identical on every route, and it is the whole point of
this file:

  * A client naming a PLAN is a request. A client naming an AMOUNT is
    ignored — prices come from payments.price_for() on the server, so
    "subscription for 1 rupee" is not expressible.
  * A client saying "I paid" is never sufficient. Upgrades happen only after
    an HMAC computed with a secret the browser never holds, or a
    server-to-server call to the provider with our own credentials.
  * The tenant to upgrade comes from the order's server-set notes, and is
    then re-checked against the authenticated caller. A verified payment for
    someone else's tenant is a 403, not a silent cross-tenant write. There is
    no path here that writes across tenants at all.
  * Every upgrade is written to the append-only audit trail with the
    provider's own reference, so a disputed charge can be traced.

Providers are independent by construction: an unconfigured PayPal must never
stop Razorpay from working, so configuration is checked per route at call
time rather than once at import.
"""

from __future__ import annotations

import logging
from typing import Callable

from auth_middleware import AuthContext, require_auth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from schema_validators import PlanTier

logger = logging.getLogger("cg.gateway.payments")

_PLAN_PATTERN = "^(oneoff|subscription)$"


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Request / response models
#
# Note what is absent from every request: an amount. The server looks the
# price up from the plan.
# ---------------------------------------------------------------------------


class OrderRequest(_Strict):
    plan: str = Field(pattern=_PLAN_PATTERN)


class RazorpayOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    # Razorpay Checkout needs the key id in the browser. It is the publishable
    # half of the pair and is safe to expose; the secret never leaves here.
    key_id: str


class RazorpayVerifyRequest(_Strict):
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=256)


class PayPalOrderResponse(BaseModel):
    order_id: str
    status: str
    # Where to send the browser. Empty means PayPal returned no approval link,
    # which the client treats as a failure rather than a silent no-op.
    approve_url: str = ""


class PayPalCaptureRequest(_Strict):
    order_id: str = Field(min_length=1, max_length=128)


class PaymentResult(BaseModel):
    plan_tier: str
    provider: str
    reference: str
    amount_minor: int
    currency: str


class ProviderOption(BaseModel):
    provider: str
    available: bool
    # Absent when the provider is not configured — there is no price to quote.
    amount_minor: int | None = None
    currency: str | None = None


class ProvidersResponse(BaseModel):
    oneoff: list[ProviderOption]
    subscription: list[ProviderOption]


# ---------------------------------------------------------------------------


def _tier_for(plan: str) -> PlanTier:
    return PlanTier.PRO if plan == "subscription" else PlanTier.STARTER


def build_payment_router(
    gw,
    *,
    enforce_expensive: Callable[[str, str], None],
    enforce_standard: Callable[[str, str], None],
) -> APIRouter:
    """Build the router.

    Limiter enforcement is injected rather than imported so these routes draw
    from the SAME token buckets as the rest of the gateway. Constructing new
    limiters here would quietly double every caller's budget.
    """
    router = APIRouter(tags=["payments"])

    def _apply_payment(payment, *, actor: str, caller_tenant: str | None) -> PaymentResult:
        """Upgrade a tenant from a payment the provider has confirmed.

        caller_tenant is the authenticated tenant on interactive routes and
        None on webhooks (where there is no caller, only a signature). When
        present it must match: a signature proves a payment is genuine, not
        that the person replaying it owns the tenant it belongs to.
        """
        from payments import price_for

        if not payment.tenant_id:
            # Order notes are set by us at creation, so this means the payment
            # did not originate from this application.
            logger.warning("%s payment %s has no tenant", payment.provider, payment.reference)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="payment is not linked to a workspace",
            )
        if caller_tenant is not None and payment.tenant_id != caller_tenant:
            logger.warning(
                "tenant %s presented a %s payment belonging to %s",
                caller_tenant,
                payment.provider,
                payment.tenant_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="payment belongs to another workspace"
            )

        # Underpayment guard. Orders are created server-side at the server's
        # price, so this should be unreachable — which is exactly why it is
        # worth failing loudly if it ever fires.
        expected = price_for(payment.provider, payment.plan)
        if payment.amount_minor < expected.amount_minor:
            logger.error(
                "underpaid %s payment %s: %s < %s",
                payment.provider,
                payment.reference,
                payment.amount_minor,
                expected.amount_minor,
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="payment amount is short"
            )

        g = gw()
        tenant = g.repo.get_tenant(payment.tenant_id)
        before = tenant.plan_tier
        tier = _tier_for(payment.plan)
        tenant.plan_tier = tier
        g.repo.upsert_tenant(tenant)
        g.auditor.log(
            tenant_id=payment.tenant_id,
            actor=actor,
            action="billing.subscribed" if payment.plan == "subscription" else "billing.purchased",
            # Keyed on the provider's own reference, so a replayed webhook or
            # a double-submitted callback collapses to one audit event.
            dedup_key=f"{payment.provider}:{payment.reference}",
            before_state={"plan_tier": before.value},
            after_state={
                "plan_tier": tier.value,
                "provider": payment.provider,
                "reference": payment.reference,
                "amount_minor": payment.amount_minor,
                "currency": payment.currency,
            },
        )
        return PaymentResult(
            plan_tier=tier.value,
            provider=payment.provider,
            reference=payment.reference,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
        )

    def _unavailable(provider: str, exc: Exception) -> HTTPException:
        """503 for a provider that is not set up.

        The underlying message names environment variables, so it is logged
        rather than returned.
        """
        logger.warning("%s is not configured: %s", provider, exc)
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider} payments are not available right now",
        )

    # -- discovery ---------------------------------------------------------

    @router.get("/billing/providers", response_model=ProvidersResponse)
    def list_providers(auth: AuthContext = Depends(require_auth)) -> ProvidersResponse:
        """What this deployment can actually charge with, and for how much.

        The billing page renders from this instead of a hardcoded list, so a
        provider that has no keys is never offered to a customer as a button
        that 503s.
        """
        from payments import PaymentConfigError, configured_providers, price_for

        available = configured_providers()

        def options(plan: str) -> list[ProviderOption]:
            out: list[ProviderOption] = []
            for provider in ("razorpay", "paypal"):
                if not available.get(provider, False):
                    out.append(ProviderOption(provider=provider, available=False))
                    continue
                try:
                    price = price_for(provider, plan)
                except (ValueError, PaymentConfigError) as exc:
                    logger.warning("pricing unavailable for %s/%s: %s", provider, plan, exc)
                    out.append(ProviderOption(provider=provider, available=False))
                    continue
                out.append(
                    ProviderOption(
                        provider=provider,
                        available=True,
                        amount_minor=price.amount_minor,
                        currency=price.currency,
                    )
                )
            return out

        return ProvidersResponse(oneoff=options("oneoff"), subscription=options("subscription"))

    # -- Razorpay ----------------------------------------------------------

    @router.post("/billing/razorpay/order", response_model=RazorpayOrderResponse)
    def razorpay_order(
        req: OrderRequest, auth: AuthContext = Depends(require_auth)
    ) -> RazorpayOrderResponse:
        from payments import PaymentConfigError, Razorpay, price_for

        enforce_expensive(auth.tenant_id, "payment orders")
        client = Razorpay()
        if not client.configured:
            raise _unavailable("razorpay", PaymentConfigError("keys are not set"))

        price = price_for("razorpay", req.plan)
        try:
            order = client.create_order(
                amount_minor=price.amount_minor,
                currency=price.currency,
                # From the verified session. This is what the verify step and
                # the webhook later read back to decide who to upgrade.
                tenant_id=auth.tenant_id,
                plan=req.plan,
            )
        except PaymentConfigError as exc:
            raise _unavailable("razorpay", exc) from exc
        except Exception as exc:
            logger.exception("razorpay order creation failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="could not start the payment",
            ) from exc

        return RazorpayOrderResponse(
            order_id=order["order_id"],
            amount=order["amount"],
            currency=order["currency"],
            key_id=client.key_id,
        )

    @router.post("/billing/razorpay/verify", response_model=PaymentResult)
    def razorpay_verify(
        req: RazorpayVerifyRequest, auth: AuthContext = Depends(require_auth)
    ) -> PaymentResult:
        """Verify a Checkout callback and upgrade.

        The browser hands back three values after paying. They are worth
        nothing until the HMAC recomputes and Razorpay's own API confirms the
        payment is captured — both happen inside verify_checkout().
        """
        from payments import PaymentConfigError, PaymentVerificationError, Razorpay

        enforce_expensive(auth.tenant_id, "payment verification")
        try:
            payment = Razorpay().verify_checkout(
                order_id=req.razorpay_order_id,
                payment_id=req.razorpay_payment_id,
                signature=req.razorpay_signature,
            )
        except PaymentVerificationError as exc:
            # Never echo which half failed — that tells a forger where to aim.
            logger.warning("razorpay verification rejected for %s: %s", auth.tenant_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="payment could not be verified"
            ) from exc
        except PaymentConfigError as exc:
            raise _unavailable("razorpay", exc) from exc
        except Exception as exc:
            logger.exception("razorpay verification failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="could not confirm the payment"
            ) from exc

        return _apply_payment(payment, actor="razorpay-checkout", caller_tenant=auth.tenant_id)

    @router.post("/billing/razorpay/webhook", status_code=status.HTTP_200_OK)
    async def razorpay_webhook(request: Request) -> dict:
        """Server-to-server confirmation, independent of the browser.

        Exists because the verify route depends on the customer's browser
        making it back from the payment page. If they close the tab mid-flow,
        this is what still upgrades them.
        """
        from payments import (
            PaymentConfigError,
            PaymentVerificationError,
            Razorpay,
            VerifiedPayment,
        )

        # Public by necessity (Razorpay calls it unauthenticated; authenticity
        # comes from the signature). Limited per source IP so a forged-signature
        # flood cannot spin the verifier.
        client_ip = request.client.host if request.client else "unknown"
        enforce_standard(f"webhook:{client_ip}", "razorpay webhook")

        payload = await request.body()
        signature = request.headers.get("x-razorpay-signature", "")
        try:
            event = Razorpay().verify_webhook(payload=payload, signature=signature)
        except PaymentVerificationError as exc:
            logger.warning("razorpay webhook signature rejected: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid signature"
            ) from exc
        except PaymentConfigError as exc:
            raise _unavailable("razorpay", exc) from exc

        if event.get("event") not in ("payment.captured", "order.paid"):
            # Acknowledge anything else with 200 so Razorpay stops retrying.
            return {"received": True, "handled": False}

        entity = (
            ((event.get("payload") or {}).get("payment") or {}).get("entity")
            or {}
        )
        notes = entity.get("notes") or {}
        if not entity.get("id"):
            return {"received": True, "handled": False}

        payment = VerifiedPayment(
            provider="razorpay",
            reference=str(entity["id"]),
            amount_minor=int(entity.get("amount", 0)),
            currency=str(entity.get("currency", "")),
            plan=str(notes.get("plan", "oneoff")),
            tenant_id=str(notes.get("tenant_id", "")),
        )
        if not payment.tenant_id:
            # Not ours, or notes were stripped. 200 so it is not retried
            # forever, but nothing is granted.
            logger.warning("razorpay webhook payment %s carries no tenant", payment.reference)
            return {"received": True, "handled": False}

        _apply_payment(payment, actor="razorpay-webhook", caller_tenant=None)
        return {"received": True, "handled": True}

    # -- PayPal ------------------------------------------------------------

    @router.post("/billing/paypal/order", response_model=PayPalOrderResponse)
    def paypal_order(
        req: OrderRequest, auth: AuthContext = Depends(require_auth)
    ) -> PayPalOrderResponse:
        from payments import PayPal, PaymentConfigError, price_for

        enforce_expensive(auth.tenant_id, "payment orders")
        client = PayPal()
        if not client.configured:
            raise _unavailable("paypal", PaymentConfigError("credentials are not set"))

        price = price_for("paypal", req.plan)
        try:
            order = client.create_order(
                amount_major=price.major,
                currency=price.currency,
                tenant_id=auth.tenant_id,
                plan=req.plan,
            )
        except PaymentConfigError as exc:
            raise _unavailable("paypal", exc) from exc
        except Exception as exc:
            logger.exception("paypal order creation failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="could not start the payment"
            ) from exc
        return PayPalOrderResponse(
            order_id=order["order_id"],
            status=order["status"],
            approve_url=order.get("approve_url", ""),
        )

    @router.post("/billing/paypal/capture", response_model=PaymentResult)
    def paypal_capture(
        req: PayPalCaptureRequest, auth: AuthContext = Depends(require_auth)
    ) -> PaymentResult:
        """Capture the order server-side. This call IS the verification.

        PayPal gives the browser no signature to check, so nothing the client
        sends is trusted beyond the order id — and an order id alone buys
        nothing, because the capture either succeeds against PayPal with our
        credentials or it does not.
        """
        from payments import PayPal, PaymentConfigError, PaymentVerificationError

        enforce_expensive(auth.tenant_id, "payment verification")
        try:
            payment = PayPal().capture_order(req.order_id)
        except PaymentVerificationError as exc:
            logger.warning("paypal capture rejected for %s: %s", auth.tenant_id, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="payment could not be verified"
            ) from exc
        except PaymentConfigError as exc:
            raise _unavailable("paypal", exc) from exc
        except Exception as exc:
            logger.exception("paypal capture failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="could not confirm the payment"
            ) from exc

        return _apply_payment(payment, actor="paypal-capture", caller_tenant=auth.tenant_id)

    return router
