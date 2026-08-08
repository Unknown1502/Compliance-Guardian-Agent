import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  LayoutDashboard,
  UploadCloud,
  Inbox,
  ScrollText,
  FileBarChart2,
  CreditCard,
  BookMarked,
  Users,
  Settings,
  LogOut,
  Menu,
  X,
  ShieldCheck,
  ChevronDown,
  TrendingUp,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { PageTransition } from "./ui/PageTransition";
import { VerifyEmailBanner } from "./VerifyEmailBanner";
import { cn } from "../lib/cn";

const GROUPS = [
  {
    label: "Compliance",
    items: [
      { to: "/", label: "Task queue", end: true, icon: LayoutDashboard },
      { to: "/upload", label: "Upload", icon: UploadCloud },
      { to: "/queue", label: "Human queue", icon: Inbox },
    ],
  },
  {
    label: "Records",
    items: [
      { to: "/audit", label: "Audit log", icon: ScrollText },
      { to: "/reports", label: "Reports", icon: FileBarChart2 },
      { to: "/trends", label: "Trends", icon: TrendingUp },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/rulesets", label: "Rulesets", icon: BookMarked },
      { to: "/team", label: "Team", icon: Users },
      { to: "/billing", label: "Billing", icon: CreditCard },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

function Logo({ onNavigate }: { onNavigate?: () => void }) {
  // A link, not a div: clicking the wordmark is the conventional way back to
  // the dashboard root. For a signed-in user "/" resolves to the Overview,
  // not the marketing landing page (see the auth gate in App.tsx).
  return (
    <Link
      to="/"
      onClick={onNavigate}
      aria-label="Go to overview"
      className="flex select-none items-center gap-2.5 rounded-lg transition-opacity hover:opacity-80"
    >
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-600 text-white">
        <ShieldCheck size={16} strokeWidth={2.5} />
      </div>
      <span className="text-[15px] font-bold tracking-tight text-ink">
        ComplianceGuardian
      </span>
    </Link>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  return (
    <>
      {GROUPS.map((group) => (
        <div key={group.label} className="mb-6">
          <div className="mb-1.5 flex items-center gap-1 px-2">
            <span className="eyebrow">{group.label}</span>
            <ChevronDown size={12} className="text-slate-400" />
          </div>
          <div className="space-y-0.5">
            {group.items.map((n) => {
              const isActive = n.end
                ? location.pathname === n.to
                : location.pathname.startsWith(n.to);
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onClick={onNavigate}
                  className={cn(
                    "relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                    isActive
                      ? "bg-white text-brand-700 shadow-soft dark:bg-slate-800 dark:text-brand-300"
                      : "text-slate-600 hover:bg-white/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-100",
                  )}
                >
                  {isActive && (
                    <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r bg-brand-600 dark:bg-brand-400" />
                  )}
                  <n.icon
                    size={16}
                    strokeWidth={2}
                    className={isActive ? "text-brand-600 dark:text-brand-400" : "text-slate-400"}
                  />
                  {n.label}
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </>
  );
}

export function Layout() {
  const { session, signOut } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isFullWidth = location.pathname.startsWith("/checks/");
  if (!session) return null;

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950 lg:flex">
      <aside className="hidden w-[248px] shrink-0 flex-col justify-between border-r border-slate-200 bg-slate-100 px-3 py-4 dark:border-slate-800 dark:bg-slate-900 lg:flex">
        <div>
          <div className="px-2 pb-5">
            <Logo />
          </div>
          <NavItems />
        </div>

        <div className="border-t border-slate-200 px-2 pt-3 dark:border-slate-800">
          <p className="font-mono-num truncate text-[11px] text-slate-500 dark:text-slate-400">
            {session.tenantId}
          </p>
          <p className="mt-0.5 text-[11px] font-semibold capitalize text-brand-700 dark:text-brand-400">
            {session.role}
          </p>
          <div className="mt-2.5 flex items-center justify-between">
            <button
              onClick={() => signOut()}
              className="inline-flex items-center gap-1.5 text-[12.5px] text-slate-500 transition-colors hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            >
              <LogOut size={13} />
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile header */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950 lg:hidden">
        <div className="flex items-center justify-between">
          <Logo onNavigate={() => setMobileOpen(false)} />
          <div className="flex items-center gap-1">
            <button
              onClick={() => setMobileOpen((o) => !o)}
              className="grid h-8 w-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              aria-label="Toggle menu"
            >
              {mobileOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>
        <AnimatePresence>
          {mobileOpen && (
            <motion.nav
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="pt-4">
                <NavItems onNavigate={() => setMobileOpen(false)} />
                <button
                  onClick={() => signOut()}
                  className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] font-medium text-slate-600 dark:text-slate-400"
                >
                  <LogOut size={16} className="text-slate-400" />
                  Sign out
                </button>
              </div>
            </motion.nav>
          )}
        </AnimatePresence>
      </header>

      {/* The review screen is a side-by-side document/findings layout, so it
          needs the full viewport rather than the reading-width column that
          suits the list and settings pages. */}
      <main
        className={cn(
          "min-w-0 flex-1",
          isFullWidth ? "p-0" : "px-5 py-6 sm:px-8 sm:py-8 lg:px-10",
        )}
      >
        <div className={cn(!isFullWidth && "mx-auto max-w-5xl")}>
          {/* Sits above the routed view, not inside it, so it shows on every
              page until the address is confirmed. */}
          <VerifyEmailBanner />
          <AnimatePresence mode="wait">
            <PageTransition key={location.pathname}>
              <Outlet />
            </PageTransition>
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
