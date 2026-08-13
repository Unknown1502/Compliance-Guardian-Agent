terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }

  # State lives in GCS, not on a workstation.
  #
  # This project is no longer a sandbox: the state describes the live
  # infrastructure serving customers, and a single local copy meant one disk
  # failure would leave Terraform unable to see, change or roll back anything
  # it had built. The bucket is versioned, so a corrupted or truncated state
  # can be restored from a prior generation, and GCS provides the object
  # locking that stops two concurrent applies interleaving.
  #
  # The bucket is deliberately NOT declared as a resource in this
  # configuration — Terraform cannot create the thing it stores its own state
  # in without a chicken-and-egg on first init.
  backend "gcs" {
    bucket = "cg-guardian-9856-tfstate"
    prefix = "compliance-guardian"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
