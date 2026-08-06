// Shared types mirroring the backend data model (subset used by the UI).

export type DocumentStatus = "pending" | "processed" | "failed";
export type CheckDecision = "auto_approved" | "escalated" | "rejected";
export type VerdictStatus = "pass" | "fail" | "uncertain";

export interface ReviewComment {
  comment_id: string;
  author_uid: string;
  author_email: string;
  body: string;
  created_at: string;
}

export interface DocumentContent {
  document_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  content_hash: string;
  text: string | null;
  base64: string | null;
  hash_verified: boolean;
}

export interface DocumentRecord {
  document_id: string;
  tenant_id: string;
  source: string;
  storage_ref: string;
  extracted_fields: Record<string, unknown>;
  content_hash?: string;
  content_type?: string;
  size_bytes?: number;
  filename?: string;
  created_at?: string;
  status: DocumentStatus;
}

export interface RuleVerdict {
  rule_id: string;
  status: VerdictStatus;
  confidence: number;
  explanation: string;
  triggering_data_point: string | null;
}

export interface ComplianceCheck {
  check_id: string;
  document_id: string;
  tenant_id: string;
  rule_set_version: string;
  risk_score: number;
  justification: string;
  citations: string[];
  decision: CheckDecision;
  reviewer_id: string | null;
  rule_verdicts: RuleVerdict[];
  assigned_to?: string | null;
  comments?: ReviewComment[];
  created_at?: string;
}

export interface RulesetRule {
  id: string;
  description: string;
  check_type: string;
  severity: "low" | "medium" | "high" | "critical";
}

export interface RulesetSummary {
  rule_set_version: string;
  industry: string;
  jurisdiction: string;
  required_fields: string[];
  rules: RulesetRule[];
}

export interface AuditEvent {
  event_id: string;
  tenant_id: string;
  actor: string;
  action: string;
  before_state: string | null;
  after_state: string | null;
  created_at: string;
}

export interface TaskRecord {
  task_id: string;
  tenant_id: string;
  task_type: string;
  target_ref: string;
  status: string;
  result: Record<string, unknown>;
  error: string | null;
}

export type Role = "owner" | "reviewer" | "admin";

export interface Session {
  uid: string;
  tenantId: string;
  role: Role;
  email?: string;
  getToken: () => Promise<string>;
}
