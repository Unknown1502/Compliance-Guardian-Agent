"""Every price a customer sees must be the price the server charges.

This exists because they diverged in production: the landing page advertised
$50 for a single audit while the server charged ₹1,999 / $25. Nothing failed,
no test broke, and the only symptom was a customer reaching checkout and
seeing a different number than the one that sold them.

The backend table in shared/payments is the single source. These tests read
the marketing and billing components and assert the figures in them still
resolve to it, so the next edit to either side cannot silently drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from payments import price_for

REPO_ROOT = Path(__file__).resolve().parents[2]
LANDING = REPO_ROOT / "apps/dashboard/src/views/LandingPage.tsx"
BILLING = REPO_ROOT / "apps/dashboard/src/views/BillingView.tsx"


def _rupees(amount_minor: int) -> str:
    """199900 -> '1,999' — Indian-format grouping as the UI writes it."""
    whole = amount_minor // 100
    s = str(whole)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _dollars(amount_minor: int) -> str:
    return f"{amount_minor // 100}"


@pytest.fixture(scope="module")
def landing() -> str:
    return LANDING.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def billing() -> str:
    return BILLING.read_text(encoding="utf-8")


class TestTheBackendPriceIsWhatItShouldBe:
    """The launch prices, stated once so a change here is deliberate."""

    def test_single_audit_is_1999_inr(self):
        p = price_for("razorpay", "oneoff")
        assert (p.amount_minor, p.currency) == (199900, "INR")

    def test_pro_is_8300_inr_per_month(self):
        p = price_for("razorpay", "subscription")
        assert (p.amount_minor, p.currency) == (830000, "INR")

    def test_international_prices_track_the_inr_plans(self):
        """Same two products, not a second price list. Converted near ₹83/USD
        and rounded — this asserts nobody re-points USD at a different offer."""
        for plan in ("oneoff", "subscription"):
            inr = price_for("razorpay", plan)
            usd = price_for("paypal", plan)
            implied = (inr.amount_minor / 100) / (usd.amount_minor / 100)
            assert 75 <= implied <= 95, (
                f"{plan}: ₹{inr.amount_minor // 100} vs ${usd.amount_minor // 100} "
                f"implies ₹{implied:.0f}/USD — one side has drifted"
            )


class TestTheLandingPageMatchesTheServer:
    def test_single_audit_price_is_shown(self, landing):
        assert f"₹{_rupees(price_for('razorpay', 'oneoff').amount_minor)}" in landing

    def test_pro_price_is_shown(self, landing):
        assert f"₹{_rupees(price_for('razorpay', 'subscription').amount_minor)}" in landing

    def test_usd_figures_match_paypal(self, landing):
        assert f"${_dollars(price_for('paypal', 'oneoff').amount_minor)}" in landing
        assert f"${_dollars(price_for('paypal', 'subscription').amount_minor)}" in landing

    def test_no_stale_price_survives(self, landing):
        """The specific regression: $50 outlived the price it described."""
        live = {
            f"${_dollars(price_for('paypal', p).amount_minor)}"
            for p in ("oneoff", "subscription")
        }
        for shown in set(re.findall(r"\$\d{1,4}", landing)):
            assert shown in live, f"{shown} on the landing page is not a price the server charges"


class TestTheBillingScreenMatchesTheServer:
    def test_fallback_prices_are_the_inr_plans(self, billing):
        """Shown for the moment before /billing/providers answers. A stale
        value here is worse than no value: it is a price the customer reads
        and then watches change."""
        for plan in ("oneoff", "subscription"):
            assert f"₹{_rupees(price_for('razorpay', plan).amount_minor)}" in billing


class TestWordingMatchesWhatTheBackendDelivers:
    def test_nothing_customer_facing_promises_unlimited(self, landing, billing):
        """Rate limits and entitlement checks are real, so 'unlimited' would be
        a promise the product does not keep — and the kind a customer quotes
        back during a dispute."""
        for name, src in (("landing page", landing), ("billing screen", billing)):
            # Comment prefixes include JSX's `{/*`, which is how the note
            # explaining *why* the word is avoided is written.
            offenders = [
                line.strip()
                for line in src.splitlines()
                if "unlimited" in line.lower()
                and not line.strip().startswith(("//", "*", "/*", "{/*"))
            ]
            assert not offenders, f"{name} still promises unlimited: {offenders}"

    def test_the_paid_plan_is_named_consistently(self, landing, billing):
        assert "ComplianceGuardian Pro" in landing
        assert "ComplianceGuardian Pro" in billing
