import { useEffect, useMemo, useState } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Navigate,
  useNavigate,
} from "react-router-dom";
import {
  Activity,
  Building2,
  FileText,
  UserCheck,
  Cpu,
  ShieldAlert,
  ScrollText,
  Gauge,
  LifeBuoy,
  BookMarked,
  Settings as SettingsIcon,
  Search,
  LogOut,
  Lock,
} from "lucide-react";
import { AuthProvider, useAuth } from "./auth";
import { cn } from "./ui";
import {
  OverviewSection,
  TenantsSection,
  TenantDetailSection,
  DocumentsSection,
  ReviewsSection,
  AgentsSection,
  ComplianceSection,
  RulesetsSection,
  AuditSection,
  SecuritySection,
  SystemSection,
  SupportSection,
  SettingsSection,
} from "./sections";

const CUSTOMER_APP_URL = "https://cg-guardian-9856.web.app/";

const NAV = [
  { to: "/", label: "Overview", icon: Activity, end: true },
  { to: "/tenants", label: "Tenants", icon: Building2 },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/reviews", label: "Human review", icon: UserCheck },
  { to: "/agents", label: "AI operations", icon: Cpu },
  { to: "/compliance", label: "Compliance", icon: Gauge },
  { to: "/rulesets", label: "Rulesets", icon: BookMarked },
  { to: "/audit", label: "Audit log", icon: ScrollText },
  { to: "/security", label: "Security", icon: ShieldAlert },
  { to: "/system", label: "System", icon: Gauge },
  { to: "/support", label: "Support", icon: LifeBuoy },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

/** Restrained pre-auth screen. Names no product, no project, no infrastructure. */
function LoginScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch {
      // Deliberately generic: distinguishing "no such user" from "wrong
      // password" tells an attacker which addresses are real.
      setError("Sign-in failed. Check your credentials and try again.");
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-base px-6">
      <div className="w-full max-w-[330px]">
        <div className="mb-6 flex items-center gap-2">
          <Lock size={14} className="text-muted" />
          <span className="text-sm font-semibold tracking-tight">Control Center</span>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <label className="block">
            <span className="label">Email</span>
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm shadow-soft focus:border-accent focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="label">Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm shadow-soft focus:border-accent focus:outline-none"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white shadow-soft transition-colors hover:bg-accent-dim disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
          {error && <p className="text-xs text-crit">{error}</p>}
        </form>
        <p className="mt-6 text-2xs text-faint">Authorized personnel only. Access is logged.</p>
      </div>
    </div>
  );
}

/** Shown to an authenticated user who is not a platform admin. No redirect. */
function AccessDenied() {
  const { signOut, user } = useAuth();
  return (
    <div className="grid min-h-screen place-items-center bg-base px-6">
      <div className="w-full max-w-md">
        <h1 className="text-lg font-semibold text-crit">ACCESS DENIED</h1>
        <p className="mt-2 text-sm text-fg-dim">
          You are not authorized to access the ComplianceGuardian administrative control plane.
        </p>
        {user?.email && (
          <p className="mt-3 text-xs text-faint">
            Signed in as <span className="text-muted">{user.email}</span>
          </p>
        )}
        <div className="mt-5 flex items-center gap-3">
          <button
            onClick={() => signOut()}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-fg-dim transition-colors hover:bg-raised"
          >
            Sign out
          </button>
          <a href={CUSTOMER_APP_URL} className="text-sm text-accent hover:underline">
            Go to ComplianceGuardian →
          </a>
        </div>
      </div>
    </div>
  );
}

/** Cmd/Ctrl+K palette. Navigates; it does not fetch, so it can never leak. */
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");

  useEffect(() => {
    if (open) setQ("");
  }, [open]);

  const matches = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return NAV;
    return NAV.filter((n) => n.label.toLowerCase().includes(needle));
  }, [q]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-fg/25 pt-[15vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-xl border border-line bg-panel shadow-soft-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line px-3 py-2">
          <Search size={13} className="text-faint" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "Enter" && matches[0]) {
                nav(matches[0].to);
                onClose();
              }
            }}
            placeholder="Jump to…"
            className="w-full bg-transparent text-sm text-fg placeholder:text-faint focus:outline-none"
          />
        </div>
        <ul className="max-h-72 overflow-auto py-1">
          {matches.map((m) => (
            <li key={m.to}>
              <button
                onClick={() => {
                  nav(m.to);
                  onClose();
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-fg-dim hover:bg-raised"
              >
                <m.icon size={13} className="text-faint" />
                {m.label}
              </button>
            </li>
          ))}
          {matches.length === 0 && <li className="px-3 py-3 text-sm text-faint">No matches.</li>}
        </ul>
        <div className="border-t border-line px-3 py-1.5 text-2xs text-faint">
          Enter to open · Esc to close
        </div>
      </div>
    </div>
  );
}

function Shell() {
  const { admin, signOut } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing =
        e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPaletteOpen(true);
      } else if (e.key === "/" && !typing) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-h-screen bg-base">
      <aside className="hidden w-56 shrink-0 flex-col justify-between border-r border-line bg-panel lg:flex">
        <div>
          <div className="border-b border-line px-3 py-3">
            <div className="text-sm font-semibold tracking-tight">ComplianceGuardian</div>
            <div className="mt-0.5 text-2xs font-semibold uppercase tracking-[0.09em] text-crit">
              Admin Control Center
            </div>
          </div>
          <nav className="py-2">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors",
                    isActive
                      ? "border-l-2 border-accent bg-raised pl-[10px] text-fg"
                      : "border-l-2 border-transparent pl-[10px] text-muted hover:bg-raised hover:text-fg-dim",
                  )
                }
              >
                <n.icon size={14} />
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="border-t border-line px-3 py-2.5">
          <div className="truncate text-xs text-muted">{admin?.email}</div>
          <div className="mt-1.5 flex items-center justify-between">
            <button
              onClick={() => signOut()}
              className="inline-flex items-center gap-1 text-xs text-faint hover:text-fg-dim"
            >
              <LogOut size={11} />
              Sign out
            </button>
            <button
              onClick={() => setPaletteOpen(true)}
              className="border border-line px-1.5 py-0.5 text-2xs text-faint hover:text-fg-dim"
              title="Command palette"
            >
              ⌘K
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 p-4 lg:p-6">
        <Routes>
          <Route path="/" element={<OverviewSection />} />
          <Route path="/tenants" element={<TenantsSection />} />
          <Route path="/tenants/:tenantId" element={<TenantDetailSection />} />
          <Route path="/documents" element={<DocumentsSection />} />
          <Route path="/reviews" element={<ReviewsSection />} />
          <Route path="/agents" element={<AgentsSection />} />
          <Route path="/compliance" element={<ComplianceSection />} />
          <Route path="/rulesets" element={<RulesetsSection />} />
          <Route path="/audit" element={<AuditSection />} />
          <Route path="/security" element={<SecuritySection />} />
          <Route path="/system" element={<SystemSection />} />
          <Route path="/support" element={<SupportSection />} />
          <Route path="/settings" element={<SettingsSection />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

function Gate() {
  const { phase } = useAuth();
  if (phase === "loading" || phase === "checking") {
    return (
      <div className="grid min-h-screen place-items-center bg-base">
        <span className="text-sm text-faint">Verifying authorization…</span>
      </div>
    );
  }
  if (phase === "signed-out") return <LoginScreen />;
  if (phase === "denied") return <AccessDenied />;
  return <Shell />;
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  );
}
