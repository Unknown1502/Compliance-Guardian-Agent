import { cn } from "../../lib/cn";

// The signature element: a risk score struck onto the record like an audit
// stamp. Deliberately off-axis — a stamp pressed by hand is never square to
// the page. The numeral is always paired with a written band, never colour
// alone.

function toneFor(score: number) {
  if (score >= 60)
    return {
      band: "Material breach",
      ring: "text-oxide dark:text-[#C97664]",
      figure: "text-oxide dark:text-[#D98878]",
    };
  if (score >= 30)
    return {
      band: "Qualified",
      ring: "text-brass dark:text-[#C39A46]",
      figure: "text-brass dark:text-[#D6AD57]",
    };
  return {
    band: "Compliant",
    ring: "text-brand-600 dark:text-brand-400",
    figure: "text-brand-700 dark:text-brand-300",
  };
}

export function RiskGauge({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const tone = toneFor(clamped);

  return (
    <div className="flex flex-col items-center gap-3 py-2">
      <div
        className={cn(
          "seal-ring grid h-[132px] w-[132px] animate-strike place-items-center rounded-full",
          tone.ring,
        )}
        role="img"
        aria-label={`Risk score ${clamped} of 100 — ${tone.band}`}
      >
        <div className="flex flex-col items-center leading-none">
          <span className="eyebrow !text-[8px] !tracking-[0.22em] !text-current opacity-60">
            Risk
          </span>
          <span
            className={cn(
              "font-mono-num mt-1.5 text-[40px] font-semibold leading-none",
              tone.figure,
            )}
          >
            {String(clamped).padStart(2, "0")}
          </span>
          <span className="mt-1.5 text-[9px] font-semibold uppercase tracking-[0.16em] opacity-70">
            {tone.band}
          </span>
        </div>
      </div>
      <p className="font-mono-num text-[10px] text-slate-400 dark:text-slate-500">
        {clamped} / 100 · threshold 60
      </p>
    </div>
  );
}
