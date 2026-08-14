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
        # Uploads dispatch a scan, never an ingest. If this is unset the
        # dispatcher raises rather than falling back to ingestion, so a
        # misconfiguration fails the upload instead of skipping the scan.
        name  = "SCANNER_URL"
        value = "${google_cloud_run_v2_service.scanner_agent.uri}/internal/scan"
      }
      env {
        name  = "GCS_BUCKET_QUARANTINE"
        value = google_storage_bucket.quarantine.name
      }
      env {
        # Report generation is queued, not run inside the request. Points at
        # the task entry point, which reads the period from the durable record
        # rather than the payload.
        name  = "REPORTING_URL"
        value = "${google_cloud_run_v2_service.reporting_agent.uri}/internal/report-task"
      }
      env {
        # The gateway can no longer write audit rows itself — its service
        # account has no append permission on the audit dataset. Unset, it
        # falls back to a direct BigQuery insert, which would now be denied.
        name  = "AUDIT_WRITER_URL"
        value = google_cloud_run_v2_service.audit_writer.uri
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
        # Tenant dashboard, operator console, and both local dev ports (5173
        # customer, 5174 admin — see each app's vite.config.ts).
        #
        # The console origin comes from a variable, not a literal: its Hosting
        # site ID is deliberately neutral and uncommitted, and the guessed
        # value that used to sit here ("cg-guardian-admin.web.app") did not
        # match the real site, so an apply replaced the correct live value and
        # CORS-blocked the whole console.
        name = "CG_CORS_ORIGINS"
        value = join(",", compact([
          "https://${var.project_id}.web.app",
          # Firebase Hosting always serves a site on both .web.app and
          # .firebaseapp.com — a dashboard user reaching the latter must not
          # get silently CORS-blocked on every API call. Previously hand-set
          # via `gcloud run services update`; captured here so `terraform
          # apply` cannot delete it (see terraform.tfvars.example for why
          # that already happened once, with a different origin).
          "https://${var.project_id}.firebaseapp.com",
          var.admin_console_origin,
          "http://localhost:5173",
          "http://localhost:5174",
        ]))
      }
      env {
        # Cross-tenant access allowlist. Must be declared here even when
        # empty: an env var the live service needs but Terraform does not
        # know about is an env var the next apply deletes. That is exactly
        # how every platform admin lost the operator console once already.
        name  = "CG_PLATFORM_ADMIN_UIDS"
        value = var.platform_admin_uids
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
      # Appended at the END of this list on purpose. Cloud Run env blocks are
      # positional, so inserting one mid-list makes Terraform renumber every
      # entry after it — including the secret_key_ref blocks. The resulting
      # plan reads like those secrets are being rewritten, which is
      # unreviewable on a production apply. Read such a plan by NAME
      # (terraform show -json), never by position.
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
      # make an apply look like the Gemini secret was being rewritten.
      env {
        # Who may reply to customers. Closed by default; see variables.tf for
        # why this is separate from platform admin.
        name  = "CG_SUPPORT_AGENTS"
        value = var.support_agents
      }
      env {
        name  = "SUPPORT_FROM_EMAIL"
        value = var.support_from_email
      }
      dynamic "env" {
        for_each = var.resend_api_key_secret ? [1] : []
        content {
          name = "RESEND_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.resend_api_key.secret_id
              version = "latest"
            }
          }
        }
      }
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
# Audit Writer — holds the BigQuery append permission that the gateway must
# not have, so that no single identity can both append to and rewrite the
# audit trail. See the comment on gateway_appender in iam.tf.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "audit_writer" {
  name     = "cg-audit-writer"
  location = var.region

  template {
    service_account = google_service_account.cg_audit_writer.email

    containers {
      image = "${local.service_image}/audit-writer:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET_AUDIT"
        value = google_bigquery_dataset.audit.dataset_id
      }
    }

    # Every audited action in the gateway waits on this, so a cold start would
    # add latency to uploads, signups and reviewer decisions alike.
    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
}

# ---------------------------------------------------------------------------
# Scanner Agent — ClamAV. Runs as cg_scanner, not cg_runtime: it is the only
# identity permitted to read quarantined uploads, and that separation is the
# malware trust boundary.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "scanner_agent" {
  name     = "cg-scanner-agent"
  location = var.region

  template {
    service_account = google_service_account.cg_scanner.email

    # clamd holds the whole signature database in memory (~1.3 GB) and is
    # killed outright if it cannot. 2 GB is the smallest size that leaves room
    # for the database plus the file being scanned.
    containers {
      image = "${local.service_image}/scanner-agent:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        # clamd keeps working between requests loading signatures; throttling
        # CPU outside a request would make startup take minutes.
        cpu_idle = false
      }

      # Loading signatures takes ~30-60s. Without a generous startup probe
      # Cloud Run kills the container before clamd is ready and retries
      # forever.
      startup_probe {
        tcp_socket {
          port = 8080
        }
        initial_delay_seconds = 20
        period_seconds        = 10
        failure_threshold     = 12
        timeout_seconds       = 5
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET_QUARANTINE"
        value = google_storage_bucket.quarantine.name
      }
      env {
        name  = "GCS_BUCKET_RAW_DOCS"
        value = google_storage_bucket.raw_docs.name
      }
      env {
        name  = "INGESTION_URL"
        value = "${google_cloud_run_v2_service.ingestion_agent.uri}/internal/ingest"
      }
      env {
        name  = "CLOUD_TASKS_QUEUE"
        value = google_cloud_tasks_queue.agent_queue.name
      }
      env {
        name  = "CLOUD_TASKS_LOCATION"
        value = var.region
      }
      env {
        name  = "INVOKER_SA"
        value = google_service_account.cg_runtime.email
      }
    }

    # min_instance_count = 1: a cold start here means loading the signature
    # database before the first scan can run, which would push every upload
    # after an idle period past the Cloud Tasks timeout. This is the one
    # service in the system that cannot afford to scale to zero.
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

    # A large PDF through a full signature set is slow; the default 5 minutes
    # is not always enough.
    timeout = "600s"
  }

  depends_on = [google_project_service.apis, google_artifact_registry_repository.cg_services]
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
    # Runs as cg_runtime, not cg_reader. Despite the name, this service is not
    # a reader: it streams a row into the reports table, appends an audit
    # event, and writes report HTML to GCS. cg_reader could do none of those,
    # so report generation failed here every time it was attempted.
    #
    # The alternative — granting cg_reader append on audit_logs — would have
    # been worse than the bug. cg_reader holds bigquery.jobs.create, so adding
    # tables.updateData would give it DML over the append-only audit trail and
    # break the guarantee that cg_gateway is the only documented exception to.
    # cg_runtime appends without jobs.create, so the trail stays unrewritable.
    #
    # Also makes this consistent with every other agent, all of which already
    # run as cg_runtime. cg_reader is left in place but is now unused.
    service_account = google_service_account.cg_runtime.email

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

    # `.uri` already carries the scheme — the previous value wrapped it in
    # another "https://" and handed the workflow https://https://... Compare
    # outputs.tf, which uses the same attribute bare.
    #
    # Targets the Reporting Agent, not the gateway: /internal/report exists
    # only on the agent, and the gateway is allUsers-invokable so an internal
    # route there would be publicly reachable.
    body = base64encode(jsonencode({
      argument = jsonencode({
        reporting_agent_url = google_cloud_run_v2_service.reporting_agent.uri
      })
    }))

    oauth_token {
      service_account_email = google_service_account.cg_runtime.email
    }
  }

  depends_on = [google_project_service.apis]
}
