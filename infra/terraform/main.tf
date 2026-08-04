# Core data-plane resources: Firestore, BigQuery, Cloud Storage, Cloud Tasks.

resource "google_project_service" "apis" {
  for_each = toset([
    "firestore.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "cloudtasks.googleapis.com",
    "workflows.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "aiplatform.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Firestore (native mode) — live state: tenants, documents, compliance_checks
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}

# Composite indexes backing the dashboard's tenant-scoped queries.
resource "google_firestore_index" "documents_by_tenant_created" {
  collection = "documents"
  database   = google_firestore_database.default.name

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "checks_by_tenant_created" {
  collection = "compliance_checks"
  database   = google_firestore_database.default.name

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "checks_by_tenant_decision_created" {
  collection = "compliance_checks"
  database   = google_firestore_database.default.name

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "decision"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

# Ascending created_at pairing — needed by reporting_agent's period aggregation
# query (tenant_id ==, created_at >= start, created_at < end with no explicit
# order_by). Firestore requires an exact index match per query shape; the
# DESCENDING variant above doesn't satisfy this range-filter query.
resource "google_firestore_index" "checks_by_tenant_created_asc" {
  collection = "compliance_checks"
  database   = google_firestore_database.default.name

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "ASCENDING"
  }
}

# ---------------------------------------------------------------------------
# BigQuery — append-only audit_logs + reports
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset" "audit" {
  dataset_id    = var.audit_dataset_id
  friendly_name = "ComplianceGuardian audit trail"
  description   = "Append-only audit logs and generated reports. Runtime SA has insert-only access (no DML) — see iam.tf."
  location      = var.bq_location

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "audit_logs" {
  dataset_id          = google_bigquery_dataset.audit.dataset_id
  table_id            = "audit_logs"
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }
  clustering = ["tenant_id"]

  schema = file("${path.module}/schemas/audit_logs.json")
}

resource "google_bigquery_table" "reports" {
  dataset_id          = google_bigquery_dataset.audit.dataset_id
  table_id            = "reports"
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }
  clustering = ["tenant_id"]

  schema = file("${path.module}/schemas/reports.json")
}

# ---------------------------------------------------------------------------
# Cloud Storage — raw uploaded documents + rendered reports
# Default Google-managed encryption at rest (documented choice per spec:
# CMEK adds operational burden with no requirement driving it for MVP).
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "raw_docs" {
  name                        = "${var.project_id}-cg-raw-docs"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true # raw evidence files: keep object generations
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 90
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "reports" {
  name                        = "${var.project_id}-cg-reports"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Cloud Tasks — async dispatch queue for agent work
# ---------------------------------------------------------------------------

resource "google_cloud_tasks_queue" "agent_queue" {
  name     = "cg-task-queue"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 20
  }

  retry_config {
    max_attempts       = 5
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 4
    max_retry_duration = "3600s"
  }

  depends_on = [google_project_service.apis]
}
