// Reports view — the reporting agent lands in Phase 4. This view is present so
// the navigation and role-based shell are complete; it clearly communicates the
// Phase 4 status rather than showing a fake report.

export function ReportsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-800">Reports</h2>
        <p className="text-sm text-slate-500">
          Gemini-generated, audit-ready compliance summaries over a date range.
        </p>
      </div>
      <div className="bg-white rounded-xl border border-dashed border-slate-300 p-10 text-center">
        <p className="text-slate-500">
          The reporting agent is delivered in Phase 4 (scheduled via Cloud
          Workflows and on-demand via <code>POST /api/reports</code>).
        </p>
      </div>
    </div>
  );
}
