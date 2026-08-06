import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Inbox, ChevronRight, RefreshCw, Filter } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getReviewQueue, listTeam, type TeamMember } from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import type { ComplianceCheck } from "../types";
import { cn } from "../lib/cn";

const RISK_TONE = (score: number) =>
  score >= 60 ? "text-status-critical" : score >= 30 ? "text-status-warning" : "text-status-good";

type Scope = "all" | "mine" | "unassigned";

export function HumanQueue() {
  const { session } = useAuth();
  const [checks, setChecks] = useState<ComplianceCheck[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>("all");

  const load = () => {
    if (!session) return;
    setLoading(true);
    getReviewQueue(session)
      .then(setChecks)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    if (session) listTeam(session).then(setTeam).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const emailFor = (uid: string | null | undefined) =>
    uid ? team.find((m) => m.uid === uid)?.email ?? uid : null;

  const filtered = useMemo(() => {
    if (scope === "mine") return checks.filter((c) => c.assigned_to === session?.uid);
    if (scope === "unassigned") return checks.filter((c) => !c.assigned_to);
    return checks;
  }, [checks, scope, session?.uid]);

  const counts = {
    all: checks.length,
    mine: checks.filter((c) => c.assigned_to === session?.uid).length,
    unassigned: checks.filter((c) => !c.assigned_to).length,
  };

  return (
    <div>
      <PageHeading
        title="Human queue"
        subtitle="Everything the AI declined to auto-approve and handed to a person."
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

      {error && <p className="mb-4 text-[13px] text-status-critical">{error}</p>}

      <div className="mb-5 inline-flex items-center gap-1 rounded-lg border border-line bg-surface p-1">
        <Filter size={12} className="ml-1.5 text-muted" />
        {(["all", "mine", "unassigned"] as Scope[]).map((s) => (
          <button
            key={s}
            onClick={() => setScope(s)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[12.5px] font-medium capitalize transition-colors",
              scope === s ? "bg-brand-600 text-white" : "text-ink-2 hover:bg-surface-2",
            )}
          >
            {s === "mine" ? "Assigned to me" : s} ({counts[s]})
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-12 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title={checks.length === 0 ? "Nothing awaiting review" : "Nothing in this view"}
            description={
              checks.length === 0
                ? "Every check so far cleared automatically. High-risk findings will appear here for a human decision."
                : "Try a different filter."
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {filtered.map((c) => (
              <li key={c.check_id}>
                <Link
                  to={`/checks/${c.check_id}`}
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-surface-2"
                >
                  <div className="w-12 shrink-0 text-center">
                    <div
                      className={cn(
                        "font-mono-num text-[19px] font-bold leading-none",
                        RISK_TONE(c.risk_score),
                      )}
                    >
                      {c.risk_score}
                    </div>
                    <div className="mt-0.5 text-[10px] uppercase tracking-wide text-muted">
                      risk
                    </div>
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="font-mono-num text-[13px] font-medium text-ink">
                      {c.document_id}
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-[12.5px] text-ink-2">
                      {c.justification}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="text-[11.5px] text-muted">
                        {c.citations.length} rule{c.citations.length === 1 ? "" : "s"} cited
                      </span>
                      {c.assigned_to ? (
                        <span className="text-[11.5px] text-brand-700">
                          {emailFor(c.assigned_to)}
                        </span>
                      ) : (
                        <span className="text-[11.5px] text-status-warning">Unassigned</span>
                      )}
                      {(c.comments?.length ?? 0) > 0 && (
                        <span className="text-[11.5px] text-muted">
                          {c.comments!.length} note{c.comments!.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                  </div>

                  <ChevronRight size={15} className="shrink-0 text-muted" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
