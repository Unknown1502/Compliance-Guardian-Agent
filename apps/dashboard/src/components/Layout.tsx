import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { LogOut, Menu, X } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "./ui/ThemeToggle";
import { PageTransition } from "./ui/PageTransition";
import { cn } from "../lib/cn";

// Nav entries carry a record-type label because each screen genuinely is a
// different class of record — not decoration, and not a sequence, so no
// numbering.
const NAV = [
  { to: "/", label: "Task queue", kind: "Register", end: true },
  { to: "/upload", label: "Upload", kind: "Intake" },
  { to: "/audit", label: "Audit log", kind: "Provenance" },
  { to: "/reports", label: "Reports", kind: "Statements" },
];

function Wordmark({ tone = "light" }: { tone?: "light" | "dark" }) {
  return (
    <div className="flex items-baseline gap-[3px]">
      <span
        className={cn(
          "font-display text-[17px] font-semibold leading-none tracking-tight",
          tone === "dark" ? "text-slate-900 dark:text-slate-50" : "text-slate-50",
        )}
      >
        Compliance
      </span>
      <span
        className={cn(
          "font-display text-[17px] font-normal italic leading-none tracking-tight",
          tone === "dark" ? "text-brand-700 dark:text-brand-300" : "text-brand-300",
        )}
      >
        Guardian
      </span>
    </div>
  );
}

export function Layout() {
  const { session, signOut } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  if (!session) return null;

  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-950 lg:flex">
      {/* The spine: always ink-dark, like the bound edge of a register. */}
      <aside className="hidden w-[228px] shrink-0 flex-col justify-between bg-slate-950 px-5 py-6 lg:flex">
        <div>
          <div className="px-1">
            <Wordmark />
            <p className="eyebrow mt-2 !text-slate-500">NDIS · Australia</p>
          </div>

          <nav className="mt-9 flex flex-col">
            {NAV.map((n) => {
              const isActive = n.end
                ? location.pathname === n.to
                : location.pathname.startsWith(n.to);
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className="group relative border-l border-slate-800 py-2.5 pl-4 pr-1"
                >
                  {isActive && (
                    <motion.span
                      layoutId="spine-mark"
                      transition={{ type: "spring", stiffness: 500, damping: 40 }}
                      className="absolute -left-px top-0 h-full w-[2px] bg-brand-400"
                    />
                  )}
                  <span
                    className={cn(
                      "block text-[13px] font-medium leading-tight transition-colors",
                      isActive
                        ? "text-slate-50"
                        : "text-slate-500 group-hover:text-slate-300",
                    )}
                  >
                    {n.label}
                  </span>
                  <span
                    className={cn(
                      "eyebrow mt-0.5 block !text-[9px] transition-colors",
                      isActive ? "!text-brand-400" : "!text-slate-600",
                    )}
                  >
                    {n.kind}
                  </span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        <div className="space-y-3">
          <div className="border-t border-slate-800 pt-3">
            <p className="font-mono-num truncate text-[11px] text-slate-500">
              {session.tenantId}
            </p>
            <p className="eyebrow mt-1 !text-brand-400">{session.role}</p>
          </div>
          <div className="flex items-center justify-between">
            <button
              onClick={() => signOut()}
              className="inline-flex items-center gap-1.5 text-[12px] text-slate-500 transition-colors hover:text-slate-200"
            >
              <LogOut size={13} />
              Sign out
            </button>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Mobile bar */}
      <header className="sticky top-0 z-40 border-b border-slate-300 bg-slate-950 px-4 py-3 dark:border-slate-800 lg:hidden">
        <div className="flex items-center justify-between">
          <Wordmark />
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <button
              onClick={() => setMobileOpen((o) => !o)}
              className="grid h-8 w-8 place-items-center text-slate-400 hover:text-slate-100"
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
              <div className="flex flex-col pt-3">
                {NAV.map((n) => (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    end={n.end}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "border-l py-2 pl-3 text-[13px] font-medium",
                        isActive
                          ? "border-brand-400 text-slate-50"
                          : "border-slate-800 text-slate-500",
                      )
                    }
                  >
                    {n.label}
                  </NavLink>
                ))}
                <button
                  onClick={() => signOut()}
                  className="mt-1 border-l border-slate-800 py-2 pl-3 text-left text-[13px] text-slate-500"
                >
                  Sign out
                </button>
              </div>
            </motion.nav>
          )}
        </AnimatePresence>
      </header>

      <main className="stock-ruled min-w-0 flex-1 px-4 py-7 sm:px-8 lg:px-12 lg:py-10">
        <div className="mx-auto max-w-5xl">
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
