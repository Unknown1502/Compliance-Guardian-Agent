// Typed client for the platform API.
//
// Every call carries a Firebase ID token and nothing else. The console never
// sends a tenant id, a role, or any other authorization hint — the backend
// derives all of that from the verified token, so nothing here can widen
// access by lying about who it is.

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type TokenFn = () => Promise<string>;

async function get<T>(getToken: TokenFn, path: string): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/**
 * The console's only write, and deliberately the narrowest one that solves a
 * real problem: it controls a workspace's ACCESS and never touches its
 * records. No document, verdict or audit entry is reachable from here.
 *
 * A console able to rewrite compliance history would be a liability in a
 * product whose whole claim is that history cannot be rewritten. One unable
 * to stop an abusive or non-paying tenant is merely incomplete.
 */
async function put<T>(getToken: TokenFn, path: string, body: unknown): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// -- shapes ----------------------------------------------------------------

export interface WhoAmI {
  uid: string;
  email: string;
  platform_admin: boolean;
}

export interface TenantStatusResult {
  tenant_id: string;
  name: string;
  status: string;
  status_reason: string;
  changed: boolean;
}

export interface TenantRow {
  status: string;
  status_reason: string;
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

export interface Overview {
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
  tenants: TenantRow[];
}

export interface DocumentRow {
  tenant_id: string;
  tenant_name: string;
  document_id: string;
  filename: string;
  status: string;
  created_at: string;
  risk_score: number | null;
  decision: string | null;
  citations: string[];
}

export interface ReviewRow {
  tenant_id: string;
  tenant_name: string;
  check_id: string;
  document_id: string;
  risk_score: number;
  citations: string[];
  assigned_to: string | null;
  comments: number;
  created_at: string;
  age_hours: number;
}

export interface AgentHealth {
  agent: string;
  succeeded: number;
  failed: number;
  success_rate: number | null;
  last_seen: string | null;
  latency_ms: null;
  queue_depth: null;
}

export interface ServiceStatus {
  service: string;
  status: "healthy" | "degraded" | "unavailable" | "unknown";
  detail: string;
}

export interface SecurityEvent {
  created_at: string;
  tenant_id: string;
  actor: string;
  action: string;
  category: string;
}

export interface AuditEvent {
  event_id: string;
  tenant_id: string;
  actor: string;
  action: string;
  created_at: string;
}

export interface PlatformRule {
  id: string;
  description: string;
  check_type: string;
  severity: string;
  /** Parameter NAMES only. Values are tenant documents and never cross this boundary. */
  params: string[];
}

export interface PlatformRuleset {
  industry: string;
  jurisdiction: string;
  rule_set_version: string;
  rule_count: number;
  required_fields: string[];
  severity_counts: Record<string, number>;
  check_type_counts: Record<string, number>;
  tenants_assigned: number;
  rules: PlatformRule[];
}

export interface ComplianceIntel {
  risk_distribution: { low: number; medium: number; high: number };
  top_rules: { rule_id: string; hits: number }[];
  highest_risk_tenants: {
    tenant_id: string;
    name: string;
    checks: number;
    avg_risk: number;
  }[];
  jurisdictions: Record<string, number>;
  rulesets: {
    industry: string;
    jurisdiction: string;
    version: string;
    rules: number;
  }[];
}

// -- calls -----------------------------------------------------------------

export const api = {
  whoami: (t: TokenFn) => get<WhoAmI>(t, "/api/platform/whoami"),
  overview: (t: TokenFn) => get<Overview>(t, "/api/platform/overview"),
  documents: (t: TokenFn, limit = 200) =>
    get<DocumentRow[]>(t, `/api/platform/documents?limit=${limit}`),
  reviews: (t: TokenFn) => get<ReviewRow[]>(t, "/api/platform/reviews"),
  agents: (t: TokenFn) => get<AgentHealth[]>(t, "/api/platform/agents"),
  compliance: (t: TokenFn) => get<ComplianceIntel>(t, "/api/platform/compliance"),
  security: (t: TokenFn, limit = 200) =>
    get<SecurityEvent[]>(t, `/api/platform/security?limit=${limit}`),
  system: (t: TokenFn) => get<ServiceStatus[]>(t, "/api/platform/system"),
  rulesets: (t: TokenFn) => get<PlatformRuleset[]>(t, "/api/platform/rulesets"),
  setTenantStatus: (t: TokenFn, tenantId: string, status: "active" | "suspended", reason: string) =>
    put<TenantStatusResult>(t, `/api/platform/tenants/${tenantId}/status`, { status, reason }),
  audit: (t: TokenFn, limit = 200) =>
    get<{ count: number; events: AuditEvent[] }>(t, `/api/platform/audit?limit=${limit}`),
};
