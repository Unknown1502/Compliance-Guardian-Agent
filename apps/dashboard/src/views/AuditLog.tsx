import { useEffect, useState } from "react";
import { getAuditLogs } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AuditEvent } from "../types";

export function AuditLog() {
  const { session } = useAuth();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    getAuditLogs(session)
      .then((r) => setEvents(r.events))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800">Audit log</h2>
        <p className="text-sm text-slate-500">
          Immutable, append-only record of every decision (BigQuery).
        </p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Time (UTC)</th>
                <th className="px-4 py-2 font-medium">Actor</th>
                <th className="px-4 py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-slate-400">
                    No audit events yet.
                  </td>
                </tr>
              )}
              {events.map((e) => (
                <tr key={e.event_id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-mono text-slate-500">
                    {e.created_at}
                  </td>
                  <td className="px-4 py-2 font-mono text-slate-700">{e.actor}</td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 bg-slate-100 rounded text-xs font-medium text-slate-600">
                      {e.action}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
