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

export async function signup(
  email: string,
  password: string,
  businessName: string,
  jobTitle: string,
): Promise<{ tenant_id: string; uid: string; email: string }> {
  const res = await fetch(`${API_BASE_URL}/api/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      business_name: businessName,
      job_title: jobTitle,
      industry: "healthcare_ndis",
      jurisdiction: "AU",
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

export async function createCheckout(
  session: Session,
  plan: "oneoff" | "subscription",
): Promise<{ checkout_url: string }> {
  const res = await authedFetch(session, "/api/billing/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
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
