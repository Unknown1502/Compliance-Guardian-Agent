import { useEffect, useState } from "react";
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

// Firebase rate-limits verification sends per account and per IP, and it does
// so aggressively. Without a cooldown an impatient user burns the quota in
// seconds and is then locked out of resending for far longer than this.
const RESEND_COOLDOWN_SECONDS = 60;
const COOLDOWN_KEY = "cg_verify_resend_until";

/** Firebase surfaces machine codes; users need a sentence they can act on. */
function humanizeAuthError(err: unknown): string {
  const raw = (err as { code?: string })?.code ?? (err as Error)?.message ?? "";
  if (raw.includes("too-many-requests")) {
    return "Too many requests to Firebase. Wait a few minutes, then try again — the limit clears on its own.";
  }
  if (raw.includes("network-request-failed")) {
    return "Network request failed. Check your connection and try again.";
  }
  if (raw.includes("user-token-expired") || raw.includes("user-disabled")) {
    return "Your session has expired. Sign out and back in, then resend.";
  }
  return (err as Error)?.message ?? "Unknown error.";
}

function readCooldownRemaining(): number {
  try {
    const until = Number(localStorage.getItem(COOLDOWN_KEY) ?? 0);
    return Math.max(0, Math.ceil((until - Date.now()) / 1000));
  } catch {
    return 0;
  }
}

export function VerifyEmailBanner() {
  const { session, resendVerification, refreshVerification } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<"resend" | "refresh" | null>(null);
  // Persisted so navigating away and back doesn't hand out a fresh allowance.
  const [cooldown, setCooldown] = useState(readCooldownRemaining);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setInterval(() => setCooldown(readCooldownRemaining()), 1000);
    return () => window.clearInterval(t);
  }, [cooldown]);

  if (!session || session.emailVerified) return null;

  const resend = async () => {
    if (cooldown > 0) return;
    setBusy("resend");
    try {
      await resendVerification();
      try {
        localStorage.setItem(
          COOLDOWN_KEY,
          String(Date.now() + RESEND_COOLDOWN_SECONDS * 1000),
        );
      } catch {
        /* storage unavailable — the in-memory countdown still applies */
      }
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.push({
        kind: "success",
        title: "Verification email sent",
        description: `Check ${session.email ?? "your inbox"} for the link.`,
      });
    } catch (err) {
      // Back off locally too: the send failed, but Firebase has already
      // counted the attempt, so retrying immediately makes it worse.
      try {
        localStorage.setItem(
          COOLDOWN_KEY,
          String(Date.now() + RESEND_COOLDOWN_SECONDS * 1000),
        );
      } catch {
        /* ignore */
      }
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.push({
        kind: "error",
        title: "Could not send the email",
        description: humanizeAuthError(err),
      });
    } finally {
      setBusy(null);
    }
  };

  const refresh = async () => {
    setBusy("refresh");
    try {
      await refreshVerification();
    } catch (err) {
      toast.push({
        kind: "error",
        title: "Could not check verification",
        description: humanizeAuthError(err),
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-orange-200 bg-orange-50 px-4 py-3 text-sm">
      <MailWarning size={16} className="shrink-0 text-status-warning" />
      <p className="min-w-0 flex-1 text-ink-2">
        Confirm your email address
        {session.email ? (
          <>
            {" "}
            — we sent a link to <span className="font-medium text-ink">{session.email}</span>
          </>
        ) : null}
        .
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={refresh}
          disabled={busy !== null}
          className="inline-flex items-center gap-1.5 rounded-lg border border-orange-300 px-2.5 py-1.5 text-[12px] font-medium text-ink-2 transition-colors hover:bg-orange-100 disabled:opacity-50"
        >
          <RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} />
          I've verified
        </button>
        <button
          type="button"
          onClick={resend}
          disabled={busy !== null || cooldown > 0}
          title={
            cooldown > 0
              ? `Wait ${cooldown}s before requesting another email`
              : "Send the verification email again"
          }
          className="rounded-lg bg-ink px-2.5 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
        >
          {busy === "resend" ? "Sending…" : cooldown > 0 ? `Resend in ${cooldown}s` : "Resend"}
        </button>
      </div>
    </div>
  );
}
