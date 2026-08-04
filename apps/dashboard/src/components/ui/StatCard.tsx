import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";
import { AnimatedNumber } from "./AnimatedNumber";

const TONES = {
  brand: "bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-400",
  good: "bg-green-50 text-status-good dark:bg-green-950/40 dark:text-green-400",
  warning: "bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400",
  critical: "bg-red-50 text-status-critical dark:bg-red-950/40 dark:text-red-400",
  neutral: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
} as const;

export function StatCard({
  label,
  value,
  icon: Icon,
  tone = "brand",
  index = 0,
  suffix,
}: {
  label: string;
  value: number;
  icon: LucideIcon;
  tone?: keyof typeof TONES;
  index?: number;
  suffix?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.06, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -2 }}
      className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-soft transition-shadow hover:shadow-soft-md dark:border-slate-800 dark:bg-slate-900 sm:p-5"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
          {label}
        </span>
        <div className={cn("grid h-8 w-8 place-items-center rounded-lg", TONES[tone])}>
          <Icon size={16} strokeWidth={2.25} />
        </div>
      </div>
      <div className="mt-2 font-mono-num text-2xl font-bold text-slate-800 dark:text-slate-100 sm:text-3xl">
        <AnimatedNumber value={value} />
        {suffix}
      </div>
    </motion.div>
  );
}
