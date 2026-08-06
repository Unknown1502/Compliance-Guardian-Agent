import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Inbox, Flag, ChevronRight, Activity, Bot, User as UserIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useTenantCollection } from "../hooks/useTenantCollection";
import { getAuditLogs } from "../api/client";
import { DecisionBadge, RiskBadge, StatusBadge } from "../components/Badges";
import { PageHeading } from "../components/ui/Card";
import { StatCard } from "../components/ui/StatCard";
import { EmptyState } from "../components/ui/EmptyState";
import { TableSkeleton } from "../components/ui/Skeleton";
import type { AuditEvent, ComplianceCheck, DocumentRecord } from "../types";

// Risk bands mirror the backend's escalation threshold (60) and the
// medium boundary used by RiskBadge — keep these in step with those.
const BANDS = [
  { key: "low", label: "Low", range: "0–29", cls: "bg-status-good", test: (n: number) => n < 30 },
  {
    key: "medium",
    label: "Medium",
    range: "30–59",
    cls: "bg-status-warning",
    test: (n: number) => n >= 30 && n < 60,
  },
  { key: "high", label: "High", range: "60–100", cls: "bg-status-critical", test: (n: number) => n >= 60 },
];

function isAgent(actor: string) {
  return /agent|orchestrator|webhook|-service$/i.test(actor);
}

function RiskDistribution({ checks }: { checks: ComplianceCheck[] }) {
  const total = checks.length;
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <h3 className="text-[13px] font-semibold text-ink">Risk distribution</h3>
      <p className="mt-0.5 text-[12.5px] text-ink-2">
        {total === 0 ? "No checks scored yet." : `Across ${total} scored check${total === 1 ? "" : "s"}.`}
      </p>
      <div className="mt-4 space-y-3">
        {BANDS.map((b) => {
          const count = checks.filter((c) => b.test(c.risk_score)).length;
          const pct = total === 0 ? 0 : Math.round((count / total) * 100);
          return (
            <div key={b.key} className="flex items-center gap-3">
              <span className="w-14 shrink-0 text-[12.5px] text-ink-2">{b.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <div className={`h-full ${b.cls} transition-all`} style={{ width: `${pct}%` }} />
              </div>
              <span className="font-mono-num w-16 shrink-0 text-right text-[12px] text-muted">
                {count} · {pct}%
              </span>
            </div>
          );
        })}
      </div>
      <p className="font-mono-num mt-3 border-t border-line pt-3 text-[11px] text-muted">
        Escalation threshold: 60
      </p>
    </div>
  );
}

function RecentActivity({ tenantId }: { tenantId: string | undefined }) {
  const { session } = useAuth();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    getAuditLogs(session)
      .then((r) => setEvents(r.events.slice(0, 6)))
      .catch(() => {})
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, tenantId]);

  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-ink">Recent activity</h3>
        <Link
          to="/audit"
          className="inline-flex items-center gap-0.5 text-[12.5px] font-medium text-brand-600 hover:text-brand-700"
        >
          Audit log <ChevronRight size={13} />
        </Link>
      </div>

      {loading ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-surface-2" />
          ))}
        </div>
      ) : events.length === 0 ? (
        <p className="mt-4 text-[12.5px] text-muted">
          Nothing recorded yet. Every action — human or agent — appears here.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {events.map((e) => (
            <li key={e.event_id} className="flex items-start gap-2.5">
              <div className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-surface-2 text-ink-2">
                {isAgent(e.actor) ? <Bot size={11} /> : <UserIcon size={11} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-1.5">
                  <span className="font-mono-num truncate text-[12.5px] font-medium text-ink">
                    {e.actor}
                  </span>
                  <span className="text-[12px] text-ink-2">{e.action}</span>
                </div>
                <span className="font-mono-num text-[11px] text-muted">{e.created_at}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TaskQueue() {
  const { session } = useAuth();
  const {
    data: documents,
    error: docErr,
    loading: docsLoading,
  } = useTenantCollection<DocumentRecord>("documents", session?.tenantId);
  const { data: checks, loading: checksLoading } = useTenantCollection<ComplianceCheck>(
    "compliance_checks",
    session?.tenantId,
  );

  const loading = docsLoading || checksLoading;
  const checksByDoc = new Map<string, ComplianceCheck>();
  for (const c of checks) checksByDoc.set(c.document_id, c);

  const escalated = checks.filter((c) => c.decision === "escalated");
  const approved = checks.filter((c) => c.decision === "auto_approved").length;
  const pending = documents.filter((d) => !checksByDoc.has(d.document_id)).length;

  return (
    <div>
      <PageHeading
        title="Overview"
        subtitle="Live compliance status across this workspace."
        action={
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1 text-[12px] font-medium text-ink-2">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-status-good" />
            Live
          </span>
        }
      />

      {docErr && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5 text-[13px] text-status-critical">
          Firestore listener error: {docErr}
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-6 rounded-xl border border-line bg-surface p-5 sm:grid-cols-4">
        <StatCard label="Documents" value={documents.length} tone="neutral" />
        <StatCard label="Approved" value={approved} tone="good" total={checks.length || undefined} />
        <StatCard
          label="Escalated"
          value={escalated.length}
          tone="warning"
          total={checks.length || undefined}
        />
        <StatCard label="Awaiting check" value={pending} tone="neutral" />
      </div>

      <div className="mb-6 grid gap-5 lg:grid-cols-2">
        <RiskDistribution checks={checks} />
        <RecentActivity tenantId={session?.tenantId} />
      </div>

      {session?.role !== "owner" && escalated.length > 0 && (
        <div className="mb-6 rounded-xl border border-orange-200 bg-orange-50 p-4">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-status-warning">
            <Flag size={14} strokeWidth={2.25} />
            Awaiting your review ({escalated.length})
          </h3>
          <ul className="mt-2 space-y-1">
            {escalated.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="font-mono-num text-[12.5px] text-ink-2 hover:text-status-warning"
                >
                  {c.document_id} · risk {c.risk_score}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <div className="flex items-center justify-between border-b border-line bg-surface-2 px-4 py-2.5">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink-2">
            <Activity size={13} />
            All documents
          </h3>
        </div>

        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : documents.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No documents yet"
            description="Upload a service record to run your first compliance check."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13.5px]">
              <thead>
                <tr className="border-b border-line">
                  <th className="eyebrow px-4 py-2 text-left">Document</th>
                  <th className="eyebrow px-4 py-2 text-left">Ingestion</th>
                  <th className="eyebrow px-4 py-2 text-left">Risk</th>
                  <th className="eyebrow px-4 py-2 text-left">Decision</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const check = checksByDoc.get(doc.document_id);
                  return (
                    <tr
                      key={doc.document_id}
                      className="border-b border-line transition-colors last:border-0 hover:bg-surface-2"
                    >
                      <td className="font-mono-num px-4 py-3 text-ink-2">{doc.document_id}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={doc.status} />
                      </td>
                      <td className="px-4 py-3">
                        {check ? (
                          <RiskBadge score={check.risk_score} />
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {check ? (
                          <DecisionBadge decision={check.decision} />
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {check && (
                          <Link
                            to={`/checks/${check.check_id}`}
                            className="inline-flex items-center gap-0.5 text-[13px] font-medium text-brand-600 hover:text-brand-700"
                          >
                            View
                            <ChevronRight size={14} />
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
