import { Link } from "react-router-dom";
import { Inbox, Flag, ChevronRight } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useTenantCollection } from "../hooks/useTenantCollection";
import { DecisionBadge, RiskBadge, StatusBadge } from "../components/Badges";
import { PageHeading } from "../components/ui/Card";
import { StatCard } from "../components/ui/StatCard";
import { EmptyState } from "../components/ui/EmptyState";
import { TableSkeleton } from "../components/ui/Skeleton";
import type { ComplianceCheck, DocumentRecord } from "../types";

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
  const rejected = checks.filter((c) => c.decision === "rejected").length;

  return (
    <div>
      <PageHeading
        title="Task queue"
        subtitle="Every document received, and where its decision stands."
        action={
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1 text-[12px] font-medium text-slate-500 dark:border-slate-800 dark:text-slate-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-status-good" />
            Live
          </span>
        }
      />

      {docErr && (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5 text-[13px] text-status-critical dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          Firestore listener error: {docErr}
        </div>
      )}

      <div className="mb-8 grid grid-cols-2 gap-6 rounded-xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900 sm:grid-cols-4">
        <StatCard label="Documents" value={documents.length} tone="neutral" />
        <StatCard label="Approved" value={approved} tone="good" total={checks.length || undefined} />
        <StatCard label="Escalated" value={escalated.length} tone="warning" total={checks.length || undefined} />
        <StatCard label="Rejected" value={rejected} tone="critical" total={checks.length || undefined} />
      </div>

      {session?.role !== "owner" && escalated.length > 0 && (
        <div className="mb-8 rounded-xl border border-orange-200 bg-orange-50 p-4 dark:border-orange-900/60 dark:bg-orange-950/25">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-status-warning">
            <Flag size={14} strokeWidth={2.25} />
            Awaiting your review ({escalated.length})
          </h3>
          <ul className="mt-2 space-y-1">
            {escalated.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="font-mono-num text-[12.5px] text-slate-700 hover:text-status-warning dark:text-slate-300"
                >
                  {c.document_id} · risk {c.risk_score}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
          <h3 className="text-[13px] font-semibold text-slate-700 dark:text-slate-200">
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
                <tr className="border-b border-slate-200 dark:border-slate-800">
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
                      className="border-b border-slate-100 transition-colors last:border-0 hover:bg-slate-50 dark:border-slate-800/70 dark:hover:bg-slate-900/60"
                    >
                      <td className="font-mono-num px-4 py-3 text-slate-700 dark:text-slate-300">
                        {doc.document_id}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={doc.status} />
                      </td>
                      <td className="px-4 py-3">
                        {check ? (
                          <RiskBadge score={check.risk_score} />
                        ) : (
                          <span className="text-slate-300 dark:text-slate-700">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {check ? (
                          <DecisionBadge decision={check.decision} />
                        ) : (
                          <span className="text-slate-300 dark:text-slate-700">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {check && (
                          <Link
                            to={`/checks/${check.check_id}`}
                            className="inline-flex items-center gap-0.5 text-[13px] font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400"
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
