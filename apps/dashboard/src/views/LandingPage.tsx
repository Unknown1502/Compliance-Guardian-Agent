import { Link } from "react-router-dom";
import {
  ShieldCheck,
  ArrowRight,
  UploadCloud,
  ScanSearch,
  UserCheck,
  CheckCircle2,
  XCircle,
  Lock,
  Database,
  ScrollText,
  Cpu,
  Cloud,
  Flame,
} from "lucide-react";

const NAV_LINKS = [
  { href: "#product", label: "Product" },
  { href: "#security", label: "Security" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

const STEPS = [
  {
    icon: UploadCloud,
    title: "Upload a document",
    body: "A service record, invoice, or policy form. PDF, text, CSV, or image.",
  },
  {
    icon: ScanSearch,
    title: "Gemini extracts and reasons",
    body: "Structured fields are extracted, then evaluated against your active ruleset — every rule, every time, with a plain-language explanation for each.",
  },
  {
    icon: UserCheck,
    title: "Auto-approve or escalate",
    body: "Low-risk items clear automatically. High-risk items route to a human reviewer with full context. Every decision is written to an append-only trail.",
  },
];

const SAMPLE = [
  { rule: "Consent documentation", pass: false },
  { rule: "Incident reporting window", pass: false },
  { rule: "Worker screening check", pass: false },
  { rule: "Data retention period", pass: true },
];

const SECURITY_POINTS = [
  {
    icon: Lock,
    title: "Tenant isolation is structural, not conventional",
    body: "tenant_id is sourced only from the verified Firebase Auth token — never from a request body or query parameter. There is no code path where one tenant can address another's data.",
  },
  {
    icon: Database,
    title: "The audit trail cannot be altered",
    body: "The runtime service account holds a custom BigQuery role with write access but no query-job permission — UPDATE, DELETE, and MERGE are impossible at the IAM layer, regardless of application code.",
  },
  {
    icon: ScrollText,
    title: "Every AI decision is reproducible",
    body: "Each risk score is stored with the exact prompt version, model name, and model version that produced it, so any historical decision can be explained or re-derived.",
  },
];

const FAQ = [
  {
    q: "What happens to documents I upload?",
    a: "Raw files are stored in Cloud Storage under your tenant, encrypted at rest. Extracted fields and decisions live in Firestore. Nothing is shared across tenants — every query is scoped by the tenant_id in your verified session token.",
  },
  {
    q: "Can the risk score be wrong?",
    a: "Gemini's reasoning can be uncertain, and the system is built around that: when a rule can't be confidently evaluated from the extracted data, it's marked 'uncertain,' not guessed. Uncertain and failing rules both route to a human reviewer above your risk threshold.",
  },
  {
    q: "What rulesets are supported today?",
    a: "NDIS and aged care compliance for Australian providers, plus data privacy rulesets for 11 jurisdictions. Every ruleset is a single versioned YAML file, validated on load — adding a new one is a content change, not a code change.",
  },
  {
    q: "Do you fabricate compliance rules?",
    a: "No. Every rule cites its source law in the ruleset file. Where a law itself sets no fixed deadline, the ruleset says so explicitly instead of inventing a number. This is a compliance product — a fabricated rule would be a liability, not a feature.",
  },
];

function Logo({ tone = "ink" }: { tone?: "ink" | "white" }) {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white">
        <ShieldCheck size={17} strokeWidth={2.5} />
      </div>
      <span
        className={`text-[15px] font-bold tracking-tight ${tone === "white" ? "text-white" : "text-ink"}`}
      >
        ComplianceGuardian
      </span>
    </Link>
  );
}

function Section({
  id,
  eyebrow,
  title,
  subtitle,
  children,
  surface = "bg",
}: {
  id?: string;
  eyebrow?: string;
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
  surface?: "bg" | "surface-2";
}) {
  return (
    <section id={id} className={`${surface === "surface-2" ? "bg-surface-2" : "bg-bg"} py-24`}>
      <div className="mx-auto max-w-container px-6">
        <div className="mx-auto max-w-2xl text-center">
          {eyebrow && <p className="eyebrow text-brand-700">{eyebrow}</p>}
          <h2 className="mt-3 text-section font-bold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-4 text-body text-ink-2">{subtitle}</p>}
        </div>
        {children}
      </div>
    </section>
  );
}

export function LandingPage() {
  return (
    <div className="bg-bg">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-container items-center justify-between px-6">
          <Logo />
          <nav className="hidden items-center gap-8 md:flex">
            {NAV_LINKS.map((n) => (
              <a
                key={n.href}
                href={n.href}
                className="text-[14px] font-medium text-ink-2 transition-colors hover:text-ink"
              >
                {n.label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="text-[14px] font-medium text-ink-2 transition-colors hover:text-ink"
            >
              Sign in
            </Link>
            <Link
              to="/signup"
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-[14px] font-semibold text-white shadow-soft transition-colors hover:bg-brand-700"
            >
              Start free
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="border-b border-line py-24">
        <div className="mx-auto max-w-container px-6">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="text-hero font-bold tracking-tight text-ink">
              Compliance automation that never compromises accountability.
            </h1>
            <p className="mx-auto mt-6 max-w-xl text-body text-ink-2">
              Upload contracts, invoices, policies, or compliance documents. Gemini analyzes
              every document, cites the applicable rules, calculates risk, and routes high-risk
              findings to human reviewers — creating a complete, immutable audit trail.
            </p>
            <div className="mt-8 flex items-center justify-center gap-3">
              <Link
                to="/signup"
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-5 py-2.5 text-[14px] font-semibold text-white shadow-soft transition-colors hover:bg-brand-700"
              >
                Start free
                <ArrowRight size={15} />
              </Link>
              <a
                href="#product"
                className="inline-flex items-center rounded-lg border border-line px-5 py-2.5 text-[14px] font-semibold text-ink transition-colors hover:bg-surface-2"
              >
                See how it works
              </a>
            </div>
          </div>

          {/* Real product preview — an actual result, not an illustration. */}
          <div className="mx-auto mt-16 max-w-lg rounded-xl border border-line bg-surface p-5 shadow-soft-lg">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-[13px] font-semibold text-ink-2">Sample result</span>
              <span className="rounded-md bg-red-50 px-2 py-0.5 text-[12px] font-semibold text-status-critical">
                Risk 95 · Escalated
              </span>
            </div>
            <ul className="space-y-2.5">
              {SAMPLE.map((s) => (
                <li key={s.rule} className="flex items-center gap-2 text-[14px]">
                  {s.pass ? (
                    <CheckCircle2 size={15} className="shrink-0 text-status-good" strokeWidth={2.25} />
                  ) : (
                    <XCircle size={15} className="shrink-0 text-status-critical" strokeWidth={2.25} />
                  )}
                  <span className="text-ink-2">{s.rule}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Built on */}
      <div className="border-b border-line bg-surface-2 py-8">
        <div className="mx-auto flex max-w-container flex-wrap items-center justify-center gap-x-10 gap-y-3 px-6">
          <span className="eyebrow">Built on</span>
          {[
            { icon: Cpu, label: "Gemini API" },
            { icon: Cloud, label: "Cloud Run" },
            { icon: Database, label: "Firestore + BigQuery" },
            { icon: Flame, label: "Firebase Auth" },
          ].map((t) => (
            <span key={t.label} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-2">
              <t.icon size={14} />
              {t.label}
            </span>
          ))}
        </div>
      </div>

      {/* How it works */}
      <Section
        id="product"
        eyebrow="How it works"
        title="Three steps, no manual review of the routine cases"
        subtitle="The workflow that runs behind every document, every time."
      >
        <div className="mt-16 grid gap-8 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <div key={s.title} className="text-left">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
                  <s.icon size={18} strokeWidth={2} />
                </div>
                <span className="eyebrow">Step {i + 1}</span>
              </div>
              <h3 className="mt-4 text-[17px] font-semibold text-ink">{s.title}</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{s.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Architecture */}
      <Section
        surface="surface-2"
        eyebrow="Architecture"
        title="A real pipeline, not a chat wrapper"
        subtitle="Every stage below is a separate, independently deployed Cloud Run service."
      >
        <div className="mx-auto mt-14 max-w-2xl overflow-x-auto">
          <div className="flex min-w-[640px] items-stretch gap-0 text-center text-[12.5px] font-medium">
            {[
              "Browser",
              "API Gateway",
              "Ingestion Agent",
              "Compliance Agent",
              "Firestore + BigQuery",
            ].map((n, i, arr) => (
              <div key={n} className="flex items-center">
                <div className="rounded-lg border border-line bg-surface px-4 py-3 text-ink shadow-soft">
                  {n}
                </div>
                {i < arr.length - 1 && (
                  <ArrowRight size={16} className="mx-2 shrink-0 text-slate-400" />
                )}
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* Security */}
      <Section
        id="security"
        eyebrow="Security"
        title="Built to survive a real audit"
        subtitle="Not marketing claims — mechanisms you can verify in the source."
      >
        <div className="mt-16 grid gap-8 text-left sm:grid-cols-3">
          {SECURITY_POINTS.map((p) => (
            <div key={p.title}>
              <div className="grid h-10 w-10 place-items-center rounded-lg bg-brand-50 text-brand-700">
                <p.icon size={18} strokeWidth={2} />
              </div>
              <h3 className="mt-4 text-[15px] font-semibold text-ink">{p.title}</h3>
              <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{p.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Pricing */}
      <Section
        id="pricing"
        surface="surface-2"
        eyebrow="Pricing"
        title="Your first audit is free"
        subtitle="After that, pay per audit or go unlimited. No setup fee, no lock-in."
      >
        <div className="mx-auto mt-14 grid max-w-xl gap-5 sm:grid-cols-2">
          <div className="rounded-xl border border-line bg-surface p-6 text-left">
            <h3 className="text-[16px] font-bold text-ink">Single audit</h3>
            <div className="mt-3 flex items-baseline gap-1">
              <span className="text-[30px] font-bold text-ink">$299</span>
              <span className="text-[13px] text-ink-2">USD, one-off</span>
            </div>
            <p className="mt-2 text-[13px] text-ink-2">One document, fully checked and cited.</p>
          </div>
          <div className="rounded-xl border border-brand-300 bg-brand-50/40 p-6 text-left">
            <h3 className="text-[16px] font-bold text-ink">Unlimited</h3>
            <div className="mt-3 flex items-baseline gap-1">
              <span className="text-[30px] font-bold text-ink">$99</span>
              <span className="text-[13px] text-ink-2">USD /month</span>
            </div>
            <p className="mt-2 text-[13px] text-ink-2">Every document, every month, cancel any time.</p>
          </div>
        </div>
      </Section>

      {/* FAQ */}
      <Section id="faq" eyebrow="FAQ" title="Direct answers, not evasive ones">
        <div className="mx-auto mt-14 max-w-2xl divide-y divide-line text-left">
          {FAQ.map((f) => (
            <div key={f.q} className="py-6">
              <h3 className="text-[15px] font-semibold text-ink">{f.q}</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{f.a}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Final CTA */}
      <section className="border-t border-line py-20 text-center">
        <div className="mx-auto max-w-container px-6">
          <h2 className="text-heading font-bold text-ink">See your first document scored.</h2>
          <Link
            to="/signup"
            className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-5 py-2.5 text-[14px] font-semibold text-white shadow-soft transition-colors hover:bg-brand-700"
          >
            Start free
            <ArrowRight size={15} />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-line py-10">
        <div className="mx-auto flex max-w-container flex-col items-center justify-between gap-4 px-6 sm:flex-row">
          <Logo />
          <p className="text-[12.5px] text-muted">
            © {new Date().getFullYear()} ComplianceGuardian. Built for the XPRIZE Build with Gemini Hackathon.
          </p>
        </div>
      </footer>
    </div>
  );
}
