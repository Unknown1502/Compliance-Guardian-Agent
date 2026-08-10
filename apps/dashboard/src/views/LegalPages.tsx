/**
 * Public policy pages: Terms, Privacy, Refunds, Contact.
 *
 * These exist for two reasons and both are real. Payment providers
 * (Razorpay, PayPal) will not activate a merchant account without them —
 * a website review checking for exactly these four is the most common place
 * a SaaS activation stalls. And a compliance product that has no published
 * terms of its own is a bad look for the thing it claims to sell.
 *
 * Written to describe what this system actually does, not from a template:
 * documents really are sent to Google's Gemini API, the audit trail really
 * is append-only, retention really has a 30-day floor. A policy that
 * describes a different product is worse than none, because it is a false
 * statement rather than a missing one.
 *
 * NOT legal advice, and deliberately says so on the page. For a product that
 * sells compliance checking, the distinction between "software that cites
 * rules" and "advice" is the single most important thing to state plainly.
 */

import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { LEGAL, LEGAL_ROUTES } from "../lib/legal";

const SUPPORT_EMAIL = LEGAL.supportEmail;

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-2 hover:text-ink"
          >
            <ArrowLeft size={14} />
            ComplianceGuardian
          </Link>
          <span className="text-[12px] text-muted">
            v{LEGAL.version} · Effective {LEGAL.effectiveDate} · Updated {LEGAL.lastUpdated}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="text-[26px] font-bold tracking-tight text-ink">{title}</h1>
        <div className="mt-8 space-y-7 text-[14px] leading-relaxed text-ink-2">{children}</div>
      </main>

      <footer className="border-t border-line py-8">
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

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="pt-2 text-[16px] font-semibold text-ink">{children}</h2>;
}

/** Stated on every page that could be mistaken for advice. */
function NotAdvice() {
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-4 text-[13px]">
      <strong className="font-semibold text-ink">ComplianceGuardian is software, not an adviser.</strong>{" "}
      It checks documents against published rules and shows you which rule each finding
      cites, so you can verify it yourself. It does not provide legal, financial, or
      regulatory advice, and its output is not a substitute for a qualified professional
      or for your own review. You remain responsible for your compliance obligations.
    </div>
  );
}

// ---------------------------------------------------------------- Terms

export function TermsPage() {
  return (
    <Page title="Terms of Service">
      <p>
        These terms govern your use of {LEGAL.brand}, the compliance-analysis service
        available at {LEGAL.siteUrl}. By creating an account you agree to them. Where these
        terms say &ldquo;we&rdquo; or &ldquo;us&rdquo;, they mean {LEGAL.brand}; where they say
        &ldquo;you&rdquo;, they mean the organisation whose workspace is being used.
      </p>

      <NotAdvice />

      <H>What the service does</H>
      <p>
        ComplianceGuardian is a web application. You upload documents; the service extracts
        their contents, checks them against a versioned ruleset chosen for your industry and
        jurisdiction, and returns a risk score with findings that cite the specific rules
        applied. Every check is recorded in an append-only audit trail belonging to your
        workspace.
      </p>
      <p>
        Rulesets are published as versioned files. Each completed check records the exact
        ruleset version applied at the time, and changing your workspace's industry or
        jurisdiction affects future checks only — past results are never silently
        re-scored.
      </p>

      <H>Accounts and your workspace</H>
      <p>
        You are responsible for your account credentials and for the actions of people you
        invite to your workspace. Your data is isolated to your workspace; we do not expose
        one customer's documents, checks, or audit records to another.
      </p>

      <H>Acceptable use</H>
      <p>
        Do not upload documents you have no right to process, attempt to access another
        workspace, interfere with the service's operation, or use the service to break the
        law. We may suspend an account that does these things.
      </p>

      <H>Accuracy and limits</H>
      <p>
        Checks are produced with the assistance of a large language model and can be wrong.
        They may miss a genuine breach or flag something that is not one. That is why every
        finding cites the rule it relies on, why high-risk checks are routed to a human
        reviewer, and why the audit trail records who decided what. Do not treat a passing
        result as certification that a document is compliant.
      </p>
      <p>
        The service is provided as-is. To the extent permitted by law, our liability for any
        claim relating to the service is limited to the amount you paid us in the twelve
        months before the claim.
      </p>

      <H>Fees</H>
      <p>
        Current prices are shown on the billing page inside the application. Your first
        audit is free. Paid plans are charged in advance through our payment providers; we
        never see or store your card details. See our{" "}
        <Link to="/refunds" className="text-brand-600 underline">
          Refund and Cancellation Policy
        </Link>
        .
      </p>

      <H>Ending your use</H>
      <p>
        You may stop using the service and request deletion of your data at any time. Some
        records are retained where we are required to keep them; see the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>{" "}
        for what that means in practice.
      </p>

      <H>Governing law</H>
      <p>
        These terms are governed by the laws of {LEGAL.governingLaw}, and the courts of{" "}
        {LEGAL.governingLaw} have jurisdiction over any dispute arising from them.
      </p>

      <H>Changes</H>
      <p>
        We may update these terms. Material changes will be notified to the email address on
        your account before they take effect.
      </p>
    </Page>
  );
}

// -------------------------------------------------------------- Privacy

export function PrivacyPage() {
  return (
    <Page title="Privacy Policy">
      <p>
        This policy explains what {LEGAL.brand} collects, why, and who else touches it. It
        applies to the service at {LEGAL.siteUrl} and to everything you upload to it.
      </p>

      <H>What we collect</H>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Account details</strong> — your email address, name or
          job title if you provide one, your business name, and the industry and jurisdiction
          you select.
        </li>
        <li>
          <strong className="text-ink">Documents you upload</strong> — the files themselves and
          the fields extracted from them.
        </li>
        <li>
          <strong className="text-ink">Activity records</strong> — uploads, checks, reviewer
          decisions, plan changes and administrative actions, written to an append-only audit
          trail. This is a core feature, not analytics: the product's promise is that every
          compliance decision is traceable.
        </li>
      </ul>
      <p>
        We do not collect or store payment card details. Card data goes directly to our
        payment providers and never reaches our servers.
      </p>

      <H>Who else processes your data</H>
      <p>
        Being specific about this matters more than a generic list of "trusted partners":
      </p>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-ink">Google Cloud Platform</strong> — hosting, file storage,
          database and the audit trail. Data is held in Google's United States regions.
        </li>
        <li>
          <strong className="text-ink">Google Gemini API</strong> — the contents of documents
          you upload are sent to Google's Gemini API to extract fields and produce compliance
          findings. This is how the product works; you cannot use the service without it.
        </li>
        <li>
          <strong className="text-ink">Firebase Authentication</strong> — sign-in and identity.
        </li>
        <li>
          <strong className="text-ink">Razorpay and PayPal</strong> — payment processing. They
          receive what they need to take a payment; we receive confirmation that one
          succeeded.
        </li>
        <li>
          <strong className="text-ink">Slack</strong> — only if you configure it, and only to
          send escalation notifications.
        </li>
      </ul>
      <p>
        We do not sell your data, and we do not use your documents to train models of our
        own.
      </p>

      <H>How long we keep it</H>
      <p>
        Documents and checks are retained according to your workspace's retention setting,
        with a minimum of 30 days. You can request deletion of your documents at any time.
      </p>
      <p>
        The audit trail is append-only and is not deleted. That is deliberate: an audit trail
        that can be erased is not an audit trail. When you delete documents, the deletion
        itself is recorded as a new entry rather than by removing the old ones. Audit records
        identify actions and actors, not the contents of your documents.
      </p>

      <H>Your rights</H>
      <p>
        You can ask us to access, correct, export or delete your personal data, and to
        explain how a particular check was produced. Write to{" "}
        <a href={`mailto:${SUPPORT_EMAIL}`} className="text-brand-600 underline">
          {SUPPORT_EMAIL}
        </a>{" "}
        and we will respond within 30 days. Depending on where you are, you may also have
        rights under the DPDP Act (India), the GDPR (EU/UK), or other applicable law.
      </p>

      <H>Security</H>
      <p>
        Access requires authentication, and every request is scoped to your own workspace by
        the server rather than by the browser. Uploads are scanned and validated before
        processing. Secrets and credentials are held in a managed secret store, never in our
        source code. No system is perfectly secure, and we will tell you promptly if we
        become aware of a breach affecting your data.
      </p>

      <H>Children</H>
      <p>The service is for businesses and is not directed at anyone under 18.</p>

      <H>Contact</H>
      <p>
        Questions about this policy:{" "}
        <a href={`mailto:${SUPPORT_EMAIL}`} className="text-brand-600 underline">
          {SUPPORT_EMAIL}
        </a>
        .
      </p>
    </Page>
  );
}

// -------------------------------------------------------------- Refunds

export function RefundsPage() {
  return (
    <Page title="Refund and Cancellation Policy">
      <p>
        Plain terms, so you know before you pay. Prices shown in the application are the
        prices charged; there are no setup fees and no hidden charges.
      </p>

      <H>Try it before paying</H>
      <p>
        Your first compliance check is free and requires no payment details. We would rather
        you see the output before you buy anything.
      </p>

      <H>Monthly subscription</H>
      <p>
        Cancel at any time from the billing page. Cancellation stops future charges; your
        plan stays active until the end of the period you have already paid for.
      </p>
      <p>
        <strong className="text-ink">Full refund within 7 days</strong> of a subscription
        charge if you have not run any compliance checks in that period. If you have used the
        service, that billing period is not refundable, but you can still cancel to prevent
        the next one.
      </p>

      <H>Single audit</H>
      <p>
        A single audit is delivered as soon as the check completes, so it is{" "}
        <strong className="text-ink">not refundable once you have received the result</strong>
        .
      </p>
      <p>
        <strong className="text-ink">If the check fails</strong> — we cannot process your
        document, or the system errors before producing a result — you get a{" "}
        <strong className="text-ink">full refund</strong>. You should not pay for an audit
        you did not receive.
      </p>

      <H>How to request one</H>
      <p>
        Email{" "}
        <a href={`mailto:${SUPPORT_EMAIL}`} className="text-brand-600 underline">
          {SUPPORT_EMAIL}
        </a>{" "}
        from your account address with the payment reference. We respond within 3 business
        days. Approved refunds are returned to the original payment method within 5–7
        business days, subject to your payment provider's processing time.
      </p>

      <H>Duplicate or unauthorised charges</H>
      <p>
        Contact us and we will refund a genuine duplicate charge in full, regardless of the
        timeframes above.
      </p>
    </Page>
  );
}

// -------------------------------------------------------------- Contact

export function ContactPage() {
  return (
    <Page title="Contact Us">
      <p>
        {LEGAL.brand} is a compliance-analysis service operating from {LEGAL.governingLaw}. The
        fastest route to a person is email — we do not run a phone line, and saying so is more
        useful than publishing a number nobody answers.
      </p>

      <div className="rounded-lg border border-line bg-surface-2 p-5">
        <dl className="space-y-3 text-[13.5px]">
          <div>
            <dt className="font-semibold text-ink">Email</dt>
            <dd>
              <a href={`mailto:${SUPPORT_EMAIL}`} className="text-brand-600 underline">
                {SUPPORT_EMAIL}
              </a>
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
              {LEGAL.supportTarget}. Refund requests {LEGAL.refundTarget}. These are targets we
              aim at, not a contractual service level.
            </dd>
          </div>
        </dl>
      </div>

      <H>What to include</H>
      <p>
        For anything about a specific check, send us the check reference from your audit log.
        For a billing question, include the payment reference from your provider. Both let us
        answer without asking you to send documents by email.
      </p>

      <H>Security issues</H>
      <p>
        If you believe you have found a vulnerability, email the address above with
        "Security" in the subject line. We will acknowledge within 2 business days. Please do
        not test against other customers' workspaces.
      </p>

      <H>Data requests</H>
      <p>
        Access, export, correction and deletion requests go to the same address and are
        answered within 30 days. See the{" "}
        <Link to="/privacy" className="text-brand-600 underline">
          Privacy Policy
        </Link>
        .
      </p>
    </Page>
  );
}
