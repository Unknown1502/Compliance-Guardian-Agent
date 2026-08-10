# LEGAL REVIEW REQUIRED

Internal note. The public documents at `/terms`, `/privacy`, `/refunds` and
`/contact` are production-quality drafts written against what the system
actually does. **They are not a substitute for legal counsel** and have not
been reviewed by any.

They are honest and specific, which makes them a good starting point for a
lawyer — most of the review cost in these documents is normally spent working
out what the product does, and that part is already correct here.

## What is deliberately absent

Nothing below was invented to fill a gap. If a reviewer expects one of these,
the answer is that it does not exist yet — not that it was omitted by mistake.

| Field | Status |
|---|---|
| Registered legal entity | None. Documents name the product only. |
| Company registration / CIN | None |
| GSTIN | None |
| Registered office address | None published |
| Named Data Protection Officer | None appointed |
| Named grievance officer | None appointed |
| SOC 2 / ISO 27001 / PCI DSS | None held, none claimed |
| Data Processing Addendum | Not written. Privacy Policy says to ask. |
| Service Level Agreement | None. Terms say so explicitly. |

Adding any of these to `apps/dashboard/src/lib/legal.ts` flows through to every
document automatically.

## Sections needing confirmation before scale

**1. Limitation of liability (Terms §23).** Capped at fees paid in the
preceding twelve months. Common for SaaS, but enforceability varies by
jurisdiction and this product is sold into several. Confirm the cap survives
in India and in the jurisdictions covered by the rulesets.

**2. Indemnification (Terms §24).** One-directional — customer indemnifies us.
Enterprise buyers frequently negotiate this. Confirm it is enforceable and
decide whether a mutual version is commercially necessary.

**3. Governing law and jurisdiction (Terms §25).** India. Confirm this holds
against consumer-protection rules in other jurisdictions, which sometimes
preserve a local forum regardless of contract.

**4. Refund terms (Refunds §3–4).** Single reports are non-refundable once
delivered; Pro is refundable within 7 days if unused. Confirm against the
Consumer Protection Act, 2019 and the E-Commerce Rules, 2020, and against
payment-provider requirements. §9 already subordinates the policy to
non-waivable rights, but the specific windows should be checked.

**5. Grounds for processing (Privacy §5).** Written generically because
applicability depends on where the customer is. If the product markets into
the EU/UK, this needs a proper Article 6 mapping.

**6. International transfers (Privacy §8).** Data is stored and processed in
Google Cloud's US regions. For EU/UK customers this needs a transfer mechanism
(SCCs or equivalent) that does not currently exist. **This is the most likely
blocker for a European customer** and should be resolved before selling there.

**7. DPDP Act positioning (Privacy).** The Act's substantive obligations become
enforceable 13 May 2027, with the penalty framework from 13 Nov 2026. The
policy describes current practice rather than claiming DPDP compliance.
Confirm what must change before those dates — consent notices and the grievance
mechanism are the obvious candidates.

**8. Processor vs controller (Privacy §1).** The split is described in plain
language rather than in statutory terms. A lawyer should confirm the
characterisation, particularly for uploaded documents.

**9. AI disclosure (Terms §5, Privacy §6).** Discloses that documents go to
Google's Gemini API, that output is decision support, and that a human reviews
high-risk results. Confirm this meets automated-decision-making disclosure
duties in the jurisdictions being sold into.

## Claims verified against the code

These were checked rather than assumed, and should be re-checked if the
behaviour changes:

- One free report per workspace, consumed at report generation, enforced in a
  Firestore transaction — `firestore_repo.consume_report_entitlement`
- Retention defaults to indefinite; minimum 30 days once set —
  `retention.MIN_RETENTION_DAYS`, `Tenant.retention_days`
- Audit trail is append-only and never deleted; the runtime service account
  lacks the BigQuery job permission needed for UPDATE/DELETE — `infra/terraform/iam.tf`
- Documents are sent to Google's Gemini API — `shared/gemini_client`
- Data resides in Google Cloud US regions — `infra/terraform/variables.tf`
- Suspension affects access only, never records — `admin_routes.change_tenant_status`
- No advertising, analytics or session-replay trackers, which is why no cookie
  banner is shown — verified across `apps/dashboard/src`

## Not yet true, do not claim

- Support ticketing with tracked ticket IDs — **not built**. The contact page
  correctly says to email rather than promising a ticket system.
- Email notifications — **no email provider is configured**. Any statement about
  notifying customers by email would currently be false.
