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

# Reader SA: used by reporting agent + dashboard API for SELECT queries.
resource "google_service_account" "cg_reader" {
  account_id   = "cg-reader"
  display_name = "ComplianceGuardian reader (audit SELECT, no writes)"
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

resource "google_bigquery_dataset_iam_member" "reader_select" {
  dataset_id = google_bigquery_dataset.audit.dataset_id
  role       = google_project_iam_custom_role.audit_reader.id
  member     = "serviceAccount:${google_service_account.cg_reader.email}"
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

resource "google_storage_bucket_iam_member" "reader_reports_bucket" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cg_reader.email}"
}

resource "google_storage_bucket_iam_member" "reader_raw_docs_view" {
  bucket = google_storage_bucket.raw_docs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cg_reader.email}"
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

resource "google_secret_manager_secret_iam_member" "reader_reads_gemini_key" {
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_reader.email}"
}

# bigquery.jobs.create is a project-scoped permission — a dataset-level IAM
# binding (as used for cgAuditReader above) cannot grant it; BigQuery silently
# ignores it there since jobs aren't dataset-scoped resources. Query execution
# needs this predefined role bound at the project level. The dataset-level
# cgAuditReader binding above still does the real least-privilege work (get/
# getData scoped to the audit dataset only) — this just unblocks starting the
# query job itself.
resource "google_project_iam_member" "reader_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cg_reader.email}"
}

# ---------------------------------------------------------------------------
# Gateway SA bindings — mirrors cg_runtime's write access (Firestore, raw docs,
# Gemini secret) plus cg_reader's query access (BigQuery jobs.create), plus
# report-bucket writes (report HTML) and the ability to enqueue Cloud Tasks
# that invoke ingestion/compliance as cg_runtime.
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset_iam_member" "gateway_appender" {
  dataset_id = google_bigquery_dataset.audit.dataset_id
  role       = google_project_iam_custom_role.audit_appender.id
  member     = "serviceAccount:${google_service_account.cg_gateway.email}"
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
# Secret Manager — Stripe. Only the gateway calls Stripe (checkout creation +
# webhook handling both live in api_gateway), so only cg_gateway gets access
# — unlike the Gemini key, which every agent needs.
#
# Populate out-of-band once a real Stripe account exists, same pattern as
# the Gemini key:
#   echo -n "$STRIPE_SECRET_KEY" | gcloud secrets versions add cg-stripe-secret-key --data-file=-
#   echo -n "$STRIPE_WEBHOOK_SECRET" | gcloud secrets versions add cg-stripe-webhook-secret --data-file=-
# Until then, these secrets can be left with no version at all — every
# billing endpoint fails as a clean 503, not a crash, and every other
# endpoint (signup, upload, checks, reports) is completely unaffected. See
# shared/billing/__init__.py for the lazy-construction behavior this relies on.
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "stripe_secret_key" {
  secret_id = "cg-stripe-secret-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "stripe_webhook_secret" {
  secret_id = "cg-stripe-webhook-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "gateway_reads_stripe_secret_key" {
  secret_id = google_secret_manager_secret.stripe_secret_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_gateway.email}"
}

resource "google_secret_manager_secret_iam_member" "gateway_reads_stripe_webhook_secret" {
  secret_id = google_secret_manager_secret.stripe_webhook_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cg_gateway.email}"
}

# ---------------------------------------------------------------------------
# Secret Manager — Razorpay and PayPal. Same shape and the same reasoning as
# the Stripe secrets above, for the same single consumer (the gateway).
#
# These exist because Stripe live mode requires a registered business, which
# Razorpay does not. Each provider is gated by its own variable so switching
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
