import { useEffect, useState } from "react";
import { UserPlus, Users, Trash2, ShieldAlert } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { listTeam, addTeamMember, removeTeamMember, ApiError, type TeamMember } from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { cn } from "../lib/cn";

const ROLE_STYLE: Record<string, string> = {
  owner: "bg-blue-50 text-brand-700 ring-blue-200",
  admin: "bg-blue-50 text-brand-700 ring-blue-200",
  reviewer: "bg-surface-2 text-ink-2 ring-line",
};

const FIELD =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] text-ink placeholder:text-muted focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15";
const LABEL = "mb-1.5 block text-[12.5px] font-medium text-ink-2";

export function TeamView() {
  const { session } = useAuth();
  const toast = useToast();
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmUid, setConfirmUid] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reviewer");
  const [jobTitle, setJobTitle] = useState("");

  const canManage = session?.role === "owner" || session?.role === "admin";

  const load = () => {
    if (!session) return;
    setLoading(true);
    listTeam(session)
      .then(setMembers)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [session]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await addTeamMember(session, { email, password, role, job_title: jobTitle });
      toast.push({
        kind: "success",
        title: "Member added",
        description: `${email} can now sign in as ${role}.`,
      });
      setEmail("");
      setPassword("");
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

  const remove = async (uid: string) => {
    if (!session) return;
    setBusy(true);
    try {
      await removeTeamMember(session, uid);
      toast.push({ kind: "success", title: "Member removed" });
      load();
    } catch (err) {
      toast.push({
        kind: "error",
        title: "Could not remove member",
        description: (err as Error).message,
      });
    } finally {
      setBusy(false);
      setConfirmUid(null);
    }
  };

  return (
    <div>
      <PageHeading
        title="Team"
        subtitle="Who can see and decide compliance outcomes in this workspace."
        action={
          canManage && (
            <Button size="md" onClick={() => setOpen((o) => !o)} icon={<UserPlus size={14} />}>
              Add member
            </Button>
          )
        }
      />

      {error && <p className="mb-4 text-[13px] text-status-critical">{error}</p>}

      {open && canManage && (
        <form
          onSubmit={submit}
          className="mb-6 rounded-xl border border-line bg-surface p-5"
        >
          <h3 className="text-[14px] font-semibold text-ink">Add a team member</h3>
          {/* Stated plainly: there is no email delivery in this system. */}
          <p className="mt-1 text-[12.5px] text-ink-2">
            This creates the account immediately. No invitation email is sent — set a
            password here and pass it to them yourself.
          </p>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className={LABEL}>Email</span>
              <input
                type="email"
                required
                className={FIELD}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="reviewer@provider.com.au"
              />
            </label>
            <label className="block">
              <span className={LABEL}>Their role in the company</span>
              <input
                type="text"
                className={FIELD}
                value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
                placeholder="Quality &amp; Safeguarding Lead"
              />
            </label>
            <label className="block">
              <span className={LABEL}>Temporary password</span>
              <input
                type="text"
                required
                minLength={6}
                className={FIELD}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="at least 6 characters"
              />
            </label>
            <label className="block">
              <span className={LABEL}>Access level</span>
              <select className={FIELD} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="reviewer">Reviewer — can approve or reject escalations</option>
                <option value="admin">Admin — can also manage the team</option>
              </select>
            </label>
          </div>

          <div className="mt-4 flex gap-2.5">
            <Button type="submit" loading={busy} size="md">
              Create account
            </Button>
            <Button type="button" variant="ghost" size="md" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

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

      {!canManage && (
        <p className="mt-4 flex items-start gap-2 text-[12.5px] text-ink-2">
          <ShieldAlert size={14} className="mt-0.5 shrink-0 text-muted" />
          Only an owner or admin can change the team roster.
        </p>
      )}

      <ConfirmDialog
        open={confirmUid !== null}
        onClose={() => setConfirmUid(null)}
        onConfirm={() => confirmUid && remove(confirmUid)}
        busy={busy}
        variant="danger"
        icon={Trash2}
        title="Remove this member?"
        description="Their account is deleted and they lose access immediately. Compliance decisions they already made stay in the audit trail — that record cannot be rewritten."
        confirmLabel="Remove"
      />
    </div>
  );
}
