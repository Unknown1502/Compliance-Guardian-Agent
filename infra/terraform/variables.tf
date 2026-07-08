variable "project_id" {
  description = "GCP project ID to deploy ComplianceGuardian into"
  type        = string
}

variable "region" {
  description = "Primary region for Cloud Run, Cloud Tasks, and buckets"
  type        = string
  default     = "us-central1"
}

variable "firestore_location" {
  description = "Firestore location ID (multi-region nam5 recommended for US)"
  type        = string
  default     = "nam5"
}

variable "bq_location" {
  description = "BigQuery dataset location"
  type        = string
  default     = "US"
}

variable "audit_dataset_id" {
  description = "BigQuery dataset for audit logs and reports"
  type        = string
  default     = "compliance_audit"
}

variable "risk_escalation_threshold" {
  description = "Risk score (0-100) at or above which checks escalate to a human reviewer"
  type        = number
  default     = 60
}

variable "gemini_model" {
  description = "Gemini model name used by all agents (recorded with every call for reproducibility)"
  type        = string
  default     = "gemini-2.5-flash"
}
