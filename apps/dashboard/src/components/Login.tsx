import { useState } from "react";
import { AUTH_MODE } from "../config";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";

// Seeded demo tenants (dev mode convenience).
const DEMO_TENANTS = [
  { id: "tenant-sunrise-care", label: "Sunrise Community Care (NDIS)" },
  { id: "tenant-coastal-fresh", label: "Coastal Fresh Distributors" },
];

export function Login() {
  const { devSignIn, firebaseSignIn } = useAuth();
  const [tenantId, setTenantId] = useState(DEMO_TENANTS[0].id);
  const [role, setRole] = useState<Role>("owner");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleDev = () => {
    const uid = `${role}-${tenantId}`;
    devSignIn(tenantId, role, uid);
  };

  const handleFirebase = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await firebaseSignIn(email, password);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100">
      <div className="bg-white shadow-lg rounded-xl p-8 w-full max-w-md">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-9 h-9 rounded-lg bg-brand-600 text-white grid place-items-center font-bold">
            CG
          </div>
          <h1 className="text-xl font-semibold text-slate-800">
            ComplianceGuardian
          </h1>
        </div>

        {AUTH_MODE === "dev" ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              Local dev sign-in. Pick a tenant and role to explore the dashboard.
            </p>
            <label className="block text-sm font-medium text-slate-700">
              Tenant
              <select
                className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2"
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
            <label className="block text-sm font-medium text-slate-700">
              Role
              <select
                className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
              >
                <option value="owner">Owner</option>
                <option value="reviewer">Reviewer</option>
                <option value="admin">Admin</option>
              </select>
            </label>
            <button
              onClick={handleDev}
              className="w-full bg-brand-600 hover:bg-brand-700 text-white rounded-lg py-2 font-medium"
            >
              Enter dashboard
            </button>
          </div>
        ) : (
          <form onSubmit={handleFirebase} className="space-y-4">
            <input
              type="email"
              placeholder="Email"
              className="w-full border border-slate-300 rounded-lg px-3 py-2"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              type="password"
              placeholder="Password"
              className="w-full border border-slate-300 rounded-lg px-3 py-2"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="submit"
              className="w-full bg-brand-600 hover:bg-brand-700 text-white rounded-lg py-2 font-medium"
            >
              Sign in
            </button>
          </form>
        )}
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
