import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  User,
  FileText,
  Loader2,
} from "lucide-react";
import { getCheck, getDocument, decideCheck, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { DecisionBadge, VerdictPill } from "../components/Badges";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { CardSkeleton } from "../components/ui/Skeleton";
import type { ComplianceCheck, DocumentRecord } from "../types";

const VERDICT_BAR: Record<string, string> = {
  pass: "bg-status-good",
  fail: "bg-status-critical",
  uncertain: "bg-status-warning",
};

const RISK_TONE = (score: number) =>
  score >= 60 ? "text-status-critical" : score >= 30 ? "text-status-warning" : "text-status-good";

export function CheckDetail() {
  const { checkId } = useParams<{ checkId: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [check, setCheck] = useState<ComplianceCheck | null>(null);
  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"approve" | "reject" | null>(null);

  const load = async () => {
    if (!session || !checkId) return;
    try {
      const c = await getCheck(session, checkId);
      setCheck(c);
      getDocument(session, c.document_id).then(setDoc).catch(() => {});
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

  if (error && !check) return <p className="text-[13.5px] text-status-critical">{error}</p>;
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
    <div className="-mx-5 -mt-2 flex h-[calc(100vh-64px)] flex-col sm:-mx-8 lg:-mx-10">
      {/* PR-style header bar: identity + verdict + risk, always visible. */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface px-5 py-3.5 sm:px-8 lg:px-10">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => navigate(-1)}
            className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ink-2 transition-colors hover:bg-surface-2"
          >
            <ArrowLeft size={15} />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono-num truncate text-[13px] font-semibold text-ink">
                {check.document_id}
              </span>
              <DecisionBadge decision={check.decision} />
            </div>
            <p className="font-mono-num text-[11.5px] text-muted">
              ruleset v{check.rule_set_version} · check {check.check_id.slice(0, 8)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-mono-num text-[22px] font-bold leading-none ${RISK_TONE(check.risk_score)}`}>
            {check.risk_score}
          </span>
          <span className="text-[11.5px] text-muted">/ 100 risk</span>
        </div>
      </div>

      {/* Split body: document (left) | findings + actions (right) — the GitHub PR pattern. */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* Left: the artifact under review — extracted data, since that's what was actually evaluated. */}
        <div className="min-h-0 flex-1 overflow-y-auto border-b border-line bg-surface-2 lg:border-b-0 lg:border-r">
          <div className="border-b border-line bg-surface px-5 py-2.5 sm:px-8">
            <span className="eyebrow inline-flex items-center gap-1.5">
              <FileText size={12} />
              Extracted data
            </span>
          </div>
          <div className="px-5 py-5 sm:px-8">
            {!doc ? (
              <div className="flex items-center gap-2 text-[13px] text-muted">
                <Loader2 size={13} className="animate-spin" />
                Loading document…
              </div>
            ) : (
              <dl className="space-y-4">
                {Object.entries(doc.extracted_fields).map(([field, value]) => (
                  <div key={field} className="border-b border-line pb-3 last:border-0">
                    <dt className="font-mono-num text-[11.5px] font-medium text-muted">{field}</dt>
                    <dd className="mt-1 whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">
                      {value === null || value === "" ? (
                        <span className="italic text-muted">not present</span>
                      ) : (
                        String(value)
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </div>

        {/* Right: findings + reviewer actions — the "review comments" side. */}
        <div className="flex min-h-0 w-full flex-col lg:w-[440px] lg:shrink-0">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="border-b border-line bg-surface px-5 py-2.5">
              <span className="eyebrow">Findings · {check.rule_verdicts.length} rules evaluated</span>
            </div>
            <ul className="divide-y divide-line">
              {check.rule_verdicts.map((v) => (
                <li key={v.rule_id} className="px-5 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono-num text-[12.5px] font-medium text-ink">
                      {v.rule_id}
                    </span>
                    <VerdictPill status={v.status} />
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{v.explanation}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="h-1 w-20 overflow-hidden rounded-full bg-surface-2">
                      <div
                        className={`h-full ${VERDICT_BAR[v.status]}`}
                        style={{ width: `${v.confidence * 100}%` }}
                      />
                    </div>
                    <span className="font-mono-num text-[11px] text-muted">
                      {(v.confidence * 100).toFixed(0)}% confidence
                    </span>
                  </div>
                  {v.triggering_data_point && (
                    <p className="font-mono-num mt-1.5 text-[11px] text-muted">
                      {v.triggering_data_point}
                    </p>
                  )}
                </li>
              ))}
            </ul>

            <div className="border-t border-line px-5 py-4">
              <span className="eyebrow">Overall justification</span>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{check.justification}</p>
            </div>

            {check.reviewer_id && (
              <div className="flex items-center gap-1.5 border-t border-line px-5 py-3 text-[12.5px] text-ink-2">
                <User size={13} />
                Reviewed by <span className="font-mono-num">{check.reviewer_id}</span>
              </div>
            )}
          </div>

          {/* Actions pinned at the bottom of the right rail, like a PR's merge box. */}
          <div className="border-t border-line bg-surface px-5 py-4">
            {notice && (
              <p className="mb-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-[12.5px] text-brand-800">
                {notice}
              </p>
            )}
            {error && <p className="mb-3 text-[12.5px] text-status-critical">{error}</p>}

            {canReview ? (
              <div className="flex gap-2.5">
                <Button
                  variant="success"
                  size="lg"
                  className="flex-1"
                  onClick={() => setConfirmAction("approve")}
                >
                  <CheckCircle2 size={15} className="mr-1" />
                  Approve
                </Button>
                <Button
                  variant="danger"
                  size="lg"
                  className="flex-1"
                  onClick={() => setConfirmAction("reject")}
                >
                  <XCircle size={15} className="mr-1" />
                  Reject
                </Button>
              </div>
            ) : (
              check.decision === "escalated" && (
                <p className="text-[12.5px] text-muted">
                  Awaiting a reviewer. Sign in with a reviewer role to action this.
                </p>
              )
            )}
          </div>
        </div>
      </div>

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
