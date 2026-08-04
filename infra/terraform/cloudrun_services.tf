# ---------------------------------------------------------------------------
# API Gateway (public — Cloud Run IAM allows allUsers after auth middleware)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api_gateway" {
  name     = "cg-api-gateway"
  location = var.region

  template {
    service_account = google_service_account.cg_gateway.email

    containers {
      image = "${local.service_image}/api-gateway:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "RISK_ESCALATION_THRESHOLD"
        value = tostring(var.risk_escalation_threshold)
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "CG_DISPATCH_MODE"
        value = "cloud"
      }
      env {
        # .uri already includes the https:// scheme — do not prefix it again.
        name  = "INGESTION_URL"
        value = "${google_cloud_run_v2_service.ingestion_agent.uri}/internal/ingest"
      }
      env {
        name  = "COMPLIANCE_URL"
        value = "${google_cloud_run_v2_service.compliance_agent.uri}/internal/check"
      }
      env {
        name  = "INVOKER_SA"
        value = google_service_account.cg_runtime.email
      }
      # DANGER: dev-mode auth bypass. Controlled by var.enable_auth_dev_mode —
      # see variables.tf. Must be false once Firebase Auth is live.
      env {
        name  = "CG_AUTH_DEV_MODE"
        value = var.enable_auth_dev_mode ? "1" : "0"
      }
      env {
        name  = "CG_ENABLE_DOCS"
        value = var.enable_api_docs ? "1" : "0"
      }
      env {
        # Firebase Hosting default domain + localhost for local dev. Add a
        # custom domain here too if one is ever mapped in Firebase Hosting.
        name  = "CG_CORS_ORIGINS"
        value = "https://${var.project_id}.web.app,http://localhost:5173"
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

resource "google_cloud_run_v2_service_iam_member" "api_gateway_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api_gateway.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Ingestion Agent (internal — invoked by Cloud Tasks via OIDC)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "ingestion_agent" {
  name     = "cg-ingestion-agent"
  location = var.region

  template {
    service_account = google_service_account.cg_runtime.email

    containers {
      image = "${local.service_image}/ingestion-agent:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

resource "google_cloud_run_v2_service_iam_member" "ingestion_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ingestion_agent.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Compliance Agent
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "compliance_agent" {
  name     = "cg-compliance-agent"
  location = var.region

  template {
    service_account = google_service_account.cg_runtime.email

    containers {
      image = "${local.service_image}/compliance-agent:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "RISK_ESCALATION_THRESHOLD"
        value = tostring(var.risk_escalation_threshold)
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

resource "google_cloud_run_v2_service_iam_member" "compliance_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.compliance_agent.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Escalation Service
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "escalation_service" {
  name     = "cg-escalation-service"
  location = var.region

  template {
    service_account = google_service_account.cg_runtime.email

    containers {
      image = "${local.service_image}/escalation-service:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

resource "google_cloud_run_v2_service_iam_member" "escalation_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.escalation_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Reporting Agent
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "reporting_agent" {
  name     = "cg-reporting-agent"
  location = var.region

  template {
    service_account = google_service_account.cg_reader.email

    containers {
      image = "${local.service_image}/reporting-agent:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

resource "google_cloud_run_v2_service_iam_member" "reporting_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.reporting_agent.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cg_runtime.email}"
}

# ---------------------------------------------------------------------------
# Cloud Workflows — weekly report
# ---------------------------------------------------------------------------

resource "google_workflows_workflow" "weekly_report" {
  name            = "cg-weekly-report"
  region          = var.region
  service_account = google_service_account.cg_runtime.email
  source_contents = file("${path.module}/../workflows/weekly_report.yaml")

  depends_on = [google_project_service.apis]
}

# Cloud Scheduler triggers the weekly-report workflow every Monday 07:00 UTC.
resource "google_cloud_scheduler_job" "weekly_report" {
  name      = "cg-weekly-report-trigger"
  region    = var.region
  schedule  = "0 7 * * 1"
  time_zone = "UTC"

  http_target {
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.weekly_report.id}/executions"
    http_method = "POST"

    body = base64encode(jsonencode({
      argument = jsonencode({
        api_gateway_url = "https://${google_cloud_run_v2_service.api_gateway.uri}"
      })
    }))

    oauth_token {
      service_account_email = google_service_account.cg_runtime.email
    }
  }

  depends_on = [google_project_service.apis]
}
