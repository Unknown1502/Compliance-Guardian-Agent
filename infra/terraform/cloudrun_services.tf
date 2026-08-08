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
        # Tenant dashboard, operator console (separate Hosting site so admin
        # code never ships in the customer bundle), and both local dev ports.
        value = "https://${var.project_id}.web.app,https://cg-guardian-admin.web.app,http://localhost:5173,http://localhost:5273"
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
      env {
        name  = "STRIPE_PRICE_ID_ONEOFF"
        value = var.stripe_price_id_oneoff
      }
      env {
        name  = "STRIPE_PRICE_ID_SUBSCRIPTION"
        value = var.stripe_price_id_subscription
      }
      env {
        name  = "STRIPE_CHECKOUT_SUCCESS_URL"
        value = "https://${var.project_id}.web.app/billing?status=success"
      }
      env {
        name  = "STRIPE_CHECKOUT_CANCEL_URL"
        value = "https://${var.project_id}.web.app/billing?status=cancelled"
      }
      # Gated behind var.enable_billing — see variables.tf. A secret_key_ref
      # pointing at a version-less secret fails Cloud Run revision creation
      # outright, which would take the whole gateway down, not just billing.
      # Only attach these once cg-stripe-secret-key and cg-stripe-webhook-secret
      # both have a real version populated.
      dynamic "env" {
        for_each = var.enable_billing ? [1] : []
        content {
          name = "STRIPE_SECRET_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.stripe_secret_key.secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_billing ? [1] : []
        content {
          name = "STRIPE_WEBHOOK_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.stripe_webhook_secret.secret_id
              version = "latest"
            }
          }
        }
      }
      # Appended at the END of this list on purpose. Cloud Run env blocks are
      # positional, so inserting one mid-list makes Terraform renumber every
      # entry after it — including the secret_key_ref blocks for the Gemini and
      # Stripe secrets. The resulting plan reads like those secrets are being
      # rewritten, which is unreviewable on a production apply.
      env {
        name  = "CG_REQUIRE_EMAIL_VERIFICATION"
        value = var.require_email_verification ? "1" : "0"
      }
      # Base URL used to build the "Review" deep link in Slack escalation
      # alerts. This existed on the live service but not in Terraform, so an
      # apply would have silently deleted it and broken those links.
      env {
        name  = "CG_DASHBOARD_BASE_URL"
        value = "https://${var.project_id}.web.app"
      }

      # --- Razorpay / PayPal -------------------------------------------
      # Appended at the end for the same positional reason documented above:
      # inserting these higher up would renumber every later env block and
      # make an apply look like the Gemini and Stripe secrets were being
      # rewritten.
      env {
        name  = "PAYPAL_LIVE"
        value = var.paypal_live ? "1" : "0"
      }
      env {
        name  = "PAYPAL_RETURN_URL"
        value = "https://${var.project_id}.web.app/billing"
      }
      env {
        name  = "PAYPAL_CANCEL_URL"
        value = "https://${var.project_id}.web.app/billing?status=cancelled"
      }
      # Prices in minor units. Absent keys fall back to the defaults compiled
      # into shared/payments, so this map only needs entries that differ.
      dynamic "env" {
        for_each = var.payment_prices
        content {
          name  = "CG_PRICE_${upper(env.key)}"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.enable_razorpay ? [1] : []
        content {
          name = "RAZORPAY_KEY_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.payment_secrets["cg-razorpay-key-id"].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_razorpay ? [1] : []
        content {
          name = "RAZORPAY_KEY_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.payment_secrets["cg-razorpay-key-secret"].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_razorpay ? [1] : []
        content {
          name = "RAZORPAY_WEBHOOK_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.payment_secrets["cg-razorpay-webhook-secret"].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_paypal ? [1] : []
        content {
          name = "PAYPAL_CLIENT_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.payment_secrets["cg-paypal-client-id"].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_paypal ? [1] : []
        content {
          name = "PAYPAL_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.payment_secrets["cg-paypal-secret"].secret_id
              version = "latest"
            }
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
