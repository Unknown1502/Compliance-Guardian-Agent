import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const NAV = [
  { to: "/", label: "Task Queue", end: true },
  { to: "/upload", label: "Upload" },
  { to: "/audit", label: "Audit Log" },
  { to: "/reports", label: "Reports" },
];

export function Layout() {
  const { session, signOut } = useAuth();
  if (!session) return null;

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded bg-brand-600 text-white grid place-items-center text-sm font-bold">
              CG
            </div>
            <span className="font-semibold text-slate-800">
              ComplianceGuardian
            </span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">{session.tenantId}</span>
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                session.role === "reviewer"
                  ? "bg-amber-100 text-amber-700"
                  : session.role === "admin"
                    ? "bg-purple-100 text-purple-700"
                    : "bg-brand-100 text-brand-700"
              }`}
            >
              {session.role}
            </span>
            <button
              onClick={() => signOut()}
              className="text-slate-500 hover:text-slate-800"
            >
              Sign out
            </button>
          </div>
        </div>
        <nav className="max-w-6xl mx-auto px-4 flex gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `px-3 py-2 text-sm border-b-2 -mb-px ${
                  isActive
                    ? "border-brand-600 text-brand-700 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
