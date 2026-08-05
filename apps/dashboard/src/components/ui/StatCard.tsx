import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";
import { AnimatedNumber } from "./AnimatedNumber";

// Ledger tallies, not dashboard tiles: the figure leads, the label sits under
// a hairline. No icon chips, no tinted squares.

const TONES = {
  brand: "text-brand-700 dark:text-brand-300",
  good: "text-brand-700 dark:text-brand-300",
  warning: "text-brass dark:text-[#D6AD57]",
  critical: "text-oxide dark:text-[#D98878]",
  neutral: "text-slate-700 dark:text-slate-200",
} as const;

export function StatCard({
  label,
  value,
  tone = "brand",
  suffix,
}: {
  label: string;
  value: number;
  /** Accepted for call-site compatibility; the design no longer shows icons. */
  icon?: LucideIcon;
  tone?: keyof typeof TONES;
  index?: number;
  suffix?: string;
}) {
  return (
    <div className="border-t-2 border-slate-900 pt-3 dark:border-slate-100">
      <div className={cn("font-mono-num text-[30px] font-semibold leading-none", TONES[tone])}>
        <AnimatedNumber value={value} />
        {suffix}
      </div>
      <div className="eyebrow mt-2">{label}</div>
    </div>
  );
}
