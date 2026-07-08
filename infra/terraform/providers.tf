terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }

  # Remote state for team use — uncomment and set a real bucket before shared
  # environments. Local state is acceptable for the sandbox project.
  # backend "gcs" {
  #   bucket = "REPLACE-tfstate-bucket"
  #   prefix = "compliance-guardian"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
