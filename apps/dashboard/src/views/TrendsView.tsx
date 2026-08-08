import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { TrendingUp, BarChart3, Table2, AlertTriangle } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { fetchTrends, type TrendsResponse, type WeekBucket } from "../api/client";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

// Colors come from the design system's status tokens (tailwind.config.js →
// colors.status), NOT ad-hoc hexes. Two obligations came out of validating
// this palette, and both are met below rather than waved through:
//
//   1. amber↔green sit in the 6-8 CVD separation band, which is only legal
//      with secondary encoding — so every segment carries a labelled legend
//      entry and segments are separated by a visible surface gap. Identity
//      never rides on hue alone.
//   2. amber falls under 3:1 against the light surface, which obliges a
//      non-colour route to the same numbers — hence the table view toggle,
//      which is also just the faster way to read exact counts.
const SERIES = [
  { key: "auto_approved", label: "Approved", color: "#16A34A" },
  { key: "escalated", label: "Escalated", color: "#F59E0B" },
  { key: "rejected", label: "Rejected", color: "#DC2626" },
] as const;

type SeriesKey = (typeof SERIES)[number]["key"];

function weekLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Stacked column per week. Height is share-of-max, so the tallest week fills the plot. */
function TrendChart({ weeks }: { weeks: WeekBucket[] }) {
  const max = Math.max(1, ...weeks.map((w) => w.total_checks));
  const [hovered, setHovered] = useState<number | null>(null);

  // At 52 weeks each column is ~11px wide, so a label under every one would
  // collide into an unreadable smear. Thin them to roughly a dozen, always
  // keeping the newest week labelled.
  const labelEvery = Math.ceil(weeks.length / 12);

  return (
    <div>
      <div className="relative flex h-52 items-end gap-1.5" role="img"
        aria-label={`Compliance checks per week for the last ${weeks.length} weeks`}>
        {weeks.map((w, i) => {
          const heightPct = (w.total_checks / max) * 100;
          // Tooltips are anchored to the column, so the ones at either end
          // would render past the card edge and get clipped. Pin the first
          // and last few to the inside instead of centring them.
          const nearStart = i < 2;
          const nearEnd = i > weeks.length - 3;
          const tooltipAnchor = nearStart
            ? "left-0"
            : nearEnd
              ? "right-0"
              : "left-1/2 -translate-x-1/2";
          return (
            <div
              key={w.week_start}
              className="group relative flex h-full flex-1 flex-col justify-end"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              {hovered === i && (
                <div
                  className={`pointer-events-none absolute bottom-full z-10 mb-2 w-40 rounded-lg border border-slate-200 bg-white p-2.5 text-left shadow-soft-lg dark:border-slate-700 dark:bg-slate-800 ${tooltipAnchor}`}
                >
                  <p className="mb-1.5 text-[11px] font-semibold text-slate-900 dark:text-slate-100">
                    Week of {weekLabel(w.week_start)}
                  </p>
                  {SERIES.map((s) => (
                    <div key={s.key} className="flex items-center gap-1.5 text-[11px]">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: s.color }}
                        aria-hidden
                      />
                      <span className="text-slate-500 dark:text-slate-400">{s.label}</span>
                      <span className="ml-auto font-mono-num font-semibold text-slate-700 dark:text-slate-200">
                        {w[s.key as SeriesKey]}
                      </span>
                    </div>
                  ))}
                  <div className="mt-1.5 flex items-center gap-1.5 border-t border-slate-100 pt-1.5 text-[11px] dark:border-slate-700">
                    <span className="text-slate-500 dark:text-slate-400">Total</span>
                    <span className="ml-auto font-mono-num font-semibold text-slate-900 dark:text-slate-100">
                      {w.total_checks}
                    </span>
                  </div>
                </div>
              )}

              {/* 2px gaps between stacked segments so adjacent fills never touch. */}
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: `${heightPct}%` }}
                transition={{ duration: 0.6, delay: i * 0.03, ease: [0.16, 1, 0.3, 1] }}
                className="flex w-full flex-col-reverse gap-[2px] overflow-hidden rounded-t"
              >
                {SERIES.map((s) => {
                  const value = w[s.key as SeriesKey];
                  if (value <= 0) return null;
                  return (
                    <div
                      key={s.key}
                      style={{
                        backgroundColor: s.color,
                        flexGrow: value,
                        // Keep a thin segment visible rather than sub-pixel.
                        minHeight: 3,
                      }}
                      className="w-full first:rounded-t"
                    />
                  );
                })}
              </motion.div>

              <span className="mt-2 block h-3 truncate text-center text-[10px] text-slate-400 dark:text-slate-500">
                {i % labelEvery === 0 || i === weeks.length - 1
                  ? weekLabel(w.week_start)
                  : ""}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend is always present for 3 series — identity never colour-alone. */}
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-slate-100 pt-3 dark:border-slate-800">
        {SERIES.map((s) => {
          const total = weeks.reduce((sum, w) => sum + w[s.key as SeriesKey], 0);
          return (
            <div key={s.key} className="flex items-center gap-1.5 text-xs">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: s.color }}
                aria-hidden
              />
              <span className="text-slate-500 dark:text-slate-400">{s.label}</span>
              <span className="font-mono-num font-semibold text-slate-700 dark:text-slate-200">
                {total}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The same numbers without colour — required relief for the amber contrast warning. */
function TrendTable({ weeks }: { weeks: WeekBucket[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12.5px]">
        <thead className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 dark:border-slate-700 dark:text-slate-500">
          <tr>
            <th className="py-2 pr-4 font-medium">Week of</th>
            {SERIES.map((s) => (
              <th key={s.key} className="py-2 pr-4 text-right font-medium">
                {s.label}
              </th>
            ))}
            <th className="py-2 text-right font-medium">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {weeks.map((w) => (
            <tr key={w.week_start}>
              <td className="py-2 pr-4 text-slate-600 dark:text-slate-300">
                {weekLabel(w.week_start)}
              </td>
              {SERIES.map((s) => (
                <td
                  key={s.key}
                  className="py-2 pr-4 text-right font-mono-num text-slate-700 dark:text-slate-200"
                >
                  {w[s.key as SeriesKey]}
                </td>
              ))}
              <td className="py-2 text-right font-mono-num font-semibold text-slate-900 dark:text-slate-100">
                {w.total_checks}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Ranked horizontal bars. One series, so no legend — the card title names it. */
function TopViolations({ items }: { items: { rule_id: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={item.rule_id}>
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className="truncate font-mono-num text-[12px] text-slate-700 dark:text-slate-300">
              {item.rule_id}
            </span>
            {/* Direct value label — a single series needs no legend lookup. */}
            <span className="shrink-0 font-mono-num text-[12px] font-semibold text-slate-900 dark:text-slate-100">
              {item.count}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${(item.count / max) * 100}%` }}
              transition={{ duration: 0.6, delay: 0.1 + i * 0.05, ease: [0.16, 1, 0.3, 1] }}
              className="h-full rounded-full bg-brand-600 dark:bg-brand-500"
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function TrendsView() {
  const { session } = useAuth();
  const [data, setData] = useState<TrendsResponse | null>(null);
  const [weeks, setWeeks] = useState(12);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTrends(session, weeks)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session, weeks]);

  const hasChecks = useMemo(
    () => (data?.weeks ?? []).some((w) => w.total_checks > 0),
    [data],
  );

  return (
    <div className="space-y-6">
      <PageHeading
        title="Trends"
        subtitle="How compliance risk has moved over time, and which rules keep failing."
        action={
          <select
            value={weeks}
            onChange={(e) => setWeeks(Number(e.target.value))}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            aria-label="Time range"
          >
            <option value={4}>Last 4 weeks</option>
            <option value={12}>Last 12 weeks</option>
            <option value={26}>Last 26 weeks</option>
            <option value={52}>Last 52 weeks</option>
          </select>
        }
      />

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-status-critical dark:border-red-900/60 dark:bg-red-950/25">
          <AlertTriangle size={15} className="shrink-0" />
          {error}
        </div>
      )}

      {loading && (
        <Card>
          <div className="h-52 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
        </Card>
      )}

      {!loading && data && !hasChecks && (
        <Card>
          <EmptyState
            icon={TrendingUp}
            title="No compliance checks yet"
            description="Once documents have been checked, this page charts the decision mix week by week and surfaces the rules that fail most often."
          />
        </Card>
      )}

      {!loading && data && hasChecks && (
        <>
          <Card>
            <CardHeader
              title="Decision mix by week"
              subtitle="Every compliance check, grouped into 7-day windows."
              action={
                <button
                  type="button"
                  onClick={() => setAsTable((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  {asTable ? <BarChart3 size={13} /> : <Table2 size={13} />}
                  {asTable ? "Chart" : "Table"}
                </button>
              }
            />
            {asTable ? <TrendTable weeks={data.weeks} /> : <TrendChart weeks={data.weeks} />}
          </Card>

          <Card>
            <CardHeader
              title="Most-cited rules, all time"
              subtitle="Where this business keeps tripping — the best place to fix a process rather than a document."
            />
            {data.top_violations.length > 0 ? (
              <TopViolations items={data.top_violations} />
            ) : (
              <p className="py-6 text-center text-[13px] text-slate-500 dark:text-slate-400">
                No rule citations recorded yet.
              </p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
