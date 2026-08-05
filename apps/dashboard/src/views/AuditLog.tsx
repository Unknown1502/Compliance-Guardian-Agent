import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Search, ScrollText, RefreshCw } from "lucide-react";
import { getAuditLogs } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AuditEvent } from "../types";
import { Card, PageHeading } from "../components/ui/Card";
import { TableSkeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";

export function AuditLog() {
  const { session } = useAuth();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const load = () => {
    if (!session) return;
    setLoading(true);
    getAuditLogs(session)
      .then((r) => setEvents(r.events))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [session]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return events;
    return events.filter(
      (e) =>
        e.actor.toLowerCase().includes(q) ||
        e.action.toLowerCase().includes(q) ||
        e.event_id.toLowerCase().includes(q),
    );
  }, [events, query]);

  return (
    <div className="space-y-6">
      <PageHeading
        kind="Provenance"
        title="Audit log"
        subtitle="Immutable, append-only record of every decision."
        action={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-slate-500 transition-colors hover:text-brand-700 disabled:opacity-50 dark:text-slate-400 dark:hover:text-brand-300"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      <div className="relative max-w-sm">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by actor, action, or event id…"
          className="w-full rounded-xl border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm shadow-sm focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        />
      </div>

      {error && <p className="text-sm text-status-critical">{error}</p>}

      <Card padded={false} className="overflow-hidden">
        {loading ? (
          <TableSkeleton rows={7} cols={3} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title={events.length === 0 ? "No audit events yet" : "No matches"}
            description={
              events.length === 0
                ? "Actions taken across the tenant will appear here as they happen."
                : "Try a different search term."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Time (UTC)</th>
                  <th className="px-5 py-2.5 font-medium">Actor</th>
                  <th className="px-5 py-2.5 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e, i) => (
                  <motion.tr
                    key={e.event_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.25, delay: Math.min(i * 0.02, 0.3) }}
                    className="border-t border-slate-100 hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/40"
                  >
                    <td className="px-5 py-2.5 font-mono-num text-slate-500 dark:text-slate-400">
                      {e.created_at}
                    </td>
                    <td className="px-5 py-2.5 font-mono-num text-slate-700 dark:text-slate-300">
                      {e.actor}
                    </td>
                    <td className="px-5 py-2.5">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {e.action}
                      </span>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
