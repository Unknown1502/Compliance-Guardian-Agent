// Shared primitives for the console.
//
// Intentionally few and plain. An operations surface earns trust by being
// predictable, so there is one way to draw a metric, one way to draw a table,
// and one severity scale used everywhere.

import { useEffect, useState, type ReactNode } from "react";

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
    <section
      className={cn("overflow-hidden rounded-xl border border-line bg-panel shadow-soft", className)}
    >
      {(title || right) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-3 py-2.5">
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


/**
 * Confirmation for a privileged action.
 *
 * Deliberately not a window.confirm: a privileged action needs to state its
 * consequence, name what it does NOT do, and collect a reason before the
 * confirm button becomes usable. The reason is not optional anywhere it is
 * used — an operator who cannot say why in a sentence has not decided yet.
 */
export function ConfirmAction({
  open,
  title,
  intent = "warn",
  consequence,
  preserved,
  reasonLabel = "Reason",
  reasonPlaceholder,
  confirmLabel,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  intent?: "warn" | "crit" | "ok";
  consequence: ReactNode;
  preserved?: ReactNode;
  reasonLabel?: string;
  reasonPlaceholder?: string;
  confirmLabel: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (open) setReason("");
  }, [open]);
  if (!open) return null;

  const tone = { warn: "text-warn", crit: "text-crit", ok: "text-ok" }[intent];
  // Matches the server's own minimum, so the button and the API agree about
  // what counts as a reason rather than the user discovering it on submit.
  const ready = reason.trim().length >= 12;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-fg/25 px-4 pt-[12vh]"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-panel shadow-soft-md"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b border-line px-4 py-3">
          <h2 className={cn("text-lg font-semibold", tone)}>{title}</h2>
        </header>

        <div className="space-y-3 px-4 py-4 text-sm">
          <div className="text-fg-dim">{consequence}</div>
          {preserved && (
            <div className="rounded-lg border border-line bg-raised px-3 py-2.5 text-sm text-muted">
              {preserved}
            </div>
          )}

          <label className="block">
            <span className="label">{reasonLabel}</span>
            <textarea
              autoFocus
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={reasonPlaceholder}
              className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none"
            />
            <span className="mt-1 block text-2xs text-faint">
              Recorded against your name in the append-only audit trail, and shown to the
              workspace. Minimum 12 characters.
            </span>
          </label>

          {error && <p className="text-sm text-crit">{error}</p>}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-line px-4 py-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-fg-dim transition-colors hover:bg-raised"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(reason.trim())}
            disabled={!ready || busy}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium text-white shadow-soft transition-colors disabled:opacity-40",
              intent === "crit" ? "bg-crit hover:opacity-90" : "bg-accent hover:bg-accent-dim",
            )}
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
}
