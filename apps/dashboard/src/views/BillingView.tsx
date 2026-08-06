import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, FileCheck2, Repeat, ShieldCheck } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import { ApiError, createCheckout } from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

const PLANS = [
  {
    id: "oneoff" as const,
    icon: FileCheck2,
    title: "Single audit",
    price: "$50",
    cadence: "USD, one-off",
    description: "One more document, one more risk-scored, cited compliance check.",
    features: ["Full Gemini extraction + risk score", "Cited rule verdicts", "Added to your audit trail"],
  },
  {
    id: "subscription" as const,
    icon: Repeat,
    title: "Unlimited",
    price: "$99",
    cadence: "USD /month",
    description: "Every document, every month, no per-audit decision to make.",
    features: ["Unlimited compliance checks", "Weekly Gemini-authored reports", "Cancel any time"],
    highlight: true,
  },
];

export function BillingView() {
  const { session } = useAuth();
  const toast = useToast();
  const [params] = useSearchParams();
  const status = params.get("status");
  const [busyPlan, setBusyPlan] = useState<string | null>(null);

  const buy = async (plan: "oneoff" | "subscription") => {
    if (!session) return;
    setBusyPlan(plan);
    try {
      const { checkout_url } = await createCheckout(session, plan);
      window.location.href = checkout_url;
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 503
          ? "Payments aren't switched on yet — check back shortly."
          : (err as Error).message;
      toast.push({ kind: "error", title: "Could not start checkout", description: msg });
      setBusyPlan(null);
    }
  };

  return (
    <div>
      <PageHeading
        title="Billing"
        subtitle="Your first audit was free. Pick a plan for everything after that."
      />

      {status === "success" && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-[13.5px] text-status-good dark:border-green-900/60 dark:bg-green-950/25">
          <CheckCircle2 size={16} strokeWidth={2.25} />
          Payment received — your plan updates within a few seconds.
        </div>
      )}
      {status === "cancelled" && (
        <div className="mb-6 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13.5px] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          Checkout was cancelled — nothing was charged.
        </div>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        {PLANS.map((p) => (
          <div
            key={p.id}
            className={`relative rounded-xl border p-6 ${
              p.highlight
                ? "border-brand-300 bg-brand-50/40 dark:border-brand-800 dark:bg-brand-950/20"
                : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
            }`}
          >
            {p.highlight && (
              <span className="absolute -top-2.5 left-6 rounded-full bg-brand-600 px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-white">
                Most providers choose this
              </span>
            )}
            <p.icon size={20} className="text-brand-600 dark:text-brand-400" strokeWidth={2} />
            <h3 className="mt-3 text-[17px] font-bold text-slate-900 dark:text-slate-50">
              {p.title}
            </h3>
            <p className="mt-1 text-[13px] text-slate-500 dark:text-slate-400">{p.description}</p>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="font-mono-num text-[30px] font-bold text-slate-900 dark:text-slate-50">
                {p.price}
              </span>
              <span className="text-[13px] text-slate-500 dark:text-slate-400">{p.cadence}</span>
            </div>
            <ul className="mt-4 space-y-1.5">
              {p.features.map((f) => (
                <li key={f} className="flex items-start gap-2 text-[12.5px] text-slate-600 dark:text-slate-400">
                  <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-status-good" strokeWidth={2.25} />
                  {f}
                </li>
              ))}
            </ul>
            <Button
              onClick={() => buy(p.id)}
              loading={busyPlan === p.id}
              variant={p.highlight ? "primary" : "outline"}
              size="lg"
              className="mt-5 w-full"
            >
              {p.id === "oneoff" ? "Buy this audit" : "Subscribe"}
            </Button>
          </div>
        ))}
      </div>

      <div className="mt-6 flex items-start gap-2 text-[12px] text-slate-400 dark:text-slate-500">
        <ShieldCheck size={14} className="mt-0.5 shrink-0" />
        Payment is handled entirely by Stripe — your card details never reach
        ComplianceGuardian's servers.
      </div>
    </div>
  );
}
