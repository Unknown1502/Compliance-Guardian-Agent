import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { API_BASE_URL } from "../config";

interface ReportSummary {
  report_id: string;
  period_start: string;
  period_end: string;
  total_checks: number;
  pass_count: number;
  fail_count: number;
  escalated_count: number;
  executive_summary: string;
  model_name: string;
  used_fixture: boolean;
  content_ref: string;
}

async function postReport(
  session: import("../types").Session,
  periodStart: string,
  periodEnd: string,
): Promise<ReportSummary> {
  const token = await session.getToken();
  const res = await fetch(`${API_BASE_URL}/api/reports`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      period_start: new Date(periodStart).toISOString(),
      period_end: new Date(periodEnd).toISOString(),
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json();
}

export function ReportsView() {
  const { session } = useAuth();
  const today = new Date().toISOString().split("T")[0];
  const monthAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000)
    .toISOString()
    .split("T")[0];

  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportSummary | null>(null);

  const generate = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await postReport(session, start, end));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800">Reports</h2>
        <p className="text-sm text-slate-500">
          Gemini-generated, audit-ready compliance summaries. Select a date
          range and generate on demand.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-5 flex flex-wrap gap-4 items-end">
        <label className="block text-sm font-medium text-slate-700">
          From
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="mt-1 block border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          To
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="mt-1 block border border-slate-300 rounded-lg px-3 py-2 text-sm"
          />
        </label>
        <button
          onClick={generate}
          disabled={busy}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium"
        >
          {busy ? "Generating…" : "Generate report"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {report && (
        <div className="space-y-4">
          {report.used_fixture && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 text-sm text-amber-800">
              Executive summary generated with a fixture (no GEMINI_API_KEY set).
              Set the key and regenerate for a real Gemini-authored summary.
            </div>
          )}

          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="font-semibold text-slate-800">
                  {report.period_start.split("T")[0]} –{" "}
                  {report.period_end.split("T")[0]}
                </h3>
                <p className="text-xs text-slate-400 font-mono">
                  {report.report_id}
                </p>
              </div>
              <a
                href={`${API_BASE_URL}/api/reports/${report.report_id}`}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-brand-600 hover:text-brand-700 font-medium"
              >
                View full HTML →
              </a>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
              {[
                { label: "Reviewed", n: report.total_checks },
                { label: "Approved", n: report.pass_count },
                { label: "Escalated", n: report.escalated_count },
                { label: "Rejected", n: report.fail_count },
              ].map((s) => (
                <div
                  key={s.label}
                  className="bg-slate-50 rounded-lg p-3 text-center"
                >
                  <div className="text-2xl font-bold text-brand-600">{s.n}</div>
                  <div className="text-xs text-slate-500">{s.label}</div>
                </div>
              ))}
            </div>

            <div className="bg-blue-50 border-l-4 border-blue-500 p-4 rounded-r-lg">
              <h4 className="text-xs uppercase tracking-wide text-slate-400 mb-1">
                Executive summary
                {!report.used_fixture && (
                  <span className="ml-2 text-green-600 font-medium">
                    ✓ Gemini ({report.model_name})
                  </span>
                )}
              </h4>
              <p className="text-sm text-slate-700">{report.executive_summary}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
