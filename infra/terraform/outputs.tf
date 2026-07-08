output "runtime_service_account_email" {
  description = "Writer SA used by agents (audit append-only)"
  value       = google_service_account.cg_runtime.email
}

output "reader_service_account_email" {
  description = "Reader SA used by reporting/dashboard (SELECT only)"
  value       = google_service_account.cg_reader.email
}

output "raw_docs_bucket" {
  value = google_storage_bucket.raw_docs.name
}

output "reports_bucket" {
  value = google_storage_bucket.reports.name
}

output "audit_dataset" {
  value = google_bigquery_dataset.audit.dataset_id
}

output "task_queue_name" {
  value = google_cloud_tasks_queue.agent_queue.name
}

output "gemini_secret_id" {
  description = "Secret Manager secret holding the Gemini API key (version added out-of-band)"
  value       = google_secret_manager_secret.gemini_api_key.secret_id
}
