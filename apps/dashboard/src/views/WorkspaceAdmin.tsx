import { useEffect, useState } from "react";
import {
  ShieldCheck,
  FileText,
  Inbox,
  Users,
  KeyRound,
  Bell,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ClipboardList,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import {
  fetchTenantAdminOverview,
  type TenantAdminOverview,
} from "../api/client";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { StatCard } from "../components/ui/StatCard";
import { DecisionBreakdown } from "../components/ui/DecisionBreakdown";
import { EmptyState } from "../components/ui/EmptyState";

/** One label/value row in the configuration panel. */
function Row({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Bell;
  label: string;
  value: string;
  tone?: "good" | "muted";
}) {
  return (
    <div className="flex items-center gap-3 border-b border-slate-100 py-2.5 last:border-0 dark:border-slate-800">
      <Icon size={15} className="shrink-0 text-slate-400 dark:text-slate-500" />
      <span className="text-[13px] text-slate-600 dark:text-slate-400">{label}</span>
      <span
        className={`ml-auto text-[13px] font-medium ${
          tone === "good"
            ? "text-status-good"
            : tone === "muted"
              ? "text-slate-400 dark:text-slate-500"
              : "text-slate-900 dark:text-slate-100"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

export function WorkspaceAdmin() {
  const { session } = useAuth();
  const [data, setData] = useState<TenantAdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTenantAdminOverview(session)
      .then((d) => !cancelled && setData(d))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [session]);

  return (
    <div className="space-y-6">
      <PageHeading
        title="Workspace"
        subtitle="Everything in this workspace at a glance — volume, people, and configuration."
      />

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-status-critical dark:border-red-900/60 dark:bg-red-950/25">
          <AlertTriangle size={15} className="shrink-0" />
          {error}
        </div>
      )}

      {loading && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800"
            />
          ))}
        </div>
      )}

      {!loading && !error && data && (
        <>
          <Card>
            <CardHeader
              title={data.name}
              subtitle={
                <>
                  <span className="font-mono-num">{data.tenant_id}</span>
                  {" · "}
                  {data.industry} / {data.jurisdiction}
                  {" · "}
                  <span className="capitalize">{data.plan_tier}</span> plan
                  {data.created_at ? ` · since ${data.created_at.split("T")[0]}` : ""}
                </>
              }
            />

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard
                label="Documents"
                value={data.documents_total}
                icon={FileText}
                tone="brand"
                index={0}
              />
              <StatCard
                label="Checks run"
                value={data.checks_total}
                icon={ClipboardList}
                tone="brand"
                index={1}
              />
              <StatCard
                label="Awaiting review"
                value={data.open_escalations}
                icon={Inbox}
                tone="warning"
                index={2}
              />
              <StatCard
                label="Team members"
                value={data.members_total}
                icon={Users}
                tone="good"
                index={3}
              />
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Decision mix"
                subtitle="How every check in this workspace was resolved."
              />
              {data.checks_total > 0 ? (
                <>
                  <DecisionBreakdown
                    approved={data.checks_auto_approved}
                    escalated={data.checks_escalated}
                    rejected={data.checks_rejected}
                  />
                  <div className="mt-5 grid grid-cols-3 gap-3">
                    <StatCard
                      label="Approved"
                      value={data.checks_auto_approved}
                      icon={CheckCircle2}
                      tone="good"
                      index={0}
                    />
                    <StatCard
                      label="Escalated"
                      value={data.checks_escalated}
                      icon={AlertTriangle}
                      tone="warning"
                      index={1}
                    />
                    <StatCard
                      label="Rejected"
                      value={data.checks_rejected}
                      icon={XCircle}
                      tone="critical"
                      index={2}
                    />
                  </div>
                </>
              ) : (
                <EmptyState
                  icon={ClipboardList}
                  title="No checks run yet"
                  description="Upload a document and trigger a compliance check to populate this."
                />
              )}
            </Card>

            <Card>
              <CardHeader
                title="Configuration"
                subtitle="What is switched on for this workspace."
              />
              <div>
                <Row
                  icon={Bell}
                  label="Slack escalation alerts"
                  value={data.slack_configured ? "Configured" : "Not configured"}
                  tone={data.slack_configured ? "good" : "muted"}
                />
                <Row
                  icon={Trash2}
                  label="Document retention"
                  value={
                    data.retention_days > 0
                      ? `Delete after ${data.retention_days} days`
                      : "Keep indefinitely"
                  }
                  tone={data.retention_days > 0 ? undefined : "muted"}
                />
                <Row
                  icon={KeyRound}
                  label="Active API keys"
                  value={String(data.api_keys_active)}
                  tone={data.api_keys_active > 0 ? undefined : "muted"}
                />
                <Row
                  icon={Users}
                  label="Roles"
                  value={
                    Object.entries(data.members_by_role)
                      .map(([r, n]) => `${n} ${r}`)
                      .join(", ") || "none recorded"
                  }
                />
                <Row
                  icon={FileText}
                  label="Document status"
                  value={
                    Object.entries(data.documents_by_status)
                      .map(([s, n]) => `${n} ${s}`)
                      .join(", ") || "none yet"
                  }
                />
              </div>
              {/* The audit trail is the product's actual guarantee, so say so
                  here rather than leaving the panel feeling like settings. */}
              <p className="mt-4 flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-[12px] leading-relaxed text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
                <ShieldCheck size={14} className="mt-0.5 shrink-0" />
                Every decision above — automated or human — is recorded in an
                append-only audit trail that this workspace cannot edit or delete.
              </p>
            </Card>
          </div>

          {data.top_failing_rules.length > 0 && (
            <Card>
              <CardHeader
                title="Rules failing most often"
                subtitle="Where a process change would prevent the most future exceptions."
              />
              <ul className="flex flex-wrap gap-2">
                {data.top_failing_rules.map((rule) => (
                  <li
                    key={rule}
                    className="rounded-lg bg-slate-100 px-2.5 py-1.5 font-mono-num text-[12px] text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {rule}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
