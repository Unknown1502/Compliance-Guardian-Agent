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
  description = "Gemini model name used by all agents (recorded with every call for reproducibility). gemini-2.5-flash is no longer available to new API keys (returns 404) — using the cheapest current Flash-Lite tier model instead."
  type        = string
  default     = "gemini-3.1-flash-lite"
}

variable "enable_auth_dev_mode" {
  description = <<-EOT
    DANGER — leave false in any environment real users or judges can reach.
    When true, the API gateway accepts forged 'dev:<base64-claims>' bearer
    tokens instead of verifying real Firebase Auth JWTs. Only ever set true
    for a fully local/offline dev environment. Flip to false the moment
    Firebase Auth is enabled on this project.
  EOT
  type        = bool
  default     = false
}

variable "require_email_verification" {
  description = <<-EOT
    Refuse API requests from Firebase sessions whose email address has not
    been verified (HTTP 403).

    Defaults false because switching it on locks out every account created
    before email verification existed, until each of those users clicks a
    verification link. Turn it on deliberately, once you know who that
    affects — not as a side effect of an unrelated apply.
  EOT
  type        = bool
  default     = false
}

variable "enable_api_docs" {
  description = "Expose Swagger UI (/docs, /redoc, /openapi.json) on the public API gateway. Keep false in production — the API surface should not be publicly browsable."
  type        = bool
  default     = false
}

variable "enable_billing" {
  description = <<-EOT
    Gates whether the Stripe secret_key_ref env vars are attached to the API
    gateway container. Keep false until cg-stripe-secret-key and
    cg-stripe-webhook-secret both have at least one real version populated —
    Cloud Run fails to start a revision that references a secret with zero
    versions, which would take down the ENTIRE gateway (signup, uploads,
    everything), not just billing. Flip to true only after populating both
    secrets via `gcloud secrets versions add` (see iam.tf).
  EOT
  type        = bool
  default     = false
}

variable "stripe_price_id_oneoff" {
  description = "Stripe Price ID for the one-off audit purchase. Set once created in the Stripe dashboard; irrelevant while enable_billing is false."
  type        = string
  default     = ""
}

variable "stripe_price_id_subscription" {
  description = "Stripe Price ID for the monthly unlimited-audits subscription. Set once created in the Stripe dashboard; irrelevant while enable_billing is false."
  type        = string
  default     = ""
}

variable "enable_razorpay" {
  description = <<-EOT
    Gates the Razorpay secret_key_ref env vars on the API gateway. Same
    hazard as enable_billing: a secret with zero versions makes the Cloud Run
    revision fail to start, taking down the whole gateway rather than one
    payment method. Flip to true only after cg-razorpay-key-id,
    cg-razorpay-key-secret and cg-razorpay-webhook-secret all have a version.

    Independent of enable_billing on purpose — Razorpay exists precisely so
    payments can go live before Stripe's business verification completes.
  EOT
  type        = bool
  default     = false
}

variable "enable_paypal" {
  description = <<-EOT
    Gates the PayPal secret_key_ref env vars on the API gateway. Requires
    cg-paypal-client-id and cg-paypal-secret to have versions populated. See
    enable_razorpay for the failure mode this prevents.
  EOT
  type        = bool
  default     = false
}

variable "paypal_live" {
  description = <<-EOT
    false uses PayPal's sandbox API, true uses live. Defaults to sandbox so a
    misconfiguration cannot move real money. The credentials in Secret Manager
    must match this setting — sandbox credentials against the live API simply
    fail to authenticate.
  EOT
  type        = bool
  default     = false
}

variable "payment_prices" {
  description = <<-EOT
    Server-side prices in MINOR units (paise, cents), keyed as
    "<provider>_<plan>", e.g. { razorpay_oneoff = "420000" }. Empty values
    fall back to the defaults in shared/payments/__init__.py.

    These are set here rather than in the frontend because a price the client
    can name is a price the client can change.
  EOT
  type        = map(string)
  default     = {}
}
