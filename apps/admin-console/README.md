# Operator Console

Cross-tenant console for whoever runs ComplianceGuardian. A **separate Vite app
on a separate Firebase Hosting site**, not a route inside the tenant dashboard.

## Why it is separate

A different origin means none of this code ships in the customer bundle, and a
cross-site scripting bug in the tenant dashboard cannot reach this app's
storage or tokens.

**The separate URL is not the security boundary.** Hostnames are discoverable.
What actually protects this surface is server-side:

- `/api/platform/*` requires the caller to be on the `CG_PLATFORM_ADMIN_UIDS`
  allowlist. That is environment configuration — there is no code path in the
  product that can grant it, so no tenant can grant it to themselves.
- Platform access is **not** a role. Roles come from `POST /api/team`, so a
  role named `founder` could be minted by any tenant owner inviting themselves.
- The endpoints are **read-only**. There is no cross-tenant write path.
- Every request is written to the append-only audit trail before data is
  returned. The operator's own access is accountable too.
- A non-allowlisted caller gets **404**, not 403, so the routes do not confirm
  they exist to anyone probing.

## Granting access

```bash
gcloud run services update cg-api-gateway --region us-central1 \
  --project cg-guardian-9856 \
  --update-env-vars CG_PLATFORM_ADMIN_UIDS=you@example.com
```

Comma-separated; accepts Firebase UIDs or email addresses. Unset means nobody
has access — never everybody.

## Local development

```bash
cp .env.example .env.local   # fill in VITE_FIREBASE_* and the API base URL
npm install && npm run dev   # http://localhost:5273
```

## Deploy

Requires a one-time hosting site + target:

```bash
npx firebase-tools hosting:sites:create cg-guardian-admin --project cg-guardian-9856
npx firebase-tools target:apply hosting admin cg-guardian-admin --project cg-guardian-9856
npm run deploy
```

The console's origin must also be added to the gateway's `CG_CORS_ORIGINS`.
