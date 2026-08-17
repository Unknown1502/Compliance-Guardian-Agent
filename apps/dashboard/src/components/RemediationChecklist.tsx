import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Clock, ListChecks, Sparkles, AlertTriangle } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { fetchRemediationPlan, type RemediationPlan } from "../api/client";
import { Card, CardHeader } from "./ui/Card";

/**
 * The fix list for one compliance check.
 *
 * A risk score tells a provider something is wrong; this tells them what to do
 * about it, in the order worth doing. Items are already sorted server-side
 * (blocking first, then severity, then quickest) so the ordering is identical
 * every time the same check is viewed.
 *
 * Ticking an item is local only — deliberately. Persisting completion would
 * imply the system had verified the fix, and it has not. Re-running the check
 * is what proves the work; the checkbox is just a place to keep your finger.
 */
export function RemediationChecklist({ checkId }: { checkId: string }) {
  const { session } = useAuth();
  const [plan, setPlan] = useState<RemediationPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRemediationPlan(session, checkId)
      .then((p) => !cancelled && setPlan(p))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [session, checkId]);

  if (loading) {
    return (
      <Card>
        <div className="h-24 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-sm text-status-critical">
          <AlertTriangle size={15} className="shrink-0" />
          Could not load the fix list: {error}
        </div>
      </Card>
    );
  }

  // No plan, or a plan with nothing in it, both mean the same thing to a user.
  if (!plan || plan.items.length === 0) {
    return (
      <Card>
        <div className="flex items-center gap-2.5 py-1 text-sm text-slate-600 dark:text-slate-400">
          <CheckCircle2 size={16} className="shrink-0 text-status-good" />
          Nothing to fix on this document.
        </div>
      </Card>
    );
  }

  const blocking = plan.items.filter((i) => i.blocking).length;
  const hours = Math.round((plan.total_estimated_minutes / 60) * 10) / 10;

  return (
    <Card>
      <CardHeader
        title="What to fix"
        subtitle={
          <>
            {plan.items.length} item{plan.items.length === 1 ? "" : "s"}
            {blocking > 0 && (
              <>
                {" · "}
                <span className="font-medium text-status-critical">
                  {blocking} blocking
                </span>
              </>
            )}
            {" · "}~
            {plan.total_estimated_minutes < 60
              ? `${plan.total_estimated_minutes} min`
              : `${hours} hr`}{" "}
            total
          </>
        }
        action={
          !plan.used_fixture ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-status-good">
              <Sparkles size={11} />
              AI-generated
            </span>
          ) : undefined
        }
      />

      {plan.used_fixture && (
        <p className="mb-4 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-[12px] text-status-warning dark:border-orange-900/60 dark:bg-orange-950/25">
          These steps were derived from the rule text rather than written by the
          AI model, which was unavailable. They are accurate but less specific.
        </p>
      )}

      <ul className="space-y-2">
        {plan.items.map((item, i) => {
          const isDone = done.has(item.rule_id);
          return (
            <motion.li
              key={item.rule_id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.04 }}
              className={`rounded-xl border p-3 transition-colors ${
                isDone
                  ? "border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/40"
                  : item.blocking
                    ? "border-red-200 bg-red-50/40 dark:border-red-900/50 dark:bg-red-950/15"
                    : "border-slate-200 dark:border-slate-800"
              }`}
            >
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={isDone}
                  onChange={() =>
                    setDone((prev) => {
                      const next = new Set(prev);
                      if (next.has(item.rule_id)) next.delete(item.rule_id);
                      else next.add(item.rule_id);
                      return next;
                    })
                  }
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-brand-600 focus:ring-brand-500 dark:border-slate-600 dark:bg-slate-800"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                      className={`text-[13.5px] font-semibold ${
                        isDone
                          ? "text-slate-400 line-through dark:text-slate-500"
                          : "text-slate-900 dark:text-slate-100"
                      }`}
                    >
                      {item.title}
                    </span>
                    {item.blocking && !isDone && (
                      <span className="rounded bg-status-critical/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-status-critical">
                        Blocking
                      </span>
                    )}
                    <span className="inline-flex items-center gap-1 text-[11px] text-slate-400 dark:text-slate-500">
                      <Clock size={10} />
                      {item.estimated_minutes} min
                    </span>
                  </div>
                  <p
                    className={`mt-1 text-[13px] leading-relaxed ${
                      isDone
                        ? "text-slate-400 dark:text-slate-600"
                        : "text-slate-600 dark:text-slate-400"
                    }`}
                  >
                    {item.action}
                  </p>
                  {/* The rule id is what makes this an obligation rather than
                      an opinion — always show which rule demands it. */}
                  <p className="mt-1.5 font-mono-num text-[11px] text-slate-400 dark:text-slate-500">
                    {item.rule_id}
                  </p>
                </div>
              </label>
            </motion.li>
          );
        })}
      </ul>

      <p className="mt-4 flex items-start gap-2 text-[12px] leading-relaxed text-slate-500 dark:text-slate-400">
        <ListChecks size={13} className="mt-0.5 shrink-0" />
        Ticking items here is just for your own tracking — it is not saved and
        does not change the compliance result. Re-run the check once you have
        made the changes.
      </p>
    </Card>
  );
}
