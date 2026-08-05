# Five-year plan

This is a business-planning document — market sizing, revenue trajectory,
team, and funding posture. For the engineering/feature roadmap this depends
on, see [`future.md`](future.md); the "no code changes, one YAML file"
ruleset architecture described there is the mechanism that makes the
vertical-expansion years below (2 and 4) realistic instead of aspirational.

**On the numbers below:** provider counts and revenue targets are planning
assumptions reasoned from the business model, not verified market research
or audited projections. They should be validated against real registry data
before being used in any external pitch document, and revised once Year 1
actual usage/pricing data exists. The point of writing them down is to make
the assumptions checkable and arguable, not to claim false precision.

---

## The five-year thesis

Start with the smallest defensible wedge — a single regulated Australian
human-services category where audit failure is expensive and a manual
compliance review is a recurring five-figure cost. Prove the model there.
Use the same rule-engine architecture to expand into adjacent regulated
categories the buyer profile already trusts, without re-architecting
anything. Only leave Australia once the domestic playbook is boring and
repeatable, not before.

| Year | Focus | Vertical(s) | Illustrative ARR | Team size |
|---|---|---|---|---|
| 1 | Prove the wedge | NDIS (AU) | $150K–$400K | 1–3 |
| 2 | Expand verticals, same country | + Aged care, + Childcare (AU) | $1M–$2M | 8–12 |
| 3 | Channel + ecosystem | Consultant white-label, ruleset marketplace | $4M–$6M | 15–25 |
| 4 | First international beachhead | + UK or NZ equivalent regime | $12M–$18M | 40–60 |
| 5 | Category platform | Multi-country, multi-vertical | $30M+ | 80–120 |

---

## Year 1 — Prove the NDIS wedge (through the first 12 months)

**Product.** Concierge-assisted audits transition to self-serve subscription
once ~10–20 customers have validated the workflow. Ruleset stays
NDIS-only in the pitch; aged_care exists in the codebase as proven
extensibility but isn't sold yet.

**Go-to-market.** Personal network, cold outreach, and NDIS provider
communities (Facebook/LinkedIn groups). No paid acquisition — CAC stays
near zero because the channel is relationship-driven, which also builds the
trust a regulated buyer needs before handing over client records.

**Target.** ~50–150 paying providers out of an Australian NDIS registered-
provider base on the order of the low tens of thousands (illustrative,
unverified) — a low single-digit percentage. Pricing anchored around a
one-off audit fee plus a monthly subscription tier once retention is
proven; exact figures TBD from real Year 1 conversion data, not fixed in
advance.

**Team & funding.** Founder(s) only, or founder + 1–2 early hires.
Bootstrapped. No outside capital needed at this stage — the cost structure
(Cloud Run + Gemini API, both usage-billed) stays low relative to revenue
even at small scale.

**Primary risk.** Trust barrier: a regulated-industry buyer adopting an
unknown vendor's AI tool for compliance-sensitive client data. Mitigated by
the free-first-audit offer, the append-only audit trail as a visible trust
signal, and leading with real specimen output rather than marketing claims.

---

## Year 2 — Expand verticals inside Australia

**Product.** `aged_care/au.yaml` goes from proof-of-concept to a sold
product. A third vertical (childcare/early learning) ships using the same
zero-code ruleset mechanism. Proactive monitoring (flagging an approaching
retention-date or police-check expiry before it becomes a violation) begins
replacing pure reactive scoring as the headline feature.

**Go-to-market.** Referral loops start compounding — regulated-industry
buyers talk to each other inside the same provider associations. First
paid acquisition channel tested (industry-specific publications/newsletters)
once organic CAC data exists to benchmark against.

**Target.** ARR in the low seven figures across three verticals. Customer
base large enough that per-vertical pricing/tiering is set from real usage
data rather than a single flat number.

**Team & funding.** Small team (engineering, one go-to-market hire, part-
time support). A seed round becomes a live option here if growth capital
would meaningfully accelerate the vertical expansion — not required if
organic growth already funds it.

**Primary risk.** Regulatory dependency — a change to NDIS Practice
Standards or Aged Care Quality Standards could require rapid ruleset
updates. Mitigated structurally: a ruleset update is a YAML edit and a
version bump, not a re-architecture, so response time to a regulatory
change is days, not months.

---

## Year 3 — Channel and ecosystem

**Product.** White-label version ships for the compliance consultants the
product originally disrupted — same rule engine, their branding, letting
them scale their own practice instead of losing it to automation. Community/
marketplace rulesets open, so domain experts outside the company can
contribute and version rulesets for niches the core team will never have
direct expertise in.

**Go-to-market.** The consultant channel becomes a second acquisition
motion that scales sub-linearly with headcount — each consultant partner
brings their existing client book.

**Target.** ARR in the mid-to-high single-digit millions. Meaningful share
of revenue now comes through the channel rather than direct sales.

**Team & funding.** Team grows to support a real product org, not just
founders. Series A-shaped raise becomes plausible if the channel motion is
proven and international expansion is the next capital-intensive step.

**Primary risk.** Channel conflict — consultants fear the tool eventually
disintermediates them anyway. Mitigated by the white-label positioning
being genuine (their brand, their client relationship) rather than a
trojan horse.

---

## Year 4 — First international beachhead

**Product.** A jurisdiction with an analogous registered-provider
compliance regime (UK's CQC-regulated care providers, or New Zealand's
aged-care/disability equivalents, are the most structurally similar
candidates) gets its first ruleset. This is deliberately **not** a rewrite
— it's the same architecture proving it generalizes across jurisdictions,
not just industries.

**Go-to-market.** Whatever channel motion worked in Year 3 (consultant
partnerships, provider-association relationships) gets replicated in the
new market rather than reinvented.

**Target.** ARR in the low-to-mid eight figures, split across AU and the
new market, with AU still the larger share.

**Team & funding.** Team roughly triples from Year 3 to support a second
market's go-to-market and localization. This is the year most likely to
need a real institutional raise if organic revenue doesn't already cover
the expansion cost.

**Primary risk.** International regulatory complexity is genuinely harder
than the roadmap makes it look — a new country means new legal review, not
just a new YAML file, even if the technical mechanism is identical.
Mitigated by choosing the closest structural analog first rather than the
largest market first.

---

## Year 5 — Category platform

**Product.** Multi-country, multi-vertical. The proactive-monitoring
product line and the ruleset marketplace are both mature enough that new
verticals and new jurisdictions are primarily a go-to-market decision, not
an engineering one.

**Target.** ARR north of $30M, illustrative. At this scale the company is
either a durable, profitable independent platform in "AI-native compliance
for regulated human-services SMBs," or an attractive acquisition target for
a larger vertical-SaaS or GRC (governance/risk/compliance) player — both
are legitimate outcomes and the plan doesn't need to pick one prematurely.

**Team & funding.** 80–120 people. Later-stage funding or sustainable
profitability, depending on the growth-vs-margin decisions made in Years
3–4.

---

## What has to stay true across all five years

- **The ruleset stays the moat, not a bottleneck.** Every vertical and
  jurisdiction added has to keep being "write a YAML file, not rebuild the
  system" — the day that stops being true, growth slows to engineering
  speed instead of sales speed.
- **The audit trail stays the trust anchor.** Append-only, cited, versioned
  — the thing that lets a regulated buyer trust an AI vendor at all. Never
  trade this away for speed.
- **Expansion follows proven demand, not the roadmap.** This document is a
  set of assumptions to test, not a schedule to hit. If Year 1 shows NDIS
  providers actually want a fourth NDIS-specific feature more than a second
  vertical, the plan should bend toward that signal, not away from it.
