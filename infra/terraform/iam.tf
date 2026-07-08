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
