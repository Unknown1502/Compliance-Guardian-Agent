# Future development

Roadmap beyond the XPRIZE Hackathon submission (Aug 17, 2026). Nothing here
should be built before that date — everything between now and submission
goes to revenue and users, not new features. This document exists so the
forward plan is written down, not just described in a pitch.

## The structural advantage everything below leans on

A new ruleset is one YAML file under `rulesets/{industry}/{jurisdiction}.yaml`,
validated against the `RuleSet` Pydantic schema on load, with the field list
for extraction derived automatically (`required_fields` ∪ every field
referenced by any rule's `params`). **No code changes.** This was proven
twice: once at launch (`healthcare_ndis/au.yaml`) and again by adding
`aged_care/au.yaml` — verified end-to-end against production with zero lines
of Python touched. That means the product can expand into a new compliance
niche in an afternoon, not a sprint. Everything below depends on that.

---

## Phase 1 — deepen the NDIS wedge (first 1–3 months post-hackathon)

- **More NDIS rulesets, customer-driven.** `healthcare_ndis/au.yaml`
  currently covers 4 rules (retention, consent, incident reporting, worker
  screening). Real NDIS Practice Standards cover more: restrictive
  practices reporting, complaints handling, medication management, staff
  qualification records, service agreement terms. The right way to add
  these is **not** to write twenty rules speculatively — it's to let real
  customer conversations drive it. First provider asks "can it also check
  X" → that becomes the next ruleset. A product that visibly grows from
  real usage is a better story than one that grew from guessing.
- **Self-serve billing, fully live.** Concierge-first by design during
  launch; Stripe subscriptions come once demand is proven.
- **Ingestion beyond manual upload.** Email-forward was in the original
  spec (`doc/development.md`). NDIS providers live in Outlook, not
  dashboards — meeting them there removes the last piece of adoption
  friction.
- **Reviewer workflow depth.** Assignment, SLA tracking on escalations.

## Phase 2 — adjacent regulated niches (3–6 months)

- **Aged care** — already shipped (`rulesets/aged_care/au.yaml`), same
  regulator relationship and audit-anxious buyer profile as NDIS. Next step
  is real customers, not more rules, until one asks for more.
- **Childcare / early learning** — another human-services niche with real
  compliance deadlines and a comparable buyer.
- **Turn on what's already built but hidden from the pitch.**
  `contract_review/generic.yaml` and `bookkeeping/au.yaml` already exist in
  the repo, deliberately excluded from the NDIS-only pitch to keep
  go-to-market focused during the hackathon window. Once there's a working
  sales motion, these become real second and third product lines with
  almost no new engineering.

## Phase 3 — platform depth (6–12 months)

- **Proactive, not just reactive.** Today the product scores what you
  upload. The bigger version watches retention dates approaching expiry,
  worker screening checks about to lapse, and police checks nearing their
  3-year currency limit — and flags them *before* an assessor asks.
  Ongoing compliance monitoring instead of a one-off audit tool.
- **Sell to the consultants, not just past them.** A white-label version
  for the compliance consultants this product currently disrupts, so they
  can scale their own practice instead of losing it to automation. Same
  rule engine, different customer.
- **Community/marketplace rulesets.** Leaning into the YAML-drop-in
  architecture publicly — let compliance experts outside the company
  contribute and version rulesets for niches the core team will never have
  direct expertise in.

---

## Explicitly out of scope for now

- Multi-jurisdiction expansion outside Australia. NDIS's regulatory
  relationships are specific to Australia and don't transplant directly;
  other countries have analogous but distinct disability-support
  frameworks. Worth revisiting once the AU business is real, not before.
- Anything on this page, before Aug 17, 2026. This document is for
  articulating the roadmap in the pitch — "sustainability of the underlying
  business model" is a judging criterion — not a build queue for the
  remaining hackathon days.
