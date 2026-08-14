# Reviewer Self-Assignment and Team Page Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `reviewer` (or `admin`) claim an unassigned compliance check for themselves, atomically and tenant-scoped, and fix the Team page so every tenant member — including reviewers — can actually see their team roster.

**Architecture:** One new backend endpoint (`POST /checks/{id}/claim`) that wraps a Firestore transaction mirroring the existing `apply_reviewer_decision` concurrency pattern, plus one new frontend button on `CheckDetail.tsx`. The Team page fix is frontend-only — the backend endpoint it calls already has no role restriction; the bug is a state-handling defect in `TeamView.tsx`.

**Tech Stack:** FastAPI + Firestore (`google-cloud-firestore` transactions) on the backend, React + TypeScript (Vite) on the frontend, `pytest` with an in-memory `FakeRepo`/`TestClient` harness (no emulator) for backend tests.

**Spec:** `compliance-agent/docs/superpowers/specs/2026-08-14-reviewer-self-assignment-team-visibility-design.md`

## Global Constraints

- Roles are exactly `owner`, `reviewer`, `admin` (plus machine-only `service`) — do not introduce new role names.
- Self-claim eligibility is `require_role("reviewer")` (reviewer, or admin implicitly) — `owner` is explicitly excluded, matching `decide_check`'s existing gate.
- The claimed identity is always `auth.uid` from the verified token — the claim endpoint takes no request body field for identity.
- No `firestore.rules` changes (every client-facing collection already denies writes; all mutations go through the backend Admin SDK, which bypasses rules).
- No changes to `POST`/`DELETE /api/team` (stay `owner`/`admin`-only).
- Follow the existing test harness exactly: `CG_AUTH_DEV_MODE=1`, `_dev_token(uid, tenant_id, role)`, the shared `FakeRepo`/`FakeAuditor`/`client` fixture in `tests/unit/test_api_gateway.py`. No Firestore emulator — this codebase's own convention (see the docstring atop `tests/unit/test_escalation_decisions.py`) is to unit-test the transactional guard with an in-memory fake that reproduces the state check, not against a real emulator.
- Commit messages must NOT include a `Co-Authored-By` trailer.
- Do not run `firebase deploy`, `gcloud run deploy`, or any other live-infrastructure command as part of this plan — implementation and local/test verification only. Deployment is a separate, explicit step outside this plan.

---

### Task 1: Backend — atomic self-claim endpoint

**Files:**
- Modify: `shared/gcp_clients/firestore_repo.py:67-69` (add `ClaimConflictError`), and after `apply_reviewer_decision` (`shared/gcp_clients/firestore_repo.py:604`) (add `claim_check` method)
- Modify: `apps/api-gateway/api_gateway/main.py:54-59` (import), `apps/api-gateway/api_gateway/main.py:1279` (add route between `assign_check` and `review_queue`)
- Test: `tests/unit/test_api_gateway.py` (extend `FakeRepo` at `tests/unit/test_api_gateway.py:84-101`, add tests to `class TestOversight` at `tests/unit/test_api_gateway.py:538`)

**Interfaces:**
- Produces: `FirestoreRepo.claim_check(*, check_id: str, tenant_id: str, reviewer_id: str) -> ComplianceCheck`, raising `NotFoundError` / `TenantMismatchError` (cross-tenant) / `ClaimConflictError` (already assigned).
- Produces: route `POST /api/compliance/checks/{check_id}/claim` → `CheckResponse` (200), 409 with detail `"This review has already been assigned to another reviewer."` on conflict, 404 on not-found/cross-tenant, 403 if caller isn't `reviewer`/`admin`.
- Consumes: existing `_own_or_raise`, `ComplianceCheck`, `CheckResponse`, `_check_to_response`, `id_path`, `require_role`, `NotFoundError`, `TenantMismatchError` — all already defined/imported in the files above.

- [ ] **Step 1: Write the failing tests**

Add to `FakeRepo` in `tests/unit/test_api_gateway.py` (place right after the existing `apply_reviewer_decision` fake, `tests/unit/test_api_gateway.py:93-101`):

```python
    def claim_check(self, *, check_id, tenant_id, reviewer_id):
        from gcp_clients.firestore_repo import ClaimConflictError

        c = self.get_check(check_id, tenant_id)
        if c.assigned_to is not None:
            raise ClaimConflictError(check_id)
        updated = c.model_copy(update={"assigned_to": reviewer_id})
        self.checks[check_id] = updated
        return updated
```

Add to `class TestOversight` in `tests/unit/test_api_gateway.py` (after `test_unassign_clears`, `tests/unit/test_api_gateway.py:618-631`, before `test_queue_returns_escalated_only_and_is_tenant_scoped`):

```python
    def test_reviewer_can_claim_unassigned_check(self, client):
        c, fake = client
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="rev-1", role="reviewer"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["assigned_to"] == "rev-1"

    def test_admin_can_claim_unassigned_check(self, client):
        c, _ = client
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="admin-1", role="admin"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["assigned_to"] == "admin-1"

    def test_owner_cannot_claim(self, client):
        c, _ = client
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(role="owner"),
        )
        assert r.status_code == 403

    def test_claim_ignores_any_client_supplied_identity(self, client):
        """The endpoint takes no body field for identity — nothing to spoof."""
        c, _ = client
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="rev-1", role="reviewer"),
            json={"assignee_uid": "someone-else"},  # no request model reads this
        )
        assert r.status_code == 200, r.text
        assert r.json()["assigned_to"] == "rev-1"

    def test_claim_on_already_assigned_check_is_409(self, client):
        c, _ = client
        c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="rev-1", role="reviewer"),
        )
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="rev-2", role="reviewer"),
        )
        assert r.status_code == 409
        assert "already been assigned" in r.json()["detail"]

    def test_claim_on_other_tenant_check_is_404(self, client):
        c, _ = client
        r = c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(tenant="tenant-b", role="reviewer"),
        )
        assert r.status_code == 404

    def test_claim_writes_audit_event_with_self_method(self, client):
        c, fake = client
        c.post(
            "/api/compliance/checks/check-a/claim",
            headers=self._hdr(uid="rev-1", role="reviewer"),
        )
        events = [e for e in fake.auditor.events if e["action"] == "check.assigned"]
        assert len(events) == 1
        assert events[0]["actor"] == "rev-1"
        assert events[0]["after_state"]["assignment_method"] == "self"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd compliance-agent && python -m pytest tests/unit/test_api_gateway.py -k claim -v`
Expected: FAIL — no route registered for `POST /api/compliance/checks/{check_id}/claim`, so every new test gets a `404`/`405` instead of the asserted status code (e.g. `test_reviewer_can_claim_unassigned_check` fails on `assert r.status_code == 200` because it actually got 404/405).

- [ ] **Step 3: Implement the backend**

In `shared/gcp_clients/firestore_repo.py`, add right after `class DecisionConflictError` (`shared/gcp_clients/firestore_repo.py:67-69`):

```python
class ClaimConflictError(RuntimeError):
    """Raised when a reviewer's self-claim loses a race (already assigned)."""
```

In `shared/gcp_clients/firestore_repo.py`, add a new method to `FirestoreRepo` directly after `apply_reviewer_decision` ends (`shared/gcp_clients/firestore_repo.py:604`, right before the `# -- remediation plans --` section comment):

```python
    def claim_check(
        self,
        *,
        check_id: str,
        tenant_id: str,
        reviewer_id: str,
    ) -> ComplianceCheck:
        """Self-assign an unclaimed check to the caller, inside a transaction.

        Concurrency guarantee: mirrors apply_reviewer_decision above. The
        transaction re-reads the check and refuses to act unless assigned_to
        is still None. If two reviewers claim at once, exactly one
        transaction commits; the other sees the now-claimed state and raises
        ClaimConflictError -> HTTP 409.
        """
        db = self._db
        check_ref = db.collection(COLLECTION_CHECKS).document(check_id)

        @firestore.transactional
        def _txn(transaction) -> ComplianceCheck:
            snap = check_ref.get(transaction=transaction)
            current = ComplianceCheck.model_validate(
                _own_or_raise(snap, tenant_id, f"compliance check {check_id}")
            )
            if current.assigned_to is not None:
                raise ClaimConflictError(
                    f"check {check_id} is already assigned to {current.assigned_to}"
                )
            updated = current.model_copy(update={"assigned_to": reviewer_id})
            transaction.set(check_ref, updated.model_dump(mode="json"))
            return updated

        return _txn(db.transaction())
```

In `apps/api-gateway/api_gateway/main.py`, add `ClaimConflictError` to the existing import block (`apps/api-gateway/api_gateway/main.py:54-59`):

```python
from gcp_clients.firestore_repo import (
    ClaimConflictError,
    DecisionConflictError,
    EntitlementExhaustedError,
    NotFoundError,
    TenantMismatchError,
)
```

In `apps/api-gateway/api_gateway/main.py`, add the new route directly after `assign_check` ends and before `review_queue` begins (`apps/api-gateway/api_gateway/main.py:1279`, i.e. right after the `return _check_to_response(updated)` that closes `assign_check`):

```python
@app.post("/api/compliance/checks/{check_id}/claim", response_model=CheckResponse)
def claim_check(
    check_id: str = id_path(),
    auth: AuthContext = Depends(require_role("reviewer")),
) -> CheckResponse:
    """Let the caller assign an unclaimed check to themselves.

    Identity always comes from the verified token (auth.uid) — the request
    has no body, so there is nothing for a client to spoof. require_role
    ("reviewer") matches decide_check's own gate exactly (reviewer, or admin
    implicitly): an owner who self-claimed would be handed a check
    decide_check then refuses to let them act on.
    """
    g = gw()
    try:
        updated = g.repo.claim_check(
            check_id=check_id, tenant_id=auth.tenant_id, reviewer_id=auth.uid
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc
    except TenantMismatchError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from None
    except ClaimConflictError as exc:
        logger.info("claim conflict on check %s: %s", check_id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review has already been assigned to another reviewer.",
        ) from exc
    g.auditor.log(
        tenant_id=auth.tenant_id,
        actor=auth.uid,
        action="check.assigned",
        dedup_key=f"{check_id}:assign:{auth.uid}:{datetime.now(timezone.utc).isoformat()}",
        before_state={"assigned_to": None},
        after_state={"assigned_to": auth.uid, "assignment_method": "self"},
    )
    return _check_to_response(updated)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd compliance-agent && python -m pytest tests/unit/test_api_gateway.py -v`
Expected: PASS — every test in `TestOversight`, including the seven new ones, plus the full existing suite in this file (confirms nothing else regressed).

- [ ] **Step 5: Run the full backend suite**

Run: `cd compliance-agent && python -m pytest tests/unit/ -v`
Expected: PASS — all pre-existing tests (per project notes, ~700+) plus the new ones. If anything outside `test_api_gateway.py` fails, stop and investigate before continuing; do not proceed with a red suite.

- [ ] **Step 6: Commit**

```bash
cd compliance-agent
git add shared/gcp_clients/firestore_repo.py apps/api-gateway/api_gateway/main.py tests/unit/test_api_gateway.py
git commit -m "$(cat <<'EOF'
Let a reviewer claim an unassigned compliance check for themselves

Adds POST /checks/{id}/claim: reviewer- or admin-eligible (matching
decide_check's own gate; owner is excluded since decide_check would
then refuse them anyway), always assigns the caller's own verified
uid, and is race-safe via a Firestore transaction that mirrors the
existing apply_reviewer_decision pattern. Logs the same check.assigned
audit action the owner/admin assignment path already uses, with
assignment_method: self in after_state.
EOF
)"
```

---

### Task 2: Backend — close the reviewer-can-list-team coverage gap

`GET /api/team` already has no role restriction (`Depends(require_auth)` only) and is not touched by this task — this closes a real gap where that behavior was asserted only in a code comment, never a test. If this test fails, the "Failed to fetch" bug is a backend role gate after all, contradicting the investigation — stop and re-investigate rather than adjusting the test to match unexpected behavior.

**Files:**
- Test: `tests/unit/test_api_gateway.py` (add to `class TestTeam` at `tests/unit/test_api_gateway.py:247`)

**Interfaces:**
- Consumes: existing `GET /api/team` route (unchanged), existing `TestTeam._seed` helper (`tests/unit/test_api_gateway.py:251-262`).

- [ ] **Step 1: Write the failing test**

Add to `class TestTeam` in `tests/unit/test_api_gateway.py`, directly after `test_list_team_is_tenant_scoped` (`tests/unit/test_api_gateway.py:283-294`):

```python
    def test_reviewer_can_list_team(self, client):
        c, fake = client
        self._seed(fake, uid="u-mine", tenant="tenant-a", role="owner")
        self._seed(fake, uid="u-mine-2", tenant="tenant-a", role="reviewer")

        r = c.get(
            "/api/team",
            headers={"Authorization": f"Bearer {_dev_token('u1','tenant-a','reviewer')}"},
        )
        assert r.status_code == 200, r.text
        uids = {m["uid"] for m in r.json()}
        assert uids == {"u-mine", "u-mine-2"}
```

- [ ] **Step 2: Run the test**

Run: `cd compliance-agent && python -m pytest tests/unit/test_api_gateway.py::TestTeam::test_reviewer_can_list_team -v`
Expected: PASS immediately — no production code change is needed. If this fails, stop (see the note above the task).

- [ ] **Step 3: Commit**

```bash
cd compliance-agent
git add tests/unit/test_api_gateway.py
git commit -m "$(cat <<'EOF'
Add coverage for reviewer access to GET /api/team

The route already allows any authenticated tenant member (no role
restriction) — this was previously asserted only in a code comment.
Closes the gap without changing any production behavior.
EOF
)"
```

---

### Task 3: Frontend — "Assign to me" on the check detail page

**Files:**
- Modify: `apps/dashboard/src/api/client.ts` (add `claimCheck`, after `assignCheck` at `apps/dashboard/src/api/client.ts:614-626`)
- Modify: `apps/dashboard/src/views/CheckDetail.tsx` (import, handler, and the "Assigned reviewer" block at `apps/dashboard/src/views/CheckDetail.tsx:401-426`)

**Interfaces:**
- Consumes: `Session`, `ComplianceCheck`, `ApiError`, `authedFetch`, `jsonOrThrow` (all already defined in `client.ts`); `canReview`/`canAssign`/`check`/`session`/`team`/`busy`/`setCheck`/`toast`/`load` (all already defined in `CheckDetail.tsx`).
- Produces: `claimCheck(session: Session, checkId: string): Promise<ComplianceCheck>` in `client.ts`, for any other view to reuse later.

- [ ] **Step 1: Add the API client function**

In `apps/dashboard/src/api/client.ts`, add directly after `assignCheck` (`apps/dashboard/src/api/client.ts:614-626`):

```ts
export async function claimCheck(
  session: Session,
  checkId: string,
): Promise<ComplianceCheck> {
  return jsonOrThrow(
    await authedFetch(session, `/api/compliance/checks/${checkId}/claim`, {
      method: "POST",
    }),
  );
}
```

- [ ] **Step 2: Add the claim handler to CheckDetail.tsx**

In `apps/dashboard/src/views/CheckDetail.tsx`, update the import at line 15-25 to add `claimCheck`:

```tsx
import {
  getCheck,
  getDocument,
  getDocumentContent,
  decideCheck,
  addCheckComment,
  assignCheck,
  claimCheck,
  listTeam,
  ApiError,
  type TeamMember,
} from "../api/client";
```

Add a new handler directly after `changeAssignee` (`apps/dashboard/src/views/CheckDetail.tsx:250-261`):

```tsx
  const claimForSelf = async () => {
    if (!session || !checkId) return;
    setBusy(true);
    try {
      setCheck(await claimCheck(session, checkId));
      toast.push({ kind: "success", title: "Assigned to you" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.push({
          kind: "warning",
          title: "This review has already been assigned to another reviewer.",
        });
        await load();
      } else {
        toast.push({
          kind: "error",
          title: "Could not assign",
          description: (err as Error).message,
        });
      }
    } finally {
      setBusy(false);
    }
  };
```

- [ ] **Step 3: Replace the "Assigned reviewer" block**

In `apps/dashboard/src/views/CheckDetail.tsx`, replace the block at `apps/dashboard/src/views/CheckDetail.tsx:401-426`:

```tsx
            {/* Assignment */}
            <div className="border-t border-line px-5 py-4">
              <span className="eyebrow">Assigned reviewer</span>
              {canAssign ? (
                <select
                  value={check.assigned_to ?? ""}
                  onChange={(e) => changeAssignee(e.target.value)}
                  disabled={busy}
                  className="mt-1.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15"
                >
                  <option value="">Unassigned</option>
                  {team.map((m) => (
                    <option key={m.uid} value={m.uid}>
                      {m.email}
                      {m.job_title ? ` — ${m.job_title}` : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="mt-1 text-[13px] text-ink-2">
                  {check.assigned_to
                    ? team.find((m) => m.uid === check.assigned_to)?.email ?? check.assigned_to
                    : "Unassigned"}
                </p>
              )}
            </div>
```

with:

```tsx
            {/* Assignment */}
            <div className="border-t border-line px-5 py-4">
              <span className="eyebrow">Assigned reviewer</span>
              {canAssign ? (
                <select
                  value={check.assigned_to ?? ""}
                  onChange={(e) => changeAssignee(e.target.value)}
                  disabled={busy}
                  className="mt-1.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15"
                >
                  <option value="">Unassigned</option>
                  {team.map((m) => (
                    <option key={m.uid} value={m.uid}>
                      {m.email}
                      {m.job_title ? ` — ${m.job_title}` : ""}
                    </option>
                  ))}
                </select>
              ) : check.assigned_to === session?.uid ? (
                <div className="mt-1.5">
                  <p className="text-[13px] font-medium text-ink">You</p>
                  <p className="mt-0.5 text-[12px] text-ink-2">
                    You are assigned as the reviewer.
                  </p>
                </div>
              ) : check.assigned_to ? (
                <p className="mt-1 text-[13px] text-ink-2">
                  {team.find((m) => m.uid === check.assigned_to)?.email ?? check.assigned_to}
                </p>
              ) : canReview ? (
                <div className="mt-1.5">
                  <p className="text-[13px] text-ink-2">Unassigned</p>
                  <p className="mt-0.5 text-[12px] text-muted">
                    No reviewer is currently assigned.
                  </p>
                  <Button size="sm" className="mt-2" onClick={claimForSelf} disabled={busy}>
                    Assign to me
                  </Button>
                </div>
              ) : (
                <div className="mt-1.5">
                  <p className="text-[13px] text-ink-2">Unassigned</p>
                  <p className="mt-0.5 text-[12px] text-muted">
                    Awaiting an authorized reviewer.
                  </p>
                </div>
              )}
            </div>
```

- [ ] **Step 4: Type-check**

Run: `cd compliance-agent/apps/dashboard && npm run lint`
Expected: PASS (`tsc --noEmit` finds no type errors — `claimForSelf`, `claimCheck`, and the new JSX branch all type-check against existing `Session`/`ComplianceCheck`/`TeamMember` types).

- [ ] **Step 5: Manual verification in a running browser**

No frontend test framework exists in this repo (`apps/dashboard/package.json` has no `test` script) — verify manually using the existing dev-mode role switch:

Run: `cd compliance-agent/apps/dashboard && npm run dev`, open the printed local URL.

1. Sign in via `/login` with `AUTH_MODE=dev`, pick a demo tenant, role **reviewer**. Navigate to an escalated, unassigned check (`/checks/{id}` for a check with `decision: escalated` and no `assigned_to` — use the seed/demo data already in this tenant, e.g. via the Human Review Queue).
2. Confirm you see "Unassigned" / "No reviewer is currently assigned." / an **Assign to me** button.
3. Click it. Confirm the panel updates to "You" / "You are assigned as the reviewer." **without a page refresh**, and a success toast appears.
4. Reload the page — confirm the assignment persisted (still shows "You").
5. Sign out, sign in as a **second** reviewer in the same tenant, open a *different* unassigned escalated check, and — before clicking — use a second browser tab signed in as the first reviewer to claim the same check first. Then click "Assign to me" in the second tab: confirm a warning toast reading "This review has already been assigned to another reviewer." and that the panel refreshes to show the real assignee.
6. Sign in as **owner**: confirm no "Assign to me" button appears on an unassigned check (owner is excluded by design), and the existing dropdown still works for explicit assignment.
7. Sign in as **admin**: confirm the existing owner/admin dropdown still behaves exactly as before (this task changed the `!canAssign` branch only).

- [ ] **Step 6: Commit**

```bash
cd compliance-agent
git add apps/dashboard/src/api/client.ts apps/dashboard/src/views/CheckDetail.tsx
git commit -m "$(cat <<'EOF'
Add "Assign to me" to the check detail page

Lets a reviewer or admin claim an unassigned, escalated check for
themselves, calling the new POST /claim endpoint. Owner/admin's
existing explicit-assignment dropdown is unchanged; the new button
only replaces the previously-static "Unassigned" text shown to
reviewers.
EOF
)"
```

---

### Task 4: Frontend — fix the Team page's conflated error/empty state

**Files:**
- Modify: `apps/dashboard/src/views/TeamView.tsx`

**Interfaces:**
- Consumes: existing `listTeam`, `ApiError`, `TeamMember`, `EmptyState`, `Button`, `Users`, `ShieldAlert` (all already imported in this file).
- No change to any other file — `GET /api/team` itself is untouched (see Task 2's note).

- [ ] **Step 1: Split the overloaded `error` state**

In `apps/dashboard/src/views/TeamView.tsx`, replace (`apps/dashboard/src/views/TeamView.tsx:25-27`):

```tsx
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
```

with:

```tsx
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<
    { kind: "permission" | "network"; message: string } | null
  >(null);
  const [formError, setFormError] = useState<string | null>(null);
```

- [ ] **Step 2: Fix `load()` to produce mutually exclusive states**

Replace (`apps/dashboard/src/views/TeamView.tsx:39-48`):

```tsx
  const load = () => {
    if (!session) return;
    setLoading(true);
    listTeam(session)
      .then(setMembers)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [session]);
```

with:

```tsx
  const load = () => {
    if (!session) return;
    setLoading(true);
    setLoadError(null);
    listTeam(session)
      .then((m) => {
        setMembers(m);
        setLoadError(null);
      })
      .catch((e) => {
        setMembers([]);
        if (e instanceof ApiError && e.status === 403) {
          setLoadError({
            kind: "permission",
            message: "You don't have permission to view this team's members.",
          });
        } else {
          setLoadError({
            kind: "network",
            message: "Something went wrong loading this workspace's team.",
          });
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, [session]);
```

- [ ] **Step 3: Point the add-member form's error at `formError`**

Replace (`apps/dashboard/src/views/TeamView.tsx:50-77`), changing only the two `setError` calls:

```tsx
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const invited = await addTeamMember(session, { email, role, job_title: jobTitle });
      setInvite(invited);
      toast.push({
        kind: "success",
        title: "Member added",
        description: `${email} was added as ${role}. They set their own password next.`,
      });
      setEmail("");
      setJobTitle("");
      setOpen(false);
      load();
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 409
          ? "That email already has an account."
          : (err as Error).message;
      setError(msg);
      toast.push({ kind: "error", title: "Could not add member", description: msg });
    } finally {
      setBusy(false);
    }
  };
```

with:

```tsx
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setFormError(null);
    try {
      const invited = await addTeamMember(session, { email, role, job_title: jobTitle });
      setInvite(invited);
      toast.push({
        kind: "success",
        title: "Member added",
        description: `${email} was added as ${role}. They set their own password next.`,
      });
      setEmail("");
      setJobTitle("");
      setOpen(false);
      load();
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 409
          ? "That email already has an account."
          : (err as Error).message;
      setFormError(msg);
      toast.push({ kind: "error", title: "Could not add member", description: msg });
    } finally {
      setBusy(false);
    }
  };
```

- [ ] **Step 4: Point the form's error banner at `formError`**

Replace (`apps/dashboard/src/views/TeamView.tsx:112`):

```tsx
      {error && <p className="mb-4 text-[13px] text-status-critical">{error}</p>}
```

with:

```tsx
      {formError && <p className="mb-4 text-[13px] text-status-critical">{formError}</p>}
```

- [ ] **Step 5: Make loading / error / empty / list mutually exclusive**

Replace (`apps/dashboard/src/views/TeamView.tsx:206-261`):

```tsx
      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <div className="border-b border-line bg-surface-2 px-4 py-2.5">
          <h3 className="text-[13px] font-semibold text-ink-2">
            {members.length} member{members.length === 1 ? "" : "s"}
          </h3>
        </div>

        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : members.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No members yet"
            description="Add a reviewer so high-risk checks can be actioned by someone other than you."
          />
        ) : (
          <ul className="divide-y divide-line">
            {members.map((m) => (
              <li key={m.uid} className="flex flex-wrap items-center gap-3 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-medium text-ink">{m.email}</span>
                    <span
                      className={cn(
                        "rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset",
                        ROLE_STYLE[m.role] ?? ROLE_STYLE.reviewer,
                      )}
                    >
                      {m.role}
                    </span>
                    {m.uid === session?.uid && (
                      <span className="text-[11.5px] text-muted">you</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-ink-2">
                    {m.job_title || <span className="italic text-muted">no role given</span>}
                  </p>
                </div>
                {canManage && m.uid !== session?.uid && (
                  <button
                    onClick={() => setConfirmUid(m.uid)}
                    className="grid h-8 w-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-status-critical"
                    aria-label={`Remove ${m.email}`}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
```

with:

```tsx
      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <div className="border-b border-line bg-surface-2 px-4 py-2.5">
          <h3 className="text-[13px] font-semibold text-ink-2">
            {loading
              ? "Loading team members…"
              : loadError
                ? "Team"
                : `${members.length} member${members.length === 1 ? "" : "s"}`}
          </h3>
        </div>

        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : loadError ? (
          <EmptyState
            icon={ShieldAlert}
            title={
              loadError.kind === "permission"
                ? "Permission required"
                : "Unable to load team members"
            }
            description={
              loadError.kind === "permission" ? loadError.message : "Please try again."
            }
            action={
              loadError.kind === "network" ? (
                <Button size="sm" variant="outline" onClick={load}>
                  Retry
                </Button>
              ) : undefined
            }
          />
        ) : members.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No members yet"
            description="Add a reviewer so high-risk checks can be actioned by someone other than you."
          />
        ) : (
          <ul className="divide-y divide-line">
            {members.map((m) => (
              <li key={m.uid} className="flex flex-wrap items-center gap-3 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-medium text-ink">{m.email}</span>
                    <span
                      className={cn(
                        "rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset",
                        ROLE_STYLE[m.role] ?? ROLE_STYLE.reviewer,
                      )}
                    >
                      {m.role}
                    </span>
                    {m.uid === session?.uid && (
                      <span className="text-[11.5px] text-muted">you</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[12.5px] text-ink-2">
                    {m.job_title || <span className="italic text-muted">no role given</span>}
                  </p>
                </div>
                {canManage && m.uid !== session?.uid && (
                  <button
                    onClick={() => setConfirmUid(m.uid)}
                    className="grid h-8 w-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-status-critical"
                    aria-label={`Remove ${m.email}`}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
```

- [ ] **Step 6: Type-check**

Run: `cd compliance-agent/apps/dashboard && npm run lint`
Expected: PASS.

- [ ] **Step 7: Manual verification in a running browser**

Run: `cd compliance-agent/apps/dashboard && npm run dev`.

1. Sign in as **reviewer** in a tenant with an owner and at least one other member. Open `/team`. Confirm the roster loads and shows every member with their role — this is the actual bug fix (previously showed "Failed to fetch" / "0 members" / "No members yet" together).
2. Confirm no **Add member** button and no remove icons are visible to the reviewer, and the "Only an owner or admin can change the team roster." hint is shown.
3. Sign in as **owner**: confirm **Add member**, remove icons, and the invite form still all work exactly as before (this task did not touch `canManage`, `submit`, or `remove`).
4. Simulate a load failure: in devtools, block the request to `/api/team` (Network tab → block request URL) and reload `/team`. Confirm the page shows "Unable to load team members" with a **Retry** button, NOT "No members yet", and NOT both messages at once. Click Retry, unblock the request, confirm it recovers.
5. Trigger the add-member form's own error path (e.g. invite an email that already has an account) and confirm that error appears only near the form, not conflated with the roster-loading state.

- [ ] **Step 8: Commit**

```bash
cd compliance-agent
git add apps/dashboard/src/views/TeamView.tsx
git commit -m "$(cat <<'EOF'
Fix Team page showing "Failed to fetch" and "No members yet" together

TeamView previously used one `error` state for both the roster load
and the add-member form, and never cleared `members` on a load
failure — so a failed fetch and the empty-roster message always
rendered simultaneously, regardless of what caused the failure. Splits
load errors (with a permission vs. network distinction, and a Retry
action on the latter) from form errors, and makes loading / error /
empty / list mutually exclusive.

GET /api/team itself was already open to every tenant role — this is
a frontend state-handling fix, not a permissions change.
EOF
)"
```

---

### Task 5: Frontend — force a fresh ID token after sign-in, and verify live CORS config

**Files:**
- Modify: `apps/dashboard/src/auth/AuthContext.tsx:74`

**Interfaces:**
- No new exports; behavior-only change to the existing `onAuthStateChanged` handler.

- [ ] **Step 1: Force the token refresh**

In `apps/dashboard/src/auth/AuthContext.tsx`, replace (`apps/dashboard/src/auth/AuthContext.tsx:72-76`):

```tsx
    const unsub = onAuthStateChanged(firebaseAuth(), async (user) => {
      if (user) {
        const tokenResult = await user.getIdTokenResult();
        const tenantId = (tokenResult.claims.tenant_id as string) ?? "";
        const role = (tokenResult.claims.role as Role) ?? "owner";
```

with:

```tsx
    const unsub = onAuthStateChanged(firebaseAuth(), async (user) => {
      if (user) {
        // Force-refresh rather than trust a cached token: a member who was
        // just invited (custom claims set server-side moments ago) must not
        // be stuck with a token minted before tenant_id/role existed on it.
        const tokenResult = await user.getIdTokenResult(true);
        const tenantId = (tokenResult.claims.tenant_id as string) ?? "";
        const role = (tokenResult.claims.role as Role) ?? "owner";
```

- [ ] **Step 2: Type-check**

Run: `cd compliance-agent/apps/dashboard && npm run lint`
Expected: PASS.

- [ ] **Step 3: Manual verification in a running browser**

This only applies in Firebase mode (`AUTH_MODE=firebase`), not dev mode, since dev-mode sessions don't call `getIdTokenResult` at all. If a Firebase-mode environment is available: sign in as an existing user, confirm sign-in still succeeds and `/team`/`/checks/*` still load (i.e. the extra round trip didn't break anything). If only dev mode is available locally, skip this step and rely on Step 4's live check plus code review — this change is a one-line, low-risk force-refresh with a precedent already in this same file (`refreshVerification`, `apps/dashboard/src/auth/AuthContext.tsx:118-128`, already does `user.getIdToken(true)`).

- [ ] **Step 4: Verify the live CORS configuration (read-only, no code change, no commit)**

The investigation could not fully confirm what caused the one reported "Failed to fetch," since that error is the browser's own network-layer failure and only reproducible live. Check whether the deployed gateway's allowed origins actually include the Hosting domain:

Run: `gcloud run services describe cg-api-gateway --project cg-guardian-9856 --region us-central1 --format="value(spec.template.spec.containers[0].env)"`

Look for `CG_CORS_ORIGINS` in the output and confirm it includes `https://cg-guardian-9856.web.app`. **Do not run `terraform apply` to "fix" this without first reading the current value carefully** — `CG_PLATFORM_ADMIN_UIDS` and `CG_CORS_ORIGINS` are hand-set on this service (per `infra/terraform/terraform.tfvars.example:7`) and a careless apply can silently drop hand-set env vars that aren't captured in `.tfvars`. If the value is missing or wrong, that's a live-infrastructure change requiring its own explicit go-ahead — report it rather than changing it as part of this plan.

- [ ] **Step 5: Commit**

```bash
cd compliance-agent
git add apps/dashboard/src/auth/AuthContext.tsx
git commit -m "$(cat <<'EOF'
Force a fresh ID token on sign-in

getIdTokenResult() without force=true can return a cached token
minted before a just-invited member's custom claims (tenant_id, role)
were set server-side. Forcing a refresh here closes that gap; the
same pattern already exists in this file's refreshVerification.
EOF
)"
```

---

## Plan self-review

**Spec coverage:**
- New dedicated `POST /claim` endpoint, self-claim eligibility `reviewer`/`admin` only, server-derived identity, atomic transaction, 409 message, audit event with `assignment_method: self` → Task 1.
- Reviewer team-visibility already works server-side; locking in test coverage → Task 2.
- "Assign to me" UI states (unassigned+eligible / assigned-to-you / assigned-to-other / unassigned+ineligible), no page refresh, no overwrite of an existing assignment (the `check.assigned_to === null` guard is enforced both by the transaction in Task 1 and by only rendering the button when `!check.assigned_to` in Task 3) → Task 3.
- Team page "Failed to fetch" / "0 members" / "No members yet" conflation, loading/error/empty states, permission-denied vs. network-failure distinction with Retry → Task 4.
- Token-freshness hardening + CORS live-config verification → Task 5.
- No `firestore.rules` changes, no new entity types, no changes to `POST`/`DELETE /api/team` → explicitly called out in Global Constraints and the spec; no task touches any of these.
- `HumanQueue.tsx` needs no changes — its existing `assigned_to === session?.uid` filter (`apps/dashboard/src/views/HumanQueue.tsx:43`) becomes reachable automatically once Task 1+3 ship. No task added for it, matching the design doc.

**Placeholder scan:** no TBD/TODO; every code block is complete, real code with exact file:line anchors.

**Type consistency:** `claimCheck(session: Session, checkId: string): Promise<ComplianceCheck>` in Task 3 matches the shape of the existing `assignCheck`/`decideCheck` in the same file; `FirestoreRepo.claim_check(*, check_id, tenant_id, reviewer_id)` in Task 1 matches the keyword-only signature style of `apply_reviewer_decision` directly above it; `ClaimConflictError` is imported with the exact same name everywhere it's used (firestore_repo.py, main.py, FakeRepo in tests).

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-14-reviewer-self-assignment-team-visibility.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
