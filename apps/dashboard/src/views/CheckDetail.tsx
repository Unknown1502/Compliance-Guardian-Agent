import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  User,
  Hash,
  FileSearch,
  BookMarked,
} from "lucide-react";
import { getCheck, decideCheck, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { DecisionBadge, VerdictPill } from "../components/Badges";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { RiskGauge } from "../components/ui/RiskGauge";
import { CardSkeleton } from "../components/ui/Skeleton";
import type { ComplianceCheck } from "../types";

const VERDICT_BAR: Record<string, string> = {
  pass: "bg-status-good",
  fail: "bg-status-critical",
  uncertain: "bg-amber-400",
};

export function CheckDetail() {
  const { checkId } = useParams<{ checkId: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [check, setCheck] = useState<ComplianceCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"approve" | "reject" | null>(null);

  const load = async () => {
    if (!session || !checkId) return;
    try {
      setCheck(await getCheck(session, checkId));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkId, session]);

  const decide = async (action: "approve" | "reject") => {
    if (!session || !checkId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await decideCheck(session, checkId, action);
      setCheck(updated);
      setNotice(`Decision recorded: ${action} → ${updated.decision}`);
      toast.push({
        kind: action === "approve" ? "success" : "warning",
        title: action === "approve" ? "Check approved" : "Check rejected",
        description: `${updated.document_id} → ${updated.decision.replace("_", " ")}`,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNotice("This item was already actioned by another reviewer.");
        await load();
      } else if (err instanceof ApiError && err.status === 403) {
        setError("Only reviewers can approve or reject.");
      } else {
        setError((err as Error).message);
      }
    } finally {
      setBusy(false);
      setConfirmAction(null);
    }
  };

  if (error && !check) return <p className="text-sm text-status-critical">{error}</p>;
  if (!check) {
    return (
      <div className="space-y-6">
        <div className="h-4 w-16 rounded bg-slate-200 dark:bg-slate-800" />
        <CardSkeleton />
      </div>
    );
  }

  const canReview =
    (session?.role === "reviewer" || session?.role === "admin") &&
    check.decision === "escalated";

  return (
    <div className="space-y-6">
      <motion.button
        whileHover={{ x: -2 }}
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
      >
        <ArrowLeft size={14} />
        Back
      </motion.button>

      <Card>
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 space-y-1.5">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                Compliance check
              </h2>
              <DecisionBadge decision={check.decision} />
            </div>
            <p className="flex items-center gap-1.5 font-mono-num text-xs text-slate-400 dark:text-slate-500">
              <Hash size={11} />
              {check.check_id}
            </p>
            <p className="font-mono-num text-xs text-slate-400 dark:text-slate-500">
              document: {check.document_id} · ruleset v{check.rule_set_version}
            </p>
          </div>
          <RiskGauge score={check.risk_score} />
        </div>

        <div className="mt-5 rounded-xl bg-slate-50 p-4 dark:bg-slate-800/50">
          <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            <FileSearch size={12} />
            Justification
          </h3>
          <p className="text-sm text-slate-700 dark:text-slate-300">{check.justification}</p>
        </div>

        {check.citations.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
              <BookMarked size={12} />
              Cited rules
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {check.citations.map((c) => (
                <span
                  key={c}
                  className="rounded-md bg-slate-100 px-2 py-0.5 font-mono-num text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}

        {check.reviewer_id && (
          <p className="mt-4 flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400">
            <User size={13} />
            Reviewed by <span className="font-mono-num">{check.reviewer_id}</span>
          </p>
        )}
      </Card>

      <Card padded={false}>
        <div className="border-b border-slate-100 px-5 py-3.5 dark:border-slate-800">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            Per-rule verdicts
          </h3>
        </div>
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {check.rule_verdicts.map((v, i) => (
            <motion.li
              key={v.rule_id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.05 }}
              className="px-5 py-3.5"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono-num text-sm text-slate-700 dark:text-slate-300">
                  {v.rule_id}
                </span>
                <VerdictPill status={v.status} />
              </div>
              <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-400">{v.explanation}</p>
              <div className="mt-2 flex items-center gap-2">
                <div className="h-1.5 w-28 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${v.confidence * 100}%` }}
                    transition={{ duration: 0.6, delay: 0.15 + i * 0.05 }}
                    className={`h-full ${VERDICT_BAR[v.status]}`}
                  />
                </div>
                <span className="font-mono-num text-xs text-slate-400 dark:text-slate-500">
                  {(v.confidence * 100).toFixed(0)}% confidence
                </span>
              </div>
              {v.triggering_data_point && (
                <p className="mt-1.5 font-mono-num text-xs text-slate-400 dark:text-slate-600">
                  {v.triggering_data_point}
                </p>
              )}
            </motion.li>
          ))}
        </ul>
      </Card>

      {notice && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm text-brand-800 dark:border-brand-900 dark:bg-brand-950/30 dark:text-brand-300"
        >
          {notice}
        </motion.div>
      )}
      {error && <p className="text-sm text-status-critical">{error}</p>}

      {canReview ? (
        <div className="flex gap-3">
          <Button variant="success" size="lg" onClick={() => setConfirmAction("approve")}>
            <CheckCircle2 size={15} className="mr-1" />
            Approve
          </Button>
          <Button variant="danger" size="lg" onClick={() => setConfirmAction("reject")}>
            <XCircle size={15} className="mr-1" />
            Reject
          </Button>
        </div>
      ) : (
        check.decision === "escalated" && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            This item is awaiting a reviewer. Sign in with a reviewer role to action it.
          </p>
        )
      )}

      <ConfirmDialog
        open={confirmAction !== null}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => confirmAction && decide(confirmAction)}
        busy={busy}
        variant={confirmAction === "approve" ? "success" : "danger"}
        icon={confirmAction === "approve" ? CheckCircle2 : XCircle}
        title={confirmAction === "approve" ? "Approve this check?" : "Reject this check?"}
        description={
          confirmAction === "approve"
            ? "This will mark the compliance check as approved and record your decision in the audit trail."
            : "This will mark the compliance check as rejected and record your decision in the audit trail."
        }
        confirmLabel={confirmAction === "approve" ? "Approve" : "Reject"}
      />
    </div>
  );
}
