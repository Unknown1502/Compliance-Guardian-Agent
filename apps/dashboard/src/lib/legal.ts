/**
 * Central legal/business identity configuration.
 *
 * One place, so a change to the contact address or a document version cannot
 * land in three pages and miss the fourth. It also means the public site has
 * exactly one definition of who operates the service, which is the point:
 *
 * The public-facing identity is the PRODUCT, "ComplianceGuardian" — not any
 * individual. No founder name, no residential address, no hackathon framing
 * appears anywhere a customer, a payment provider's reviewer, or a search
 * engine can see it.
 *
 * Nothing here is invented. There is deliberately no company registration
 * number, no CIN, no GSTIN, no registered office, no DPO and no certification
 * claim, because none of those exist yet. Fields that a registered entity
 * would eventually carry are absent rather than filled with plausible
 * fiction — a fabricated legal identity on a compliance product is the worst
 * possible thing to get caught with.
 *
 * When an entity is incorporated, add the real values here and the documents
 * pick them up.
 */

export const LEGAL = {
  /** The only name that appears in public legal text. */
  brand: "ComplianceGuardian",

  /**
   * Support address. Currently a working mailbox rather than a branded one;
   * swap for support@<domain> once a domain is registered.
   */
  supportEmail: "nikhiltale710@gmail.com",

  /** Where the product lives. Used for canonical links and in-document refs. */
  siteUrl: "https://cg-guardian-9856.web.app",

  /**
   * Document version and dates. Bump `version` and `lastUpdated` together
   * whenever the substance of a policy changes — a policy that silently
   * changes under a customer is exactly what these documents promise not to
   * do.
   */
  version: "1.1",
  effectiveDate: "10 August 2026",
  lastUpdated: "10 August 2026",

  /** Jurisdiction for governing-law and dispute clauses. */
  governingLaw: "India",

  /**
   * Response targets. Deliberately expressed as targets, not guarantees:
   * there is no SLA behind them and claiming one would be a false promise.
   */
  supportTarget: "2 business days",
  refundTarget: "3 business days",
  dataRequestTarget: "30 days",
} as const;

/** Routes for the legal centre, used by the footer and by cross-links. */
export const LEGAL_ROUTES = [
  { to: "/terms", label: "Terms of Service" },
  { to: "/privacy", label: "Privacy Policy" },
  { to: "/refunds", label: "Refunds & Cancellation" },
  { to: "/contact", label: "Contact Us" },
] as const;
