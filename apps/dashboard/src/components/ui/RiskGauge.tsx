import { motion } from "framer-motion";
import { cn } from "../../lib/cn";

// Risk score as a clean donut. The numeral and the written band always carry
// the meaning — colour is reinforcement, never the only signal.

const SIZE = 140;
const STROKE = 10;
const R = (SIZE - STROKE) / 2;
const C = 2 * Math.PI * R;

function toneFor(score: number) {
  if (score >= 60)
    return { color: "#DC2626", label: "High risk", text: "text-status-critical" };
  if (score >= 30)
    return { color: "#EA580C", label: "Medium risk", text: "text-status-warning" };
  return { color: "#16A34A", label: "Low risk", text: "text-status-good" };
}

export function RiskGauge({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const tone = toneFor(clamped);

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} className="-rotate-90">
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            strokeWidth={STROKE}
            className="stroke-slate-200 dark:stroke-slate-800"
          />
          <motion.circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={R}
            fill="none"
            stroke={tone.color}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={C}
            initial={{ strokeDashoffset: C }}
            animate={{ strokeDashoffset: C - (clamped / 100) * C }}
            transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono-num text-[34px] font-bold leading-none tracking-tight text-slate-900 dark:text-slate-50">
            {clamped}
          </span>
          <span className="mt-1 text-[11px] font-medium text-slate-400 dark:text-slate-500">
            of 100
          </span>
        </div>
      </div>
      <span className={cn("mt-3 text-[13px] font-semibold", tone.text)}>{tone.label}</span>
      <span className="mt-0.5 text-[11.5px] text-slate-400 dark:text-slate-500">
        Escalation threshold 60
      </span>
    </div>
  );
}
