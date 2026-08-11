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

variable "platform_admin_uids" {
  description = <<-EOT
    Comma-separated UIDs or emails allowed to reach /api/platform/*, written
    to CG_PLATFORM_ADMIN_UIDS on the gateway.

    This lives in Terraform because it previously did not: it was set once by
    hand with `gcloud run services update` and was therefore invisible to the
    configuration. The next apply rewrote the container's env list to match
    config, silently dropping it, and every platform admin lost access to the
    operator console at once. Anything the live service needs must be here,
    or an apply will eventually delete it.

    Empty means nobody is a platform admin — closed by default, which is the
    right failure mode for a cross-tenant surface.
  EOT
  type        = string
  default     = ""
}

variable "admin_console_origin" {
  description = <<-EOT
    Origin of the operator console, added to CG_CORS_ORIGINS.

    A variable rather than a literal because the console's Hosting site ID is
    deliberately neutral and uncommitted (see apps/admin-dashboard/scripts/
    apply-target.mjs) — hardcoding it here would put it in the repository,
    which is the one thing that choice exists to prevent. Terraform used to
    carry a guessed value that did not match the real site, so the console's
    browser calls were blocked by CORS after an apply.

    Empty simply omits it; the customer dashboard is unaffected.
  EOT
  type        = string
  default     = ""
}

variable "support_agents" {
  description = <<-EOT
    Comma-separated operator emails permitted to REPLY to support tickets,
    written to CG_SUPPORT_AGENTS on the gateway.

    Deliberately separate from platform_admin_uids. Reading the support inbox
    and writing to customers in the company's name are different powers, and
    conflating them means every operator can send mail on the company's behalf
    by accident.

    Empty means nobody can reply — closed by default, which is the right
    failure mode for a permission that speaks as the company. Declared here
    rather than set by hand because an env var Terraform does not know about
    is an env var the next apply deletes.
  EOT
  type        = string
  default     = ""
}

variable "resend_api_key_secret" {
  description = <<-EOT
    Whether to attach the Resend email secret to the gateway. Keep false until
    cg-resend-api-key has a real version — a secret_key_ref to a version-less
    secret makes the Cloud Run revision fail to start, taking down the whole
    gateway rather than just email.

    While false, support runs fully in-app: tickets are recorded and threads
    work, and the product never claims to have sent mail it did not.
  EOT
  type        = bool
  default     = false
}

variable "support_from_email" {
  description = "Verified sender address for support email. Empty disables sending."
  type        = string
  default     = ""
}

variable "enable_razorpay" {
  description = <<-EOT
    Gates the Razorpay secret_key_ref env vars on the API gateway. Same
    hazard as every other secret gate: a secret with zero versions makes the
    Cloud Run revision fail to start, taking down the whole gateway rather
    than one payment method. Flip to true only after cg-razorpay-key-id,
    cg-razorpay-key-secret and cg-razorpay-webhook-secret all have a
    version.
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

variable "alert_email" {
  description = <<-EOT
    Address that monitoring alerts are mailed to. Empty disables the
    notification channel, so the policies still exist but page nobody —
    which is the state this project was in (implicitly) until 2026-08-11.
  EOT
  type        = string
  default     = ""
}
