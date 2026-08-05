import { useState } from "react";
import { AUTH_MODE } from "../config";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";
import { Button } from "./ui/Button";
import { cn } from "../lib/cn";
import { ApiError, signup as signupRequest } from "../api/client";

const DEMO_TENANTS = [
  { id: "tenant-sunrise-care", label: "Sunrise Community Care (NDIS)" },
  { id: "tenant-coastal-fresh", label: "Coastal Fresh Distributors" },
];

const ROLES: { id: Role; label: string }[] = [
  { id: "owner", label: "Owner" },
  { id: "reviewer", label: "Reviewer" },
  { id: "admin", label: "Admin" },
];

// A real specimen line from the register — the product's actual output, used
// as the hero rather than a claim about it.
const SPECIMEN = [
  { clause: "consent_documentation", verdict: "fail", note: "No signed consent on file" },
  { clause: "incident_reporting_window", verdict: "fail", note: "Lodged 3 days after incident" },
  { clause: "worker_screening_check", verdict: "fail", note: "Clearance not recorded" },
  { clause: "data_retention_period", verdict: "pass", note: "Retained to 2029-06-20" },
];

const FIELD =
  "w-full border border-slate-300 bg-white px-3 py-2.5 text-[13px] text-slate-900 placeholder:text-slate-400 transition-colors focus:border-brand-600 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-brand-400";
const LABEL = "eyebrow mb-1.5 block";

export function Login() {
  const { devSignIn, firebaseSignIn } = useAuth();
  const [tenantId, setTenantId] = useState(DEMO_TENANTS[0].id);
  const [role, setRole] = useState<Role>("owner");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        await signupRequest(email, password, businessName);
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
    <div className="min-h-screen bg-slate-100 dark:bg-slate-950 lg:grid lg:grid-cols-[1.05fr_1fr]">
      {/* Left: the specimen record. The product's real output is the argument. */}
      <div className="relative flex flex-col justify-between bg-slate-950 px-8 py-10 sm:px-12 lg:px-14 lg:py-14">
        <div className="flex items-baseline gap-[3px]">
          <span className="font-display text-lg font-semibold leading-none tracking-tight text-slate-50">
            Compliance
          </span>
          <span className="font-display text-lg font-normal italic leading-none tracking-tight text-brand-300">
            Guardian
          </span>
        </div>

        <div className="my-12 lg:my-0">
          <p className="eyebrow !text-brand-400">Specimen record · NDIS AU</p>
          <h1 className="mt-4 max-w-md font-display text-[30px] font-normal leading-[1.18] text-slate-50 sm:text-[36px]">
            Every finding cites the clause
            <span className="text-brand-300"> it came from.</span>
          </h1>
          <p className="mt-4 max-w-sm text-[13px] leading-relaxed text-slate-400">
            Upload a service record. Findings are returned against the NDIS
            ruleset, scored, and written to an append-only register you can hand
            an auditor.
          </p>

          {/* The specimen table: a real extract, not a marketing graphic. */}
          <div className="mt-9 max-w-md border-t border-slate-800">
            {SPECIMEN.map((row) => (
              <div
                key={row.clause}
                className="flex items-baseline justify-between gap-4 border-b border-slate-800/70 py-2.5"
              >
                <div className="min-w-0">
                  <p className="font-mono-num truncate text-[11.5px] text-slate-300">
                    {row.clause}
                  </p>
                  <p className="mt-0.5 truncate text-[11px] text-slate-500">{row.note}</p>
                </div>
                <span
                  className={cn(
                    "shrink-0 border px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.1em]",
                    row.verdict === "fail"
                      ? "border-[#C97664]/40 text-[#D98878]"
                      : "border-brand-400/40 text-brand-300",
                  )}
                >
                  {row.verdict}
                </span>
              </div>
            ))}
            <div className="flex items-baseline justify-between pt-3.5">
              <span className="eyebrow !text-slate-500">Score</span>
              <span className="font-mono-num text-[13px] font-semibold text-[#D98878]">
                95 / 100 · Escalated
              </span>
            </div>
          </div>
        </div>

        <p className="eyebrow !text-slate-600">
          Append-only audit trail · Rule version pinned to every decision
        </p>
      </div>

      {/* Right: the form. */}
      <div className="flex flex-col justify-center px-6 py-12 sm:px-10 lg:px-14">
        <div className="mx-auto w-full max-w-[340px]">
          {AUTH_MODE === "dev" ? (
            <div className="space-y-6">
              <div>
                <p className="eyebrow">Local access</p>
                <h2 className="mt-2 font-display text-[26px] font-normal leading-tight text-slate-900 dark:text-slate-50">
                  Sign in to explore
                </h2>
                <p className="mt-2 text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
                  Development sign-in. Pick a tenant and role — no password.
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
                <div className="grid grid-cols-3 border border-slate-300 dark:border-slate-700">
                  {ROLES.map((r, i) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setRole(r.id)}
                      className={cn(
                        "py-2 text-[12px] font-medium transition-colors",
                        i > 0 && "border-l border-slate-300 dark:border-slate-700",
                        role === r.id
                          ? "bg-brand-600 text-white"
                          : "text-slate-500 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-900",
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
            <form onSubmit={handleFirebase} className="space-y-5">
              <div>
                <p className="eyebrow">{mode === "signin" ? "Registered access" : "New provider"}</p>
                <h2 className="mt-2 font-display text-[26px] font-normal leading-tight text-slate-900 dark:text-slate-50">
                  {mode === "signin" ? "Sign in" : "Open your register"}
                </h2>
                <p className="mt-2 text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
                  {mode === "signin"
                    ? "Use your organisation credentials."
                    : "Set up your NDIS compliance workspace in under a minute."}
                </p>
              </div>

              {mode === "signup" && (
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

              <Button type="submit" loading={busy} size="lg" className="w-full">
                {mode === "signin" ? "Sign in" : "Create account"}
              </Button>

              <button
                type="button"
                onClick={() => {
                  setMode(mode === "signin" ? "signup" : "signin");
                  setError(null);
                }}
                className="w-full text-center text-[12.5px] text-slate-500 underline decoration-slate-300 underline-offset-[3px] transition-colors hover:text-brand-700 dark:text-slate-400 dark:decoration-slate-700 dark:hover:text-brand-300"
              >
                {mode === "signin"
                  ? "New here? Open a register"
                  : "Already registered? Sign in"}
              </button>
            </form>
          )}

          {error && (
            <p className="mt-5 border-l-2 border-oxide pl-3 text-[12.5px] leading-relaxed text-oxide dark:text-[#D98878]">
              {error}
            </p>
          )}

          {/* Anchors the column and states the offer — the reason a provider
              arriving from outreach would sign up at all. */}
          <dl className="mt-10 border-t border-slate-300 pt-5 dark:border-slate-800">
            {[
              ["First audit", "Free — no card required"],
              ["Turnaround", "Minutes, not weeks"],
              ["Ruleset", "NDIS Practice Standards (AU)"],
            ].map(([term, detail]) => (
              <div key={term} className="flex items-baseline justify-between gap-4 py-1.5">
                <dt className="eyebrow">{term}</dt>
                <dd className="text-[12px] text-slate-600 dark:text-slate-400">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
