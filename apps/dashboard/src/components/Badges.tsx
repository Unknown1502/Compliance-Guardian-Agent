import type { CheckDecision, DocumentStatus, VerdictStatus } from "../types";

export function RiskBadge({ score }: { score: number }) {
  const color =
    score >= 60 ? "bg-red-100 text-red-700" : score >= 30 ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${color}`}>
      Risk {score}
    </span>
  );
}

export function DecisionBadge({ decision }: { decision: CheckDecision }) {
  const map: Record<CheckDecision, string> = {
    auto_approved: "bg-green-100 text-green-700",
    escalated: "bg-amber-100 text-amber-700",
    rejected: "bg-red-100 text-red-700",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${map[decision]}`}>
      {decision.replace("_", " ")}
    </span>
  );
}

export function StatusBadge({ status }: { status: DocumentStatus | string }) {
  const map: Record<string, string> = {
    pending: "bg-slate-100 text-slate-600",
    processed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    queued: "bg-slate-100 text-slate-600",
    running: "bg-blue-100 text-blue-700",
    succeeded: "bg-green-100 text-green-700",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${map[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status}
    </span>
  );
}

export function VerdictPill({ status }: { status: VerdictStatus }) {
  const map: Record<VerdictStatus, string> = {
    pass: "bg-green-100 text-green-700",
    fail: "bg-red-100 text-red-700",
    uncertain: "bg-amber-100 text-amber-700",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase ${map[status]}`}>
      {status}
    </span>
  );
}
