# Admin Control Center

A separate frontend application for platform operators. It shares the customer
app's Firebase project and FastAPI backend, and shares nothing else: its own
build, its own routes, its own Hosting site, and its own authorization.

The separate URL is **operational separation, not security**. The security
boundary is server-side: `/api/platform/*` is gated by
`require_platform_admin`, which checks an environment allowlist that no token,
role, or request body can influence. Non-admins receive `404`, never `403`, so
the surface does not confirm its own existence to anyone probing for it.

## Why the site ID is not in this repository

The admin site ID must be **neutral** — it must not reveal the customer
project, the product name, or any tenant identifier. Choosing it is an
operator decision, so it is supplied at deploy time rather than committed.

## First-time setup

1. **Create a Hosting site** with a neutral ID of your choosing:

   ```
   npx firebase-tools hosting:sites:create <ADMIN_SITE_ID> --project <FIREBASE_PROJECT_ID>
   ```

   Pick something unrelated to `cg-guardian`, `ComplianceGuardian`, the
   customer site, or any tenant ID.

2. **Configure the environment.** Copy `.env.example` to `.env.local` and fill
   in the API base URL and the Firebase web config. This is the *same* Firebase
   project as the customer app — identity and the backend are shared
   deliberately; duplicating them would create a second, weaker identity system.

3. **Grant platform admin** to the operators who should have access. This is an
   environment variable on the API Gateway, not a role, precisely so that a
   tenant owner cannot mint it for themselves via `POST /api/team`:

   ```
   gcloud run services update cg-api-gateway \
     --region us-central1 --project <FIREBASE_PROJECT_ID> \
     --update-env-vars "^:^CG_PLATFORM_ADMIN_UIDS=first@example.com,second@example.com"
   ```

   The `^:^` prefix changes gcloud's delimiter — without it, the comma is read
   as a separator between env vars and only the first address survives.
   The allowlist matches on **either** Firebase UID or email address. Unset
   means nobody, never everybody.

## Deploying

```
ADMIN_SITE_ID=<ADMIN_SITE_ID> npm run deploy          # bash
set ADMIN_SITE_ID=<ADMIN_SITE_ID> && npm run deploy   # cmd.exe
```

`npm run deploy` builds, binds the `admin-control` Hosting target to your site
ID, and deploys only that target. The customer app deploys independently and is
never touched.

A custom domain can be attached later through Firebase Hosting without changing
anything in the application.

## What is real, and what is not

Every figure in the console comes from the backend. Where a metric genuinely is
not recorded, the console prints **"Metric unavailable"** rather than a zero
that would read as a measurement:

| Shown | Source |
|---|---|
| Tenants, documents, checks, escalations | Firestore, per tenant |
| Agent success/failure rates | Audit trail — each agent writes distinct success and failure actions |
| Risk distribution, rule hit counts | Compliance checks |
| Rulesets and versions | The YAML files that actually drive evaluation |
| Firestore / BigQuery / Cloud Storage health | A real probe call per request |
| Security events | Audit trail, filtered to failures, credential and privileged actions |
| **Agent latency, queue depth** | **Not recorded — unavailable** |
| **Cloud Run / Tasks / Workflows / Scheduler health** | **Not measurable from this service — unknown** |
| **Average review time** | **Not aggregated by the API — omitted** |

## Deliberate constraints

- **Read-only across tenants.** There is no cross-tenant write path, so the
  console cannot alter a customer's records.
- **Every platform read is audited** before data is returned. The product's
  promise is that access is accountable; the operator is not an exception.
- **No secrets are reachable.** The audit trail stores action names and
  identifiers only, and no endpoint returns credentials.
- **Configuration is not editable here.** Risk thresholds, rulesets, and the
  admin allowlist live in deployment config and version control, so an attacker
  who reaches this console still cannot widen their own access.
