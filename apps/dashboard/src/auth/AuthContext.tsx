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
        const tokenResult = await user.getIdTokenResult();
        const tenantId = (tokenResult.claims.tenant_id as string) ?? "";
        const role = (tokenResult.claims.role as Role) ?? "owner";
        setSession({
          uid: user.uid,
          tenantId,
          role,
          email: user.email ?? undefined,
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
    await signInWithEmailAndPassword(firebaseAuth(), email, password);
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
    () => ({ session, loading, devSignIn, firebaseSignIn, signOut }),
    [session, loading, devSignIn, firebaseSignIn, signOut],
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
    getToken: async () => token,
  };
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
