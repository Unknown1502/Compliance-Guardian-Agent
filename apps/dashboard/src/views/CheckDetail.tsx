import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  User,
  FileText,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  MessageSquare,
  Send,
} from "lucide-react";
import {
  getCheck,
  getDocument,
  getDocumentContent,
  decideCheck,
  addCheckComment,
  assignCheck,
  listTeam,
  ApiError,
  type TeamMember,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { DecisionBadge, VerdictPill } from "../components/Badges";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { CardSkeleton } from "../components/ui/Skeleton";
import { RemediationChecklist } from "../components/RemediationChecklist";
import type { ComplianceCheck, DocumentRecord, DocumentContent } from "../types";
import { cn } from "../lib/cn";

const VERDICT_BAR: Record<string, string> = {
  pass: "bg-status-good",
  fail: "bg-status-critical",
  uncertain: "bg-status-warning",
};

const RISK_TONE = (score: number) =>
  score >= 60 ? "text-status-critical" : score >= 30 ? "text-status-warning" : "text-status-good";

function formatBytes(n: number): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** The document as uploaded. Triggering values from failed rules are
 *  highlighted in the text so a reviewer can see the evidence in place
 *  rather than taking the finding on faith. */
function DocumentPane({
  doc,
  content,
  highlights,
}: {
  doc: DocumentRecord | null;
  content: DocumentContent | null;
  highlights: string[];
}) {
  if (!content && !doc) {
    return (
      <div className="flex items-center gap-2 px-5 py-5 text-[13px] text-muted sm:px-8">
        <Loader2 size={13} className="animate-spin" />
        Loading document…
      </div>
    );
  }

  const renderText = (text: string) => {
    // Longest first so a short fragment can't pre-empt a longer match.
    const terms = highlights
      .filter((h) => h && h.length >= 4)
      .sort((a, b) => b.length - a.length);
    if (terms.length === 0) return text;

    const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = new RegExp(`(${escaped.join("|")})`, "gi");
    return text.split(re).map((part, i) =>
      terms.some((t) => t.toLowerCase() === part.toLowerCase()) ? (
        <mark key={i} className="rounded bg-orange-100 px-0.5 text-ink">
          {part}
        </mark>
      ) : (
        <span key={i}>{part}</span>
      ),
    );
  };

  return (
    <div>
      {content && (
        <div className="border-b border-line px-5 py-3 sm:px-8">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <span className="text-[13px] font-medium text-ink">{content.filename}</span>
            <span className="text-[11.5px] text-muted">
              {content.content_type} · {formatBytes(content.size_bytes)}
            </span>
            <span
              className={cn(
                "inline-flex items-center gap-1 text-[11.5px] font-medium",
                content.hash_verified ? "text-status-good" : "text-muted",
              )}
              title={
                content.hash_verified
                  ? "The stored file still matches the hash recorded at upload."
                  : "No upload hash on record for this document."
              }
            >
              {content.hash_verified ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
              {content.hash_verified ? "Integrity verified" : "Unverified"}
            </span>
          </div>
          <p className="font-mono-num mt-1 break-all text-[10.5px] text-muted">
            sha256 {content.content_hash}
          </p>
        </div>
      )}

      <div className="px-5 py-5 sm:px-8">
        {content?.text != null ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-ink">
            {renderText(content.text)}
          </pre>
        ) : content?.base64 && content.content_type.startsWith("image/") ? (
          <img
            src={`data:${content.content_type};base64,${content.base64}`}
            alt={content.filename}
            className="max-w-full rounded-lg border border-line"
          />
        ) : content?.base64 ? (
          <div className="rounded-lg border border-line bg-surface p-4 text-[13px] text-ink-2">
            <p className="mb-2">
              This is a {content.content_type} file, which can't be shown inline.
            </p>
            <a
              href={`data:${content.content_type};base64,${content.base64}`}
              download={content.filename}
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              Download to view
            </a>
          </div>
        ) : (
          <p className="text-[13px] text-muted">Original file is no longer available.</p>
        )}

        {/* The extracted fields are what the rules were actually evaluated
            against, so they belong beside the source, not instead of it. */}
        {doc && Object.keys(doc.extracted_fields).length > 0 && (
          <div className="mt-6 border-t border-line pt-5">
            <span className="eyebrow">Extracted fields</span>
            <dl className="mt-3 space-y-3">
              {Object.entries(doc.extracted_fields).map(([field, value]) => (
                <div key={field} className="border-b border-line pb-2.5 last:border-0">
                  <dt className="font-mono-num text-[11.5px] font-medium text-muted">{field}</dt>
                  <dd className="mt-0.5 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                    {value === null || value === "" ? (
                      <span className="italic text-muted">not present</span>
                    ) : (
                      String(value)
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}

export function CheckDetail() {
  const { checkId } = useParams<{ checkId: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [check, setCheck] = useState<ComplianceCheck | null>(null);
  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [content, setContent] = useState<DocumentContent | null>(null);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"approve" | "reject" | null>(null);
  const [commentBody, setCommentBody] = useState("");

  const load = async () => {
    if (!session || !checkId) return;
    try {
      const c = await getCheck(session, checkId);
      setCheck(c);
      getDocument(session, c.document_id).then(setDoc).catch(() => {});
      getDocumentContent(session, c.document_id).then(setContent).catch(() => {});
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
    if (session) listTeam(session).then(setTeam).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkId, session]);

  const decide = async (action: "approve" | "reject") => {
    if (!session || !checkId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await decideCheck(session, checkId, action);
      setCheck(updated);
      toast.push({
        kind: action === "approve" ? "success" : "warning",
        title: action === "approve" ? "Check approved" : "Check rejected",
        description: `${updated.document_id} → ${updated.decision.replace("_", " ")}`,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.push({ kind: "warning", title: "Already actioned by another reviewer" });
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

  const submitComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !checkId || !commentBody.trim()) return;
    setBusy(true);
    try {
      setCheck(await addCheckComment(session, checkId, commentBody.trim()));
      setCommentBody("");
    } catch (err) {
      toast.push({ kind: "error", title: "Could not add note", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const changeAssignee = async (uid: string) => {
    if (!session || !checkId) return;
    setBusy(true);
    try {
      setCheck(await assignCheck(session, checkId, uid || null));
      toast.push({ kind: "success", title: uid ? "Reviewer assigned" : "Assignment cleared" });
    } catch (err) {
      toast.push({ kind: "error", title: "Could not assign", description: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (error && !check) return <p className="text-[13.5px] text-status-critical">{error}</p>;
  if (!check) {
    return (
      <div className="space-y-6">
        <div className="h-4 w-16 rounded bg-slate-200" />
        <CardSkeleton />
      </div>
    );
  }

  const canReview =
    (session?.role === "reviewer" || session?.role === "admin") && check.decision === "escalated";
  const canAssign = session?.role === "owner" || session?.role === "admin";

  // Evidence to highlight in the source: the exact values that drove failures.
  const highlights = (check.rule_verdicts ?? [])
    .filter((v) => v.status !== "pass" && v.triggering_data_point)
    .map((v) => String(v.triggering_data_point).split("=").slice(1).join("=").trim())
    .filter(Boolean);

  return (
    // No negative margins here. They existed to cancel the main column's
    // padding and go full-bleed, but Layout already routes /checks/* through
    // its p-0 branch — so there was nothing to cancel and they dragged the
    // panel 40px past the container edge on desktop, which is what produced
    // the page-level horizontal scrollbar. Full-bleed is unchanged.
    <div className="flex h-[calc(100vh-64px)] w-full min-w-0 flex-col">
      {/* Asymmetric on purpose. This bar spans both columns, so each side has
          to line up with a different one: the left edge with the document
          pane below it (px-5 sm:px-8), the right edge with the findings list
          (px-5). It previously carried lg:px-10 to match the main column's
          padding, but this route renders through Layout's p-0 branch — so on
          a wide screen the heading sat 8px further in than the document and
          the risk score 20px further in than the findings beneath it. */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface py-3.5 pl-5 pr-5 sm:pl-8">
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ink-2 transition-colors hover:bg-surface-2"
          >
            <ArrowLeft size={15} />
          </button>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono-num truncate text-[13px] font-semibold text-ink">
                {check.document_id}
              </span>
              <DecisionBadge decision={check.decision} />
            </div>
            <p className="font-mono-num text-[11.5px] text-muted">
              ruleset v{check.rule_set_version} · check {check.check_id.slice(0, 8)}
              {doc?.content_hash ? ` · sha256 ${doc.content_hash.slice(0, 10)}…` : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "font-mono-num text-[22px] font-bold leading-none",
              RISK_TONE(check.risk_score),
            )}
          >
            {check.risk_score}
          </span>
          <span className="text-[11.5px] text-muted">/ 100 risk</span>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* Left: the actual document under review.
            min-w-0 is load-bearing. A flex item defaults to min-width:auto, so
            without it this pane refuses to shrink below the intrinsic width of
            the document text — and a source file with long unbroken lines then
            pushes the findings pane off the right edge of the screen, clipping
            the verdict badges. The document is the one thing here with
            unpredictable width, so it is the one that must be allowed to
            scroll instead of expand. */}
        <div className="min-w-0 min-h-0 flex-1 overflow-y-auto border-b border-line bg-surface-2 lg:border-b-0 lg:border-r">
          <div className="sticky top-0 z-10 border-b border-line bg-surface px-5 py-2.5 sm:px-8">
            <span className="eyebrow inline-flex items-center gap-1.5">
              <FileText size={12} />
              Source document
            </span>
          </div>
          <DocumentPane doc={doc} content={content} highlights={highlights} />
        </div>

        {/* Right: findings, oversight, actions. */}
        <div className="flex min-h-0 w-full flex-col lg:w-[440px] lg:shrink-0">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="border-b border-line bg-surface px-5 py-2.5">
              <span className="eyebrow">
                Findings · {check.rule_verdicts.length} rules evaluated
              </span>
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

            {/* What to fix. Sits directly under the findings because that is
                the question a provider has the moment they read them. */}
            {checkId && (
              <div className="border-t border-line px-5 py-4">
                <RemediationChecklist checkId={checkId} />
              </div>
            )}

            {/* Assignment */}
            <div className="border-t border-line px-5 py-4">
              <span className="eyebrow">Assigned reviewer</span>
              {canAssign ? (
                <select
                  value={check.assigned_to ?? ""}
                  onChange={(e) => changeAssignee(e.target.value)}
                  disabled={busy}
                  className="mt-1.5 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15"
                >
                  <option value="">Unassigned</option>
                  {team.map((m) => (
                    <option key={m.uid} value={m.uid}>
                      {m.email}
                      {m.job_title ? ` — ${m.job_title}` : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="mt-1 text-[13px] text-ink-2">
                  {check.assigned_to
                    ? team.find((m) => m.uid === check.assigned_to)?.email ?? check.assigned_to
                    : "Unassigned"}
                </p>
              )}
            </div>

            {/* Reviewer notes */}
            <div className="border-t border-line px-5 py-4">
              <span className="eyebrow inline-flex items-center gap-1.5">
                <MessageSquare size={11} />
                Reviewer notes ({check.comments?.length ?? 0})
              </span>

              <ul className="mt-3 space-y-3">
                {(check.comments ?? []).map((cm) => (
                  <li key={cm.comment_id} className="rounded-lg bg-surface-2 p-3">
                    <p className="text-[13px] leading-relaxed text-ink">{cm.body}</p>
                    <p className="mt-1 text-[11px] text-muted">
                      {cm.author_email || cm.author_uid} · {cm.created_at.split("T")[0]}
                    </p>
                  </li>
                ))}
                {(check.comments ?? []).length === 0 && (
                  <li className="text-[12.5px] text-muted">
                    No notes yet. Record why this decision was made.
                  </li>
                )}
              </ul>

              <form onSubmit={submitComment} className="mt-3 flex items-end gap-2">
                <textarea
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  rows={2}
                  placeholder="Add a note…"
                  className="min-h-[38px] flex-1 resize-y rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-muted focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/15"
                />
                <Button
                  type="submit"
                  size="sm"
                  disabled={busy || !commentBody.trim()}
                  icon={<Send size={13} />}
                >
                  Add
                </Button>
              </form>
              <p className="mt-1.5 text-[11px] text-muted">
                Notes are permanent — they can't be edited or deleted.
              </p>
            </div>

            {check.reviewer_id && (
              <div className="flex items-center gap-1.5 border-t border-line px-5 py-3 text-[12.5px] text-ink-2">
                <User size={13} />
                Decided by <span className="font-mono-num">{check.reviewer_id}</span>
              </div>
            )}
          </div>

          <div className="border-t border-line bg-surface px-5 py-4">
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
