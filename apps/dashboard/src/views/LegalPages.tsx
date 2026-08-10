/**
 * Public policy pages: Terms, Privacy, Refunds & Cancellation, Contact.
 *
 * Two reasons they exist, both real. Payment providers will not activate a
 * merchant without them — a website review checking for exactly these is the
 * most common place a SaaS activation stalls. And a compliance product with
 * no published terms of its own is a poor advertisement for what it sells.
 *
 * Every claim here is checked against the running system rather than lifted
 * from a template. Documents really are sent to Google's Gemini API. The
 * audit trail really is append-only and really is never deleted. Retention
 * really defaults to indefinite with a 30-day floor once set. The free
 * allowance really is one report per workspace, enforced in a transaction.
 * A policy that describes a different product is worse than no policy,
 * because it is a false statement rather than a missing one.
 *
 * Equally important is what is NOT here: no company registration number, no
 * CIN, no GSTIN, no registered office, no named DPO, no SOC 2, no ISO 27001.
 * None of those exist yet. On a compliance product, a fabricated legal
 * identity is the single worst thing to be caught with.
 *
 * NOT legal advice, and the pages say so. For a product that sells compliance
 * checking, the line between "software that cites rules" and "advice" is the
 * most important thing to state plainly.
 *
 * See LEGAL-REVIEW.md for the sections that need counsel before scale.
 */

import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { LEGAL, LEGAL_ROUTES } from "../lib/legal";

const SUPPORT_EMAIL = LEGAL.supportEmail;

/** Section heading that doubles as an anchor target for the contents list. */
function H({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-24 pt-3 text-[16px] font-semibold text-ink">
      {children}
    </h2>
  );
}

/** In-page contents. Long documents are unusable without one. */
function Contents({ items }: { items: { id: string; label: string }[] }) {
  return (
    <nav aria-label="Contents" className="rounded-xl border border-line bg-surface-2 p-4">
      <p className="text-[12px] font-semibold uppercase tracking-wide text-muted">Contents</p>
      <ol className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {items.map((i, n) => (
          <li key={i.id} className="text-[13px]">
            <a href={`#${i.id}`} className="text-ink-2 hover:text-brand-600 hover:underline">
              <span className="text-muted">{n + 1}.</span> {i.label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Page({
  title,
  intro,
  contents,
  children,
}: {
  title: string;
  intro: React.ReactNode;
  contents: { id: string; label: string }[];
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-bg">
      <a
        href="#doc"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:rounded-lg focus:bg-brand-600 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to document
      </a>

      <header className="border-b border-line print:hidden">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-6 py-5">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-2 hover:text-ink"
          >
            <ArrowLeft size={14} />
            {LEGAL.brand}
          </Link>
          <span className="text-[12px] text-muted">
            v{LEGAL.version} · Effective {LEGAL.effectiveDate} · Updated {LEGAL.lastUpdated}
          </span>
        </div>
      </header>

      <main id="doc" className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="text-[26px] font-bold tracking-tight text-ink">{title}</h1>
        <div className="mt-4 text-[14px] leading-relaxed text-ink-2">{intro}</div>
        <div className="mt-7 print:hidden">
          <Contents items={contents} />
        </div>
        <div className="mt-8 space-y-4 text-[14px] leading-relaxed text-ink-2">{children}</div>
      </main>

      <footer className="border-t border-line py-8 print:hidden">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-x-5 gap-y-2 px-6 text-[12.5px] text-muted">
          {LEGAL_ROUTES.map((r) => (
            <Link key={r.to} to={r.to} className="hover:text-ink">
              {r.label}
            </Link>
          ))}
        </div>
      </footer>
    </div>
  );
}

/** Stated wherever output could be mistaken for advice. */
function NotAdvice() {
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-4 text-[13px]">
      <strong className="font-semibold text-ink">
        {LEGAL.brand} is software, not an adviser.
      </strong>{" "}
      It checks documents against published rules and shows which rule each finding cites, so
      you can verify it yourself. It does not provide legal, financial or regulatory advice,
      and its output is not a substitute for a qualified professional or for your own review.
      You remain responsible for your compliance obligations.
    </div>
  );
}

function Mail() {
  return (
    <a href={`mailto:${SUPPORT_EMAIL}`} className="text-brand-600 underline">
      {SUPPORT_EMAIL}
    </a>
  );
}

// ============================================================ TERMS

const TERMS_TOC = [
  { id: "definitions", label: "Definitions" },
  { id: "eligibility", label: "Eligibility and accounts" },
  { id: "workspace", label: "Workspaces and users" },
  { id: "service", label: "What the service does" },
  { id: "ai", label: "AI-assisted analysis" },
  { id: "responsibilities", label: "Your responsibilities" },
  { id: "acceptable", label: "Acceptable use" },
  { id: "prohibited", label: "Prohibited activities" },
  { id: "customer-data", label: "Customer Data and ownership" },
  { id: "confidentiality", label: "Confidentiality" },
  { id: "ip", label: "Intellectual property" },
  { id: "third-party", label: "Third-party services" },
  { id: "security", label: "Security" },
  { id: "availability", label: "Service availability" },
  { id: "fees", label: "Plans, fees and entitlements" },
  { id: "renewal", label: "Renewal and cancellation" },
  { id: "refunds", label: "Refunds" },
  { id: "suspension", label: "Suspension" },
  { id: "termination", label: "Termination and data export" },
  { id: "retention", label: "Data retention" },
  { id: "disclaimers", label: "Disclaimers" },
  { id: "no-guarantee", label: "No guarantee of compliance" },
  { id: "liability", label: "Limitation of liability" },
  { id: "indemnity", label: "Indemnification" },
  { id: "law", label: "Governing law and disputes" },
  { id: "changes", label: "Changes, notices and contact" },
  { id: "general", label: "Severability and entire agreement" },
];

export function TermsPage() {
  return (
    <Page
      title="Terms of Service"
      contents={TERMS_TOC}
      intro={
        <p>
          These terms govern your use of {LEGAL.brand}, the compliance-analysis service at{" "}
          {LEGAL.siteUrl}. By creating an account or using the service you agree to them. Where
          these terms say &ldquo;we&rdquo; or &ldquo;us&rdquo; they mean {LEGAL.brand}; where
          they say &ldquo;you&rdquo; they mean the organisation whose workspace is used.
        </p>
      }
    >
      <NotAdvice />

      <H id="definitions">1. Definitions</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Workspace</strong> — the tenant account holding your
          documents, checks, members and settings. All access is scoped to it.
        </li>
        <li>
          <strong className="text-ink">Customer Data</strong> — documents you upload, fields
          extracted from them, check results, comments and configuration.
        </li>
        <li>
          <strong className="text-ink">Ruleset</strong> — a versioned set of rules for one
          industry and jurisdiction, against which documents are evaluated.
        </li>
        <li>
          <strong className="text-ink">Report</strong> — one completed compliance check of one
          document, with per-rule findings and a risk score.
        </li>
        <li>
          <strong className="text-ink">Entitlement</strong> — your allowance of reports, from
          the free allocation, a single purchase, or a Pro subscription.
        </li>
      </ul>

      <H id="eligibility">2. Eligibility and accounts</H>
      <p>
        The service is for businesses and organisations. You must be able to form a binding
        contract and must be at least 18. You are responsible for the accuracy of your account
        details, for your credentials, and for all activity under them. Tell us at{" "}
        <Mail /> if you believe an account has been compromised.
      </p>

      <H id="workspace">3. Workspaces and users</H>
      <p>
        A workspace belongs to your organisation, not to the individual who created it. An
        owner or admin can add members and assign roles. You are responsible for the actions of
        everyone you invite, and for removing people who should no longer have access. Data is
        isolated per workspace: there is no path in the product by which one workspace can
        address another&rsquo;s documents, checks or audit records.
      </p>

      <H id="service">4. What the service does</H>
      <p>
        You upload a document. The service extracts structured fields, evaluates every rule in
        the ruleset selected for your workspace&rsquo;s industry and jurisdiction, and returns a
        risk score with findings that cite the specific rule each relies on. Low-risk results
        may be approved automatically; higher-risk results are routed to a human reviewer in
        your workspace. Every step is written to an append-only audit trail.
      </p>
      <p>
        Rulesets are versioned. Each completed check records the exact ruleset version applied,
        and changing your workspace&rsquo;s industry or jurisdiction affects future checks only —
        past results are never silently re-scored.
      </p>

      <H id="ai">5. AI-assisted analysis</H>
      <p>
        Analysis is produced with the assistance of a large language model. That has specific
        consequences you should plan around:
      </p>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>Output is decision support. It is informational, not a determination.</li>
        <li>
          Results can be wrong in both directions — a genuine breach can be missed, and a
          compliant document can be flagged.
        </li>
        <li>
          Where a rule cannot be evaluated from the data present, the finding is marked
          <em> uncertain</em> rather than guessed. Uncertainty is a real answer here.
        </li>
        <li>
          Applicability can depend on facts the platform does not have. A ruleset is a model of
          a regime, not the regime itself.
        </li>
        <li>
          Every finding cites the rule it relies on so you can verify it. Where a finding is
          legally material, verify the citation independently.
        </li>
      </ul>
      <p>
        Each result records the prompt version, model name and model version that produced it,
        so a past decision can be explained or re-derived.
      </p>

      <H id="responsibilities">6. Your responsibilities</H>
      <p>
        You decide which documents to upload and must have the rights and authority to do so,
        including any consent required from the people the documents describe. You are
        responsible for reviewing findings, for acting on them, and for your compliance
        obligations generally. Do not rely on a passing result as certification.
      </p>

      <H id="acceptable">7. Acceptable use</H>
      <p>
        Use the service for its intended purpose: analysing documents your organisation is
        entitled to process. Keep your credentials secure, and use API keys only within your own
        workspace.
      </p>

      <H id="prohibited">8. Prohibited activities</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>Uploading documents you have no right to process.</li>
        <li>Attempting to access another workspace, or another organisation&rsquo;s data.</li>
        <li>Probing, scanning or interfering with the service or its infrastructure.</li>
        <li>Circumventing entitlement, rate or access limits.</li>
        <li>Reselling or white-labelling the service without a written agreement.</li>
        <li>Using the service to break the law or to facilitate someone else doing so.</li>
      </ul>
      <p>
        We may suspend a workspace that does these things — see{" "}
        <a href="#suspension" className="text-brand-600 underline">
          Suspension
        </a>
        .
      </p>

      <H id="customer-data">9. Customer Data and ownership</H>
      <p>
        <strong className="text-ink">Customer Data is yours.</strong> Uploading a document does
        not transfer ownership of it to us. You grant us the limited right to process it for the
        purpose of providing the service you asked for — extraction, evaluation, reporting and
        the associated audit record — and for nothing else.
      </p>
      <p>
        We do not use your documents to train models of our own. Your documents are sent to
        Google&rsquo;s Gemini API to perform analysis; see the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>{" "}
        for who processes what.
      </p>
      <p>
        Aggregate, de-identified operational statistics — counts of checks, rule hit rates,
        error rates — may be used to operate and improve the service. These contain no document
        contents and identify no customer.
      </p>

      <H id="confidentiality">10. Confidentiality</H>
      <p>
        Each party will protect the other&rsquo;s confidential information with at least
        reasonable care and use it only to perform under these terms. This does not cover
        information that is public, already known, independently developed, or required to be
        disclosed by law.
      </p>

      <H id="ip">11. Intellectual property</H>
      <p>
        The service, its software, its rulesets and its documentation are ours. These terms grant
        you a limited, non-exclusive, non-transferable right to use the service while your
        account is in good standing. Reports generated about your documents are yours to use.
      </p>

      <H id="third-party">12. Third-party services</H>
      <p>
        The service runs on and integrates with third parties — cloud infrastructure, an AI API,
        an authentication provider, and payment providers. They are listed by name in the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>
        . Their availability and behaviour are outside our control.
      </p>

      <H id="security">13. Security</H>
      <p>
        We apply technical and organisational measures designed to protect the service: transport
        encryption, encryption at rest in our cloud provider&rsquo;s managed storage,
        authentication on every request, workspace-scoped authorisation enforced server-side,
        least-privilege service accounts, validation of uploads, secrets held in a managed secret
        store, and an append-only audit trail. No system is perfectly secure, and we make no
        absolute guarantee.
      </p>

      <H id="availability">14. Service availability</H>
      <p>
        We aim to keep the service available and to give notice of planned maintenance where
        practical. <strong className="text-ink">There is no service level agreement.</strong> We
        do not currently commit to an uptime percentage, and you should not rely on one.
      </p>

      <H id="fees">15. Plans, fees and entitlements</H>
      <p>Current prices are shown on the billing page in the application. There are three:</p>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Free</strong> — every new workspace receives{" "}
          <strong className="text-ink">one report</strong>, with no payment details required.
        </li>
        <li>
          <strong className="text-ink">Single report</strong> — a one-time purchase adding{" "}
          <strong className="text-ink">one</strong> report to your allowance. It does not
          renew and there is nothing to cancel.
        </li>
        <li>
          <strong className="text-ink">Pro</strong> — a monthly subscription providing a
          recurring allowance of reports for each billing period.
        </li>
      </ul>
      <p>
        Allowance is per workspace and is consumed when a check is <em>generated</em>, not when a
        document is uploaded. You can upload documents whenever you like; analysing one requires
        available allowance. Purchases are additive: buying while you still hold an unused free
        report keeps both. Unused allowance from a Pro period does not carry into the next
        period.
      </p>
      <p>
        Payment is taken by our payment providers. Card details never reach our servers and we do
        not store them.
      </p>

      <H id="renewal">16. Renewal and cancellation</H>
      <p>
        A Pro subscription renews automatically each month until cancelled. Cancel at any time
        from the billing page; cancellation stops future charges and your access continues to the
        end of the period you have already paid for. A single report purchase does not renew. See
        the{" "}
        <Link to="/refunds" className="text-brand-600 underline">
          Refund and Cancellation Policy
        </Link>
        .
      </p>

      <H id="refunds">17. Refunds</H>
      <p>
        Refund terms are set out in full in the{" "}
        <Link to="/refunds" className="text-brand-600 underline">
          Refund and Cancellation Policy
        </Link>
        , which forms part of these terms. Nothing in it limits rights you have under applicable
        consumer law that cannot be waived.
      </p>

      <H id="suspension">18. Suspension</H>
      <p>
        We may suspend a workspace&rsquo;s access where there is abuse, a breach of these terms, a
        payment problem, a security concern, or a legal requirement. Suspension is recorded with
        a reason and that reason is shown to you when you sign in.
      </p>
      <p>
        <strong className="text-ink">Suspension affects access, not records.</strong> Your
        documents, checks and audit trail are preserved unchanged and are available again on
        restoration. We aim to suspend no more broadly, and for no longer, than the cause
        requires.
      </p>

      <H id="termination">19. Termination and data export</H>
      <p>
        You may stop using the service at any time and ask us to delete your data. We may
        terminate for material breach, or where required by law. Before termination takes effect
        you may export your data; contact <Mail /> and we will provide it in a machine-readable
        format.
      </p>

      <H id="retention">20. Data retention</H>
      <p>
        Documents and checks are kept according to your workspace&rsquo;s retention setting. The
        default is to keep them indefinitely; if you set a retention period, the minimum is 30
        days. The audit trail is append-only and is not deleted — deletions are recorded as new
        entries rather than by removing old ones. Details are in the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>
        .
      </p>

      <H id="disclaimers">21. Disclaimers</H>
      <p>
        The service is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo;. To the extent
        permitted by law we disclaim implied warranties of merchantability, fitness for a
        particular purpose and non-infringement. We do not warrant that the service will be
        uninterrupted, error-free, or that findings will be complete or accurate.
      </p>

      <H id="no-guarantee">22. No legal advice, no guarantee of compliance</H>
      <p>
        {LEGAL.brand} is a compliance automation and decision-support platform. It is not a law
        firm, not a legal adviser, and not a certification body. A report is not a certificate,
        an audit opinion, or evidence of regulatory approval. It does not guarantee that you are
        compliant with any law or standard, and it is not a defence to a regulatory finding.
        Obtain qualified professional advice where the stakes warrant it.
      </p>

      <H id="liability">23. Limitation of liability</H>
      <p>
        To the extent permitted by law, neither party is liable for indirect, incidental, special
        or consequential loss, or for lost profits, revenue or data. Our total aggregate
        liability for all claims relating to the service is limited to the amount you paid us in
        the twelve months before the event giving rise to the claim. Nothing here limits
        liability that cannot lawfully be limited.
      </p>

      <H id="indemnity">24. Indemnification</H>
      <p>
        You will defend and indemnify us against third-party claims arising from your Customer
        Data, from your lack of rights to upload it, or from your use of the service in breach of
        these terms.
      </p>

      <H id="law">25. Governing law and disputes</H>
      <p>
        These terms are governed by the laws of {LEGAL.governingLaw}, and the courts of{" "}
        {LEGAL.governingLaw} have jurisdiction. Before starting proceedings, contact <Mail /> so
        we can try to resolve the matter directly.
      </p>

      <H id="changes">26. Changes, notices and contact</H>
      <p>
        We may update these terms. Material changes will be notified to the email address on your
        account before they take effect, and the version and effective date at the top of this
        page will change. Continuing to use the service after that constitutes acceptance.
        Notices to us go to <Mail />.
      </p>

      <H id="general">27. Severability and entire agreement</H>
      <p>
        If any provision is held unenforceable, the rest remains in force. These terms, together
        with the Privacy Policy and the Refund and Cancellation Policy, are the entire agreement
        between us about the service and supersede earlier discussions. Failure to enforce a
        provision is not a waiver of it. You may not assign these terms without our consent.
      </p>
    </Page>
  );
}

// ========================================================== PRIVACY

const PRIVACY_TOC = [
  { id: "scope", label: "Scope and roles" },
  { id: "collect", label: "What we collect" },
  { id: "inventory", label: "Data inventory" },
  { id: "use", label: "How we use it" },
  { id: "grounds", label: "Grounds for processing" },
  { id: "ai-processing", label: "AI and automated processing" },
  { id: "processors", label: "Who else processes your data" },
  { id: "transfers", label: "International transfers" },
  { id: "security", label: "Security" },
  { id: "retention", label: "Retention and deletion" },
  { id: "rights", label: "Your rights" },
  { id: "grievance", label: "Complaints" },
  { id: "children", label: "Children" },
  { id: "marketing", label: "Marketing" },
  { id: "cookies", label: "Cookies and local storage" },
  { id: "changes", label: "Changes and contact" },
];

export function PrivacyPage() {
  return (
    <Page
      title="Privacy Policy"
      contents={PRIVACY_TOC}
      intro={
        <p>
          This policy explains what {LEGAL.brand} collects, why, who else touches it, and what you
          can ask us to do about it. It applies to the service at {LEGAL.siteUrl} and to
          everything uploaded to it.
        </p>
      }
    >
      <H id="scope">1. Scope and roles</H>
      <p>
        For your account and usage data we decide the purposes and means, and act accordingly. For
        the documents you upload, you decide what to send and why — we process them on your
        instruction to provide the service. If your organisation needs a separate data processing
        agreement, contact <Mail />; we do not publish one yet and will not pretend otherwise.
      </p>

      <H id="collect">2. What we collect</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Account</strong> — email, optional name and job title,
          business name, and the industry and jurisdiction you select.
        </li>
        <li>
          <strong className="text-ink">Documents</strong> — the files you upload and the fields
          extracted from them. These can contain personal data; you choose what to send.
        </li>
        <li>
          <strong className="text-ink">Compliance records</strong> — findings, risk scores,
          reviewer decisions and comments.
        </li>
        <li>
          <strong className="text-ink">Activity</strong> — uploads, checks, decisions, plan
          changes and administrative actions, written to an append-only audit trail. This is a
          product feature, not analytics: the service&rsquo;s promise is that every compliance
          decision is traceable.
        </li>
        <li>
          <strong className="text-ink">Support</strong> — what you send us when you get in touch.
        </li>
      </ul>
      <p>
        We do not collect or store card details. Those go directly to the payment provider and
        never reach our servers.
      </p>

      <H id="inventory">3. Data inventory</H>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line text-left text-[12px] uppercase tracking-wide text-muted">
              <th className="py-2 pr-3">Data</th>
              <th className="py-2 pr-3">Purpose</th>
              <th className="py-2 pr-3">Retention</th>
              <th className="py-2">Processor</th>
            </tr>
          </thead>
          <tbody className="align-top">
            {[
              ["Email, name", "Authentication, service notices", "While the account exists", "Firebase Auth"],
              ["Business, industry, jurisdiction", "Selecting the applicable ruleset", "While the account exists", "Firestore"],
              ["Uploaded documents", "Producing the analysis you requested", "Per your retention setting", "Cloud Storage, Gemini API"],
              ["Extracted fields", "Rule evaluation", "Per your retention setting", "Firestore, Gemini API"],
              ["Findings, risk scores", "The report you asked for", "Per your retention setting", "Firestore"],
              ["Audit trail", "Traceability of every decision", "Not deleted", "BigQuery"],
              ["Payment confirmation", "Granting your entitlement", "As required for records", "Razorpay"],
            ].map((r) => (
              <tr key={r[0]} className="border-b border-line last:border-0">
                <td className="py-2 pr-3 font-medium text-ink">{r[0]}</td>
                <td className="py-2 pr-3">{r[1]}</td>
                <td className="py-2 pr-3">{r[2]}</td>
                <td className="py-2">{r[3]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <H id="use">4. How we use it</H>
      <p>
        To operate the service: authenticate you, analyse the documents you submit, produce
        reports, route high-risk results for review, maintain the audit trail, take payment,
        provide support, keep the service secure, and meet legal obligations. We do not sell your
        data. We do not use your documents to train models of our own, and we do not use them for
        any purpose other than providing the service you asked for.
      </p>

      <H id="grounds">5. Grounds for processing</H>
      <p>
        We process account and usage data to perform our contract with you, and to pursue our
        legitimate interest in operating and securing the service. Documents are processed on
        your instruction. Where consent is the applicable ground — for example marketing — we ask
        for it separately and you can withdraw it at any time. Which framework applies depends on
        where you are; if you need this stated for a specific regime, ask.
      </p>

      <H id="ai-processing">6. AI and automated processing</H>
      <p>
        Documents are sent to Google&rsquo;s Gemini API to extract fields and produce findings.
        This is how the product works and cannot be switched off while using it.
      </p>
      <p>
        Results are produced automatically, but the design deliberately keeps a person in the
        loop for consequential outcomes: high-risk results are escalated to a human reviewer in
        your workspace rather than being finalised by the system, findings that cannot be
        determined are marked uncertain rather than guessed, and every result records the prompt
        and model version that produced it so it can be explained afterwards.
      </p>

      <H id="processors">7. Who else processes your data</H>
      <p>Named specifically, because a generic list of &ldquo;trusted partners&rdquo; tells you nothing:</p>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Google Cloud Platform</strong> — hosting, file storage,
          database and the audit trail.
        </li>
        <li>
          <strong className="text-ink">Google Gemini API</strong> — extraction and analysis of
          document contents.
        </li>
        <li>
          <strong className="text-ink">Firebase Authentication</strong> — sign-in and identity.
        </li>
        <li>
          <strong className="text-ink">Razorpay</strong> — payment processing.
        </li>
        <li>
          <strong className="text-ink">Slack</strong> — only if you configure it, and only to
          deliver escalation notifications you asked for.
        </li>
      </ul>

      <H id="transfers">8. International transfers</H>
      <p>
        The service runs in Google Cloud&rsquo;s United States regions, so data you upload is
        stored and processed there regardless of where you are. If your obligations require data
        to remain in a particular country, this service does not currently meet that requirement
        and you should tell us before uploading.
      </p>

      <H id="security">9. Security</H>
      <p>
        Access requires authentication, and every request is scoped to your workspace by the
        server rather than by the browser. Service accounts hold least privilege — the account
        that writes the audit trail has no permission to run the job type that could modify or
        delete rows, so the trail cannot be rewritten by application code. Uploads are validated
        before processing. Secrets are held in a managed secret store, never in source. We will
        tell you promptly if we become aware of a breach affecting your data. No system is
        perfectly secure and we claim no certification.
      </p>

      <H id="retention">10. Retention and deletion</H>
      <p>
        Documents and checks follow your workspace&rsquo;s retention setting. The default is to
        keep them indefinitely; if you choose a period, the minimum is 30 days. You can request
        deletion at any time.
      </p>
      <p>
        The audit trail is append-only and is not deleted. That is deliberate — a trail that can
        be erased is not a trail. When documents are deleted, the deletion itself is recorded as
        a new entry rather than by removing the old ones. Audit records identify actions and
        actors, not document contents.
      </p>

      <H id="rights">11. Your rights</H>
      <p>
        You can ask us to access, correct, export or delete your personal data, to explain how a
        particular result was produced, and to withdraw consent where consent is the ground.
        Write to <Mail /> and we will respond within {LEGAL.dataRequestTarget}. Depending on where
        you are, you may have rights under India&rsquo;s DPDP Act, the GDPR, or other applicable
        law; we will honour the rights that apply to you rather than a generic list.
      </p>

      <H id="grievance">12. Complaints</H>
      <p>
        If you are unhappy with how we have handled your data, contact <Mail /> with
        &ldquo;Privacy&rdquo; in the subject and we will investigate. You may also complain to the
        supervisory authority in your jurisdiction. We have not appointed a named grievance
        officer and do not claim to have one.
      </p>

      <H id="children">13. Children</H>
      <p>
        The service is for businesses and is not directed at anyone under 18. We do not knowingly
        collect data directly from children. Documents you upload may describe individuals of any
        age; you are responsible for having the authority to send them.
      </p>

      <H id="marketing">14. Marketing</H>
      <p>
        We send service messages — security notices, billing, and changes to these documents —
        because they are part of running your account. Any marketing email is separate, requires
        your consent, and can be stopped at any time. We do not pre-tick consent boxes.
      </p>

      <H id="cookies">15. Cookies and local storage</H>
      <p>
        The application uses browser storage strictly to keep you signed in and to remember
        interface preferences such as whether the sidebar is collapsed. There is no advertising
        tracker, no analytics pixel and no session replay, which is why you are not being shown a
        cookie consent banner — there is nothing non-essential to consent to. If that changes, we
        will ask before setting anything.
      </p>

      <H id="changes">16. Changes and contact</H>
      <p>
        We may update this policy; the version and effective date at the top will change and
        material changes will be notified to your account email. Questions: <Mail />.
      </p>
    </Page>
  );
}

// ================================================ REFUNDS & CANCELLATION

const REFUND_TOC = [
  { id: "before", label: "Try before you pay" },
  { id: "what", label: "What you are buying" },
  { id: "single", label: "Single report" },
  { id: "pro", label: "Pro subscription" },
  { id: "cancel", label: "Cancellation" },
  { id: "failures", label: "Failures and duplicates" },
  { id: "how", label: "How to request a refund" },
  { id: "processing", label: "How refunds are processed" },
  { id: "rights", label: "Your consumer rights" },
];

export function RefundsPage() {
  return (
    <Page
      title="Refund and Cancellation Policy"
      contents={REFUND_TOC}
      intro={
        <p>
          Plain terms, so you know before you pay. The price shown in the application is the price
          charged. There are no setup fees and no hidden charges.
        </p>
      }
    >
      <H id="before">1. Try before you pay</H>
      <p>
        Every new workspace gets <strong className="text-ink">one report at no cost</strong>, with
        no payment details required. We would rather you see the output before buying anything.
      </p>

      <H id="what">2. What you are buying</H>
      <p>
        Both paid options buy <strong className="text-ink">report allowance</strong>. Allowance is
        consumed when a compliance check is generated, not when a document is uploaded — you can
        upload freely, and only analysis draws on it. Purchases are additive: buying while you
        still hold an unused free report keeps both.
      </p>

      <H id="single">3. Single report</H>
      <p>
        A one-time purchase adding one report. It does not renew and there is nothing to cancel.
      </p>
      <p>
        Because it is delivered as soon as the check completes, it is{" "}
        <strong className="text-ink">not refundable once you have received the result</strong>.
        Before it is used, it is refundable in full.
      </p>

      <H id="pro">4. Pro subscription</H>
      <p>
        Billed monthly, providing a recurring report allowance for each period. Unused allowance
        does not carry into the next period.
      </p>
      <p>
        <strong className="text-ink">Full refund within 7 days</strong> of a charge if you have
        run no checks in that period. If you have used the service in the period, that period is
        not refundable — but you can cancel to prevent the next one. Cancelling does not
        retroactively refund a period you have already used.
      </p>

      <H id="cancel">5. Cancellation</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Pro</strong> — cancel any time from the billing page.
          Cancellation stops future charges; access and remaining allowance continue to the end of
          the period you have paid for. There is no cancellation fee.
        </li>
        <li>
          <strong className="text-ink">Single report</strong> — nothing recurring exists, so there
          is nothing to cancel. Refund eligibility is in section 3.
        </li>
        <li>
          <strong className="text-ink">Your account</strong> — you can stop using the service and
          ask us to delete your data at any time. Closing an account does not by itself refund a
          period already paid for.
        </li>
      </ul>

      <H id="failures">6. Failures and duplicates</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">The check fails</strong> — we cannot process your document,
          or the system errors before producing a result: <strong className="text-ink">full
          refund</strong>, and the allowance is returned automatically. You should not pay for a
          report you did not receive.
        </li>
        <li>
          <strong className="text-ink">Payment succeeded but allowance was not granted</strong> —
          tell us and we will either grant it or refund in full, whichever you prefer.
        </li>
        <li>
          <strong className="text-ink">Duplicate charge</strong> — refunded in full, regardless of
          the timeframes above.
        </li>
        <li>
          <strong className="text-ink">Payment failed</strong> — no allowance is granted and no
          charge should settle. If your statement shows one, contact us.
        </li>
      </ul>

      <H id="how">7. How to request a refund</H>
      <p>
        Email <Mail /> from your account address with the payment reference. We respond within{" "}
        {LEGAL.refundTarget}.
      </p>

      <H id="processing">8. How refunds are processed</H>
      <p>
        Refunds are returned to the original payment method through the payment provider that took
        the payment. How long the money takes to appear depends on that provider, your payment
        method and your bank — typically several business days. We cannot guarantee a specific
        credit date because that step is not ours.
      </p>

      <H id="rights">9. Your consumer rights</H>
      <p>
        Nothing in this policy limits rights you have under applicable consumer law that cannot be
        waived by agreement. Where such a right conflicts with anything above, the right applies.
      </p>
    </Page>
  );
}

// ========================================================== CONTACT

const CONTACT_TOC = [
  { id: "how", label: "How to reach us" },
  { id: "include", label: "What to include" },
  { id: "security", label: "Security reports" },
  { id: "privacy", label: "Privacy and data requests" },
  { id: "billing", label: "Billing and refunds" },
];

export function ContactPage() {
  return (
    <Page
      title="Contact Us"
      contents={CONTACT_TOC}
      intro={
        <p>
          Have a question about {LEGAL.brand}? Send it over and we will get back to you. Email is
          the fastest route to a person — we do not run a phone line, and saying so is more useful
          than publishing a number nobody answers.
        </p>
      }
    >
      <H id="how">1. How to reach us</H>
      <div className="rounded-lg border border-line bg-surface-2 p-5">
        <dl className="space-y-3 text-[13.5px]">
          <div>
            <dt className="font-semibold text-ink">Email</dt>
            <dd>
              <Mail />
            </dd>
          </div>
          <div>
            <dt className="font-semibold text-ink">Service</dt>
            <dd>{LEGAL.brand}</dd>
          </div>
          <div>
            <dt className="font-semibold text-ink">Operating from</dt>
            <dd>{LEGAL.governingLaw}</dd>
          </div>
          <div>
            <dt className="font-semibold text-ink">Response target</dt>
            <dd>
              {LEGAL.supportTarget}; refund requests {LEGAL.refundTarget}. These are targets we aim
              at, not a contractual service level.
            </dd>
          </div>
        </dl>
      </div>

      <H id="include">2. What to include</H>
      <p>
        For a question about a specific result, send the check reference from your audit log. For
        a billing question, include the payment reference from your provider. Either lets us
        answer without asking you to send documents by email.
      </p>

      <H id="security">3. Security reports</H>
      <p>
        If you believe you have found a vulnerability, email <Mail /> with
        &ldquo;Security&rdquo; in the subject. We will acknowledge within {LEGAL.supportTarget}.
        Please do not test against other customers&rsquo; workspaces, and please give us a
        reasonable chance to fix an issue before disclosing it.
      </p>

      <H id="privacy">4. Privacy and data requests</H>
      <p>
        Access, export, correction and deletion requests go to the same address with
        &ldquo;Privacy&rdquo; in the subject, and are answered within {LEGAL.dataRequestTarget}.
        See the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>{" "}
        for what we hold and why.
      </p>

      <H id="billing">5. Billing and refunds</H>
      <p>
        Refund requests and billing questions are covered by the{" "}
        <Link to="/refunds" className="text-brand-600 underline">
          Refund and Cancellation Policy
        </Link>
        . Email from your account address with the payment reference.
      </p>
    </Page>
  );
}
