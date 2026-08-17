import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  FileBarChart2,
  Sparkles,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ClipboardList,
  Download,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  ApiError,
  createReport,
  getReportState,
  listReports,
  type ReportListItem,
  type ReportState,
} from "../api/client";
import { API_BASE_URL } from "../config";
import { Card, CardHeader, PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { StatCard } from "../components/ui/StatCard";
import { DecisionBreakdown } from "../components/ui/DecisionBreakdown";

/** What each durable state means to someone watching the page. */
const STATE_LABEL: Record<string, string> = {
  queued: "Queued…",
  generating: "Generating…",
  validating: "Validating…",
  persisting: "Saving…",
  verifying: "Verifying…",
  ready: "Ready",
  failed: "Generation failed",
  retrying: "Retrying…",
};

const TERMINAL = new Set(["ready", "failed"]);

export function ReportsView() {
  const { session } = useAuth();
  const toast = useToast();
  const today = new Date().toISOString().split("T")[0];
  const monthAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString().split("T")[0];

  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportState | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [past, setPast] = useState<ReportListItem[] | null>(null);

  // The generated report used to live only in the state above, so a reload
  // put a workspace's own compliance evidence out of reach.
  const refreshPast = useCallback(async () => {
    if (!session) return;
    try {
      setPast(await listReports(session));
    } catch {
      setPast([]);
    }
  }, [session]);

  useEffect(() => {
    refreshPast();
  }, [refreshPast]);

  // The report endpoint requires a bearer token, so a plain <a href> would
  // navigate without one and render the API's "Missing bearer token" error.
  // Fetch it with the token, then hand the browser a blob URL instead.
  //
  // The response is a PDF when one exists and HTML when it doesn't (reports
  // generated before PDF rendering existed), so the content type is read off
  // the response rather than assumed — assuming HTML would hand the browser
  // a PDF mislabelled as markup and render binary as text.
  const openReport = async (reportId: string, download = false) => {
    if (!session) return;
    setOpeningId(reportId);
    try {
      const token = await session.getToken();
      const res = await fetch(`${API_BASE_URL}/api/reports/${reportId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? res.statusText);
      }
      const contentType = res.headers.get("content-type") ?? "application/pdf";
      const isPdf = contentType.includes("application/pdf");
      const url = URL.createObjectURL(await res.blob());

      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = `compliance-report-${reportId}.${isPdf ? "pdf" : "html"}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      // Give the new tab or the download time to start before releasing it.
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      const msg = (err as Error).message;
      toast.push({ kind: "error", title: "Could not open report", description: msg });
    } finally {
      setOpeningId(null);
    }
  };

  /**
   * Queue the report, then follow its durable state until it settles.
   *
   * The status shown is whatever the server says it is — there is no local
   * progress animation, because a progress bar disconnected from the backend
   * is how "your report is ready" came to mean nothing. Leaving the page is
   * safe: the work continues in a worker and the report appears in the list
   * below on the next visit.
   */
  const generate = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      let state = await createReport(session, start, end);
      setReport(state);

      const startedAt = Date.now();
      while (!TERMINAL.has(state.status)) {
        // Two minutes is well past a normal run; past that the report is not
        // lost, it is just no longer worth holding the page open for.
        if (Date.now() - startedAt > 120_000) break;
        await new Promise((r) => setTimeout(r, 2_000));
        state = await getReportState(session, state.report_id);
        setReport(state);
      }
      await refreshPast();

      if (state.status === "ready") {
        toast.push({
          kind: "success",
          title: "Report ready",
          description: `${state.total_checks} checks reviewed for the selected period.`,
        });
      } else if (state.status === "failed") {
        setError(state.error || "Report generation failed.");
        toast.push({ kind: "error", title: "Report generation failed" });
      } else {
        toast.push({
          kind: "warning",
          title: "Still generating",
          description: "It will appear below once it finishes.",
        });
      }
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      toast.push({ kind: "error", title: "Could not queue the report", description: msg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeading
        kind="Statements"
        title="Reports"
        subtitle="Audit-ready compliance summaries. Pick a range and generate on demand."
      />

      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            From
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-1.5 block rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
            To
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-1.5 block rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <Button onClick={generate} loading={busy} size="lg" icon={<FileBarChart2 size={15} />}>
            Generate report
          </Button>
        </div>
      </Card>

      {error && <p className="text-sm text-status-critical">{error}</p>}

      <AnimatePresence mode="wait">
        {report && (
          <motion.div
            key={report.report_id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-4"
          >
            {report.used_fixture && (
              <div className="flex items-center gap-2 rounded-xl border border-orange-200 bg-orange-50 px-4 py-2.5 text-sm text-status-warning dark:border-orange-900/60 dark:bg-orange-950/25 dark:text-orange-400">
                <AlertTriangle size={15} className="shrink-0" />
                Executive summary generated with a fixture (no AI credential set). Set
                the credential and regenerate for a real AI-authored summary.
              </div>
            )}

            <Card>
              <CardHeader
                title={`${report.period_start.split("T")[0]} – ${report.period_end.split("T")[0]}`}
                subtitle={
                  <span className="flex items-center gap-2">
                    <span className="font-mono-num">{report.report_id}</span>
                    <span
                      className={
                        report.downloadable
                          ? "rounded bg-status-good/10 px-1.5 py-0.5 text-[11px] font-medium text-status-good"
                          : report.status === "failed"
                            ? "rounded bg-status-critical/10 px-1.5 py-0.5 text-[11px] font-medium text-status-critical"
                            : "rounded bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-ink-2"
                      }
                    >
                      {STATE_LABEL[report.status] ?? report.status}
                    </span>
                  </span>
                }
                action={
                  <div className="flex items-center gap-3">
                    {/* Download is offered only once the server has verified
                        the artifact — downloadable is computed there, not from
                        a status string compared here. */}
                    <button
                      type="button"
                      onClick={() => openReport(report.report_id, true)}
                      disabled={openingId === report.report_id || !report.downloadable}
                      className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 disabled:opacity-40 dark:text-slate-400 dark:hover:text-slate-100"
                    >
                      Download
                      <Download size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={() => openReport(report.report_id)}
                      disabled={openingId === report.report_id}
                      className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 transition-colors hover:text-brand-700 disabled:opacity-50 dark:text-brand-400"
                    >
                      {openingId === report.report_id ? "Opening…" : "Open report"}
                      <ExternalLink size={13} />
                    </button>
                  </div>
                }
              />

              <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard label="Reviewed" value={report.total_checks} icon={ClipboardList} tone="brand" index={0} />
                <StatCard label="Approved" value={report.pass_count} icon={CheckCircle2} tone="good" index={1} />
                <StatCard label="Escalated" value={report.escalated_count} icon={AlertTriangle} tone="warning" index={2} />
                <StatCard label="Rejected" value={report.fail_count} icon={XCircle} tone="critical" index={3} />
              </div>

              <div className="mb-5">
                <DecisionBreakdown
                  approved={report.pass_count}
                  escalated={report.escalated_count}
                  rejected={report.fail_count}
                />
              </div>

              <div className="rounded-r-xl border-l-4 border-brand-500 bg-brand-50/60 p-4 dark:bg-brand-950/20">
                <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                  Executive summary
                  {!report.used_fixture && (
                    <span className="inline-flex items-center gap-1 font-medium text-status-good">
                      <Sparkles size={11} />
                      AI-generated
                    </span>
                  )}
                </h4>
                <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                  {report.executive_summary}
                </p>
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      <Card>
        <CardHeader
          title="Previous reports"
          subtitle="Every report still held in storage for this workspace."
        />
        {past === null ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : past.length === 0 ? (
          <p className="text-sm text-slate-500">
            No reports yet. Generate one above and it will stay available here.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {past.map((r) => (
              <li key={r.report_id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-mono-num truncate text-[12.5px] text-ink">{r.report_id}</p>
                  <p className="text-[12px] text-ink-2">
                    {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                    {" · "}
                    {r.status === "ready"
                      ? r.has_pdf
                        ? "PDF"
                        : "HTML only"
                      : (STATE_LABEL[r.status] ?? r.status)}
                  </p>
                </div>
                {/* An unfinished report has nothing to fetch, so it offers no
                    buttons rather than buttons that 404. */}
                <button
                  type="button"
                  onClick={() => openReport(r.report_id, true)}
                  disabled={openingId === r.report_id || r.status !== "ready"}
                  className="inline-flex items-center gap-1 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 disabled:opacity-40 dark:text-slate-400 dark:hover:text-slate-100"
                >
                  Download
                  <Download size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => openReport(r.report_id)}
                  disabled={openingId === r.report_id || r.status !== "ready"}
                  className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 transition-colors hover:text-brand-700 disabled:opacity-40 dark:text-brand-400"
                >
                  {openingId === r.report_id ? "Opening…" : "Open"}
                  <ExternalLink size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
