# Reviewer self-assignment and tenant-scoped team visibility

Status: approved 2026-08-14. Implementation tracked separately via the
writing-plans/executing-plans workflow.

## Problem

Two related gaps, both scoped to a single tenant at all times:

1. When a compliance check is escalated for human review and nobody has
   claimed it, only an `owner`/`admin` can assign a reviewer (including
   assigning the current user to themselves) via the existing
   `PATCH /checks/{id}/assignee` dropdown. A `reviewer` who opens an
   unassigned check has no way to take it themselves.
2. A `reviewer` logging into the Team page sees "Failed to fetch" / "0
   members" / "No members yet" simultaneously, even in tenants with several
   real members, and cannot tell who else is on their team.

## What the codebase already provides (verified by direct inspection, not
assumed)

- **Tenant/role resolution**: `tenant_id` and `role` are Firebase custom
  claims embedded in the verified ID token
  (`shared/auth_middleware/__init__.py`, `_verify_bearer_token`). No
  Firestore round trip is needed to resolve them, and neither can be
  spoofed by the client — every route reads them off `AuthContext`, built
  solely from the verified token.
- **Roles**: exactly `owner`, `reviewer`, `admin` (`VALID_ROLES` in
  `shared/auth_middleware/__init__.py`), plus a non-human `service` role for
  API-key callers. There is no `Compliance Officer`/`Auditor` role in this
  codebase — the brief's mention of those was illustrative, not literal.
- **The only reviewable entity today is `ComplianceCheck`**
  (`shared/schema_validators/models.py`), Firestore collection
  `compliance_checks`. It already has `assigned_to: str | None`. No
  Documents/Tasks/Alerts/Exceptions/Approvals entity has an independent
  assignment concept — "Documents" and "Tasks" in the UI are dashboards
  over `documents`/`compliance_checks`, not separate assignable entities.
  This design intentionally scopes work to `ComplianceCheck`, structured so
  a second entity could reuse the same transaction pattern later without
  rework — it does not fabricate entities that don't exist.
- **Atomic claim pattern already exists**, just not on the assignment path:
  `FirestoreRepo.apply_reviewer_decision` (used by the approve/reject flow)
  re-reads the check inside a Firestore transaction and refuses to act
  unless it is still unclaimed, raising `DecisionConflictError` → HTTP 409
  on a race. `assign_check` (the existing owner/admin PATCH endpoint) has
  no such guard today — a plain read-then-write.
- **Audit logging**: `check.assigned`/`check.unassigned` actions already
  exist, written via `auditor.log(tenant_id=, actor=, action=, dedup_key=,
  before_state=, after_state=)`. `before_state`/`after_state` are free-form
  dicts, so a new `assignment_method` key needs no schema change.
- **`GET /api/team` already has no role restriction** —
  `Depends(require_auth)` only, returning `uid, email, role, job_title,
  created_at` for every tenant member via `FirestoreRepo.list_users`
  (filtered by `tenant_id`). The "Failed to fetch" text is the browser's
  native Fetch API network-error string, never produced by this app's own
  `ApiError` handling (`apps/dashboard/src/api/client.ts`) — meaning the
  request never reached a usable HTTP response. The actual, confirmed bug
  is in `TeamView.tsx`: on a fetch failure it sets `error` but leaves
  `members` at its initial `[]`, so the empty-state ("No members yet") and
  the error text render simultaneously regardless of what caused the
  failure.
- **Firestore rules**: every client-facing collection already denies all
  writes (`allow write: if false`); every mutation goes through the backend
  via the Admin SDK, which bypasses rules entirely. `users` has no rule at
  all (default-denied) and is never read client-side. No rules file change
  is needed for this work — adding a rule for `users` would only open a
  second, redundant, unaudited access path.

## Decisions

1. **New dedicated endpoint**: `POST /api/compliance/checks/{check_id}/claim`,
   separate from the existing owner/admin `PATCH .../assignee`. Chosen over
   extending the existing endpoint so the self-claim authorization rule
   (simple: caller must be reviewer-eligible in this tenant, can only ever
   target themselves, only when currently unassigned) stays isolated from
   the owner/admin override rule (arbitrary target, no unassigned
   precondition), and so the existing, already-tested `assign_check`
   behavior is untouched.
2. **Self-claim eligibility is `role in {"reviewer", "admin"}`** — the same
   set that can *decide* a check today (`decide_check` uses
   `require_role("reviewer")`, and `admin` is always implicitly allowed by
   `require_role`'s own logic). `owner` is deliberately excluded: an owner
   who self-assigned would be handed a check `decide_check` then rejects
   (confirmed by the existing `test_owner_cannot_make_reviewer_decisions`
   test), which would be a confusing dead end. Owners keep the ability to
   *explicitly* assign anyone, including themselves, via the existing
   dropdown/endpoint.
3. **Identity is always server-derived.** The claim endpoint's request body
   carries no reviewer/assignee field at all — the assigned uid is always
   `auth.uid` from the verified token. There is nothing for a client to
   spoof.
4. **Concurrency**: the claim handler wraps a read of the check and the
   write of `assigned_to` in one Firestore transaction, modeled directly on
   `apply_reviewer_decision`. If `assigned_to` is no longer `None` by the
   time the transaction runs, it raises a new `ClaimConflictError` → HTTP
   409, and the frontend shows "This review has already been assigned to
   another reviewer." then refetches the check.
5. **No `firestore.rules` change.** Confirmed unnecessary per the existing
   architecture — see above.
6. **Team page**: fix the state-handling bug (loading / real error / real
   empty are three mutually exclusive states, not overlapping), distinguish
   a genuine 403 from a network failure (only the network-failure path gets
   a Retry button; 403 shows a fixed permission message and no retry, since
   retrying won't change a role), and force one ID-token refresh after
   sign-in so a just-invited member can't be stuck on a token minted before
   their custom claims existed. `CG_CORS_ORIGINS` on the live gateway will
   be checked against the actual deployed Hosting origin as part of
   implementation, not assumed from prior notes.

## Data model changes

None. `ComplianceCheck.assigned_to` and `TeamMemberResponse` already carry
everything needed.

## New backend surface

`POST /api/compliance/checks/{check_id}/claim`
- Auth: `require_auth`, then inline check `auth.role in {"reviewer",
  "admin"}` → 403 otherwise (matching the codebase's existing inline-check
  convention; there is no central permission-map to hook into anywhere
  else in this codebase either).
- Transaction: re-read check via `_own_or_raise(tenant_id=auth.tenant_id)`
  (404 on cross-tenant, consistent with every other check route); if
  `assigned_to is not None` → `ClaimConflictError`; else set
  `assigned_to = auth.uid` and commit.
- Route translates `ClaimConflictError` → HTTP 409 with the message "This
  review has already been assigned to another reviewer." (mirrors the
  existing `DecisionConflictError` → 409 handling in `decide_check`).
- Audit: `auditor.log(action="check.assigned", actor=auth.uid,
  after_state={"assigned_to": auth.uid, "assignment_method": "self"},
  before_state={"assigned_to": None}, ...)`, same dedup_key convention as
  the existing `assign_check` (includes a timestamp, since repeat
  assign/unassign cycles are each a distinct real event).
- Response: existing `CheckResponse` model, unchanged shape.

## Frontend changes

- `CheckDetail.tsx`: new "Assign to me" action, visible only when
  `check.assigned_to == null && canReview` (the same `canReview` boolean
  already used to gate the approve/reject controls). Calls the new
  endpoint, updates local state immediately on success (same pattern as
  the existing `decide()`/`changeAssignee()` handlers — no page refresh),
  and on 409 shows the spec's exact message then refetches the check.
  Existing owner/admin dropdown is unchanged.
- Assignment display states (unassigned+eligible / assigned to you /
  assigned to someone else / unassigned+ineligible) implemented per the
  UX states enumerated in the brief, reusing the existing team-lookup
  pattern (`team.find(...)`) rather than duplicating member data.
- `HumanQueue.tsx`: no changes required — its existing "mine" filter
  (`assigned_to === session.uid`) already becomes reachable once
  self-claim exists.
- `TeamView.tsx`: state-handling fix described in Decision 6. No new
  fields requested from the backend — `TeamMemberResponse` already returns
  `email`/`role`/`job_title`, which is what the brief's mockups show.

## Testing

Backend (`pytest`, extending `tests/unit/test_api_gateway.py` and
`tests/unit/test_escalation_decisions.py`-style patterns):
- reviewer claims an unassigned check → 200, `assigned_to == own uid`,
  audit event `check.assigned` with `assignment_method: "self"`.
- admin claims → 200 (implicitly allowed, same as decide).
- owner attempts to claim → 403.
- second claim on an already-claimed check → 409 with the exact message.
- cross-tenant check id → 404.
- two concurrent claims on the same check → exactly one succeeds (mirrors
  the existing `DecisionConflictError` race test).
- `GET /api/team` with a reviewer-role token → 200 with the tenant's
  members (this exact case has no test today — closing a real coverage
  gap the investigation surfaced, not new behavior).

Frontend: no test framework exists in `apps/dashboard` today (no
vitest/jest configured) — verified manually in a running browser via the
existing dev-mode role switch (`Login.tsx`'s demo tenants/roles), per
project convention for UI changes.

## Explicitly out of scope

- Any entity other than `ComplianceCheck` (no Alert/Exception/Approval
  entities exist to attach assignment to).
- Any change to `firestore.rules`.
- Any change to who can invite/remove team members or change roles
  (`POST`/`DELETE /api/team` stay `owner`/`admin`-only, unchanged).
- Deploying this to the live GCP project — implementation and testing only;
  deployment requires a separate explicit go-ahead.
