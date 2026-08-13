# IAM — least privilege, with the append-only audit guarantee enforced here,
# not in app code.
#
# THE KEY MECHANISM:
#   BigQuery UPDATE/DELETE require running a DML *job*, which needs
#   bigquery.jobs.create. The runtime service account's custom role grants
#   bigquery.tables.updateData (needed for streaming inserts via
#   insertAll/insert_rows_json) but deliberately OMITS bigquery.jobs.create.
#   Result: the app can stream-append rows but has no code path — even if
#   compromised — to run UPDATE, DELETE, MERGE, or TRUNCATE against the audit
#   dataset. Reads for dashboards/reports go through a separate read-only
#   role that grants jobs.create for SELECT queries but no write permissions,
#   held by a distinct reader service account.

# Runtime SA: used by ingestion/compliance/escalation agents (writers).
resource "google_service_account" "cg_runtime" {
  account_id   = "cg-runtime"
  display_name = "ComplianceGuardian runtime (agents; audit append-only)"
}

# Reader SA. UNUSED as of 2026-08-11 and holds no bindings at all.
#
# It was the reporting agent's identity, but that service writes (reports row,
# audit event, report HTML) so a read-only identity could never work — report
# generation had never once succeeded. The agent moved to cg_runtime and every
# cg_reader grant was removed with it. The dashboard API does its SELECTs as
# cg_gateway, which holds its own reader role.
#
# The account is kept rather than destroyed: deleting a service account leaves
# a ~30-day tombstone on the name, so a recreate would fail, and nothing is
# gained by removing an identity that can now do nothing. Delete it if it is
# still unused once that no longer matters.
resource "google_service_account" "cg_reader" {
  account_id   = "cg-reader"
  display_name = "ComplianceGuardian reader (unused)"
}

# Gateway SA: the API Gateway is the one identity that legitimately needs both
# audit-log writes (upload events) AND SELECT queries (/api/audit-logs,
# /api/reports) in the same process. Deliberately kept separate from
# cg_runtime so the ingestion/compliance/escalation agents — which only ever
# stream-append and never construct queries — retain the strict no-DML
# guarantee. This SA is the one documented exception to that guarantee: it
# holds both the appender and reader custom roles, so unlike cg_runtime it
# is NOT provably incapable of DML at the IAM level. Scope stays as small as
# the gateway's actual code path (see api_gateway/main.py get_audit_logs and
# create_report, which is the same code that would otherwise need a
# reporting-agent HTTP proxy to preserve the split).
resource "google_service_account" "cg_gateway" {
  account_id   = "cg-gateway"
  display_name = "ComplianceGuardian API Gateway (audit append + SELECT)"
}

# Custom role: streaming insert ONLY. No jobs.create → no DML possible.
resource "google_project_iam_custom_role" "audit_appender" {
  role_id     = "cgAuditAppender"
  title       = "CG Audit Appender (insert-only)"
  description = "Streaming inserts into BigQuery tables. Deliberately omits bigquery.jobs.create so UPDATE/DELETE/MERGE DML cannot run."
  permissions = [
    "bigquery.tables.get",
    "bigquery.tables.updateData", # required for insertAll streaming inserts
    "bigquery.datasets.get",
  ]
}

# Custom role: read-only querying for reporting.
resource "google_project_iam_custom_role" "audit_reader" {
  role_id     = "cgAuditReader"
  title       = "CG Audit Reader (select-only)"
  description = "Read + query audit dataset. No table data mutation permissions."
  permissions = [
    "bigquery.tables.get",
    "bigquery.tables.getData",
    "bigquery.datasets.get",
    "bigquery.jobs.create", # needed to run SELECT query jobs; SA lacks updateData so DML still fails
  ]
}

# Bind appender role on the audit dataset only (not project-wide).
resource "google_bigquery_dataset_iam_member" "runtime_appender" {
  dataset_id = google_bigquery_dataset.audit.dataset_id
  role       = google_project_iam_custom_role.audit_appender.id
  member     = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# Firestore: runtime SA gets datastore.user (documents + checks live state).
resource "google_project_iam_member" "runtime_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# Cloud Storage: writer on raw docs, writer on reports bucket.
resource "google_storage_bucket_iam_member" "runtime_raw_docs" {
  bucket = google_storage_bucket.raw_docs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# The reporting agent writes report HTML here, and it runs as cg_runtime
# (see the reporting agent's service_account for why).
resource "google_storage_bucket_iam_member" "runtime_reports_bucket" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Quarantine — the malware trust boundary, enforced by IAM rather than by
# application code.
#
# Note what is deliberately ABSENT: cg_runtime gets no binding on the
# quarantine bucket at all. The ingestion and compliance agents run as
# cg_runtime, so even if a bug pointed one of them at a quarantined object,
# the read is denied by Google before any of our code runs. That is the whole
# reason quarantine is a separate bucket and not a prefix.
# ---------------------------------------------------------------------------

resource "google_service_account" "cg_scanner" {
  account_id   = "cg-scanner"
  display_name = "ComplianceGuardian scanner (only reader of quarantine)"
}

# The gateway writes uploads here. objectCreator, NOT objectAdmin: the gateway
# must be able to put a file into quarantine and must not be able to read one
# back out, so a compromised gateway cannot use quarantine as a staging area
# to retrieve arbitrary tenants' unscanned uploads.
resource "google_storage_bucket_iam_member" "gateway_quarantine_write" {
  bucket = google_storage_bucket.quarantine.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# The scanner is the only identity that may read quarantined bytes, and the
# only one that may delete them after promotion.
resource "google_storage_bucket_iam_member" "scanner_quarantine_admin" {
  bucket = google_storage_bucket.quarantine.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_scanner.email}"
}

# Promotion target: the scanner writes the cleared copy into approved storage.
resource "google_storage_bucket_iam_member" "scanner_raw_docs_write" {
  bucket = google_storage_bucket.raw_docs.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.cg_scanner.email}"
}

# Firestore: read the document, write the scan verdict.
resource "google_project_iam_member" "scanner_datastore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cg_scanner.email}"
}

# Audit: append-only, same custom role as the other agents. Not
# bigquery.dataEditor — the scanner must not be able to rewrite the trail that
# records what it rejected.
resource "google_project_iam_member" "scanner_audit_appender" {
  project = var.project_id
  role    = google_project_iam_custom_role.audit_appender.id
  member  = "serviceAccount:${google_service_account.cg_scanner.email}"
}

# The scanner hands a cleared document on to ingestion.
resource "google_project_iam_member" "scanner_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.cg_scanner.email}"
}

resource "google_project_iam_member" "scanner_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cg_scanner.email}"
}

# Cloud Tasks OIDC: tasks invoke the scanner as cg_runtime, so cg_runtime must
# hold run.invoker on it — the invoker identity, distinct from the scanner's
# own runtime identity above.
resource "google_cloud_run_v2_service_iam_member" "scanner_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.scanner_agent.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# Cloud Tasks: runtime SA can enqueue tasks.
resource "google_project_iam_member" "runtime_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# Cloud Tasks OIDC: allow tasks to invoke Cloud Run services as the runtime SA.
resource "google_service_account_iam_member" "tasks_act_as_runtime" {
  service_account_id = google_service_account.cg_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# Lets the Cloud Scheduler job start a weekly-report execution. The job
# authenticates as cg_runtime, and creating an execution needs this role.
#
# Its absence is why the weekly report never ran once between 2026-07-18 and
# 2026-08-11: the schedule fired every Monday and the API rejected it with
# PERMISSION_DENIED, which is invisible unless you read the scheduler's own
# logs.
#
# Project-scoped, which is wider than ideal: it lets cg_runtime start any
# workflow in the project, not just this one. Workflow-level IAM
# (google_workflows_workflow_iam_member) does not exist in hashicorp/google
# ~> 5.30 — validate rejects it outright. cg-weekly-report is currently the
# only workflow here, so the practical grant is the same; narrow this if a
# second workflow is ever added.
resource "google_project_iam_member" "runtime_workflows_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# The weekly-report workflow runs as cg_runtime and calls sys.log, which needs
# logging.logEntries.create. Without it the log step 403s and fails the whole
# execution.
#
# This was latent before the workflow was rewritten: the original already
# called sys.log from its per-tenant error handler, so the first time a single
# tenant failed, the attempt to record why would have killed the run outright.
# It was never observed only because the run never got that far.
resource "google_project_iam_member" "runtime_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Secret Manager — Gemini API key. No secrets in code or tfvars committed.
# Populate the secret VERSION out-of-band:
#   echo -n "$GEMINI_API_KEY" | gcloud secrets versions add cg-gemini-api-key --data-file=-
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "cg-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_gemini_key" {
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_runtime.email}"
}



# ---------------------------------------------------------------------------
# Gateway SA bindings — mirrors cg_runtime's write access (Firestore, raw docs,
# Gemini secret) plus cg_reader's query access (BigQuery jobs.create), plus
# report-bucket writes (report HTML) and the ability to enqueue Cloud Tasks
# that invoke ingestion/compliance as cg_runtime.
# ---------------------------------------------------------------------------

# The gateway deliberately has NO append permission on the audit dataset.
#
# It must keep roles/bigquery.jobUser: /api/audit-logs and five platform-admin
# routes run SELECT queries. But jobs.create together with
# bigquery.tables.updateData is exactly what DML requires — so an identity
# holding both can UPDATE or DELETE the append-only trail. The custom role's
# own comment ("no jobs.create → no DML possible") is true of the role in
# isolation and was false for this service account in combination.
#
# Appends now go through cg-audit-writer, which holds the appender role and
# does NOT hold jobUser. Neither identity can rewrite history:
#
#   cg-gateway       jobs.create + read   → SELECT yes, append no
#   cg-audit-writer  append               → insert yes, statements no
#
# Removing this binding is the control. Do not re-add it to make something
# work; route the write through the writer service instead.

resource "google_service_account" "cg_audit_writer" {
  account_id   = "cg-audit-writer"
  display_name = "ComplianceGuardian audit writer (append-only, no jobs.create)"
}

resource "google_bigquery_dataset_iam_member" "audit_writer_appender" {
  dataset_id = google_bigquery_dataset.audit.dataset_id
  role       = google_project_iam_custom_role.audit_appender.id
  member     = "serviceAccount:${google_service_account.cg_audit_writer.email}"
}

resource "google_project_iam_member" "audit_writer_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cg_audit_writer.email}"
}

# Only the gateway may call it.
resource "google_cloud_run_v2_service_iam_member" "audit_writer_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.audit_writer.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_bigquery_dataset_iam_member" "gateway_reader" {
  dataset_id = google_bigquery_dataset.audit.dataset_id
  role       = google_project_iam_custom_role.audit_reader.id
  member     = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_project_iam_member" "gateway_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_storage_bucket_iam_member" "gateway_raw_docs" {
  bucket = google_storage_bucket.raw_docs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_storage_bucket_iam_member" "gateway_reports_bucket" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_project_iam_member" "gateway_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# Lets the gateway enqueue Cloud Tasks whose OIDC token impersonates
# cg_runtime (INVOKER_SA), which is what's actually authorized to invoke the
# internal ingestion/compliance Cloud Run services.
resource "google_service_account_iam_member" "gateway_acts_as_runtime" {
  service_account_id = google_service_account.cg_runtime.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_secret_manager_secret_iam_member" "gateway_reads_gemini_key" {
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# ---------------------------------------------------------------------------
# Secret Manager — Razorpay and PayPal. Same shape and the same reasoning as
# the Gemini secret above, for a single consumer (the gateway).
#
# Each provider is gated by its own variable so switching
# one on does not require the other to be configured — an unpopulated secret
# attached to the container is a revision that will not start, and that would
# take down the whole gateway rather than one payment method.
#
#   printf %s "$RAZORPAY_KEY_ID"         | gcloud secrets versions add cg-razorpay-key-id --data-file=-
#   printf %s "$RAZORPAY_KEY_SECRET"     | gcloud secrets versions add cg-razorpay-key-secret --data-file=-
#   printf %s "$RAZORPAY_WEBHOOK_SECRET" | gcloud secrets versions add cg-razorpay-webhook-secret --data-file=-
#   printf %s "$PAYPAL_CLIENT_ID"        | gcloud secrets versions add cg-paypal-client-id --data-file=-
#   printf %s "$PAYPAL_SECRET"           | gcloud secrets versions add cg-paypal-secret --data-file=-
#
# printf, not `echo -n`: cmd.exe's echo has no -n and writes the flag itself
# into the secret. That has already happened once on this project.
# ---------------------------------------------------------------------------

locals {
  payment_secret_ids = [
    "cg-razorpay-key-id",
    "cg-razorpay-key-secret",
    "cg-razorpay-webhook-secret",
    "cg-paypal-client-id",
    "cg-paypal-secret",
  ]
}

resource "google_secret_manager_secret" "payment_secrets" {
  for_each  = toset(local.payment_secret_ids)
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Transactional email for support notifications. Created empty; support runs
# in-app until a version exists, and the product never claims to have sent
# mail it did not.
#   printf %s "$RESEND_API_KEY" | gcloud secrets versions add cg-resend-api-key --data-file=-
resource "google_secret_manager_secret" "resend_api_key" {
  secret_id = "cg-resend-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "gateway_reads_resend_key" {
  secret_id = google_secret_manager_secret.resend_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_secret_manager_secret_iam_member" "gateway_reads_payment_secrets" {
  for_each  = google_secret_manager_secret.payment_secrets
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# See reader_job_user above — jobs.create must be project-scoped.
resource "google_project_iam_member" "gateway_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# Firebase Authentication Admin — required for POST /api/signup to call
# firebase_admin.auth.create_user()/set_custom_user_claims() when creating a
# new tenant's owner account. Verifying existing tokens (every other
# endpoint) needs no special role; only *creating* users does.
resource "google_project_iam_member" "gateway_firebase_auth_admin" {
  project = var.project_id
  role    = "roles/firebaseauth.admin"
  member  = "serviceAccount:${google_service_account.cg_gateway.email}"
}
