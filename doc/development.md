Problem & scope
This system automates recurring compliance and reporting work for small businesses — document intake, rule checking, audit logging, and escalation — using Gemini-powered agents with human approval gates for high-risk cases.

1. Requirements
Functional

Ingest documents/data (PDF, email, spreadsheet, form) from SMB sources.

Extract structured fields via Gemini.

Check extracted data against a configurable ruleset (industry, jurisdiction).

Score risk/compliance status; auto-approve low-risk, escalate high-risk to a human.

Log every decision immutably for audit purposes.

Generate periodic compliance reports on demand.

Provide dashboard for SMB owner and reviewer roles.

Non-functional

Auditability: every AI decision must be traceable to source data and rule citation.

Latency: document processing result within 60 seconds for standard documents.

Availability: 99.5% uptime target for MVP.

Data privacy: encryption at rest/in transit, tenant data isolation.

Explainability: every risk score must include a plain-language justification.

2. High-level architecture
Client (dashboard + integrations) → API Gateway/Auth (Cloud Run) → Cloud Tasks →
sub-agents (Ingestion, Compliance) → Gemini API for reasoning → Firestore for live
task/document state → BigQuery for immutable audit logs → Cloud Storage for raw files.
Escalation Service handles reviewer decisions; Reporting Agent produces summaries and
is driven both on demand and by Cloud Workflows + Scheduler.

NOTE — this originally described an "Orchestrator Agent (Cloud Run)". That was the
design intent, not what shipped. `services/orchestrator/` is a **library imported by
the API Gateway**, not a deployed service: Cloud Build builds five images
(api-gateway, ingestion-agent, compliance-agent, escalation-service, reporting-agent)
and there is no sixth. The gateway owns task lifecycle and dispatches through Cloud
Tasks itself. Diagrams predating 2026-08-12 show the orchestrator as a service and
omit the Escalation Service entirely; see the README for the current architecture.

3. Low-level component design
Each service exposes a narrow REST contract. The gateway owns task lifecycle via the
orchestrator library. Compliance service chains a rule engine → Gemini reasoning
module → risk scorer. Reporting service pulls from a template store and fills reports
using Gemini-generated summaries.

Internal routes live on the agents, never on the gateway. The gateway is
`allUsers`-invokable so the browser can reach it, which means an `/internal/*` route
placed there would be publicly reachable. The agents are IAM-locked to `cg-runtime`,
and that is what actually protects them.

4. Data model (core entities)
Tenant — business id, industry, jurisdiction, plan tier.

Document — id, tenant_id, source, raw_file_ref, extracted_fields (JSON), status.

ComplianceCheck — id, document_id, rule_set_version, risk_score, citations, decision (auto/escalated), reviewer_id, timestamp.

AuditLog (BigQuery, append-only) — event_id, tenant_id, actor (agent/human), action, before/after state, timestamp.

Report — id, tenant_id, period, generated_by, content_ref.

5. Suggested repo file structure
text
compliance-agent/
├── apps/
│   ├── dashboard/                 # React frontend
│   └── api-gateway/                # Auth + routing
├── services/
│   ├── orchestrator/               # Task lifecycle, Cloud Run service
│   ├── ingestion-agent/            # Document parsing via Gemini
│   ├── compliance-agent/           # Rule engine + risk scoring
│   ├── reporting-agent/            # Report generation
│   └── escalation-service/         # Human-in-the-loop routing
├── shared/
│   ├── auth-middleware/
│   ├── audit-logger/
│   └── schema-validators/
├── infra/
│   ├── terraform/                  # Cloud Run, Firestore, BigQuery, IAM
│   └── workflows/                  # Cloud Workflows YAML definitions
├── rulesets/
│   └── {industry}/{jurisdiction}.yaml
├── tests/
│   ├── unit/
│   └── integration/
└── docs/
    ├── architecture.md
    └── api-spec.yaml
6. Tech stack mapping to Google Cloud requirement
Gemini API (AI Studio or Vertex AI) for extraction/reasoning; Cloud Run for all services; Firestore for live state; BigQuery for audit analytics; Cloud Tasks + Workflows for orchestration — satisfying the mandatory Gemini call and Google Cloud product requirement.

7. Build sequence (90-day-compatible)
Weeks 1–2: data model, auth, one ruleset, ingestion agent.

Weeks 3–4: compliance agent + Gemini integration + risk scoring.

Weeks 5–6: escalation flow, dashboard, audit logging.

Weeks 7–8: reporting agent, onboarding first real SMB customers.

Weeks 9–12: iterate on feedback, collect revenue/usage evidence for submission.

1. Product requirements document (PRD)
Problem statement: 73% of small businesses spend 40+ hours a year on compliance-related work, and data security/compliance is now the #1 cited barrier to SMBs adopting AI agents more broadly. This product removes that friction directly.

Target users: small business owners (10–100 employees), operations staff, and optionally a human compliance reviewer/advisor role.

Core user stories:

As an SMB owner, I upload a document (invoice, policy form, client contract) and get an instant compliance risk assessment.

As an SMB owner, I get auto-approval for low-risk items and see exactly why.

As a reviewer, I get escalated only the high-risk exceptions with full context.

As an SMB owner, I can pull an audit-ready compliance report at any time.

Out of scope for MVP: core banking integrations, multi-jurisdiction legal advice, litigation support.

2. Functional & non-functional requirements
Functional

Document/data ingestion from upload, email forward, or connected SaaS (Google Workspace, QuickBooks).

Field extraction and classification via Gemini.

Rule evaluation against a configurable, versioned ruleset per industry/jurisdiction.

Risk scoring with plain-language justification and rule citations.

Auto-approve / escalate branching logic.

Immutable audit logging for every decision.

On-demand and scheduled compliance report generation.

Role-based dashboard (owner, reviewer, admin).

Non-functional

Processing latency: under 60 seconds per standard document.

Availability: 99.5% target.

Data isolation per tenant; encryption at rest and in transit.

Full explainability: every AI decision traceable to source data + rule version.

Audit trail immutability (append-only log).

3. High-level architecture
Client (dashboard + integrations) → API Gateway/Auth (Cloud Run) → Cloud Tasks →
sub-agents (Ingestion, Compliance) → Gemini API for reasoning → Firestore for live task
state → BigQuery for audit logs → Cloud Storage for raw files. Escalation Service for
reviewer decisions, Reporting Agent for summaries, Cloud Workflows + Scheduler for the
weekly run. See the note in section 2 — the orchestrator is a library inside the
gateway, not a deployed Cloud Run service.

4. Low-level component design
The gateway exposes task lifecycle routes via the orchestrator library. Compliance
service chains Rule Engine → Gemini Reasoning Module → Risk Scorer → Report Generator,
with a Template Store feeding standardized report formats.

5. Data model (ERD)
Tenant → Documents → Compliance Checks → Audit Logs, with Compliance Checks optionally escalated to a Reviewer, and Tenants generating Reports over time. Full entity/field breakdown is in the ERD diagram above.

6. Deployment architecture
Users hit Cloud CDN → Load Balancer → separate Cloud Run services for Dashboard API, Orchestrator, and each agent (Ingestion, Compliance, Reporting). Agents call Gemini directly; Compliance writes to Firestore (live state) and BigQuery (audit trail); Ingestion writes raw files to Cloud Storage; async work runs through Cloud Tasks + Workflows. This satisfies the mandatory Gemini + Google Cloud product requirement.

7. Repo file structure
text
compliance-agent/
├── apps/
│   ├── dashboard/                 # React frontend
│   └── api-gateway/                # Auth + routing
├── services/
│   ├── orchestrator/               # Task lifecycle, Cloud Run service
│   ├── ingestion-agent/            # Document parsing via Gemini
│   ├── compliance-agent/           # Rule engine + risk scoring
│   ├── reporting-agent/            # Report generation
│   └── escalation-service/         # Human-in-the-loop routing
├── shared/
│   ├── auth-middleware/
│   ├── audit-logger/
│   └── schema-validators/
├── infra/
│   ├── terraform/                  # Cloud Run, Firestore, BigQuery, IAM
│   └── workflows/                  # Cloud Workflows YAML definitions
├── rulesets/
│   └── {industry}/{jurisdiction}.yaml
├── tests/
│   ├── unit/
│   └── integration/
└── docs/
    ├── architecture.md
    └── api-spec.yaml
8. API contract sketch
text
POST   /tasks                  → create ingestion/compliance task
GET    /tasks/:id               → task status + result
GET    /documents/:id            → extracted fields + status
POST   /compliance/checks        → trigger a check
GET    /compliance/checks/:id    → risk score, citations, decision
POST   /reports                  → generate report for a period
GET    /audit-logs?tenant_id=    → paginated audit trail
9. Agent decision flow (text sequence)
User uploads document → Orchestrator creates task.

Orchestrator calls Compliance Agent.

Compliance Agent calls Gemini with document + active ruleset → gets risk score + citations.

Result logged to BigQuery (audit trail) and Firestore (live state).

If risk score is low → auto-approve, notify user.

If risk score is high → escalate to human reviewer → reviewer decision logged → user notified.

10. 90-day build & rollout timeline
Weeks 1–2: auth, data model, ingestion agent. Weeks 3–4: compliance agent + Gemini integration + risk scoring. Weeks 5–6: escalation flow, dashboard, audit logging. Weeks 7–8: reporting agent, onboard first real SMB customers. Weeks 9–12: iterate based on feedback and collect revenue/usage evidence for submission.

11. Evidence checklist for XPRIZE submission
Signed-up/paying customers with names/contact (real, arms-length).

Revenue export (payment provider / bank) by month.

Screenshots/logs proving Gemini + Google Cloud product usage in production.

Audit log samples demonstrating AI-driven decisions and human escalation.

Short demo video (under 3 minutes) showing the end-to-end flow.

This gives you a full requirements-to-deployment package you can start executing against immediately, mapped directly to what the judges and the domain evidence say matters.

Prepared using Claude Sonnet 5.0 Thinking
also the well detail prompt

Here's a comprehensive, ready-to-use build prompt you can feed into Claude, Cursor, Gemini, or any AI coding assistant to scaffold this project end-to-end.

Master build prompt
text
ROLE
You are a senior full-stack AI engineer building a production-grade SaaS product for the "Build with Gemini XPRIZE" hackathon. This must be a real, working business — not a demo — deployed on Google Cloud with live Gemini API calls.

PRODUCT
Build "ComplianceGuardian" — an AI agent system that automates recurring compliance and back-office review work for small businesses (10-100 employees). SMBs upload documents (contracts, invoices, policy forms, client onboarding paperwork), and AI agents extract data, check it against configurable compliance rules, score risk, auto-approve low-risk items, and escalate high-risk items to a human reviewer — with a full immutable audit trail for every decision.

TARGET USER
Small business owners and operations managers who currently track compliance manually via spreadsheets/email and have no dedicated compliance staff. Primary category: Small Business Services. Secondary relevance: Professional Services Access.

CORE PRINCIPLE
AI must do real work in production — extraction, reasoning, scoring, drafting — not just chat. Every AI decision must be explainable (plain-language justification) and traceable (rule version + citation). Humans only handle escalated exceptions.

TECH STACK (MANDATORY)
- Gemini API (via Google AI Studio or Vertex AI) for all document extraction, rule reasoning, and report generation
- Google Cloud Run for every backend service (containerized, stateless)
- Firestore for live task/document state
- BigQuery for append-only audit logs
- Cloud Storage for raw uploaded files
- Cloud Tasks + Cloud Workflows for async orchestration of multi-step agent pipelines
- Firebase Auth for user authentication
- React (Vite) + Tailwind CSS for the dashboard frontend
- Node.js/TypeScript or Python (FastAPI) for backend services — pick one and be consistent

ARCHITECTURE TO IMPLEMENT
1. Orchestrator Service (Cloud Run): receives new tasks via POST /tasks, manages task lifecycle, dispatches to sub-agents via Cloud Tasks.
2. Ingestion Agent (Cloud Run): accepts uploaded file, calls Gemini to extract structured fields (entities, dates, amounts, parties, obligations), stores raw file in Cloud Storage, writes extracted JSON to Firestore.
3. Compliance Agent (Cloud Run): loads the relevant ruleset (YAML config per industry/jurisdiction), sends extracted data + ruleset context to Gemini, receives a risk score (0-100), a plain-language justification, and specific rule citations. Writes result to Firestore (live state) and BigQuery (immutable audit log).
4. Escalation Service: if risk score > threshold, creates a reviewer task, sends notification, waits for human decision (approve/reject/modify), logs the human decision to BigQuery with reviewer ID and timestamp.
5. Reporting Agent (Cloud Run): on-demand or scheduled (via Cloud Workflows cron), queries BigQuery for a date range, calls Gemini to summarize findings into a structured PDF/HTML report per tenant.

DATA MODEL
Implement these Firestore collections and BigQuery tables:
- tenants: tenant_id, name, industry, jurisdiction, plan_tier, created_at
- documents: document_id, tenant_id, source, storage_ref, extracted_fields (map), status (pending/processed/failed), created_at
- compliance_checks: check_id, document_id, tenant_id, rule_set_version, risk_score, justification, citations (array), decision (auto_approved/escalated/rejected), reviewer_id (nullable), created_at
- audit_logs (BigQuery, append-only): event_id, tenant_id, actor (agent_name or reviewer_id), action, before_state (json), after_state (json), created_at
- reports: report_id, tenant_id, period_start, period_end, generated_by, content_ref, created_at

API CONTRACT
Implement these REST endpoints with proper auth middleware (Firebase Auth JWT verification) and tenant isolation (every query scoped by tenant_id from the authenticated user's claims):
POST   /api/documents               (multipart upload, triggers ingestion)
GET    /api/documents/:id
POST   /api/compliance/checks       (trigger check on a document_id)
GET    /api/compliance/checks/:id
PATCH  /api/compliance/checks/:id   (reviewer decision: approve/reject)
GET    /api/audit-logs?tenant_id=&from=&to=
POST   /api/reports                 (generate report for period)
GET    /api/reports/:id
GET    /api/tasks/:id               (poll task status)

RULESET FORMAT
Define rulesets as versioned YAML files under /rulesets/{industry}/{jurisdiction}.yaml with this structure:
rule_set_version: "1.0.0"
industry: "healthcare_ndis"
jurisdiction: "AU"
rules:
  - id: "data_retention_period"
    description: "Client records must be retained for minimum 7 years"
    check_type: "date_comparison"
    severity: "high"
  - id: "consent_documentation"
    description: "Explicit consent record required before data processing"
    check_type: "field_presence"
    severity: "critical"

GEMINI PROMPT DESIGN (implement these as system prompts for each agent)
- Ingestion Agent prompt: "Extract the following structured fields from this document: [dynamic field list based on document type]. Return strict JSON. If a field is missing, return null and flag it as 'missing_required_field' if it's in the required list."
- Compliance Agent prompt: "You are a compliance risk analyst. Given this extracted data: {data} and this ruleset: {ruleset}, evaluate compliance for each rule. For each rule, return: rule_id, pass/fail/uncertain, confidence (0-1), plain-language explanation, and the specific data point that triggered the result. Then compute an overall risk_score (0-100) where 0 is fully compliant and 100 is severe violation. Never fabricate a citation — only cite rules explicitly provided."
- Reporting Agent prompt: "Summarize the following compliance check results for the period {start} to {end} into a professional audit-ready report. Include: total documents processed, pass/fail/escalated breakdown, top 3 recurring risk patterns, and a plain-language executive summary suitable for a small business owner with no compliance background."

FRONTEND REQUIREMENTS
Build a dashboard with:
- Upload view (drag-drop, shows processing status in real time via Firestore listener)
- Task queue view (list of documents with status badges: processed, escalated, needs_review)
- Compliance check detail view (shows risk score, justification, citations, approve/reject buttons for reviewers)
- Audit log view (searchable, filterable by date/actor/tenant)
- Reports view (generate on demand, download PDF)
- Role-based access: owner sees everything, reviewer sees escalation queue only

SECURITY & COMPLIANCE (CRITICAL — this is the product's own selling point)
- All Firestore/BigQuery queries MUST be scoped by tenant_id — no cross-tenant data leakage
- Encrypt files at rest in Cloud Storage (default GCS encryption is fine, document it)
- Audit logs must be append-only (no update/delete permissions on the BigQuery table for the app service account)
- Every AI decision must store the exact prompt version and model version used, for reproducibility
- Implement rate limiting on upload endpoints to prevent abuse

DELIVERABLES
1. Full working codebase organized per this structure:
   compliance-agent/apps/dashboard, apps/api-gateway, services/orchestrator, services/ingestion-agent, services/compliance-agent, services/reporting-agent, services/escalation-service, shared/auth-middleware, shared/audit-logger, shared/schema-validators, infra/terraform, infra/workflows, rulesets/, tests/unit, tests/integration, docs/
2. Terraform scripts to provision Cloud Run services, Firestore, BigQuery datasets, Cloud Storage buckets, and IAM roles
3. A seed script with 2-3 example rulesets and sample documents for demo purposes
4. Unit tests for the rule engine and risk scoring logic
5. A README explaining setup, environment variables needed (GEMINI_API_KEY, GCP_PROJECT_ID, etc.), and how to run locally vs deploy
6. Clear inline comments explaining WHERE Gemini is called and WHY, since judges will review AI-native operations

BUILD ORDER
Start with: (1) data model + Firestore setup, (2) ingestion agent with Gemini extraction, (3) compliance agent with rule engine + Gemini reasoning, (4) escalation flow, (5) dashboard, (6) audit logging, (7) reporting agent last.

Do not use localStorage or client-side secrets. Do not hardcode API keys — use environment variables and Google Secret Manager references in Terraform. Write production-quality error handling — every Gemini call must have a fallback/retry path and log failures to the audit trail as well.