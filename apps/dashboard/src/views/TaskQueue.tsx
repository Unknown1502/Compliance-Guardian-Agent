import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  FileStack,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ArrowUpRight,
  Inbox,
  Radio,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useTenantCollection } from "../hooks/useTenantCollection";
import { DecisionBadge, RiskBadge, StatusBadge } from "../components/Badges";
import { Card, CardHeader } from "../components/ui/Card";
import { StatCard } from "../components/ui/StatCard";
import { EmptyState } from "../components/ui/EmptyState";
import { TableSkeleton } from "../components/ui/Skeleton";
import { DecisionBreakdown } from "../components/ui/DecisionBreakdown";
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-slate-800 dark:text-slate-100">
            Task queue
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Live view of documents and their compliance status.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-soft ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800">
          <Radio size={11} className="text-status-good animate-pulse" />
          Real-time · {documents.length} documents
        </span>
      </div>

      {docErr && (
        <p className="text-sm text-status-critical">Firestore listener error: {docErr}</p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        <StatCard label="Documents" value={documents.length} icon={FileStack} tone="brand" index={0} />
        <StatCard label="Approved" value={approved} icon={CheckCircle2} tone="good" index={1} />
        <StatCard label="Escalated" value={escalated.length} icon={AlertTriangle} tone="warning" index={2} />
        <StatCard label="Rejected" value={rejected} icon={XCircle} tone="critical" index={3} />
      </div>

      {checks.length > 0 && (
        <Card>
          <CardHeader title="Decision breakdown" subtitle="All compliance checks for this tenant" />
          <DecisionBreakdown approved={approved} escalated={escalated.length} rejected={rejected} />
        </Card>
      )}

      {session?.role !== "owner" && escalated.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30"
        >
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-amber-800 dark:text-amber-300">
            <AlertTriangle size={15} />
            Awaiting your review ({escalated.length})
          </h3>
          <ul className="space-y-1">
            {escalated.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="group inline-flex items-center gap-1 text-sm text-amber-800 hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-200"
                >
                  <span className="underline decoration-amber-300 underline-offset-2">
                    {c.document_id} — risk {c.risk_score}
                  </span>
                  <ArrowUpRight
                    size={12}
                    className="opacity-0 transition-opacity group-hover:opacity-100"
                  />
                </Link>
              </li>
            ))}
          </ul>
        </motion.div>
      )}

      <Card padded={false} className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5 dark:border-slate-800">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            All documents
          </h3>
        </div>

        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : documents.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No documents yet"
            description="Upload a document to trigger ingestion and get an instant compliance check."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Document</th>
                  <th className="px-5 py-2.5 font-medium">Ingestion</th>
                  <th className="px-5 py-2.5 font-medium">Risk</th>
                  <th className="px-5 py-2.5 font-medium">Decision</th>
                  <th className="px-5 py-2.5 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc, i) => {
                  const check = checksByDoc.get(doc.document_id);
                  return (
                    <motion.tr
                      key={doc.document_id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: Math.min(i * 0.04, 0.4) }}
                      className="border-t border-slate-100 transition-colors hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/40"
                    >
                      <td className="px-5 py-3 font-mono-num text-slate-700 dark:text-slate-300">
                        {doc.document_id}
                      </td>
                      <td className="px-5 py-3">
                        <StatusBadge status={doc.status} />
                      </td>
                      <td className="px-5 py-3">
                        {check ? <RiskBadge score={check.risk_score} /> : <span className="text-slate-300 dark:text-slate-600">—</span>}
                      </td>
                      <td className="px-5 py-3">
                        {check ? <DecisionBadge decision={check.decision} /> : <span className="text-slate-300 dark:text-slate-600">—</span>}
                      </td>
                      <td className="px-5 py-3 text-right">
                        {check && (
                          <Link
                            to={`/checks/${check.check_id}`}
                            className="inline-flex items-center gap-0.5 font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400 dark:hover:text-brand-300"
                          >
                            View
                            <ArrowUpRight size={13} />
                          </Link>
                        )}
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
