import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";
import { AnimatedNumber } from "./AnimatedNumber";

// KPI reading: small uppercase label above, large figure below, with a small
// ring showing the share of total where one applies.

const TONES = {
  brand: "text-slate-900 dark:text-slate-50",
  good: "text-status-good",
  warning: "text-status-warning",
  critical: "text-status-critical",
  neutral: "text-slate-900 dark:text-slate-50",
} as const;

const RING = {
  brand: "#2563EB",
  good: "#16A34A",
  warning: "#EA580C",
  critical: "#DC2626",
  neutral: "#A8A29B",
} as const;

export function StatCard({
  label,
  value,
  tone = "brand",
  suffix,
  total,
}: {
  label: string;
  value: number;
  /** Accepted for call-site compatibility; this design leads with the figure. */
  icon?: LucideIcon;
  tone?: keyof typeof TONES;
  index?: number;
  suffix?: string;
  total?: number;
}) {
  const pct = total && total > 0 ? Math.round((value / total) * 100) : null;
  const R = 9;
  const C = 2 * Math.PI * R;

  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className="mt-1.5 flex items-center gap-2">
        {pct !== null && (
          <svg width="22" height="22" viewBox="0 0 22 22" className="-rotate-90 shrink-0">
            <circle cx="11" cy="11" r={R} fill="none" strokeWidth="3" className="stroke-slate-200 dark:stroke-slate-700" />
            <circle
              cx="11"
              cy="11"
              r={R}
              fill="none"
              strokeWidth="3"
              strokeLinecap="round"
              stroke={RING[tone]}
              strokeDasharray={C}
              strokeDashoffset={C - (pct / 100) * C}
            />
          </svg>
        )}
        <span
          className={cn(
            "font-mono-num text-[26px] font-bold leading-none tracking-tight",
            TONES[tone],
          )}
        >
          <AnimatedNumber value={value} />
          {suffix}
        </span>
        {pct !== null && (
          <span className="font-mono-num text-[13px] font-medium text-slate-500 dark:text-slate-400">
            {pct}%
          </span>
        )}
      </div>
    </div>
  );
}
