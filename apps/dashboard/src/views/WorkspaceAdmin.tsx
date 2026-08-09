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
  changeJurisdiction,
  fetchTenantAdminOverview,
  getAvailableRulesets,
  type RulesetOptionRow,
  type TenantAdminOverview,
} from "../api/client";
import { INDUSTRY_LABEL, JURISDICTION_LABEL, label } from "../lib/rulesetLabels";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
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

/**
 * Move the workspace to a different industry / jurisdiction.
 *
 * Exists because the pair used to be fixed at signup forever: a business that
 * picked wrong, or expanded into another market, had to abandon the workspace
 * and its entire audit history to correct it.
 *
 * The copy is deliberately blunt about two things — that this changes which
 * law future checks apply, and that it does NOT re-check past documents. A
 * user who assumes their history was re-evaluated would be badly misled.
 */
function JurisdictionCard({
  current,
  onChanged,
}: {
  current: { industry: string; jurisdiction: string };
  onChanged: () => void;
}) {
  const { session } = useAuth();
  const [rulesets, setRulesets] = useState<RulesetOptionRow[]>([]);
  const [industry, setIndustry] = useState(current.industry.toLowerCase());
  const [jurisdiction, setJurisdiction] = useState(current.jurisdiction.toLowerCase());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getAvailableRulesets()
      .then((rows) => live && setRulesets(rows))
      .catch(() => live && setRulesets([]));
    return () => {
      live = false;
    };
  }, []);

  const industries = Array.from(new Set(rulesets.map((r) => r.industry)));
  const jurisdictions = rulesets.filter((r) => r.industry === industry);
  const selected = jurisdictions.find((r) => r.jurisdiction === jurisdiction);
  const isCurrent =
    industry === current.industry.toLowerCase() &&
    jurisdiction === current.jurisdiction.toLowerCase();

  const save = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const r = await changeJurisdiction(session, industry, jurisdiction);
      setNote(
        r.changed
          ? `Moved to ${label(INDUSTRY_LABEL, r.industry)} · ${label(
              JURISDICTION_LABEL,
              r.jurisdiction,
            )}. New checks use ${r.rule_count} rules (v${r.rule_set_version}).`
          : "That is already this workspace's ruleset — nothing changed.",
      );
      if (r.changed) onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const field =
    "mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[13px] dark:border-slate-800 dark:bg-slate-900";

  return (
    <Card className="mt-4">
      <CardHeader
        title="Applicable rules"
        subtitle="Which industry and jurisdiction this workspace is checked against."
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-[12px] text-slate-500 dark:text-slate-400">Industry</span>
          <select
            className={field}
            value={industry}
            disabled={rulesets.length === 0}
            onChange={(e) => {
              const next = e.target.value;
              setIndustry(next);
              const first = rulesets.find((r) => r.industry === next);
              if (first) setJurisdiction(first.jurisdiction);
            }}
          >
            {industries.map((i) => (
              <option key={i} value={i}>
                {label(INDUSTRY_LABEL, i)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-[12px] text-slate-500 dark:text-slate-400">Jurisdiction</span>
          <select
            className={field}
            value={jurisdiction}
            disabled={rulesets.length === 0}
            onChange={(e) => setJurisdiction(e.target.value)}
          >
            {jurisdictions.map((r) => (
              <option key={r.jurisdiction} value={r.jurisdiction}>
                {label(JURISDICTION_LABEL, r.jurisdiction)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="mt-3 flex items-start gap-2 text-[12px] text-slate-500 dark:text-slate-400">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-status-warn" />
        <span>
          Changing this affects <strong>future</strong> checks only. Documents already checked
          keep the verdicts and citations from the ruleset that was actually applied at the
          time — they are not re-evaluated, and the change itself is recorded in your audit
          trail.
          {selected ? ` The selected ruleset has ${selected.rule_count} rules.` : ""}
        </span>
      </p>

      <div className="mt-3 flex items-center gap-3">
        <Button onClick={save} loading={busy} disabled={isCurrent || rulesets.length === 0}>
          {isCurrent ? "No change to save" : "Change applicable rules"}
        </Button>
        {note && <span className="text-[12.5px] text-status-good">{note}</span>}
        {error && <span className="text-[12.5px] text-status-bad">{error}</span>}
      </div>
    </Card>
  );
}

export function WorkspaceAdmin() {
  const { session } = useAuth();
  const [data, setData] = useState<TenantAdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumped after a jurisdiction change so the header re-reads the workspace
  // rather than showing the ruleset that was in force a moment ago.
  const [reloadKey, setReloadKey] = useState(0);

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
  }, [session, reloadKey]);

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
                  {label(INDUSTRY_LABEL, data.industry)} ·{" "}
                  {label(JURISDICTION_LABEL, data.jurisdiction)}
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

          <JurisdictionCard
            current={{ industry: data.industry, jurisdiction: data.jurisdiction }}
            onChanged={() => setReloadKey((k) => k + 1)}
          />

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
