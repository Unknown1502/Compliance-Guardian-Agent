# ---------------------------------------------------------------------------
# Monitoring
#
# This project ran with no monitoring at all until 2026-08-11, which is how
# the weekly report managed to fail every Monday from 2026-07-18 without
# anyone noticing: Cloud Scheduler logged PERMISSION_DENIED into a log nobody
# was reading. The scheduler alert below is aimed squarely at that class of
# failure — an unattended job that stops working and says nothing.
# ---------------------------------------------------------------------------

resource "google_monitoring_notification_channel" "email" {
  # Optional so a deployment without an alert address still applies cleanly;
  # the policies simply have nowhere to send. Set alert_email in tfvars.
  count        = var.alert_email == "" ? 0 : 1
  display_name = "ComplianceGuardian alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

# Probes /api/healthz, NOT /healthz. The bare path is registered in the app
# but returns a Google frontend 404 before reaching the container, so an
# uptime check pointed at it would report a permanent outage that is not real.
resource "google_monitoring_uptime_check_config" "api_gateway" {
  display_name = "cg-api-gateway /api/healthz"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path         = "/api/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(google_cloud_run_v2_service.api_gateway.uri, "https://")
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "api_gateway_down" {
  display_name = "API gateway failing health checks"
  combiner     = "OR"

  conditions {
    display_name = "uptime check failing"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.api_gateway.uptime_check_id}\"",
      ])
      duration        = "300s"
      comparison      = "COMPARISON_LT"
      threshold_value = 1

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_FRACTION_TRUE"
        group_by_fields      = ["resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  documentation {
    content = "The API gateway stopped answering /api/healthz. Check the serving revision: a failed deploy leaves the previous revision serving, so the service can look healthy in the console while the new code is not live."
  }

  depends_on = [google_project_service.apis]
}

# The one that would have caught the weekly-report outage on 2026-07-20.
# Log-based rather than metric-based on purpose: a job that is rejected before
# it starts produces an error log, not a failed-execution metric.
resource "google_monitoring_alert_policy" "unattended_job_failed" {
  display_name = "Scheduled job or workflow failed"
  combiner     = "OR"

  conditions {
    display_name = "scheduler or workflow error"

    condition_matched_log {
      filter = join(" OR ", [
        "(resource.type=\"cloud_scheduler_job\" AND severity>=ERROR)",
        "(resource.type=\"workflows.googleapis.com/Workflow\" AND severity>=ERROR)",
      ])
    }
  }

  alert_strategy {
    # Required for log-based conditions. One mail an hour is enough for a
    # weekly job; the point is to notice at all, not to be paged repeatedly.
    notification_rate_limit {
      period = "3600s"
    }
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  documentation {
    content = "A Cloud Scheduler job or Cloud Workflows execution failed. PERMISSION_DENIED here usually means the runtime service account is missing a role; check the scheduler job's own logs, since a job rejected at the API never creates an execution to inspect."
  }

  depends_on = [google_project_service.apis]
}
