import { useEffect, useState } from "react";
import { BookMarked, ShieldAlert } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getActiveRuleset } from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import type { RulesetSummary } from "../types";
import { cn } from "../lib/cn";

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-red-50 text-status-critical ring-red-200",
  high: "bg-orange-50 text-status-warning ring-orange-200",
  medium: "bg-blue-50 text-brand-700 ring-blue-200",
  low: "bg-surface-2 text-ink-2 ring-line",
};

export function RulesetsView() {
  const { session } = useAuth();
  const [ruleset, setRuleset] = useState<RulesetSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    getActiveRuleset(session)
      .then(setRuleset)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeading
        title="Rulesets"
        subtitle="The exact rules your documents are evaluated against — nothing hidden."
        action={
          ruleset && (
            <span className="font-mono-num rounded-lg border border-line px-2.5 py-1 text-[12px] text-ink-2">
              v{ruleset.rule_set_version}
            </span>
          )
        }
      />

      {error && <p className="mb-4 text-[13px] text-status-critical">{error}</p>}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-surface-2" />
          ))}
        </div>
      ) : !ruleset ? (
        <div className="rounded-xl border border-line bg-surface">
          <EmptyState
            icon={BookMarked}
            title="No ruleset resolved"
            description="No ruleset matched this workspace's industry and jurisdiction."
          />
        </div>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            {[
              { label: "Industry", value: ruleset.industry },
              { label: "Jurisdiction", value: ruleset.jurisdiction },
              { label: "Rules active", value: String(ruleset.rules.length) },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-line bg-surface p-4">
                <div className="eyebrow">{s.label}</div>
                <div className="font-mono-num mt-1 text-[15px] font-semibold text-ink">
                  {s.value}
                </div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-line bg-surface">
            <div className="border-b border-line bg-surface-2 px-4 py-2.5">
              <h3 className="text-[13px] font-semibold text-ink-2">
                Active rules · every one is evaluated on every document
              </h3>
            </div>
            <ul className="divide-y divide-line">
              {ruleset.rules.map((r) => (
                <li key={r.id} className="px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono-num text-[13px] font-semibold text-ink">
                      {r.id}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono-num text-[11.5px] text-muted">
                        {r.check_type}
                      </span>
                      <span
                        className={cn(
                          "rounded-md px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset",
                          SEVERITY_STYLE[r.severity] ?? SEVERITY_STYLE.low,
                        )}
                      >
                        {r.severity}
                      </span>
                    </div>
                  </div>
                  <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-2">
                    {r.description}
                  </p>
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-6 rounded-xl border border-line bg-surface p-4">
            <div className="flex items-start gap-2.5">
              <ShieldAlert size={16} className="mt-0.5 shrink-0 text-muted" />
              <div>
                <h3 className="text-[13px] font-semibold text-ink">Required fields</h3>
                <p className="mt-1 text-[13px] text-ink-2">
                  These must be extracted from a document for it to be fully evaluated. A
                  missing field is flagged, never silently ignored.
                </p>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {ruleset.required_fields.map((f) => (
                    <span
                      key={f}
                      className="font-mono-num rounded-md bg-surface-2 px-2 py-0.5 text-[11.5px] text-ink-2"
                    >
                      {f}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
