import { motion } from "framer-motion";
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  Loader2,
  HelpCircle,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
} from "lucide-react";
import type { CheckDecision, DocumentStatus, VerdictStatus } from "../types";
import { cn } from "../lib/cn";

const badgeMotion = {
  initial: { opacity: 0, scale: 0.85 },
  animate: { opacity: 1, scale: 1 },
  transition: { type: "spring" as const, stiffness: 500, damping: 28 },
};

export function RiskBadge({ score }: { score: number }) {
  const tone =
    score >= 60
      ? "bg-red-50 text-status-critical ring-1 ring-inset ring-red-200 dark:bg-red-950/40 dark:text-red-400 dark:ring-red-900"
      : score >= 30
        ? "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:ring-amber-900"
        : "bg-green-50 text-status-good ring-1 ring-inset ring-green-200 dark:bg-green-950/40 dark:text-green-400 dark:ring-green-900";
  const Icon = score >= 60 ? ShieldX : score >= 30 ? ShieldAlert : ShieldCheck;
  return (
    <motion.span
      {...badgeMotion}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-mono-num text-xs font-semibold",
        tone,
      )}
    >
      <Icon size={12} strokeWidth={2.5} />
      {score}
    </motion.span>
  );
}

export function DecisionBadge({ decision }: { decision: CheckDecision }) {
  const map: Record<CheckDecision, { cls: string; icon: typeof CheckCircle2; label: string }> = {
    auto_approved: {
      cls: "bg-green-50 text-status-good ring-green-200 dark:bg-green-950/40 dark:text-green-400 dark:ring-green-900",
      icon: CheckCircle2,
      label: "Auto-approved",
    },
    escalated: {
      cls: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:ring-amber-900",
      icon: AlertTriangle,
      label: "Escalated",
    },
    rejected: {
      cls: "bg-red-50 text-status-critical ring-red-200 dark:bg-red-950/40 dark:text-red-400 dark:ring-red-900",
      icon: XCircle,
      label: "Rejected",
    },
  };
  const { cls, icon: Icon, label } = map[decision];
  return (
    <motion.span
      {...badgeMotion}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        cls,
      )}
    >
      <Icon size={12} strokeWidth={2.5} />
      {label}
    </motion.span>
  );
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, { cls: string; icon: typeof Clock }> = {
    pending: {
      cls: "bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
      icon: Clock,
    },
    processed: {
      cls: "bg-green-50 text-status-good ring-green-200 dark:bg-green-950/40 dark:text-green-400 dark:ring-green-900",
      icon: CheckCircle2,
    },
    failed: {
      cls: "bg-red-50 text-status-critical ring-red-200 dark:bg-red-950/40 dark:text-red-400 dark:ring-red-900",
      icon: XCircle,
    },
    queued: {
      cls: "bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
      icon: Clock,
    },
    running: {
      cls: "bg-blue-50 text-brand-600 ring-blue-200 dark:bg-brand-950/40 dark:text-brand-400 dark:ring-brand-900",
      icon: Loader2,
    },
    succeeded: {
      cls: "bg-green-50 text-status-good ring-green-200 dark:bg-green-950/40 dark:text-green-400 dark:ring-green-900",
      icon: CheckCircle2,
    },
  };
  const entry = map[status] ?? {
    cls: "bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
    icon: HelpCircle,
  };
  const Icon = entry.icon;
  return (
    <motion.span
      {...badgeMotion}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ring-1 ring-inset",
        entry.cls,
      )}
    >
      <Icon size={12} strokeWidth={2.5} className={status === "running" ? "animate-spin" : ""} />
      {status}
    </motion.span>
  );
}

export function VerdictPill({ status }: { status: VerdictStatus }) {
  const map: Record<VerdictStatus, { cls: string; icon: typeof CheckCircle2 }> = {
    pass: {
      cls: "bg-green-50 text-status-good dark:bg-green-950/40 dark:text-green-400",
      icon: CheckCircle2,
    },
    fail: {
      cls: "bg-red-50 text-status-critical dark:bg-red-950/40 dark:text-red-400",
      icon: XCircle,
    },
    uncertain: {
      cls: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
      icon: HelpCircle,
    },
  };
  const { cls, icon: Icon } = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
        cls,
      )}
    >
      <Icon size={12} strokeWidth={2.5} />
      {status}
    </span>
  );
}
