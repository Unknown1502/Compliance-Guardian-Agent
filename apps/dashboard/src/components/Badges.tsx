import type { CheckDecision, DocumentStatus, VerdictStatus } from "../types";
import { cn } from "../lib/cn";

// Stamps, not pills. Squared, ruled, letterpress caps — the vocabulary of a
// record that was marked rather than a status that was rendered.

const STAMP_BASE =
  "inline-flex items-center gap-1.5 border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em]";

export function RiskBadge({ score }: { score: number }) {
  const tone =
    score >= 60
      ? "border-oxide/35 text-oxide dark:border-oxide/50 dark:text-[#D98878]"
      : score >= 30
        ? "border-brass/35 text-brass dark:border-brass/50 dark:text-[#D6AD57]"
        : "border-brand-600/30 text-brand-700 dark:border-brand-400/40 dark:text-brand-300";
  return (
    <span className={cn(STAMP_BASE, "font-mono-num tracking-normal", tone)}>
      {String(score).padStart(2, "0")}
      <span className="text-[9px] opacity-55">/100</span>
    </span>
  );
}

export function DecisionBadge({ decision }: { decision: CheckDecision }) {
  const map: Record<CheckDecision, { cls: string; label: string }> = {
    auto_approved: {
      cls: "border-brand-600/30 text-brand-700 bg-brand-50 dark:border-brand-400/40 dark:text-brand-300 dark:bg-brand-950/50",
      label: "Approved",
    },
    escalated: {
      cls: "border-brass/35 text-brass bg-brass/[0.06] dark:border-brass/50 dark:text-[#D6AD57] dark:bg-brass/10",
      label: "Escalated",
    },
    rejected: {
      cls: "border-oxide/35 text-oxide bg-oxide/[0.06] dark:border-oxide/50 dark:text-[#D98878] dark:bg-oxide/10",
      label: "Rejected",
    },
  };
  const { cls, label } = map[decision];
  return <span className={cn(STAMP_BASE, cls)}>{label}</span>;
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, string> = {
    processed: "border-brand-600/30 text-brand-700 dark:border-brand-400/40 dark:text-brand-300",
    succeeded: "border-brand-600/30 text-brand-700 dark:border-brand-400/40 dark:text-brand-300",
    failed: "border-oxide/35 text-oxide dark:border-oxide/50 dark:text-[#D98878]",
    running: "border-slate-400/40 text-slate-600 dark:border-slate-500/50 dark:text-slate-300",
    pending: "border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400",
    queued: "border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400",
  };
  const cls = map[status] ?? "border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400";
  return (
    <span className={cn(STAMP_BASE, cls)}>
      {status === "running" && (
        <span className="h-1 w-1 animate-pulse bg-current" aria-hidden="true" />
      )}
      {status}
    </span>
  );
}

export function VerdictPill({ status }: { status: VerdictStatus }) {
  const map: Record<VerdictStatus, string> = {
    pass: "border-brand-600/30 text-brand-700 dark:border-brand-400/40 dark:text-brand-300",
    fail: "border-oxide/35 text-oxide dark:border-oxide/50 dark:text-[#D98878]",
    uncertain: "border-brass/35 text-brass dark:border-brass/50 dark:text-[#D6AD57]",
  };
  return <span className={cn(STAMP_BASE, map[status])}>{status}</span>;
}
