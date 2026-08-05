import { useEffect, useMemo, useState } from "react";
import { Search, ScrollText, RefreshCw, ChevronRight, Bot, User as UserIcon } from "lucide-react";
import { getAuditLogs } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { AuditEvent } from "../types";
import { PageHeading } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { cn } from "../lib/cn";

const ACTION_TONE: Record<string, string> = {
  escalated: "bg-status-warning",
  rejected: "bg-status-critical",
  failed: "bg-status-critical",
  approved: "bg-status-good",
  purchased: "bg-status-good",
  subscribed: "bg-status-good",
};

function toneForAction(action: string): string {
  for (const [key, cls] of Object.entries(ACTION_TONE)) {
    if (action.includes(key)) return cls;
  }
  return "bg-audit";
}

function isAgent(actor: string) {
  return /agent|orchestrator|webhook|-service$/i.test(actor);
}

function prettyJson(raw: string | null): string | null {
  if (!raw || raw === "null") return null;
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function EventRow({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const before = prettyJson(e.before_state);
  const after = prettyJson(e.after_state);
  const hasMeta = before || after;

  return (
    <li className="relative pl-9">
      {/* Timeline rail + node — the commit-history visual language. */}
      <span className="absolute left-[7px] top-0 h-full w-px bg-line" aria-hidden="true" />
      <span
        className={cn(
          "absolute left-0 top-[18px] h-3.5 w-3.5 rounded-full ring-4 ring-bg dark:ring-slate-950",
          toneForAction(e.action),
        )}
        aria-hidden="true"
      />

      <button
        type="button"
        onClick={() => hasMeta && setOpen((o) => !o)}
        className={cn(
          "flex w-full items-start gap-3 rounded-lg py-3 pr-3 text-left transition-colors",
          hasMeta && "hover:bg-surface-2",
        )}
      >
        <div className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-surface-2 text-ink-2">
          {isAgent(e.actor) ? <Bot size={12.5} /> : <UserIcon size={12.5} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-mono-num text-[13px] font-semibold text-ink">{e.actor}</span>
            <span className="text-[12.5px] text-muted">{e.action}</span>
          </div>
          <p className="font-mono-num mt-0.5 text-[11.5px] text-muted">
            {e.created_at} · {e.event_id.slice(0, 8)}
          </p>
        </div>
        {hasMeta && (
          <ChevronRight
            size={14}
            className={cn("mt-1 shrink-0 text-muted transition-transform", open && "rotate-90")}
          />
        )}
      </button>

      {hasMeta && open && (
        <div className="mb-3 ml-9 grid gap-3 rounded-lg border border-line bg-surface-2 p-3 sm:grid-cols-2">
          {before && (
            <div>
              <span className="eyebrow">Before</span>
              <pre className="font-mono-num mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed text-ink-2">
                {before}
              </pre>
            </div>
          )}
          {after && (
            <div>
              <span className="eyebrow">After</span>
              <pre className="font-mono-num mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed text-ink-2">
                {after}
              </pre>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

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
    <div>
      <PageHeading
        title="Audit log"
        subtitle="Immutable, append-only record of every decision — human and AI."
        action={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[12.5px] font-medium text-ink-2 transition-colors hover:bg-surface-2 disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      <div className="relative mb-6 max-w-sm">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by actor, action, or event id…"
          className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-[13.5px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15"
        />
      </div>

      {error && <p className="mb-4 text-[13px] text-status-critical">{error}</p>}

      <div className="rounded-xl border border-line bg-surface p-5">
        {loading ? (
          <div className="space-y-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="h-6 w-6 animate-pulse rounded-md bg-surface-2" />
                <div className="h-3.5 flex-1 animate-pulse rounded bg-surface-2" style={{ maxWidth: 320 }} />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title={events.length === 0 ? "No audit events yet" : "No matches"}
            description={
              events.length === 0
                ? "Actions taken across the tenant — by people and by agents — appear here as they happen."
                : "Try a different search term."
            }
          />
        ) : (
          <ul>
            {filtered.map((e) => (
              <EventRow key={e.event_id} e={e} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
