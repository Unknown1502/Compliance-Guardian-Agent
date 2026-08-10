// API Gateway client. Attaches the session bearer token to every request and
// surfaces typed helpers for the endpoints the dashboard uses.

import { API_BASE_URL } from "../config";
import type { ComplianceCheck, DocumentRecord, Session, TaskRecord } from "../types";

async function authedFetch(
  session: Session,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await session.getToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore parse errors */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export interface RulesetOptionRow {
  industry: string;
  jurisdiction: string;
  rule_set_version: string;
  rule_count: number;
}

/**
 * Which industry/jurisdiction pairs a workspace can be created for.
 *
 * Public — signup needs it before an account exists. Read from the server
 * rather than listed here, because a hardcoded list is exactly what caused
 * every workspace to be created as Australian NDIS regardless of where the
 * business operated.
 */
export async function getAvailableRulesets(): Promise<RulesetOptionRow[]> {
  return jsonOrThrow(await fetch(`${API_BASE_URL}/api/rulesets/available`));
}

export interface JurisdictionChange {
  industry: string;
  jurisdiction: string;
  rule_set_version: string;
  rule_count: number;
  changed: boolean;
}

/**
 * Move the caller's workspace to a different industry / jurisdiction.
 *
 * Owner or admin. Does not re-check past documents — completed verdicts stay
 * cited to the ruleset actually applied at the time.
 */
export async function changeJurisdiction(
  session: Session,
  industry: string,
  jurisdiction: string,
): Promise<JurisdictionChange> {
  const res = await authedFetch(session, "/api/admin/jurisdiction", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ industry, jurisdiction }),
  });
  return jsonOrThrow(res);
}

export async function signup(
  email: string,
  password: string,
  businessName: string,
  jobTitle: string,
  industry: string,
  jurisdiction: string,
): Promise<{ tenant_id: string; uid: string; email: string }> {
  const res = await fetch(`${API_BASE_URL}/api/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      business_name: businessName,
      job_title: jobTitle,
      // Chosen by the customer, then re-validated server-side against the
      // rulesets that actually exist — the client cannot invent a pair.
      industry,
      jurisdiction,
    }),
  });
  return jsonOrThrow(res);
}

export async function uploadDocument(
  session: Session,
  file: File,
): Promise<{ document_id: string; task_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("source", "upload");
  const res = await authedFetch(session, "/api/documents", {
    method: "POST",
    body: form,
  });
  return jsonOrThrow(res);
}

export async function getDocument(
  session: Session,
  documentId: string,
): Promise<DocumentRecord> {
  return jsonOrThrow(await authedFetch(session, `/api/documents/${documentId}`));
}

export async function triggerCheck(
  session: Session,
  documentId: string,
): Promise<TaskRecord> {
  const res = await authedFetch(session, "/api/compliance/checks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId }),
  });
  return jsonOrThrow(res);
}

export async function getCheck(
  session: Session,
  checkId: string,
): Promise<ComplianceCheck> {
  return jsonOrThrow(
    await authedFetch(session, `/api/compliance/checks/${checkId}`),
  );
}

export async function decideCheck(
  session: Session,
  checkId: string,
  action: "approve" | "reject",
): Promise<ComplianceCheck> {
  const res = await authedFetch(session, `/api/compliance/checks/${checkId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return jsonOrThrow(res);
}

export async function getActiveRuleset(
  session: Session,
): Promise<import("../types").RulesetSummary> {
  return jsonOrThrow(await authedFetch(session, "/api/ruleset"));
}

/* --- Payments -------------------------------------------------------------
 *
 * Note what is never sent from here: an amount. The plan is a name; the
 * server looks up the price. And nothing on this page can grant a plan —
 * every call below ends in a server-side verification.
 */

export type Plan = "oneoff" | "subscription";

export interface ProviderOption {
  provider: "razorpay" | "paypal";
  available: boolean;
  amount_minor: number | null;
  currency: string | null;
}

export interface Entitlement {
  /** free_report_available | paid_report_available | payment_required */
  state: string;
  /** free | single | pro — a one-time buyer is never described as Pro. */
  source: string;
  granted: number;
  consumed: number;
  remaining: number;
  expires_at: string | null;
  plan_tier: string;
}

/**
 * The workspace's report allowance.
 *
 * Advisory only. The authoritative check runs inside a transaction on the
 * server when a check is triggered, so a client that lies about this gains
 * nothing — it just gets a 402 a moment later.
 */
export async function getEntitlement(session: Session): Promise<Entitlement> {
  return jsonOrThrow(await authedFetch(session, "/api/entitlement"));
}

export async function getPaymentProviders(
  session: Session,
): Promise<{ oneoff: ProviderOption[]; subscription: ProviderOption[] }> {
  return jsonOrThrow(await authedFetch(session, "/api/billing/providers"));
}

export async function createRazorpayOrder(
  session: Session,
  plan: Plan,
): Promise<{ order_id: string; amount: number; currency: string; key_id: string }> {
  const res = await authedFetch(session, "/api/billing/razorpay/order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
  return jsonOrThrow(res);
}

export interface PaymentResult {
  plan_tier: string;
  provider: string;
  reference: string;
  amount_minor: number;
  currency: string;
}

export async function verifyRazorpayPayment(
  session: Session,
  fields: {
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  },
): Promise<PaymentResult> {
  const res = await authedFetch(session, "/api/billing/razorpay/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return jsonOrThrow(res);
}

export async function createPayPalOrder(
  session: Session,
  plan: Plan,
): Promise<{ order_id: string; status: string; approve_url: string }> {
  const res = await authedFetch(session, "/api/billing/paypal/order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
  return jsonOrThrow(res);
}

export async function capturePayPalOrder(
  session: Session,
  orderId: string,
): Promise<PaymentResult> {
  const res = await authedFetch(session, "/api/billing/paypal/capture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order_id: orderId }),
  });
  return jsonOrThrow(res);
}

export async function getAuditLogs(
  session: Session,
): Promise<{ events: import("../types").AuditEvent[]; count: number }> {
  return jsonOrThrow(await authedFetch(session, "/api/audit-logs?limit=100"));
}

export async function getTask(
  session: Session,
  taskId: string,
): Promise<TaskRecord> {
  return jsonOrThrow(await authedFetch(session, `/api/tasks/${taskId}`));
}

// -- team ------------------------------------------------------------------

export interface TeamMember {
  uid: string;
  email: string;
  role: string;
  job_title: string;
  created_at: string;
}

export async function listTeam(session: Session): Promise<TeamMember[]> {
  return jsonOrThrow(await authedFetch(session, "/api/team"));
}

export async function addTeamMember(
  session: Session,
  body: { email: string; password: string; role: string; job_title: string },
): Promise<TeamMember> {
  return jsonOrThrow(
    await authedFetch(session, "/api/team", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function removeTeamMember(session: Session, uid: string): Promise<void> {
  const res = await authedFetch(session, `/api/team/${uid}`, { method: "DELETE" });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new ApiError(res.status, b.detail ?? res.statusText);
  }
}

// -- settings: notifications / retention / api keys -------------------------

export interface NotificationSettings {
  slack_configured: boolean;
  slack_webhook_masked: string;
}

export async function getNotificationSettings(session: Session): Promise<NotificationSettings> {
  return jsonOrThrow(await authedFetch(session, "/api/settings/notifications"));
}

export async function putNotificationSettings(
  session: Session,
  slackWebhookUrl: string,
): Promise<NotificationSettings> {
  return jsonOrThrow(
    await authedFetch(session, "/api/settings/notifications", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slack_webhook_url: slackWebhookUrl }),
    }),
  );
}

export async function testNotification(session: Session): Promise<{ sent: boolean }> {
  return jsonOrThrow(
    await authedFetch(session, "/api/settings/notifications/test", { method: "POST" }),
  );
}

export interface RetentionSettings {
  retention_days: number;
  minimum_days: number;
  enabled: boolean;
}

export async function getRetentionSettings(session: Session): Promise<RetentionSettings> {
  return jsonOrThrow(await authedFetch(session, "/api/settings/retention"));
}

export async function putRetentionSettings(
  session: Session,
  retentionDays: number,
): Promise<RetentionSettings> {
  return jsonOrThrow(
    await authedFetch(session, "/api/settings/retention", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retention_days: retentionDays }),
    }),
  );
}

export interface RetentionPreview {
  retention_days: number;
  cutoff: string | null;
  considered: number;
  deleted_count: number;
  deleted: string[];
  skipped_reason: string | null;
  dry_run: boolean;
}

export async function previewRetention(session: Session): Promise<RetentionPreview> {
  return jsonOrThrow(
    await authedFetch(session, "/api/settings/retention/preview", { method: "POST" }),
  );
}

export interface ApiKey {
  key_id: string;
  name: string;
  display_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface ApiKeyCreated extends ApiKey {
  plaintext_key: string;
}

export async function listApiKeys(session: Session): Promise<ApiKey[]> {
  return jsonOrThrow(await authedFetch(session, "/api/keys"));
}

export async function createApiKey(session: Session, name: string): Promise<ApiKeyCreated> {
  return jsonOrThrow(
    await authedFetch(session, "/api/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  );
}

export async function revokeApiKey(session: Session, keyId: string): Promise<void> {
  const res = await authedFetch(session, `/api/keys/${keyId}`, { method: "DELETE" });
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new ApiError(res.status, b.detail ?? res.statusText);
  }
}

// -- document content / oversight -------------------------------------------

export async function getDocumentContent(
  session: Session,
  documentId: string,
): Promise<import("../types").DocumentContent> {
  return jsonOrThrow(await authedFetch(session, `/api/documents/${documentId}/content`));
}

export async function addCheckComment(
  session: Session,
  checkId: string,
  body: string,
): Promise<ComplianceCheck> {
  return jsonOrThrow(
    await authedFetch(session, `/api/compliance/checks/${checkId}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }),
  );
}

export async function assignCheck(
  session: Session,
  checkId: string,
  assigneeUid: string | null,
): Promise<ComplianceCheck> {
  return jsonOrThrow(
    await authedFetch(session, `/api/compliance/checks/${checkId}/assignee`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignee_uid: assigneeUid }),
    }),
  );
}

export async function getReviewQueue(session: Session): Promise<ComplianceCheck[]> {
  return jsonOrThrow(await authedFetch(session, "/api/compliance/queue"));
}

// --- Analytics -------------------------------------------------------------

export interface WeekBucket {
  week_start: string;
  week_end: string;
  total_checks: number;
  auto_approved: number;
  escalated: number;
  rejected: number;
  top_failing_rule_ids: string[];
}

export interface TrendsResponse {
  tenant_id: string;
  weeks: WeekBucket[];
  top_violations: { rule_id: string; count: number }[];
}

export async function fetchTrends(
  session: Session,
  weeks = 12,
): Promise<TrendsResponse> {
  return jsonOrThrow(await authedFetch(session, `/api/analytics/trends?weeks=${weeks}`));
}

// --- Tenant admin ----------------------------------------------------------

export interface TenantAdminOverview {
  tenant_id: string;
  name: string;
  industry: string;
  jurisdiction: string;
  plan_tier: string;
  created_at: string;
  documents_total: number;
  documents_by_status: Record<string, number>;
  checks_total: number;
  checks_auto_approved: number;
  checks_escalated: number;
  checks_rejected: number;
  open_escalations: number;
  members_total: number;
  members_by_role: Record<string, number>;
  api_keys_active: number;
  top_failing_rules: string[];
  slack_configured: boolean;
  retention_days: number;
}

export async function fetchTenantAdminOverview(
  session: Session,
): Promise<TenantAdminOverview> {
  return jsonOrThrow(await authedFetch(session, "/api/admin/overview"));
}

// --- Remediation -----------------------------------------------------------

export interface RemediationItem {
  rule_id: string;
  title: string;
  action: string;
  blocking: boolean;
  estimated_minutes: number;
  severity: string;
}

export interface RemediationPlan {
  plan_id: string;
  check_id: string;
  document_id: string;
  items: RemediationItem[];
  total_estimated_minutes: number;
  used_fixture: boolean;
  created_at: string;
}

/** Returns null when no plan exists yet (a clean check, or one still running). */
export async function fetchRemediationPlan(
  session: Session,
  checkId: string,
): Promise<RemediationPlan | null> {
  const res = await authedFetch(session, `/api/checks/${checkId}/remediation`);
  if (res.status === 404) return null;
  return jsonOrThrow(res);
}
