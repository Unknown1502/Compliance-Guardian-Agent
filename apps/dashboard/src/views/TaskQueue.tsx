import { Link } from "react-router-dom";
import { Inbox } from "lucide-react";
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
        kind="Register"
        title="Task queue"
        subtitle="Every document received, and where its decision stands."
        action={
          <span className="font-mono-num inline-flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
            <span className="h-1.5 w-1.5 animate-pulse bg-brand-600 dark:bg-brand-400" />
            Live · {documents.length} entries
          </span>
        }
      />

      {docErr && (
        <p className="mb-6 border-l-2 border-oxide pl-3 text-[12.5px] text-oxide dark:text-[#D98878]">
          Firestore listener error: {docErr}
        </p>
      )}

      <div className="mb-9 grid grid-cols-2 gap-x-6 gap-y-7 sm:grid-cols-4">
        <StatCard label="Received" value={documents.length} tone="neutral" />
        <StatCard label="Approved" value={approved} tone="good" />
        <StatCard label="Escalated" value={escalated.length} tone="warning" />
        <StatCard label="Rejected" value={rejected} tone="critical" />
      </div>

      {session?.role !== "owner" && escalated.length > 0 && (
        <div className="mb-9 border-l-2 border-brass bg-brass/[0.05] py-4 pl-4 pr-4 dark:bg-brass/[0.08]">
          <p className="eyebrow !text-brass dark:!text-[#D6AD57]">
            Awaiting your review · {escalated.length}
          </p>
          <ul className="mt-2.5 space-y-1.5">
            {escalated.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="font-mono-num text-[12.5px] text-slate-700 underline decoration-brass/40 underline-offset-[3px] transition-colors hover:text-brass dark:text-slate-200 dark:hover:text-[#D6AD57]"
                >
                  {c.document_id} · risk {c.risk_score}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="eyebrow mb-3">Entries</p>
        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : documents.length === 0 ? (
          <div className="border border-slate-300 dark:border-slate-800">
            <EmptyState
              icon={Inbox}
              title="The register is empty"
              description="Upload a service record to open the first entry."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-y border-slate-900 dark:border-slate-100">
                  <th className="eyebrow py-2 pr-4 text-left font-medium">Document</th>
                  <th className="eyebrow py-2 pr-4 text-left font-medium">Ingestion</th>
                  <th className="eyebrow py-2 pr-4 text-left font-medium">Risk</th>
                  <th className="eyebrow py-2 pr-4 text-left font-medium">Decision</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const check = checksByDoc.get(doc.document_id);
                  return (
                    <tr
                      key={doc.document_id}
                      className="border-b border-slate-200 transition-colors hover:bg-white/70 dark:border-slate-800 dark:hover:bg-slate-900/60"
                    >
                      <td className="font-mono-num py-3 pr-4 text-slate-700 dark:text-slate-300">
                        {doc.document_id}
                      </td>
                      <td className="py-3 pr-4">
                        <StatusBadge status={doc.status} />
                      </td>
                      <td className="py-3 pr-4">
                        {check ? (
                          <RiskBadge score={check.risk_score} />
                        ) : (
                          <span className="text-slate-300 dark:text-slate-700">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        {check ? (
                          <DecisionBadge decision={check.decision} />
                        ) : (
                          <span className="text-slate-300 dark:text-slate-700">—</span>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        {check && (
                          <Link
                            to={`/checks/${check.check_id}`}
                            className="text-[12px] font-semibold uppercase tracking-[0.06em] text-brand-700 underline decoration-brand-600/30 underline-offset-[3px] transition-colors hover:decoration-brand-600 dark:text-brand-300 dark:decoration-brand-400/30"
                          >
                            Open
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
