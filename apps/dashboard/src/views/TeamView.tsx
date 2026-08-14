import { useEffect, useState } from "react";
import { UserPlus, Users, Trash2, ShieldAlert } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { listTeam, addTeamMember, type InviteResult, removeTeamMember, ApiError, type TeamMember } from "../api/client";
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
  const [loadError, setLoadError] = useState<
    { kind: "permission" | "network"; message: string } | null
  >(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmUid, setConfirmUid] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("reviewer");
  const [jobTitle, setJobTitle] = useState("");
  const [invite, setInvite] = useState<InviteResult | null>(null);

  const canManage = session?.role === "owner" || session?.role === "admin";

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

      {formError && <p className="mb-4 text-[13px] text-status-critical">{formError}</p>}

      {invite && (
        <div className="mb-4 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900/60 dark:bg-green-950/25">
          <p className="text-[13.5px] font-semibold text-status-good">
            {invite.email} has been added as {invite.role}.
          </p>
          {invite.invite_emailed ? (
            <p className="mt-1 text-[12.5px] text-ink-2">
              We emailed them a link to set their password.
            </p>
          ) : (
            <>
              <p className="mt-1 text-[12.5px] text-ink-2">
                Email is not configured on this deployment, so send them this link yourself.
                It lets them set their own password — it is not a password, and you still
                cannot sign in as them.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded border border-line bg-surface px-2 py-1 text-[11.5px]">
                  {invite.set_password_link || "Link could not be generated — ask them to use Forgot password."}
                </code>
                {invite.set_password_link && (
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(invite.set_password_link)}
                    className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-[12px] font-medium text-ink hover:bg-surface-2"
                  >
                    Copy
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {open && canManage && (
        <form
          onSubmit={submit}
          className="mb-6 rounded-xl border border-line bg-surface p-5"
        >
          <h3 className="text-[14px] font-semibold text-ink">Add a team member</h3>
          {/* You cannot set someone else's password here, and that is the
              point: an owner who knows a reviewer's password can sign in as
              them, which would make every decision attributed to that
              reviewer unprovable. */}
          <p className="mt-1 text-[12.5px] text-ink-2">
            They will receive a link to set their own password. You never see it — which is
            what keeps the decisions they record attributable to them.
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
