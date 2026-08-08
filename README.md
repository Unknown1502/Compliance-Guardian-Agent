# ComplianceGuardian

**XPRIZE Build with Gemini Hackathon — Aug 17, 2026**

Agentic compliance automation for small businesses. Upload a document, get an instant Gemini-powered risk score with cited rules, auto-approve or escalate to a human reviewer — fully auditable. Repeat for all your contracts, invoices, and policy forms.

---

## Architecture

```
Browser (React/Vite/Tailwind dashboard)
  │  Firebase Auth JWT
  ▼
API Gateway (Cloud Run, FastAPI)      — all /api/* endpoints, Firebase Auth verification,
  │                                     tenant isolation from JWT claims only
  ├─ Cloud Tasks (async) ──────────────► Ingestion Agent  (Gemini extraction)
  │                                     Compliance Agent  (Gemini reasoning + risk score)
  │
  ├─ Escalation Service               — transactional reviewer decisions
  ├─ Reporting Agent                  — Gemini executive summary, PDF + HTML → GCS
  │
  ├─ Firestore                        — live state (documents, checks, tasks)
  ├─ BigQuery (append-only)           — immutable audit trail + reports table
  ├─ Cloud Storage                    — raw files + rendered reports
  └─ Cloud Workflows + Scheduler      — weekly automated reports (Monday 07:00 UTC)
```

---

## Quick start (local)

### Prerequisites

- Python 3.11+
- Node 18+ / npm
- Docker Desktop (for local emulators)
- `gcloud` CLI

### 1. Clone and set up environment

```bash
cd compliance-agent
cp .env.example .env
# Edit .env — at minimum set GEMINI_API_KEY for live Gemini calls
```

### 2. Start local emulators

```bash
docker compose -f docker-compose.emulators.yml up -d
# Firestore :8085 · BigQuery :9050 · GCS :4443
```

### 3. Seed demo data

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements-dev.txt

export GOOGLE_CLOUD_PROJECT=cg-local
export FIRESTORE_EMULATOR_HOST=localhost:8085
export BIGQUERY_EMULATOR_HOST=http://localhost:9050
export STORAGE_EMULATOR_HOST=http://localhost:4443
python scripts/seed.py
```

### 4. Run the API Gateway

```bash
export CG_AUTH_DEV_MODE=1          # dev auth (no Firebase Auth emulator needed)
export CG_DISPATCH_MODE=inline     # run agents in-process
uvicorn api_gateway.main:app --reload --port 8080
# PYTHONPATH must include shared/ + all services/*/
```

Or use the single-command wrapper:
```bash
python scripts/run_gateway_local.py   # sets up paths automatically
```

### 5. Run the dashboard

```bash
cd apps/dashboard
cp .env.example .env.local
# Set VITE_AUTH_MODE=dev  VITE_API_BASE_URL=http://localhost:8080
npm install && npm run dev
# → http://localhost:5173
```

Log in with any tenant + role combination (dev mode). Upload a document, trigger a compliance check, and use a reviewer account to approve or reject escalations.

### 6. Run the end-to-end demos

```bash
# Phase 2 — Gemini extraction + compliance (requires GEMINI_API_KEY)
python scripts/demo_phase2.py doc-ndis-violations

# Phase 3 — RBAC + approve/reject + concurrency proof
python scripts/demo_phase3.py

# Phase 4 — Reporting agent (fixture if no key, real Gemini if key set)
python scripts/demo_phase4.py
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | Yes | `cg-local` | GCP project ID |
| `GEMINI_API_KEY` | Phase 2+ | — | Google AI Studio key. Set via `.env` locally; Secret Manager in prod |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Model name (stored with every AI call) |
| `FIRESTORE_EMULATOR_HOST` | Local | — | e.g. `localhost:8085` |
| `BIGQUERY_EMULATOR_HOST` | Local | — | e.g. `http://localhost:9050` |
| `STORAGE_EMULATOR_HOST` | Local | — | e.g. `http://localhost:4443` |
| `RISK_ESCALATION_THRESHOLD` | No | `60` | Risk score (0-100) above which checks escalate to a human |
| `CG_AUTH_DEV_MODE` | Local only | `0` | `1` → accept dev bearer tokens (no Firebase Auth emulator) |
| `CG_REQUIRE_EMAIL_VERIFICATION` | No | `0` | `1` → refuse Firebase sessions whose email is unverified (403). Off by default: enabling it retroactively locks out accounts created before verification existed |
| `CG_RL_AUTH_CAPACITY` | No | `5` | Signup burst allowance per client IP |
| `CG_RL_AUTH_REFILL_PER_SEC` | No | `0.0083` | Signup refill rate (1 per 2 min) |
| `CG_RL_EXPENSIVE_CAPACITY` | No | `20` | Burst for endpoints that spend money or call a third party (Gemini, BigQuery, Stripe, Slack, Firebase user creation) |
| `CG_RL_EXPENSIVE_REFILL_PER_SEC` | No | `0.033` | Refill rate for the expensive tier (1 per 30 s) |
| `CG_RL_STANDARD_CAPACITY` | No | `120` | Burst for ordinary authenticated reads/writes |
| `CG_RL_STANDARD_REFILL_PER_SEC` | No | `2.0` | Refill rate for the standard tier |
| `CG_RL_UPLOAD_CAPACITY` | No | `20` | Upload burst per tenant |
| `CG_RL_UPLOAD_REFILL_PER_SEC` | No | `0.5` | Upload refill rate per tenant |
| `CG_RL_BACKOFF_FREE_ATTEMPTS` | No | `3` | Failed auth attempts per account before backoff starts |
| `CG_RL_BACKOFF_BASE_SECONDS` | No | `2.0` | First backoff delay; doubles per subsequent failure |
| `CG_RL_BACKOFF_MAX_SECONDS` | No | `900` | Backoff ceiling — never a permanent lockout |
| `CG_DISPATCH_MODE` | No | `inline` | `inline` = in-process (local); `cloud` = Cloud Tasks (deployed) |
| `CG_CORS_ORIGINS` | No | `http://localhost:5173` | Comma-separated allowed CORS origins |
| `INTERNAL_TASK_TOKEN` | No | — | Shared secret header for internal service-to-service calls |

---

## Running tests

```bash
# All unit tests (hermetic — no emulators, no Gemini key needed)
python -m pytest tests/unit -v

# Expected: 280 passed
```

---

## Deploying to GCP

### Prerequisites

- A GCP project with billing enabled
- `gcloud auth application-default login`
- Push service images to Artifact Registry (see `infra/terraform/cloudrun.tf` for the registry name)

### Terraform apply

```bash
cd infra/terraform
terraform init
terraform plan -var "project_id=YOUR_PROJECT_ID"
terraform apply -var "project_id=YOUR_PROJECT_ID"
```

Terraform provisions: Firestore, BigQuery (audit_logs + reports), Cloud Storage (raw docs + reports), Cloud Tasks queue, 5 Cloud Run services, Artifact Registry, Cloud Workflows (weekly report), Cloud Scheduler, Secret Manager (Gemini key), IAM roles (including the append-only BigQuery custom role).

### Add the Gemini API key

```bash
echo -n "$GEMINI_API_KEY" | \
  gcloud secrets versions add cg-gemini-api-key \
  --project YOUR_PROJECT_ID --data-file=-
```

### Firebase Auth setup

1. Enable Firebase Auth in the Firebase Console for your project.
2. Create users and set custom claims (`tenant_id`, `role`) via the Admin SDK or a Cloud Function.
3. Set the dashboard's `VITE_AUTH_MODE=firebase` and fill in the Firebase web config in `.env.local`.

---

## Rulesets

Versioned YAML under `rulesets/{industry}/{jurisdiction}.yaml`. 15 rulesets included:

| File | Industry | Jurisdiction |
|---|---|---|
| `healthcare_ndis/au.yaml` | NDIS providers | Australia |
| `aged_care/au.yaml` | Aged care providers | Australia |
| `contract_review/generic.yaml` | Commercial contracts | Generic |
| `bookkeeping/au.yaml` | Supplier invoices | Australia |
| `data_privacy/ae.yaml` | Data privacy (PDPL) | United Arab Emirates |
| `data_privacy/in.yaml` | Data privacy (DPDP Act) | India |
| `data_privacy/us-ca.yaml` | Data privacy (CCPA/CPRA) | California, USA |
| `data_privacy/br.yaml` | Data privacy (LGPD) | Brazil |
| `data_privacy/eu.yaml` | Data privacy (GDPR) | European Union |
| `data_privacy/uk.yaml` | Data privacy (UK GDPR + DPA 2018) | United Kingdom |
| `data_privacy/ca.yaml` | Data privacy (PIPEDA) | Canada |
| `data_privacy/sg.yaml` | Data privacy (PDPA) | Singapore |
| `data_privacy/cn.yaml` | Data privacy (PIPL) | China |
| `data_privacy/za.yaml` | Data privacy (POPIA) | South Africa |
| `data_privacy/au.yaml` | Data privacy (Privacy Act 1988 / NDB scheme) | Australia |

The `data_privacy` rulesets (11 jurisdictions, spanning the Middle East,
Asia, Europe, North America, South America, Africa, and Oceania) are
modeled on real, named laws (cited in each file's header) from public
secondary guidance, not primary legal text — a structural starting point
for a real global compliance product line, not a substitute for local
legal review before real customer use. Where a law itself doesn't set a
fixed statutory deadline (Canada, South Africa), the ruleset says so
explicitly rather than inventing a precise number to look more complete
than the underlying law actually is.

To add a new ruleset: create the YAML (validated against the `RuleSet` Pydantic schema on load), bump `rule_set_version`, redeploy. No code changes needed.

---

## Repo structure

```
compliance-agent/
├── apps/
│   ├── api-gateway/         FastAPI public entry point
│   └── dashboard/           Vite + React + Tailwind + Firebase
├── services/
│   ├── orchestrator/        Task lifecycle + Cloud Tasks dispatch
│   ├── ingestion-agent/     Gemini field extraction
│   ├── compliance-agent/    Gemini risk scoring + rule verdicts
│   ├── reporting-agent/     Gemini executive summaries → PDF + HTML in GCS
│   └── escalation-service/  Transactional reviewer decisions
├── shared/
│   ├── auth_middleware/     Firebase JWT verification (+ dev mode)
│   ├── audit_logger/        Append-only BigQuery writes with retry
│   ├── gcp_clients/         Emulator/prod factory + Firestore repo
│   ├── gemini_client/       Retry, JSON repair, version tagging
│   ├── schema_validators/   Pydantic data model (single source of truth)
│   └── task_dispatch/       Cloud Tasks / inline dispatcher
├── infra/
│   ├── terraform/           All GCP resources + IAM
│   └── workflows/           Cloud Workflows YAML
├── rulesets/                Versioned compliance rule YAML files
├── scripts/                 seed.py + demo_phase2/3/4.py
├── tests/unit/             280 hermetic unit tests
└── docker-compose.emulators.yml
```

---

## Security notes

- `tenant_id` is **always** sourced from the verified Firebase JWT claim — never from client request bodies or query parameters.
- The BigQuery `audit_logs` table is **append-only** enforced at IAM level: the runtime service account holds a custom role with `bigquery.tables.updateData` but **without** `bigquery.jobs.create`, so UPDATE/DELETE/MERGE DML is physically impossible regardless of application code.
- Cloud Storage uses default Google-managed encryption at rest (documented choice: CMEK adds operational burden with no MVP requirement driving it).
- Secrets (Gemini API key) are stored in Secret Manager; no secrets in code or committed tfvars.
- The upload endpoint is rate-limited per tenant (token bucket, 20 req burst, 0.5 req/s refill).
- Firestore security rules (`infra/firestore.rules`) deny all client writes and scope reads to the authenticated user's tenant.
