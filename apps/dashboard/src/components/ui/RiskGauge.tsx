import { motion } from "framer-motion";
import { cn } from "../../lib/cn";

// Semi-circular risk gauge. 0-100 score mapped onto a 180° arc with the
// fixed status palette (good / warning / critical) — always paired with the
// numeric label at the center, never color alone.

const SIZE = 168;
const STROKE = 14;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = Math.PI * RADIUS; // half circle

function toneFor(score: number) {
  if (score >= 60) return { color: "#d03b3b", label: "High risk", text: "text-status-critical" };
  if (score >= 30) return { color: "#fab219", label: "Medium risk", text: "text-amber-600 dark:text-amber-400" };
  return { color: "#0ca30c", label: "Low risk", text: "text-status-good" };
}

export function RiskGauge({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const tone = toneFor(clamped);
  const offset = CIRCUMFERENCE - (clamped / 100) * CIRCUMFERENCE;
  const cy = SIZE / 2;

  return (
    <div className="flex flex-col items-center">
      <svg width={SIZE} height={SIZE / 2 + STROKE / 2} viewBox={`0 0 ${SIZE} ${SIZE / 2 + STROKE / 2}`}>
        <path
          d={`M ${STROKE / 2} ${cy} A ${RADIUS} ${RADIUS} 0 0 1 ${SIZE - STROKE / 2} ${cy}`}
          fill="none"
          className="stroke-slate-100 dark:stroke-slate-800"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        <motion.path
          d={`M ${STROKE / 2} ${cy} A ${RADIUS} ${RADIUS} 0 0 1 ${SIZE - STROKE / 2} ${cy}`}
          fill="none"
          stroke={tone.color}
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          initial={{ strokeDashoffset: CIRCUMFERENCE }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.1 }}
        />
      </svg>
      <div className="-mt-9 flex flex-col items-center">
        <span className="font-mono-num text-3xl font-bold text-slate-800 dark:text-slate-100">
          {clamped}
        </span>
        <span className={cn("text-xs font-semibold", tone.text)}>{tone.label}</span>
      </div>
    </div>
  );
}
