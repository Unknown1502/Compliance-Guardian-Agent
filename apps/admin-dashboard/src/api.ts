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

async function post<T>(getToken: TokenFn, path: string, body: unknown): Promise<T> {
  const token = await getToken();
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
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
  entitlement_source: string;
  reports_granted: number;
  reports_consumed: number;
  tenant_id: string;
  name: string;
  industry: string;
  jurisdiction: string;
  /** Empty on tenants created before this field existed — render as-is. */
  country_code: string;
  country_name: string;
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

/**
 * email/role/job_title/created_at come from Firestore, the source of truth
 * for display. disabled/email_verified/last_sign_in come from Firebase Auth,
 * the source of truth for identity — Firestore has neither field, so these
 * are never fabricated client-side.
 */
export interface PlatformUserRow {
  uid: string;
  email: string;
  role: string;
  job_title: string;
  tenant_id: string;
  tenant_name: string;
  created_at: string;
  email_verified: boolean;
  disabled: boolean;
  last_sign_in: string | null;
  status: "active" | "disabled" | "pending";
}

export interface PlatformUsersPage {
  total: number;
  limit: number;
  offset: number;
  users: PlatformUserRow[];
}

export interface PlatformUserDetail extends PlatformUserRow {
  reviews_assigned: number;
  reviews_decided: number;
  recent_activity: SecurityEvent[];
}

export interface UserStatusResult {
  uid: string;
  disabled: boolean;
  changed: boolean;
}

export interface UserRoleResult {
  uid: string;
  role: string;
  changed: boolean;
}

export interface DocumentReprocessResult {
  document_id: string;
  tenant_id: string;
  task_id: string;
  task_type: string;
}

export interface UsersQuery {
  limit?: number;
  offset?: number;
  q?: string;
  role?: string;
  tenantId?: string;
  status?: string;
  sort?: string;
  direction?: "asc" | "desc";
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

export interface SupportMessageRow {
  message_id: string;
  sender: "customer" | "support";
  author_email: string;
  body: string;
  /** Operator-only. Never returned on any customer-facing route. */
  internal: boolean;
  created_at: string;
}

export interface SupportTicketRow {
  reference: string;
  ticket_id: string;
  tenant_id: string;
  first_name: string;
  email: string;
  phone: string;
  category: string;
  subject: string;
  status: string;
  priority: string;
  assigned_to: string;
  created_at: string;
  updated_at: string;
  messages: SupportMessageRow[];
}

export interface SupportPermissions {
  can_reply: boolean;
  agents_configured: boolean;
  me: string;
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
  support: (t: TokenFn, limit = 200) =>
    get<SupportTicketRow[]>(t, `/api/platform/support?limit=${limit}`),
  supportPermissions: (t: TokenFn) =>
    get<SupportPermissions>(t, "/api/platform/support/permissions"),
  supportReply: (t: TokenFn, ticketId: string, body: string, internal: boolean) =>
    post<SupportTicketRow>(t, `/api/platform/support/${ticketId}/reply`, { body, internal }),
  supportUpdate: (
    t: TokenFn,
    ticketId: string,
    patch: { status?: string; priority?: string; assigned_to?: string },
  ) => put<SupportTicketRow>(t, `/api/platform/support/${ticketId}`, { assigned_to: "", ...patch }),
  audit: (t: TokenFn, limit = 200) =>
    get<{ count: number; events: AuditEvent[] }>(t, `/api/platform/audit?limit=${limit}`),
  users: (t: TokenFn, params: UsersQuery = {}) => {
    const sp = new URLSearchParams();
    if (params.limit) sp.set("limit", String(params.limit));
    if (params.offset) sp.set("offset", String(params.offset));
    if (params.q) sp.set("q", params.q);
    if (params.role) sp.set("role", params.role);
    if (params.tenantId) sp.set("tenant_id", params.tenantId);
    if (params.status) sp.set("status", params.status);
    if (params.sort) sp.set("sort", params.sort);
    if (params.direction) sp.set("direction", params.direction);
    const qs = sp.toString();
    return get<PlatformUsersPage>(t, `/api/platform/users${qs ? `?${qs}` : ""}`);
  },
  userDetail: (t: TokenFn, uid: string) =>
    get<PlatformUserDetail>(t, `/api/platform/users/${encodeURIComponent(uid)}`),
  setUserStatus: (t: TokenFn, uid: string, disabled: boolean, reason: string) =>
    put<UserStatusResult>(t, `/api/platform/users/${encodeURIComponent(uid)}/status`, {
      disabled,
      reason,
    }),
  setUserRole: (t: TokenFn, uid: string, role: string, reason: string) =>
    put<UserRoleResult>(t, `/api/platform/users/${encodeURIComponent(uid)}/role`, {
      role,
      reason,
    }),
  retryExtraction: (t: TokenFn, documentId: string, tenantId: string) =>
    post<DocumentReprocessResult>(
      t,
      `/api/platform/documents/${encodeURIComponent(documentId)}/retry-extraction?tenant_id=${encodeURIComponent(tenantId)}`,
      {},
    ),
  reanalyzeDocument: (t: TokenFn, documentId: string, tenantId: string) =>
    post<DocumentReprocessResult>(
      t,
      `/api/platform/documents/${encodeURIComponent(documentId)}/reanalyze?tenant_id=${encodeURIComponent(tenantId)}`,
      {},
    ),
};
