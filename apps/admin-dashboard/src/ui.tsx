// Shared primitives for the console.
//
// Intentionally few and plain. An operations surface earns trust by being
// predictable, so there is one way to draw a metric, one way to draw a table,
// and one severity scale used everywhere.

import type { ReactNode } from "react";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Panel({
  title,
  right,
  children,
  className,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border border-line bg-panel", className)}>
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-line px-3 py-2">
          {title && <h2 className="label">{title}</h2>}
          {right}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

/** A single number. No card chrome, no icon — the value is the point. */
export function Metric({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "crit";
  hint?: string;
}) {
  const toneCls = {
    neutral: "text-fg",
    ok: "text-ok",
    warn: "text-warn",
    crit: "text-crit",
  }[tone];
  return (
    <div className="px-3 py-2.5">
      <div className="label">{label}</div>
      <div className={cn("num mt-1 text-2xl font-semibold leading-none", toneCls)}>{value}</div>
      {hint && <div className="mt-1 text-2xs text-faint">{hint}</div>}
    </div>
  );
}

/** Severity dot + text. The only place colour is allowed to mean something. */
export function Status({ status }: { status: string }) {
  const map: Record<string, { dot: string; text: string }> = {
    healthy: { dot: "bg-ok", text: "text-ok" },
    ok: { dot: "bg-ok", text: "text-ok" },
    degraded: { dot: "bg-warn", text: "text-warn" },
    unavailable: { dot: "bg-crit", text: "text-crit" },
    unknown: { dot: "bg-faint", text: "text-faint" },
    processed: { dot: "bg-ok", text: "text-ok" },
    failed: { dot: "bg-crit", text: "text-crit" },
    pending: { dot: "bg-faint", text: "text-faint" },
    escalated: { dot: "bg-warn", text: "text-warn" },
    auto_approved: { dot: "bg-ok", text: "text-ok" },
    rejected: { dot: "bg-crit", text: "text-crit" },
  };
  const s = map[status] ?? { dot: "bg-faint", text: "text-muted" };
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", s.text)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function Risk({ score }: { score: number | null }) {
  if (score === null || score === undefined) return <span className="text-faint">—</span>;
  const tone = score >= 60 ? "text-crit" : score >= 30 ? "text-warn" : "text-ok";
  return <span className={cn("num font-semibold", tone)}>{score}</span>;
}

/** Horizontal severity bar. Proportions only — no axes, no chart library. */
export function Distribution({
  segments,
}: {
  segments: { label: string; value: number; cls: string }[];
}) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  return (
    <div className="px-3 py-3">
      <div className="flex h-1.5 w-full overflow-hidden rounded-sm bg-line-soft">
        {total > 0 &&
          segments.map((s) => (
            <div
              key={s.label}
              className={s.cls}
              style={{ width: `${(s.value / total) * 100}%` }}
              title={`${s.label}: ${s.value}`}
            />
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className={cn("h-1.5 w-1.5 rounded-full", s.cls)} />
            {s.label}
            <span className="num text-fg-dim">{s.value}</span>
            {total > 0 && (
              <span className="num text-faint">{Math.round((s.value / total) * 100)}%</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-8 text-center text-sm text-faint">{children}</div>;
}

/** Shown wherever a metric genuinely is not measured. Never a zero. */
export function Unavailable({ reason }: { reason?: string }) {
  return (
    <span className="text-sm text-faint" title={reason}>
      Metric unavailable
    </span>
  );
}

export function Loading() {
  return (
    <div className="space-y-1.5 p-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-6 animate-pulse rounded-sm bg-raised" />
      ))}
    </div>
  );
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <div className="border border-crit/40 bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>
  );
}

export function Mono({ children, dim }: { children: ReactNode; dim?: boolean }) {
  return (
    <span className={cn("font-mono text-xs", dim ? "text-faint" : "text-fg-dim")}>{children}</span>
  );
}

export function ago(iso: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
