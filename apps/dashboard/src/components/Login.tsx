import { useState } from "react";
import { motion } from "framer-motion";
import {
  ShieldCheck,
  Sparkles,
  FileCheck2,
  ScanSearch,
  GaugeCircle,
  ArrowRight,
} from "lucide-react";
import { AUTH_MODE } from "../config";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";
import { Button } from "./ui/Button";
import { cn } from "../lib/cn";

const DEMO_TENANTS = [
  { id: "tenant-sunrise-care", label: "Sunrise Community Care (NDIS)" },
  { id: "tenant-coastal-fresh", label: "Coastal Fresh Distributors" },
];

const ROLES: { id: Role; label: string }[] = [
  { id: "owner", label: "Owner" },
  { id: "reviewer", label: "Reviewer" },
  { id: "admin", label: "Admin" },
];

const FEATURES = [
  { icon: ScanSearch, text: "Gemini extracts structured fields from any document" },
  { icon: GaugeCircle, text: "Instant risk score with cited, versioned rules" },
  { icon: FileCheck2, text: "Auto-approve or escalate — fully auditable trail" },
];

export function Login() {
  const { devSignIn, firebaseSignIn } = useAuth();
  const [tenantId, setTenantId] = useState(DEMO_TENANTS[0].id);
  const [role, setRole] = useState<Role>("owner");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      await firebaseSignIn(email, password);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <div className="pointer-events-none absolute inset-0 bg-grid-fade" />
      <div className="pointer-events-none absolute -top-32 left-1/2 h-96 w-[42rem] -translate-x-1/2 rounded-full bg-brand-400/20 blur-3xl dark:bg-brand-600/10" />
      <div className="pointer-events-none absolute -left-24 top-1/3 h-72 w-72 animate-blob rounded-full bg-brand-300/25 blur-3xl dark:bg-brand-800/15" />
      <div
        className="pointer-events-none absolute -right-16 bottom-0 h-80 w-80 animate-blob rounded-full bg-violet-300/20 blur-3xl dark:bg-violet-800/10"
        style={{ animationDelay: "4s" }}
      />

      <div className="relative grid w-full max-w-4xl overflow-hidden rounded-3xl border border-slate-200/80 bg-white/70 shadow-soft-lg backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/70 lg:grid-cols-5">
        {/* Brand panel */}
        <motion.div
          initial={{ opacity: 0, x: -16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="relative hidden flex-col justify-between bg-gradient-to-br from-brand-600 via-brand-700 to-slate-900 p-8 text-white lg:col-span-2 lg:flex"
        >
          <div>
            <div className="mb-8 flex items-center gap-2.5">
              <div className="grid h-9 w-9 place-items-center rounded-lg bg-white/15 backdrop-blur-sm">
                <ShieldCheck size={18} />
              </div>
              <span className="font-semibold tracking-tight">ComplianceGuardian</span>
            </div>
            <h1 className="text-2xl font-bold leading-snug">
              Agentic compliance,
              <br />
              audited by default.
            </h1>
            <p className="mt-3 text-sm text-white/70">
              Upload a document. Gemini scores the risk, cites the rules, and routes
              the decision — every step logged.
            </p>
          </div>

          <ul className="space-y-3.5">
            {FEATURES.map((f, i) => (
              <motion.li
                key={f.text}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25 + i * 0.1, duration: 0.4 }}
                className="flex items-start gap-2.5 text-sm text-white/85"
              >
                <f.icon size={16} className="mt-0.5 shrink-0 text-white/70" />
                {f.text}
              </motion.li>
            ))}
          </ul>

          <div className="flex items-center gap-1.5 text-xs text-white/50">
            <Sparkles size={12} />
            XPRIZE Build with Gemini Hackathon
          </div>
        </motion.div>

        {/* Form panel */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="p-8 lg:col-span-3 sm:p-10"
        >
          <div className="mb-7 flex items-center gap-2.5 lg:hidden">
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white">
              <ShieldCheck size={18} />
            </div>
            <span className="font-semibold tracking-tight text-slate-800 dark:text-slate-100">
              ComplianceGuardian
            </span>
          </div>

          {AUTH_MODE === "dev" ? (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                  Sign in to explore
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  Local dev sign-in — pick a tenant and role, no password needed.
                </p>
              </div>

              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Tenant
                </span>
                <select
                  className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-800 shadow-sm transition-colors focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
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
                <span className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Role
                </span>
                <div className="relative grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800">
                  {ROLES.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setRole(r.id)}
                      className="relative z-10 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
                    >
                      <span
                        className={cn(
                          "relative z-10",
                          role === r.id
                            ? "text-brand-700 dark:text-brand-300"
                            : "text-slate-500 dark:text-slate-400",
                        )}
                      >
                        {r.label}
                      </span>
                      {role === r.id && (
                        <motion.span
                          layoutId="role-pill"
                          transition={{ type: "spring", stiffness: 450, damping: 32 }}
                          className="absolute inset-0 rounded-lg bg-white shadow-soft dark:bg-slate-700"
                        />
                      )}
                    </button>
                  ))}
                </div>
              </div>

              <Button
                onClick={handleDev}
                loading={busy}
                size="lg"
                className="w-full"
                icon={!busy ? <ArrowRight size={15} /> : undefined}
              >
                Enter dashboard
              </Button>
            </div>
          ) : (
            <form onSubmit={handleFirebase} className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                  Welcome back
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  Sign in with your organization credentials.
                </p>
              </div>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Email
                </span>
                <input
                  type="email"
                  placeholder="you@company.com"
                  className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Password
                </span>
                <input
                  type="password"
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <Button type="submit" loading={busy} size="lg" className="w-full">
                Sign in
              </Button>
            </form>
          )}

          {error && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-4 text-sm text-status-critical"
            >
              {error}
            </motion.p>
          )}
        </motion.div>
      </div>
    </div>
  );
}
