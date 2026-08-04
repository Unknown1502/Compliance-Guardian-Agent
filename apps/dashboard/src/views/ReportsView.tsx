import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  FileBarChart2,
  Sparkles,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ClipboardList,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { ApiError } from "../api/client";
import { API_BASE_URL } from "../config";
import { Card, CardHeader } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { StatCard } from "../components/ui/StatCard";
import { DecisionBreakdown } from "../components/ui/DecisionBreakdown";

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
  const toast = useToast();
  const today = new Date().toISOString().split("T")[0];
  const monthAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString().split("T")[0];

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
      const r = await postReport(session, start, end);
      setReport(r);
      toast.push({
        kind: "success",
        title: "Report generated",
        description: `${r.total_checks} checks reviewed for the selected period.`,
      });
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      toast.push({ kind: "error", title: "Report generation failed", description: msg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-slate-800 dark:text-slate-100">
          Reports
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Gemini-generated, audit-ready compliance summaries. Select a date range and
          generate on demand.
        </p>
      </div>

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
              <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                <AlertTriangle size={15} className="shrink-0" />
                Executive summary generated with a fixture (no GEMINI_API_KEY set). Set
                the key and regenerate for a real Gemini-authored summary.
              </div>
            )}

            <Card>
              <CardHeader
                title={`${report.period_start.split("T")[0]} – ${report.period_end.split("T")[0]}`}
                subtitle={<span className="font-mono-num">{report.report_id}</span>}
                action={
                  <a
                    href={`${API_BASE_URL}/api/reports/${report.report_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400"
                  >
                    View full HTML
                    <ExternalLink size={13} />
                  </a>
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
                      Gemini ({report.model_name})
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
    </div>
  );
}
