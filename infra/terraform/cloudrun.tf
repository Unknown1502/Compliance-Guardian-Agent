# Cloud Run services for every ComplianceGuardian backend.
# Image references use placeholders — CI/CD (or manual docker build+push)
# substitutes the real digests before terraform apply.
#
# All services are --no-allow-unauthenticated. The API Gateway alone accepts
# public traffic (via IAM binding below). Internal services accept requests
# only from the runtime service account (OIDC-authenticated Cloud Tasks/Workflows).

locals {
  service_image = "${var.region}-docker.pkg.dev/${var.project_id}/cg-services"
}

resource "google_artifact_registry_repository" "cg_services" {
  location      = var.region
  repository_id = "cg-services"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

# The 5 Cloud Run services + Cloud Workflows + Cloud Scheduler resources live
# in cloudrun_services.tf.
