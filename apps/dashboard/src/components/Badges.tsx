import {
  CheckCircle2,
  Clock,
  Flag,
  XCircle,
  Loader2,
  HelpCircle,
  AlertTriangle,
} from "lucide-react";
import type { CheckDecision, DocumentStatus, VerdictStatus } from "../types";
import { cn } from "../lib/cn";

// Status reads from the icon + word first, colour second — never colour alone.

const BASE = "inline-flex items-center gap-1.5 text-[12.5px] font-medium";

export function RiskBadge({ score }: { score: number }) {
  const tone =
    score >= 60
      ? "text-status-critical"
      : score >= 30
        ? "text-status-warning"
        : "text-status-good";
  return (
    <span className={cn("font-mono-num text-[13px] font-semibold", tone)}>{score}</span>
  );
}

export function DecisionBadge({ decision }: { decision: CheckDecision }) {
  const map: Record<CheckDecision, { cls: string; icon: typeof CheckCircle2; label: string }> = {
    auto_approved: { cls: "text-status-good", icon: CheckCircle2, label: "Approved" },
    escalated: { cls: "text-status-warning", icon: Flag, label: "Escalated" },
    rejected: { cls: "text-status-critical", icon: XCircle, label: "Rejected" },
  };
  const { cls, icon: Icon, label } = map[decision];
  return (
    <span className={cn(BASE, cls)}>
      <Icon size={14} strokeWidth={2.25} />
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, { cls: string; icon: typeof Clock }> = {
    processed: { cls: "text-status-good", icon: CheckCircle2 },
    succeeded: { cls: "text-status-good", icon: CheckCircle2 },
    failed: { cls: "text-status-critical", icon: AlertTriangle },
    running: { cls: "text-brand-600 dark:text-brand-400", icon: Loader2 },
    pending: { cls: "text-slate-500 dark:text-slate-400", icon: Clock },
    queued: { cls: "text-slate-500 dark:text-slate-400", icon: Clock },
  };
  const entry = map[status] ?? { cls: "text-slate-500 dark:text-slate-400", icon: HelpCircle };
  const Icon = entry.icon;
  return (
    <span className={cn(BASE, "capitalize", entry.cls)}>
      <Icon size={14} strokeWidth={2.25} className={status === "running" ? "animate-spin" : ""} />
      {status}
    </span>
  );
}

export function VerdictPill({ status }: { status: VerdictStatus }) {
  const map: Record<VerdictStatus, { cls: string; icon: typeof CheckCircle2 }> = {
    pass: {
      cls: "bg-green-50 text-status-good ring-green-200 dark:bg-green-950/40 dark:text-green-400 dark:ring-green-900",
      icon: CheckCircle2,
    },
    fail: {
      cls: "bg-red-50 text-status-critical ring-red-200 dark:bg-red-950/40 dark:text-red-400 dark:ring-red-900",
      icon: XCircle,
    },
    uncertain: {
      cls: "bg-orange-50 text-status-warning ring-orange-200 dark:bg-orange-950/40 dark:text-orange-400 dark:ring-orange-900",
      icon: HelpCircle,
    },
  };
  const { cls, icon: Icon } = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset",
        cls,
      )}
    >
      <Icon size={11} strokeWidth={2.5} />
      {status}
    </span>
  );
}
