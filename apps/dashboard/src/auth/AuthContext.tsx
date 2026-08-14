// Auth context supporting two modes:
//   dev      — pick tenant + role, mints a base64 "dev:<claims>" token accepted
//              by the API gateway's CG_AUTH_DEV_MODE. No Firebase Auth needed.
//   firebase — real Firebase Auth (email/password), ID token carries custom
//              claims (tenant_id, role) set by the backend.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  onAuthStateChanged,
  sendEmailVerification,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
} from "firebase/auth";
import { AUTH_MODE } from "../config";
import { firebaseAuth } from "../firebase";
import type { Role, Session } from "../types";

interface AuthState {
  session: Session | null;
  loading: boolean;
  devSignIn: (tenantId: string, role: Role, uid: string) => void;
  firebaseSignIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Ask Firebase to re-send the verification email to the signed-in user. */
  resendVerification: () => Promise<void>;
  /** Re-read the user from Firebase so a just-clicked link reflects immediately. */
  refreshVerification: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | undefined>(undefined);

const DEV_SESSION_KEY = "cg_dev_session";

function encodeDevToken(claims: {
  uid: string;
  tenant_id: string;
  role: Role;
}): string {
  const json = JSON.stringify(claims);
  const b64 = btoa(json).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `dev:${b64}`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore a dev session from localStorage on load.
  useEffect(() => {
    if (AUTH_MODE === "dev") {
      const stored = localStorage.getItem(DEV_SESSION_KEY);
      if (stored) {
        const claims = JSON.parse(stored) as {
          uid: string;
          tenant_id: string;
          role: Role;
        };
        setSession(makeDevSession(claims));
      }
      setLoading(false);
      return;
    }
    // firebase mode
    const unsub = onAuthStateChanged(firebaseAuth(), async (user) => {
      if (user) {
        // Force-refresh rather than trust a cached token: a member who was
        // just invited (custom claims set server-side moments ago) must not
        // be stuck with a token minted before tenant_id/role existed on it.
        const tokenResult = await user.getIdTokenResult(true);
        const tenantId = (tokenResult.claims.tenant_id as string) ?? "";
        const role = (tokenResult.claims.role as Role) ?? "owner";
        setSession({
          uid: user.uid,
          tenantId,
          role,
          email: user.email ?? undefined,
          emailVerified: user.emailVerified,
          getToken: () => user.getIdToken(),
        });
      } else {
        setSession(null);
      }
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const devSignIn = useCallback((tenantId: string, role: Role, uid: string) => {
    const claims = { uid, tenant_id: tenantId, role };
    localStorage.setItem(DEV_SESSION_KEY, JSON.stringify(claims));
    setSession(makeDevSession(claims));
  }, []);

  const firebaseSignIn = useCallback(async (email: string, password: string) => {
    const cred = await signInWithEmailAndPassword(firebaseAuth(), email, password);
    // Firebase sends this itself, so there is no mail transport or code store
    // on our side. Failure is non-fatal: a bounced send must not block a
    // sign-in the user has already completed correctly.
    if (!cred.user.emailVerified) {
      try {
        await sendEmailVerification(cred.user);
      } catch {
        /* the user can retry from the banner */
      }
    }
  }, []);

  const resendVerification = useCallback(async () => {
    const user = firebaseAuth().currentUser;
    if (user && !user.emailVerified) await sendEmailVerification(user);
  }, []);

  const refreshVerification = useCallback(async () => {
    const user = firebaseAuth().currentUser;
    if (!user) return;
    // reload() re-reads the account; without it the client keeps showing
    // "unverified" until the ID token happens to refresh on its own.
    await user.reload();
    await user.getIdToken(true);
    setSession((prev) =>
      prev ? { ...prev, emailVerified: firebaseAuth().currentUser?.emailVerified ?? false } : prev,
    );
  }, []);

  const signOut = useCallback(async () => {
    if (AUTH_MODE === "dev") {
      localStorage.removeItem(DEV_SESSION_KEY);
      setSession(null);
      return;
    }
    await fbSignOut(firebaseAuth());
  }, []);

  const value = useMemo(
    () => ({
      session,
      loading,
      devSignIn,
      firebaseSignIn,
      signOut,
      resendVerification,
      refreshVerification,
    }),
    [
      session,
      loading,
      devSignIn,
      firebaseSignIn,
      signOut,
      resendVerification,
      refreshVerification,
    ],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

function makeDevSession(claims: {
  uid: string;
  tenant_id: string;
  role: Role;
}): Session {
  const token = encodeDevToken(claims);
  return {
    uid: claims.uid,
    tenantId: claims.tenant_id,
    role: claims.role,
    // A local dev identity has no mailbox to confirm; treating it as
    // unverified would just wedge local development behind a banner.
    emailVerified: true,
    getToken: async () => token,
  };
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
