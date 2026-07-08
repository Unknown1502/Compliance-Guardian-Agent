import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getCheck, decideCheck, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
  DecisionBadge,
  RiskBadge,
  VerdictPill,
} from "../components/Badges";
import type { ComplianceCheck } from "../types";

export function CheckDetail() {
  const { checkId } = useParams<{ checkId: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const [check, setCheck] = useState<ComplianceCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

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
    }
  };

  if (error && !check) return <p className="text-red-600">{error}</p>;
  if (!check) return <p className="text-slate-500">Loading…</p>;

  const canReview =
    (session?.role === "reviewer" || session?.role === "admin") &&
    check.decision === "escalated";

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="text-sm text-slate-500 hover:text-slate-800"
      >
        ← Back
      </button>

      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">
              Compliance check
            </h2>
            <p className="text-sm text-slate-500 font-mono">{check.check_id}</p>
            <p className="text-sm text-slate-500 font-mono">
              document: {check.document_id} · ruleset v{check.rule_set_version}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <RiskBadge score={check.risk_score} />
            <DecisionBadge decision={check.decision} />
          </div>
        </div>

        <div className="mt-4 p-4 bg-slate-50 rounded-lg">
          <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-1">
            Justification
          </h3>
          <p className="text-sm text-slate-700">{check.justification}</p>
        </div>

        {check.citations.length > 0 && (
          <div className="mt-3">
            <h3 className="text-xs uppercase tracking-wide text-slate-400 mb-1">
              Cited rules
            </h3>
            <div className="flex flex-wrap gap-1">
              {check.citations.map((c) => (
                <span
                  key={c}
                  className="px-2 py-0.5 bg-slate-100 rounded text-xs font-mono text-slate-600"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}

        {check.reviewer_id && (
          <p className="mt-3 text-sm text-slate-500">
            Reviewed by <span className="font-mono">{check.reviewer_id}</span>
          </p>
        )}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100">
          <h3 className="text-sm font-medium text-slate-700">
            Per-rule verdicts
          </h3>
        </div>
        <ul className="divide-y divide-slate-100">
          {check.rule_verdicts.map((v) => (
            <li key={v.rule_id} className="px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-slate-700">
                  {v.rule_id}
                </span>
                <div className="flex items-center gap-2">
                  <VerdictPill status={v.status} />
                  <span className="text-xs text-slate-400">
                    {(v.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
              <p className="text-sm text-slate-600 mt-1">{v.explanation}</p>
              {v.triggering_data_point && (
                <p className="text-xs text-slate-400 font-mono mt-1">
                  {v.triggering_data_point}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>

      {notice && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
          {notice}
        </div>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {canReview ? (
        <div className="flex gap-3">
          <button
            onClick={() => decide("approve")}
            disabled={busy}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded-lg px-5 py-2 text-sm font-medium"
          >
            Approve
          </button>
          <button
            onClick={() => decide("reject")}
            disabled={busy}
            className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg px-5 py-2 text-sm font-medium"
          >
            Reject
          </button>
        </div>
      ) : (
        check.decision === "escalated" && (
          <p className="text-sm text-slate-500">
            This item is awaiting a reviewer. Sign in with a reviewer role to
            action it.
          </p>
        )
      )}
    </div>
  );
}
