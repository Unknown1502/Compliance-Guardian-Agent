import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, FileCheck2, Repeat, ShieldCheck } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";
import {
  ApiError,
  capturePayPalOrder,
  createPayPalOrder,
  createRazorpayOrder,
  getPaymentProviders,
  verifyRazorpayPayment,
  type Plan,
  type ProviderOption,
} from "../api/client";
import { PageHeading } from "../components/ui/Card";
import { Button } from "../components/ui/Button";

const PLANS = [
  {
    id: "oneoff" as const,
    icon: FileCheck2,
    title: "Single audit",
    description: "One more document, one more risk-scored, cited compliance check.",
    features: [
      "Full Gemini extraction + risk score",
      "Cited rule verdicts",
      "Added to your audit trail",
    ],
  },
  {
    id: "subscription" as const,
    icon: Repeat,
    title: "Unlimited",
    description: "Every document, every month, no per-audit decision to make.",
    features: [
      "Unlimited compliance checks",
      "Weekly Gemini-authored reports",
      "Cancel any time",
    ],
    highlight: true,
  },
];

const PROVIDER_LABEL: Record<string, string> = {
  razorpay: "Card / UPI / Netbanking",
  paypal: "PayPal",
};

/**
 * Shown only for the moment before /billing/providers answers with the real
 * server-side price. Matches the Razorpay INR defaults rather than a USD
 * figure, so the number does not visibly change currency once it loads.
 */
const LIST_PRICE: Record<Plan, string> = { oneoff: "₹1,999", subscription: "₹8,300" };

function formatPrice(option: ProviderOption | undefined, plan: Plan): string {
  if (!option?.amount_minor || !option.currency) return LIST_PRICE[plan];
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: option.currency,
      maximumFractionDigits: 0,
    }).format(option.amount_minor / 100);
  } catch {
    return `${option.currency} ${option.amount_minor / 100}`;
  }
}

/**
 * Razorpay Checkout is a hosted modal, so its script has to run on the page.
 * Loaded on click rather than on mount: a visitor who never opens billing
 * never fetches a third-party script, and it stays out of the bundle.
 */
function loadRazorpayScript(): Promise<boolean> {
  const SRC = "https://checkout.razorpay.com/v1/checkout.js";
  if (document.querySelector(`script[src="${SRC}"]`)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const el = document.createElement("script");
    el.src = SRC;
    el.onload = () => resolve(true);
    el.onerror = () => resolve(false);
    document.body.appendChild(el);
  });
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

export function BillingView() {
  const { session } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const status = params.get("status");
  const [busy, setBusy] = useState<string | null>(null);
  const [providers, setProviders] = useState<{
    oneoff: ProviderOption[];
    subscription: ProviderOption[];
  } | null>(null);
  const [paid, setPaid] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    let live = true;
    getPaymentProviders(session)
      .then((p) => live && setProviders(p))
      .catch(() => {
        // Not fatal: the page still renders with list prices and the buttons
        // report their own failures. A billing page that shows nothing
        // because a discovery call failed is worse than one that shows the
        // plans.
        if (live) setProviders(null);
      });
    return () => {
      live = false;
    };
  }, [session]);

  const optionsFor = (plan: Plan): ProviderOption[] =>
    (providers?.[plan] ?? []).filter((o) => o.available);

  const onPaid = useCallback(
    (tier: string) => {
      setPaid(tier);
      setBusy(null);
      toast.push({
        kind: "success",
        title: "Payment confirmed",
        description: `Your workspace is now on the ${tier} plan.`,
      });
    },
    [toast],
  );

  const fail = useCallback(
    (err: unknown) => {
      const msg =
        err instanceof ApiError && err.status === 503
          ? "That payment method isn't switched on yet — try another."
          : err instanceof ApiError && err.status === 400
            ? "We couldn't confirm that payment. Nothing has been charged to your plan."
            : (err as Error).message;
      toast.push({ kind: "error", title: "Payment could not be completed", description: msg });
      setBusy(null);
    },
    [toast],
  );

  // Returning from PayPal's approval page: ?token=<order id>. The capture —
  // and therefore the upgrade — happens server-side; the token in the URL
  // grants nothing on its own.
  useEffect(() => {
    const token = params.get("token");
    if (!session || !token) return;
    setBusy("paypal-return");
    capturePayPalOrder(session, token)
      .then((r) => onPaid(r.plan_tier))
      .catch(fail)
      .finally(() => {
        const next = new URLSearchParams(params);
        next.delete("token");
        next.delete("PayerID");
        setParams(next, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const payWithRazorpay = async (plan: Plan) => {
    if (!session) return;
    setBusy(`${plan}:razorpay`);
    try {
      const order = await createRazorpayOrder(session, plan);
      const ready = await loadRazorpayScript();
      if (!ready || !window.Razorpay) {
        throw new Error("Could not load the payment window. Check your connection and retry.");
      }
      const rzp = new window.Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        // Amount and currency are echoed from the order the server created;
        // Razorpay charges what the order says regardless of what is passed
        // here, so this is display only.
        amount: order.amount,
        currency: order.currency,
        name: "ComplianceGuardian",
        description: plan === "subscription" ? "Unlimited audits" : "Single audit",
        prefill: { email: session.email ?? "" },
        theme: { color: "#1d4ed8" },
        modal: { ondismiss: () => setBusy(null) },
        handler: async (response: {
          razorpay_order_id: string;
          razorpay_payment_id: string;
          razorpay_signature: string;
        }) => {
          try {
            const result = await verifyRazorpayPayment(session, response);
            onPaid(result.plan_tier);
          } catch (err) {
            fail(err);
          }
        },
      });
      rzp.open();
    } catch (err) {
      fail(err);
    }
  };

  const payWithPayPal = async (plan: Plan) => {
    if (!session) return;
    setBusy(`${plan}:paypal`);
    try {
      const order = await createPayPalOrder(session, plan);
      if (!order.approve_url) throw new Error("PayPal did not return an approval link.");
      window.location.href = order.approve_url;
    } catch (err) {
      fail(err);
    }
  };

  const pay = (plan: Plan, provider: string) => {
    if (provider === "razorpay") return payWithRazorpay(plan);
    if (provider === "paypal") return payWithPayPal(plan);
  };

  return (
    <div>
      <PageHeading
        title="Billing"
        subtitle="Your first audit was free. Pick a plan for everything after that."
      />

      {(status === "success" || paid) && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-[13.5px] text-status-good dark:border-green-900/60 dark:bg-green-950/25">
          <CheckCircle2 size={16} strokeWidth={2.25} />
          {paid
            ? `Payment received — your workspace is on the ${paid} plan.`
            : "Payment received — your plan updates within a few seconds."}
        </div>
      )}
      {status === "cancelled" && (
        <div className="mb-6 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13.5px] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          Checkout was cancelled — nothing was charged.
        </div>
      )}
      {busy === "paypal-return" && (
        <div className="mb-6 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13.5px] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          Confirming your PayPal payment…
        </div>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        {PLANS.map((p) => {
          const options = optionsFor(p.id);
          const price = formatPrice(options[0], p.id);
          return (
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
                  {price}
                </span>
                <span className="text-[13px] text-slate-500 dark:text-slate-400">
                  {p.id === "oneoff" ? "one-off" : "/month"}
                </span>
              </div>
              <ul className="mt-4 space-y-1.5">
                {p.features.map((f) => (
                  <li
                    key={f}
                    className="flex items-start gap-2 text-[12.5px] text-slate-600 dark:text-slate-400"
                  >
                    <CheckCircle2
                      size={13}
                      className="mt-0.5 shrink-0 text-status-good"
                      strokeWidth={2.25}
                    />
                    {f}
                  </li>
                ))}
              </ul>

              <div className="mt-5 space-y-2">
                {providers === null ? (
                  <div className="h-10 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
                ) : options.length === 0 ? (
                  <p className="rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] text-slate-500 dark:border-slate-800 dark:text-slate-400">
                    No payment method is switched on yet. Contact us and we'll invoice you
                    directly.
                  </p>
                ) : (
                  options.map((o, i) => (
                    <Button
                      key={o.provider}
                      onClick={() => pay(p.id, o.provider)}
                      loading={busy === `${p.id}:${o.provider}`}
                      disabled={busy !== null && busy !== `${p.id}:${o.provider}`}
                      variant={p.highlight && i === 0 ? "primary" : "outline"}
                      size="lg"
                      className="w-full"
                    >
                      {options.length === 1
                        ? p.id === "oneoff"
                          ? "Buy this audit"
                          : "Subscribe"
                        : `Pay with ${PROVIDER_LABEL[o.provider] ?? o.provider}`}
                    </Button>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex items-start gap-2 text-[12px] text-slate-400 dark:text-slate-500">
        <ShieldCheck size={14} className="mt-0.5 shrink-0" />
        Every payment is handled by the provider's own hosted checkout — your card details
        never reach ComplianceGuardian's servers, and your plan only changes after the
        provider confirms the payment to us directly.
      </div>
    </div>
  );
}
