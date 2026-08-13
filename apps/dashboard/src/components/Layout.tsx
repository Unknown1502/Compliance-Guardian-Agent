import { useEffect, useState } from "react";
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
  LifeBuoy,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { PageTransition } from "./ui/PageTransition";
import { VerifyEmailBanner } from "./VerifyEmailBanner";
import { cn } from "../lib/cn";
import { ThemeToggle } from "./ui/ThemeToggle";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Absent means every role sees it. */
  roles?: string[];
}

const GROUPS: { label: string; items: NavItem[] }[] = [
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
      { to: "/audit", label: "Audit log", icon: ScrollText, roles: ["owner", "admin"] },
      { to: "/reports", label: "Reports", icon: FileBarChart2 },
      { to: "/trends", label: "Trends", icon: TrendingUp },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/workspace", label: "Overview", icon: ShieldCheck },
      { to: "/rulesets", label: "Rulesets", icon: BookMarked },
      { to: "/team", label: "Team", icon: Users },
      { to: "/billing", label: "Billing", icon: CreditCard },
      { to: "/support", label: "Support", icon: LifeBuoy },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

/** Persisted so the choice survives a reload; localStorage is wrapped because
 *  it throws in private-mode Safari and a nav preference is not worth a crash. */
const COLLAPSE_KEY = "cg.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function Logo({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  // A link, not a div: clicking the wordmark is the conventional way back to
  // the dashboard root. For a signed-in user "/" resolves to the Overview,
  // not the marketing landing page (see the auth gate in App.tsx).
  return (
    <Link
      to="/"
      onClick={onNavigate}
      aria-label="Go to overview"
      title={collapsed ? "ComplianceGuardian" : undefined}
      className={cn(
        "flex select-none items-center gap-2.5 rounded-lg transition-opacity hover:opacity-80",
        collapsed && "justify-center",
      )}
    >
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-600 text-white">
        <ShieldCheck size={16} strokeWidth={2.5} />
      </div>
      {!collapsed && (
        <span className="whitespace-nowrap text-[15px] font-bold tracking-tight text-ink">
          ComplianceGuardian
        </span>
      )}
    </Link>
  );
}

function NavItems({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const location = useLocation();
  const { session } = useAuth();
  // Cosmetic only — the gateway enforces the same rule and is the control that
  // matters. This just stops showing a reviewer a link that would 403.
  const groups = GROUPS.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) => !item.roles || item.roles.includes(session?.role ?? ""),
    ),
  })).filter((group) => group.items.length > 0);
  return (
    <>
      {groups.map((group) => (
        <div key={group.label} className="mb-6">
          {/* Collapsed, the group heading is replaced by a hairline: the rail
              is too narrow for the label, but losing the grouping entirely
              would turn eleven icons into an undifferentiated column. */}
          {collapsed ? (
            <div className="mx-auto mb-1.5 h-px w-6 bg-slate-200 dark:bg-slate-800" />
          ) : (
            <div className="mb-1.5 flex items-center gap-1 px-2">
              <span className="eyebrow">{group.label}</span>
              <ChevronDown size={12} className="text-slate-400" />
            </div>
          )}
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
                  // The native tooltip is the label when it is not rendered.
                  title={collapsed ? n.label : undefined}
                  aria-label={collapsed ? n.label : undefined}
                  className={cn(
                    "relative flex items-center rounded-lg py-2 text-[13.5px] font-medium transition-colors",
                    collapsed ? "justify-center px-0" : "gap-2.5 px-2.5",
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
                    className={cn(
                      "shrink-0",
                      isActive ? "text-brand-600 dark:text-brand-400" : "text-slate-400",
                    )}
                  />
                  {!collapsed && <span className="whitespace-nowrap">{n.label}</span>}
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
  // Defaults to expanded, so an existing user sees exactly what they saw
  // before until they choose otherwise.
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const isFullWidth = location.pathname.startsWith("/checks/");

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* private mode — the preference just won't persist */
    }
  }, [collapsed]);

  if (!session) return null;

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950 lg:flex">
      {/* Desktop rail. Only the width animates; the main column is flex-1 so
          it reclaims the space on its own without any width maths here.
          overflow-hidden keeps labels from spilling mid-transition. */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col justify-between overflow-hidden border-r border-slate-200 bg-slate-100 py-4 transition-[width] duration-200 ease-out dark:border-slate-800 dark:bg-slate-900 lg:flex",
          collapsed ? "w-[68px] px-2" : "w-[248px] px-3",
        )}
      >
        <div>
          <div className={cn("pb-5", collapsed ? "px-0" : "px-2")}>
            <Logo collapsed={collapsed} />
          </div>
          <NavItems collapsed={collapsed} />
        </div>

        <div
          className={cn(
            "border-t border-slate-200 pt-3 dark:border-slate-800",
            collapsed ? "px-0" : "px-2",
          )}
        >
          {!collapsed && (
            <>
              <p className="font-mono-num truncate text-[11px] text-slate-500 dark:text-slate-400">
                {session.tenantId}
              </p>
              <p className="mt-0.5 text-[11px] font-semibold capitalize text-brand-700 dark:text-brand-400">
                {session.role}
              </p>
            </>
          )}
          <div
            className={cn(
              "flex items-center gap-1",
              collapsed ? "flex-col" : "mt-2.5 justify-between",
            )}
          >
            <button
              onClick={() => signOut()}
              title={collapsed ? "Sign out" : undefined}
              aria-label={collapsed ? "Sign out" : undefined}
              className={cn(
                "inline-flex items-center text-[12.5px] text-slate-500 transition-colors hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100",
                collapsed ? "h-8 w-8 justify-center rounded-lg" : "gap-1.5",
              )}
            >
              <LogOut size={13} className="shrink-0" />
              {!collapsed && "Sign out"}
            </button>
            <button
              onClick={() => setCollapsed((c) => !c)}
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-white/70 hover:text-slate-700 dark:hover:bg-slate-800/60 dark:hover:text-slate-200"
            >
              {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
            </button>
          </div>

          {/* Also in Settings; here too because a theme control people cannot
              find is the same as not having one. Hidden when the sidebar is
              collapsed — three segments do not fit, and the full control is
              one click away in Settings. */}
          {!collapsed && (
            <div className="mt-3">
              <ThemeToggle compact />
            </div>
          )}
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
