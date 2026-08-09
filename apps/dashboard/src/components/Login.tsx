import { useEffect, useState } from "react";
import { ShieldCheck, CheckCircle2, XCircle, ArrowRight } from "lucide-react";
import { AUTH_MODE } from "../config";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";
import { Button } from "./ui/Button";
import { cn } from "../lib/cn";
import {
  ApiError,
  getAvailableRulesets,
  signup as signupRequest,
  type RulesetOptionRow,
} from "../api/client";

/**
 * Display names for the ruleset codes on disk.
 *
 * A lookup, not a source of truth: anything missing here falls back to the
 * raw code, so adding a ruleset YAML makes it selectable immediately without
 * a frontend change. The server decides what exists; this only decides how
 * it reads.
 */
const INDUSTRY_LABEL: Record<string, string> = {
  healthcare_ndis: "NDIS / disability services",
  aged_care: "Aged care",
  bookkeeping: "Bookkeeping & payroll",
  data_privacy: "Data privacy & protection",
  contract_review: "Contract review",
};

const JURISDICTION_LABEL: Record<string, string> = {
  au: "Australia",
  in: "India",
  eu: "European Union",
  uk: "United Kingdom",
  "us-ca": "United States (California)",
  ca: "Canada",
  sg: "Singapore",
  br: "Brazil",
  cn: "China",
  ae: "United Arab Emirates",
  za: "South Africa",
  generic: "Any jurisdiction",
};

const label = (map: Record<string, string>, key: string) => map[key] ?? key;

const DEMO_TENANTS = [
  { id: "tenant-sunrise-care", label: "Sunrise Community Care (NDIS)" },
  { id: "tenant-coastal-fresh", label: "Coastal Fresh Distributors" },
];

const ROLES: { id: Role; label: string }[] = [
  { id: "owner", label: "Owner" },
  { id: "reviewer", label: "Reviewer" },
  { id: "admin", label: "Admin" },
];

// A real result from the system, used as the proof point.
const SAMPLE = [
  { rule: "Consent documentation", pass: false },
  { rule: "Incident reporting window", pass: false },
  { rule: "Worker screening check", pass: false },
  { rule: "Data retention period", pass: true },
];

const FIELD =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-[13.5px] text-slate-900 placeholder:text-slate-400 transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";
const LABEL = "mb-1.5 block text-[13px] font-medium text-slate-700 dark:text-slate-300";

export function Login({ initialMode = "signin" }: { initialMode?: "signin" | "signup" }) {
  const { devSignIn, firebaseSignIn } = useAuth();
  const [tenantId, setTenantId] = useState(DEMO_TENANTS[0].id);
  const [role, setRole] = useState<Role>("owner");
  const [mode, setMode] = useState<"signin" | "signup">(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rulesets, setRulesets] = useState<RulesetOptionRow[]>([]);
  const [industry, setIndustry] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");

  // Loaded on mount so the menu reflects what the server can actually check
  // documents against. If this call fails the selects stay empty and signup
  // is blocked rather than silently defaulting — creating a workspace under
  // the wrong jurisdiction produces confident, cited, wrong verdicts, which
  // is worse than not creating it at all.
  useEffect(() => {
    let live = true;
    getAvailableRulesets()
      .then((rows) => {
        if (!live) return;
        setRulesets(rows);
        const first = rows[0];
        if (first) {
          setIndustry(first.industry);
          setJurisdiction(first.jurisdiction);
        }
      })
      .catch(() => live && setRulesets([]));
    return () => {
      live = false;
    };
  }, []);

  const industries = Array.from(new Set(rulesets.map((r) => r.industry)));
  const jurisdictions = rulesets.filter((r) => r.industry === industry);
  const selected = jurisdictions.find((r) => r.jurisdiction === jurisdiction);

  const handleDev = () => {
    setBusy(true);
    const uid = `${role}-${tenantId}`;
    window.setTimeout(() => devSignIn(tenantId, role, uid), 320);
  };

  const handleFirebase = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        await signupRequest(email, password, businessName, jobTitle, industry, jurisdiction);
      }
      await firebaseSignIn(email, password);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 409
            ? "An account with that email already exists — sign in instead."
            : err.status === 429
              ? "Too many attempts. Wait a minute and try again."
              : err.message
          : (err as Error).message,
      );
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950 lg:grid lg:grid-cols-2">
      {/* Form side */}
      <div className="flex items-center justify-center px-6 py-12 sm:px-10 lg:px-14">
        <div className="w-full max-w-[360px]">
          <div className="mb-8 flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white">
              <ShieldCheck size={17} strokeWidth={2.5} />
            </div>
            <span className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-slate-50">
              ComplianceGuardian
            </span>
          </div>

          {AUTH_MODE === "dev" ? (
            <div className="space-y-5">
              <div>
                <h1 className="text-[24px] font-bold tracking-tight text-slate-900 dark:text-slate-50">
                  Sign in to explore
                </h1>
                <p className="mt-1.5 text-[13.5px] text-slate-500 dark:text-slate-400">
                  Development sign-in — pick a tenant and role, no password needed.
                </p>
              </div>

              <label className="block">
                <span className={LABEL}>Tenant</span>
                <select
                  className={FIELD}
                  value={tenantId}
                  onChange={(e) => setTenantId(e.target.value)}
                >
                  {DEMO_TENANTS.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>

              <div>
                <span className={LABEL}>Role</span>
                <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
                  {ROLES.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setRole(r.id)}
                      className={cn(
                        "rounded-md py-1.5 text-[12.5px] font-medium transition-colors",
                        role === r.id
                          ? "bg-white text-brand-700 shadow-soft dark:bg-slate-700 dark:text-brand-300"
                          : "text-slate-500 hover:text-slate-800 dark:text-slate-400",
                      )}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>

              <Button onClick={handleDev} loading={busy} size="lg" className="w-full">
                Enter dashboard
              </Button>
            </div>
          ) : (
            <form onSubmit={handleFirebase} className="space-y-4">
              <div className="mb-6">
                <h1 className="text-[24px] font-bold tracking-tight text-slate-900 dark:text-slate-50">
                  {mode === "signin" ? "Welcome back" : "Create your account"}
                </h1>
                <p className="mt-1.5 text-[13.5px] text-slate-500 dark:text-slate-400">
                  {mode === "signin"
                    ? "Sign in to your compliance workspace."
                    : "Set up your compliance workspace in under a minute."}
                </p>
              </div>

              {mode === "signup" && (
                <>
                  <label className="block">
                    <span className={LABEL}>Business name</span>
                    <input
                      type="text"
                      placeholder="Sunrise Community Care Pty Ltd"
                      className={FIELD}
                      value={businessName}
                      onChange={(e) => setBusinessName(e.target.value)}
                    />
                  </label>
                  <label className="block">
                    <span className={LABEL}>Your role</span>
                    <input
                      type="text"
                      placeholder="Compliance Manager"
                      className={FIELD}
                      value={jobTitle}
                      onChange={(e) => setJobTitle(e.target.value)}
                    />
                    <span className="mt-1 block text-[11.5px] text-muted">
                      Shown to your team so reviewers know who decided what.
                    </span>
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block">
                      <span className={LABEL}>What you do</span>
                      <select
                        className={FIELD}
                        value={industry}
                        onChange={(e) => {
                          const next = e.target.value;
                          setIndustry(next);
                          // Not every industry covers every jurisdiction, so
                          // move to a pair that exists rather than leaving a
                          // combination the server would reject.
                          const first = rulesets.find((r) => r.industry === next);
                          if (first) setJurisdiction(first.jurisdiction);
                        }}
                      >
                        {industries.map((i) => (
                          <option key={i} value={i}>
                            {label(INDUSTRY_LABEL, i)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className={LABEL}>Where you operate</span>
                      <select
                        className={FIELD}
                        value={jurisdiction}
                        onChange={(e) => setJurisdiction(e.target.value)}
                      >
                        {jurisdictions.map((r) => (
                          <option key={r.jurisdiction} value={r.jurisdiction}>
                            {label(JURISDICTION_LABEL, r.jurisdiction)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <span className="-mt-1 block text-[11.5px] text-muted">
                    {rulesets.length === 0
                      ? "Could not load the available rulesets — reload before signing up."
                      : selected
                        ? `Your documents will be checked against ${selected.rule_count} rules (v${selected.rule_set_version}). This decides which law applies, so pick where the business actually operates.`
                        : "Pick the combination that matches your business."}
                  </span>
                </>
              )}
              <label className="block">
                <span className={LABEL}>Email</span>
                <input
                  type="email"
                  placeholder="you@provider.com.au"
                  className={FIELD}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label className="block">
                <span className={LABEL}>Password</span>
                <input
                  type="password"
                  placeholder="••••••••"
                  className={FIELD}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>

              <Button
                type="submit"
                loading={busy}
                size="lg"
                className="!mt-5 w-full"
                icon={!busy ? <ArrowRight size={15} /> : undefined}
                // Signing up without a resolved industry/jurisdiction would
                // create a workspace with no ruleset behind it, so the button
                // waits for the catalogue rather than guessing a default.
                disabled={mode === "signup" && (!industry || !jurisdiction)}
              >
                {mode === "signin" ? "Sign in" : "Create account"}
              </Button>

              <button
                type="button"
                onClick={() => {
                  setMode(mode === "signin" ? "signup" : "signin");
                  setError(null);
                }}
                className="w-full pt-1 text-center text-[13px] text-slate-500 transition-colors hover:text-brand-700 dark:text-slate-400"
              >
                {mode === "signin" ? (
                  <>
                    New here? <span className="font-medium text-brand-600">Create an account</span>
                  </>
                ) : (
                  <>
                    Already have an account?{" "}
                    <span className="font-medium text-brand-600">Sign in</span>
                  </>
                )}
              </button>
            </form>
          )}

          {error && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[13px] text-status-critical dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Proof side */}
      <div className="hidden items-center justify-center border-l border-slate-200 bg-slate-50 px-14 dark:border-slate-800 dark:bg-slate-900 lg:flex">
        <div className="w-full max-w-[380px]">
          <h2 className="text-[22px] font-bold leading-snug tracking-tight text-slate-900 dark:text-slate-50">
            Compliance checks in minutes, not weeks.
          </h2>
          <p className="mt-2.5 text-[13.5px] leading-relaxed text-slate-500 dark:text-slate-400">
            Upload a service record. Every finding cites the exact rule behind it, and
            lands in an audit trail you can hand to an assessor.
          </p>

          <div className="mt-7 rounded-xl border border-slate-200 bg-white p-4 shadow-soft dark:border-slate-800 dark:bg-slate-950">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[12.5px] font-semibold text-slate-700 dark:text-slate-300">
                Sample result
              </span>
              <span className="rounded-md bg-red-50 px-2 py-0.5 text-[11.5px] font-semibold text-status-critical dark:bg-red-950/40 dark:text-red-400">
                Risk 95 · Escalated
              </span>
            </div>
            <ul className="space-y-2">
              {SAMPLE.map((s) => (
                <li key={s.rule} className="flex items-center gap-2 text-[13px]">
                  {s.pass ? (
                    <CheckCircle2 size={14} className="shrink-0 text-status-good" strokeWidth={2.25} />
                  ) : (
                    <XCircle size={14} className="shrink-0 text-status-critical" strokeWidth={2.25} />
                  )}
                  <span className="text-slate-600 dark:text-slate-400">{s.rule}</span>
                </li>
              ))}
            </ul>
          </div>

          <p className="mt-5 text-[12.5px] text-slate-400 dark:text-slate-500">
            First audit free · No card required
          </p>
        </div>
      </div>
    </div>
  );
}
