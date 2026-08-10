import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Bell,
  Copy,
  Check,
  KeyRound,
  Trash2,
  Clock,
  AlertTriangle,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  getNotificationSettings,
  putNotificationSettings,
  testNotification,
  getRetentionSettings,
  putRetentionSettings,
  previewRetention,
  listApiKeys,
  createApiKey,
  revokeApiKey,
  type NotificationSettings,
  type RetentionSettings,
  type ApiKey,
} from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { cn } from "../lib/cn";

const FIELD =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13.5px] text-ink placeholder:text-muted focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15";
const LABEL = "mb-1.5 block text-[12.5px] font-medium text-ink-2";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line py-3 last:border-0">
      <dt className="text-[13px] text-ink-2">{label}</dt>
      <dd className="font-mono-num text-[13px] text-ink">{value}</dd>
    </div>
  );
}

function Panel({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: typeof Bell;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-line bg-surface p-5">
      <div className="flex items-start gap-2.5">
        {Icon && (
          <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-2 text-ink-2">
            <Icon size={14} />
          </div>
        )}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {description && <p className="mt-1 text-[13px] text-ink-2">{description}</p>}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------

function NotificationsPanel({ canManage }: { canManage: boolean }) {
  const { session } = useAuth();
  const toast = useToast();
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!session) return;
    getNotificationSettings(session).then(setSettings).catch(() => {});
  };
  useEffect(load, [session]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    try {
      const next = await putNotificationSettings(session, url);
      setSettings(next);
      setUrl("");
      toast.push({
        kind: "success",
        title: next.slack_configured ? "Slack alerts on" : "Slack alerts off",
      });
    } catch (err) {
      toast.push({ kind: "error", title: "Could not save", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    if (!session) return;
    setBusy(true);
    try {
      await testNotification(session);
      toast.push({ kind: "success", title: "Test message sent", description: "Check your Slack channel." });
    } catch (err) {
      toast.push({ kind: "error", title: "Test failed", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Escalation alerts"
      icon={Bell}
      description="Post to Slack when a check escalates. The audit record is written either way — Slack is an alert, not the record."
    >
      <div className="mb-3 text-[13px]">
        {settings?.slack_configured ? (
          <span className="inline-flex items-center gap-1.5 text-status-good">
            <Check size={13} /> Connected
            <span className="font-mono-num text-muted">{settings.slack_webhook_masked}</span>
          </span>
        ) : (
          <span className="text-muted">Not configured</span>
        )}
      </div>

      {canManage && (
        <form onSubmit={save} className="space-y-3">
          <label className="block">
            <span className={LABEL}>Slack incoming webhook URL</span>
            <input
              type="url"
              className={FIELD}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://hooks.slack.com/services/..."
            />
            <span className="mt-1 block text-[11.5px] text-muted">
              Only hooks.slack.com URLs are accepted. Leave blank and save to turn alerts off.
            </span>
          </label>
          <div className="flex flex-wrap gap-2.5">
            <Button type="submit" size="md" loading={busy}>
              Save
            </Button>
            {settings?.slack_configured && (
              <Button type="button" variant="outline" size="md" onClick={sendTest} disabled={busy}>
                Send test message
              </Button>
            )}
          </div>
        </form>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function ApiKeysPanel({ canManage }: { canManage: boolean }) {
  const { session } = useAuth();
  const toast = useToast();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [justCreated, setJustCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = () => {
    if (!session || !canManage) return;
    listApiKeys(session).then(setKeys).catch(() => {});
  };
  useEffect(load, [session, canManage]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    try {
      const created = await createApiKey(session, name);
      setJustCreated(created.plaintext_key);
      setCopied(false);
      setName("");
      load();
    } catch (err) {
      toast.push({ kind: "error", title: "Could not create key", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (keyId: string) => {
    if (!session) return;
    setBusy(true);
    try {
      await revokeApiKey(session, keyId);
      toast.push({ kind: "success", title: "Key revoked" });
      load();
    } catch (err) {
      toast.push({ kind: "error", title: "Could not revoke", description: (err as Error).message });
    } finally {
      setBusy(false);
      setConfirmId(null);
    }
  };

  if (!canManage) {
    return (
      <Panel title="API keys" icon={KeyRound} description="Only an owner or admin can manage API keys.">
        <span />
      </Panel>
    );
  }

  return (
    <Panel
      title="API keys"
      icon={KeyRound}
      description="Lets another system send documents for checking without a person signing in — your document store, an intake form, a nightly job. Most workspaces never need one."
    >
      {/* A key is a machine credential. It can do the work, and nothing else:
          it cannot manage the team, change the jurisdiction, approve an
          escalation, or create another key. Keys live in CI config and env
          files and leak far more easily than passwords, so a leaked key must
          not be able to establish its own persistence. */}
      <div className="mb-4 rounded-lg border border-line bg-surface-2 p-3.5">
        <p className="text-[12.5px] font-medium text-ink">What a key can do</p>
        <p className="mt-1 text-[12.5px] text-ink-2">
          Upload a document, run a compliance check, and read the result — inside this
          workspace only. Send it as an <code className="font-mono-num">X-API-Key</code> header.
        </p>
        <p className="mt-2.5 text-[12.5px] font-medium text-ink">What it cannot do</p>
        <p className="mt-1 text-[12.5px] text-ink-2">
          Manage the team, change your jurisdiction, alter retention, or create another
          key. It also cannot approve or reject an escalation — that is a human judgement,
          and a machine credential must not be able to stand in for a reviewer.
        </p>
      </div>

      {justCreated && (
        <div className="mb-4 rounded-lg border border-brand-200 bg-brand-50 p-3.5">
          <p className="text-[12.5px] font-semibold text-brand-800">
            Copy this key now — it is shown once and cannot be retrieved again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="font-mono-num min-w-0 flex-1 truncate rounded-md bg-surface px-2.5 py-1.5 text-[12px] text-ink">
              {justCreated}
            </code>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard?.writeText(justCreated);
                setCopied(true);
              }}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] font-medium text-ink-2 hover:bg-surface-2"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <button
            type="button"
            onClick={() => setJustCreated(null)}
            className="mt-2 text-[12px] text-brand-700 underline"
          >
            I've saved it — hide
          </button>
        </div>
      )}

      <form onSubmit={create} className="mb-4 flex flex-wrap items-end gap-2.5">
        <label className="min-w-[180px] flex-1">
          <span className={LABEL}>Key name</span>
          <input
            className={FIELD}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="CI pipeline"
          />
        </label>
        <Button type="submit" size="md" loading={busy}>
          Create key
        </Button>
      </form>

      {keys.length === 0 ? (
        <p className="text-[12.5px] text-muted">
          No keys yet — and you only need one if another system will be sending documents
          on your behalf. People sign in instead.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {keys.map((k) => (
            <li key={k.key_id} className="flex flex-wrap items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono-num text-[12.5px] text-ink">
                    {k.display_prefix}…
                  </span>
                  {k.name && <span className="text-[12.5px] text-ink-2">{k.name}</span>}
                  {k.revoked && (
                    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] font-semibold uppercase text-muted">
                      revoked
                    </span>
                  )}
                </div>
                <p className="text-[11.5px] text-muted">
                  created {k.created_at.split("T")[0]} ·{" "}
                  {k.last_used_at ? `last used ${k.last_used_at.split("T")[0]}` : "never used"}
                </p>
              </div>
              {!k.revoked && (
                <button
                  onClick={() => setConfirmId(k.key_id)}
                  className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-status-critical"
                  aria-label="Revoke key"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={confirmId !== null}
        onClose={() => setConfirmId(null)}
        onConfirm={() => confirmId && revoke(confirmId)}
        busy={busy}
        variant="danger"
        icon={Trash2}
        title="Revoke this key?"
        description="Any integration using it stops working immediately. This cannot be undone — create a new key instead."
        confirmLabel="Revoke"
      />
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function RetentionPanel({ canManage }: { canManage: boolean }) {
  const { session } = useAuth();
  const toast = useToast();
  const [settings, setSettings] = useState<RetentionSettings | null>(null);
  const [days, setDays] = useState("0");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [confirmSave, setConfirmSave] = useState(false);

  const load = () => {
    if (!session) return;
    getRetentionSettings(session).then((s) => {
      setSettings(s);
      setDays(String(s.retention_days));
    }).catch(() => {});
  };
  useEffect(load, [session]);

  const doSave = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const next = await putRetentionSettings(session, Number(days));
      setSettings(next);
      toast.push({
        kind: "success",
        title: next.enabled ? `Retention set to ${next.retention_days} days` : "Retention disabled",
      });
    } catch (err) {
      toast.push({ kind: "error", title: "Could not save", description: (err as Error).message });
    } finally {
      setBusy(false);
      setConfirmSave(false);
    }
  };

  const runPreview = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const p = await previewRetention(session);
      setPreview(
        p.skipped_reason
          ? p.skipped_reason
          : `${p.deleted_count} document(s) would be deleted (older than ${p.cutoff?.split("T")[0]}). Nothing was deleted.`,
      );
    } catch (err) {
      toast.push({ kind: "error", title: "Preview failed", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Document retention"
      icon={Clock}
      description="Automatically delete uploaded documents after a set age. Off by default."
    >
      <div className="mb-3 rounded-lg border border-orange-200 bg-orange-50 p-3">
        <p className="flex items-start gap-2 text-[12.5px] text-ink-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-status-warning" />
          <span>
            This permanently deletes documents and their extracted data. The{" "}
            <strong>audit trail is never deleted</strong> — every deletion is itself appended to
            it, so the record of what was removed survives.
          </span>
        </p>
      </div>

      <div className="mb-3 text-[13px]">
        {settings?.enabled ? (
          <span className="text-ink">
            Deleting documents older than{" "}
            <span className="font-mono-num font-semibold">{settings.retention_days}</span> days
          </span>
        ) : (
          <span className="text-muted">Keeping documents indefinitely</span>
        )}
      </div>

      {canManage && settings && (
        <div className="space-y-3">
          <label className="block max-w-[260px]">
            <span className={LABEL}>Retention period (days)</span>
            <input
              type="number"
              min={0}
              max={3650}
              className={FIELD}
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
            <span className="mt-1 block text-[11.5px] text-muted">
              0 = keep forever. Minimum if enabled: {settings.minimum_days} days.
            </span>
          </label>
          <div className="flex flex-wrap gap-2.5">
            <Button
              size="md"
              loading={busy}
              onClick={() => (Number(days) > 0 ? setConfirmSave(true) : doSave())}
            >
              Save
            </Button>
            <Button variant="outline" size="md" onClick={runPreview} disabled={busy}>
              Preview what would delete
            </Button>
          </div>
          {preview && (
            <p className="rounded-lg border border-line bg-surface-2 p-3 text-[12.5px] text-ink-2">
              {preview}
            </p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmSave}
        onClose={() => setConfirmSave(false)}
        onConfirm={doSave}
        busy={busy}
        variant="danger"
        icon={AlertTriangle}
        title={`Delete documents older than ${days} days?`}
        description="From now on, documents past this age are permanently deleted, along with their extracted data. Compliance decisions and the audit trail are not affected. Run a preview first if you are unsure."
        confirmLabel="Enable retention"
      />
    </Panel>
  );
}

// ---------------------------------------------------------------------------

export function SettingsView() {
  const { session, signOut } = useAuth();
  if (!session) return null;
  const canManage = session.role === "owner" || session.role === "admin";

  return (
    <div>
      <PageHeading title="Settings" subtitle="Your account, workspace, and integrations." />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Account">
          <dl>
            <Row label="Email" value={session.email ?? "—"} />
            <Row label="User ID" value={session.uid} />
            <Row label="Role" value={<span className="capitalize">{session.role}</span>} />
          </dl>
          <Button variant="outline" size="md" className="mt-4" onClick={() => signOut()}>
            Sign out
          </Button>
        </Panel>

        <Panel
          title="Workspace"
          description="Every document, check, and audit event is scoped to this tenant."
        >
          <dl>
            <Row label="Tenant ID" value={session.tenantId} />
            <Row
              label="Active ruleset"
              value={
                <Link to="/rulesets" className="inline-flex items-center gap-0.5 text-brand-600 hover:text-brand-700">
                  View rules <ArrowUpRight size={12} />
                </Link>
              }
            />
            <Row
              label="Team"
              value={
                <Link to="/team" className="inline-flex items-center gap-0.5 text-brand-600 hover:text-brand-700">
                  Manage <ArrowUpRight size={12} />
                </Link>
              }
            />
            <Row
              label="Billing"
              value={
                <Link to="/billing" className="inline-flex items-center gap-0.5 text-brand-600 hover:text-brand-700">
                  Manage plan <ArrowUpRight size={12} />
                </Link>
              }
            />
          </dl>
        </Panel>

        <NotificationsPanel canManage={canManage} />
        <ApiKeysPanel canManage={canManage} />

        <div className={cn("lg:col-span-2")}>
          <RetentionPanel canManage={canManage} />
        </div>
      </div>
    </div>
  );
}
