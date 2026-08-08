import { useEffect, useState } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import {
  Activity,
  AlertTriangle,
  Building2,
  FileText,
  Loader2,
  LogOut,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  Users,
} from "lucide-react";
import {
  auth,
  fetchAudit,
  fetchOverview,
  login,
  logout,
  whoami,
  type AuditEvent,
  type PlatformOverview,
} from "./api";

/**
 * Operator console — cross-tenant, read-only.
 *
 * Visually distinct from the tenant dashboard on purpose. Two surfaces that
 * look alike but differ in blast radius is how someone acts on the wrong one;
 * the dark treatment makes it unmistakable that you are looking across every
 * customer rather than inside one.
 *
 * The client-side gate here is convenience, not security. The real boundary is
 * the server-side allowlist on /api/platform/* — every request is checked and
 * audited there, so a modified frontend gains nothing.
 */

function Stat({
  label,
  value,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: number | string;
  icon: typeof Users;
  tone?: "default" | "warning";
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center gap-2">
        <Icon
          size={14}
          className={tone === "warning" ? "text-status-warning" : "text-slate-500"}
        />
        <span className="text-[11px] uppercase tracking-wide text-slate-500">{label}</span>
      </div>
      <p
        className={`font-num text-2xl font-semibold ${
          tone === "warning" ? "text-status-warning" : "text-slate-100"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      // Deliberately generic: this form must not reveal whether an address
      // exists or whether it is an operator account.
      setError("Sign-in failed. Check the email and password.");
      void err;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-slate-800">
            <ShieldAlert size={17} className="text-brand-400" />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold text-slate-100">Operator Console</h1>
            <p className="text-[12px] text-slate-500">ComplianceGuardian — internal</p>
          </div>
        </div>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          autoComplete="username"
          className="mb-2 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:border-brand-500 focus:outline-none"
        />
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          className="mb-3 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-600 focus:border-brand-500 focus:outline-none"
        />
        {error && <p className="mb-3 text-[12.5px] text-status-critical">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-50"
        >
          {busy && <Loader2 size={14} className="animate-spin" />}
          Sign in
        </button>
      </form>
    </div>
  );
}

function NotAuthorised({ email }: { email: string }) {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="max-w-sm text-center">
        <ShieldAlert size={28} className="mx-auto mb-3 text-slate-600" />
        <h1 className="mb-1.5 text-[15px] font-semibold text-slate-200">Not authorised</h1>
        <p className="mb-4 text-[13px] leading-relaxed text-slate-500">
          <span className="text-slate-300">{email}</span> is not on the operator
          allowlist. Access is granted by service configuration, not from inside
          the product.
        </p>
        <button
          onClick={() => logout()}
          className="text-[13px] text-brand-400 hover:text-brand-300"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}

function Console({ user }: { user: User }) {
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    setAuditError(null);
    try {
      setOverview(await fetchOverview());
    } catch (err) {
      setError((err as Error).message);
    }
    // The audit query hits BigQuery and can fail independently — a query
    // problem there must not blank out the tenant table above it.
    try {
      setEvents((await fetchAudit()).events);
    } catch (err) {
      setAuditError((err as Error).message);
    }
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-5 py-6 sm:px-8">
      <header className="mb-7 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-5">
        <div className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-slate-800">
            <ShieldAlert size={17} className="text-brand-400" />
          </div>
          <div>
            <h1 className="text-[15px] font-semibold text-slate-100">Operator Console</h1>
            <p className="font-num text-[11.5px] text-slate-500">
              {user.email} · read-only · every view audited
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[12.5px] text-slate-300 hover:bg-slate-900 disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => logout()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[12.5px] text-slate-400 hover:bg-slate-900"
          >
            <LogOut size={12} />
            Sign out
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-red-900/60 bg-red-950/30 px-4 py-3 text-[13px] text-red-300">
          <AlertTriangle size={15} className="shrink-0" />
          {error}
        </div>
      )}

      {loading && !overview && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-slate-900" />
          ))}
        </div>
      )}

      {overview && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Tenants" value={overview.tenants_total} icon={Building2} />
            <Stat label="Members" value={overview.members_total} icon={Users} />
            <Stat label="Documents" value={overview.documents_total} icon={FileText} />
            <Stat label="Checks run" value={overview.checks_total} icon={Activity} />
          </div>

          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Signups 7d" value={overview.signups_last_7d} icon={Building2} />
            <Stat label="Signups 30d" value={overview.signups_last_30d} icon={Building2} />
            <Stat
              label="Open escalations"
              value={overview.open_escalations_total}
              icon={AlertTriangle}
              tone={overview.open_escalations_total > 0 ? "warning" : "default"}
            />
            <Stat
              label="Plans"
              value={
                Object.entries(overview.tenants_by_plan)
                  .map(([p, n]) => `${n} ${p}`)
                  .join(" · ") || "—"
              }
              icon={Activity}
            />
          </div>

          <section className="mb-7">
            <h2 className="mb-2.5 text-[13px] font-semibold text-slate-300">
              Tenants{" "}
              <span className="font-normal text-slate-600">
                — newest first ({overview.tenants.length})
              </span>
            </h2>
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              {overview.tenants.length === 0 ? (
                <p className="px-4 py-10 text-center text-[13px] text-slate-500">
                  No tenants yet. The first signup will appear here.
                </p>
              ) : (
                <table className="w-full text-left text-[12.5px]">
                  <thead className="border-b border-slate-800 bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2.5 font-medium">Business</th>
                      <th className="px-3 py-2.5 font-medium">Industry</th>
                      <th className="px-3 py-2.5 font-medium">Plan</th>
                      <th className="px-3 py-2.5 text-right font-medium">People</th>
                      <th className="px-3 py-2.5 text-right font-medium">Docs</th>
                      <th className="px-3 py-2.5 text-right font-medium">Checks</th>
                      <th className="px-3 py-2.5 text-right font-medium">Open</th>
                      <th className="px-3 py-2.5 font-medium">Joined</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {overview.tenants.map((t) => (
                      <tr key={t.tenant_id} className="hover:bg-slate-900/40">
                        <td className="px-3 py-2.5">
                          <span className="text-slate-200">{t.name}</span>
                          <span className="font-num ml-2 text-[11px] text-slate-600">
                            {t.tenant_id}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-slate-400">
                          {t.industry} / {t.jurisdiction}
                        </td>
                        <td className="px-3 py-2.5 capitalize text-slate-400">{t.plan_tier}</td>
                        <td className="font-num px-3 py-2.5 text-right text-slate-300">
                          {t.members}
                        </td>
                        <td className="font-num px-3 py-2.5 text-right text-slate-300">
                          {t.documents}
                        </td>
                        <td className="font-num px-3 py-2.5 text-right text-slate-300">
                          {t.checks}
                        </td>
                        <td
                          className={`font-num px-3 py-2.5 text-right ${
                            t.open_escalations > 0 ? "text-status-warning" : "text-slate-600"
                          }`}
                        >
                          {t.open_escalations}
                        </td>
                        <td className="font-num px-3 py-2.5 text-slate-500">
                          {t.created_at.split("T")[0]}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section>
            <h2 className="mb-2.5 flex items-center gap-1.5 text-[13px] font-semibold text-slate-300">
              <ScrollText size={14} className="text-slate-500" />
              Decision log
              <span className="font-normal text-slate-600">
                — every tenant, newest first
              </span>
            </h2>
            <div className="overflow-x-auto rounded-xl border border-slate-800">
              {auditError ? (
                <p className="px-4 py-8 text-center text-[13px] text-slate-500">
                  Could not load the audit trail: {auditError}
                </p>
              ) : events.length === 0 ? (
                <p className="px-4 py-10 text-center text-[13px] text-slate-500">
                  No audit events recorded yet.
                </p>
              ) : (
                <table className="w-full text-left text-[12.5px]">
                  <thead className="border-b border-slate-800 bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2.5 font-medium">When</th>
                      <th className="px-3 py-2.5 font-medium">Tenant</th>
                      <th className="px-3 py-2.5 font-medium">Actor</th>
                      <th className="px-3 py-2.5 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {events.map((e) => (
                      <tr key={e.event_id} className="hover:bg-slate-900/40">
                        <td className="font-num whitespace-nowrap px-3 py-2 text-slate-500">
                          {String(e.created_at).replace("T", " ").slice(0, 19)}
                        </td>
                        <td className="font-num px-3 py-2 text-slate-400">{e.tenant_id}</td>
                        <td className="font-num px-3 py-2 text-slate-400">{e.actor}</td>
                        <td className="px-3 py-2 text-slate-200">{e.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [authorised, setAuthorised] = useState<boolean | null>(null);

  useEffect(() => {
    return onAuthStateChanged(auth, async (u) => {
      setUser(u);
      setAuthorised(null);
      if (!u) {
        setChecking(false);
        return;
      }
      // Ask the server, rather than reading a claim the client could fake.
      try {
        await whoami();
        setAuthorised(true);
      } catch {
        // Fail closed. A refusal and a network problem are indistinguishable
        // from here, and guessing "probably authorised" on an error is the
        // wrong default for a cross-tenant surface.
        setAuthorised(false);
      } finally {
        setChecking(false);
      }
    });
  }, []);

  if (checking) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Loader2 size={20} className="animate-spin text-slate-600" />
      </div>
    );
  }
  if (!user) return <SignIn />;
  if (authorised === false) return <NotAuthorised email={user.email ?? "This account"} />;
  return <Console user={user} />;
}
