import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTenantCollection } from "../hooks/useTenantCollection";
import { DecisionBadge, RiskBadge, StatusBadge } from "../components/Badges";
import type { ComplianceCheck, DocumentRecord } from "../types";

export function TaskQueue() {
  const { session } = useAuth();
  const { data: documents, error: docErr } = useTenantCollection<DocumentRecord>(
    "documents",
    session?.tenantId,
  );
  const { data: checks } = useTenantCollection<ComplianceCheck>(
    "compliance_checks",
    session?.tenantId,
  );

  const checksByDoc = new Map<string, ComplianceCheck>();
  for (const c of checks) checksByDoc.set(c.document_id, c);

  const escalated = checks.filter((c) => c.decision === "escalated");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Task queue</h2>
          <p className="text-sm text-slate-500">
            Live view of documents and their compliance status.
          </p>
        </div>
        <span className="text-xs text-slate-400">
          Real-time · {documents.length} documents
        </span>
      </div>

      {docErr && (
        <p className="text-sm text-red-600">
          Firestore listener error: {docErr}
        </p>
      )}

      {session?.role !== "owner" && escalated.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">
            Awaiting your review ({escalated.length})
          </h3>
          <ul className="space-y-1">
            {escalated.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="text-sm text-amber-800 underline hover:text-amber-900"
                >
                  {c.document_id} — risk {c.risk_score}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Document</th>
              <th className="px-4 py-2 font-medium">Ingestion</th>
              <th className="px-4 py-2 font-medium">Risk</th>
              <th className="px-4 py-2 font-medium">Decision</th>
              <th className="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {documents.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                  No documents yet — upload one to get started.
                </td>
              </tr>
            )}
            {documents.map((doc) => {
              const check = checksByDoc.get(doc.document_id);
              return (
                <tr key={doc.document_id} className="border-t border-slate-100">
                  <td className="px-4 py-3 font-mono text-slate-700">
                    {doc.document_id}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={doc.status} />
                  </td>
                  <td className="px-4 py-3">
                    {check ? <RiskBadge score={check.risk_score} /> : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {check ? <DecisionBadge decision={check.decision} /> : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {check && (
                      <Link
                        to={`/checks/${check.check_id}`}
                        className="text-brand-600 hover:text-brand-700 font-medium"
                      >
                        View
                      </Link>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
