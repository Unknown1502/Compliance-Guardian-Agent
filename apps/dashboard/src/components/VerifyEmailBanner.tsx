import { useState } from "react";
import { MailWarning, RefreshCw } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../context/ToastContext";

/**
 * Prompts a signed-in user to confirm their email address.
 *
 * Advisory by default: the API only refuses unverified sessions when the
 * deployment sets CG_REQUIRE_EMAIL_VERIFICATION, so this banner nudges rather
 * than blocks. Hard-blocking in the UI while the API still accepts the session
 * would be a lie about what the product actually enforces.
 */
export function VerifyEmailBanner() {
  const { session, resendVerification, refreshVerification } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<"resend" | "refresh" | null>(null);

  if (!session || session.emailVerified) return null;

  const resend = async () => {
    setBusy("resend");
    try {
      await resendVerification();
      toast.push({
        kind: "success",
        title: "Verification email sent",
        description: `Check ${session.email ?? "your inbox"} for the link.`,
      });
    } catch (err) {
      toast.push({
        kind: "error",
        title: "Could not send the email",
        description: (err as Error).message,
      });
    } finally {
      setBusy(null);
    }
  };

  const refresh = async () => {
    setBusy("refresh");
    try {
      await refreshVerification();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-sm dark:border-orange-900/60 dark:bg-orange-950/25">
      <MailWarning size={16} className="shrink-0 text-status-warning" />
      <p className="min-w-0 flex-1 text-slate-700 dark:text-slate-300">
        Confirm your email address
        {session.email ? (
          <>
            {" "}
            — we sent a link to{" "}
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {session.email}
            </span>
          </>
        ) : null}
        .
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={refresh}
          disabled={busy !== null}
          className="inline-flex items-center gap-1.5 rounded-lg border border-orange-300 px-2.5 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:bg-orange-100 disabled:opacity-50 dark:border-orange-900 dark:text-slate-200 dark:hover:bg-orange-950/40"
        >
          <RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} />
          I've verified
        </button>
        <button
          type="button"
          onClick={resend}
          disabled={busy !== null}
          className="rounded-lg bg-slate-900 px-2.5 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
        >
          {busy === "resend" ? "Sending…" : "Resend"}
        </button>
      </div>
    </div>
  );
}
