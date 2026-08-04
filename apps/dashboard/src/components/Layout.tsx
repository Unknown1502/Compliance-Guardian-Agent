import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  ListChecks,
  UploadCloud,
  ScrollText,
  FileBarChart2,
  LogOut,
  Menu,
  X,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "./ui/ThemeToggle";
import { PageTransition } from "./ui/PageTransition";
import { cn } from "../lib/cn";

const NAV = [
  { to: "/", label: "Task queue", end: true, icon: ListChecks },
  { to: "/upload", label: "Upload", icon: UploadCloud },
  { to: "/audit", label: "Audit log", icon: ScrollText },
  { to: "/reports", label: "Reports", icon: FileBarChart2 },
];

const ROLE_STYLES: Record<string, string> = {
  reviewer:
    "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:ring-amber-900",
  admin:
    "bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200 dark:bg-violet-950/40 dark:text-violet-400 dark:ring-violet-900",
  owner:
    "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200 dark:bg-brand-950/40 dark:text-brand-400 dark:ring-brand-900",
};

export function Layout() {
  const { session, signOut } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  if (!session) return null;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/80 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/80">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow-brand">
              <ShieldCheck size={17} strokeWidth={2.25} />
            </div>
            <span className="font-semibold tracking-tight text-slate-800 dark:text-slate-100">
              ComplianceGuardian
            </span>
          </div>

          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => {
              const isActive = n.end
                ? location.pathname === n.to
                : location.pathname.startsWith(n.to);
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className="relative px-3 py-2 text-sm font-medium"
                >
                  <span
                    className={cn(
                      "relative z-10 flex items-center gap-1.5",
                      isActive
                        ? "text-brand-700 dark:text-brand-300"
                        : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
                    )}
                  >
                    <n.icon size={14} strokeWidth={2.25} />
                    {n.label}
                  </span>
                  {isActive && (
                    <motion.span
                      layoutId="nav-pill"
                      transition={{ type: "spring", stiffness: 420, damping: 34 }}
                      className="absolute inset-0 rounded-lg bg-brand-50 dark:bg-brand-950/50"
                    />
                  )}
                </NavLink>
              );
            })}
          </nav>

          <div className="flex items-center gap-2.5">
            <span className="hidden text-sm text-slate-400 dark:text-slate-500 sm:inline">
              {session.tenantId}
            </span>
            <span
              className={cn(
                "hidden rounded-full px-2.5 py-0.5 text-xs font-medium capitalize sm:inline-block",
                ROLE_STYLES[session.role],
              )}
            >
              {session.role}
            </span>
            <ThemeToggle />
            <button
              onClick={() => signOut()}
              className="hidden items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 md:inline-flex"
            >
              <LogOut size={14} />
              Sign out
            </button>
            <button
              onClick={() => setMobileOpen((o) => !o)}
              className="grid h-8 w-8 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 md:hidden"
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
              transition={{ duration: 0.22 }}
              className="overflow-hidden border-t border-slate-200 dark:border-slate-800 md:hidden"
            >
              <div className="flex flex-col gap-0.5 px-4 py-2">
                {NAV.map((n) => (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    end={n.end}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium",
                        isActive
                          ? "bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300"
                          : "text-slate-500 dark:text-slate-400",
                      )
                    }
                  >
                    <n.icon size={15} />
                    {n.label}
                  </NavLink>
                ))}
                <button
                  onClick={() => signOut()}
                  className="mt-1 flex items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-slate-500 dark:text-slate-400"
                >
                  <LogOut size={15} />
                  Sign out
                </button>
              </div>
            </motion.nav>
          )}
        </AnimatePresence>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        <AnimatePresence mode="wait">
          <PageTransition key={location.pathname}>
            <Outlet />
          </PageTransition>
        </AnimatePresence>
      </main>
    </div>
  );
}
