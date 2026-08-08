// Operator console API client.
//
// Talks only to /api/platform/*. Those endpoints are read-only and gated by a
// server-side allowlist, so the worst a compromised console session can do is
// read — it cannot alter a customer's compliance records.

import { getAuth, signInWithEmailAndPassword, signOut } from "firebase/auth";
import { initializeApp } from "firebase/app";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
const PROJECT = import.meta.env.VITE_GCP_PROJECT ?? "cg-local";

initializeApp({
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY ?? "dev-key",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN ?? `${PROJECT}.firebaseapp.com`,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID ?? PROJECT,
});

export const auth = getAuth();
export const login = (email: string, password: string) =>
  signInWithEmailAndPassword(auth, email, password);
export const logout = () => signOut(auth);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const user = auth.currentUser;
  if (!user) throw new ApiError(401, "Not signed in");
  const token = await user.getIdToken();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    // The API answers 404 for a non-allowlisted caller so the routes do not
    // announce themselves. Translate that into something a real operator can
    // act on, without claiming the route is missing.
    if (res.status === 404) {
      throw new ApiError(404, "This account is not authorised for the operator console.");
    }
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export interface PlatformTenantRow {
  tenant_id: string;
  name: string;
  industry: string;
  jurisdiction: string;
  plan_tier: string;
  created_at: string;
  members: number;
  documents: number;
  checks: number;
  open_escalations: number;
}

export interface PlatformOverview {
  generated_at: string;
  tenants_total: number;
  tenants_by_plan: Record<string, number>;
  members_total: number;
  documents_total: number;
  checks_total: number;
  checks_auto_approved: number;
  checks_escalated: number;
  checks_rejected: number;
  open_escalations_total: number;
  signups_last_7d: number;
  signups_last_30d: number;
  tenants: PlatformTenantRow[];
}

export interface AuditEvent {
  event_id: string;
  tenant_id: string;
  actor: string;
  action: string;
  created_at: string;
}

export const whoami = () =>
  get<{ uid: string; email: string; platform_admin: boolean }>("/api/platform/whoami");

export const fetchOverview = () => get<PlatformOverview>("/api/platform/overview?limit=200");

export const fetchAudit = () =>
  get<{ count: number; events: AuditEvent[] }>("/api/platform/audit?limit=100");
