import { motion } from "framer-motion";

// Segmented bar showing the pass/escalated/rejected split. Uses the fixed
// status palette; every segment carries a swatch + label + count so identity
// never rides on color alone (dataviz status-palette rule).

interface Segment {
  label: string;
  count: number;
  color: string;
}

export function DecisionBreakdown({
  approved,
  escalated,
  rejected,
}: {
  approved: number;
  escalated: number;
  rejected: number;
}) {
  const segments: Segment[] = [
    { label: "Approved", count: approved, color: "#0ca30c" },
    { label: "Escalated", count: escalated, color: "#fab219" },
    { label: "Rejected", count: rejected, color: "#d03b3b" },
  ];
  const total = Math.max(1, approved + escalated + rejected);

  return (
    <div>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        {segments.map((s, i) => {
          const pct = (s.count / total) * 100;
          if (pct <= 0) return null;
          return (
            <motion.div
              key={s.label}
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.7, delay: 0.15 + i * 0.08, ease: [0.16, 1, 0.3, 1] }}
              style={{ backgroundColor: s.color }}
              className="h-full first:rounded-l-full last:rounded-r-full"
            />
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center gap-1.5 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: s.color }}
              aria-hidden
            />
            <span className="text-slate-500 dark:text-slate-400">{s.label}</span>
            <span className="font-mono-num font-semibold text-slate-700 dark:text-slate-200">
              {s.count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
