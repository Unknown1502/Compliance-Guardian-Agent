// Admin authentication.
//
// Shares the customer app's Firebase project on purpose: identity and the
// backend are common, and duplicating them would create a second, weaker
// identity system to keep in sync. What is NOT shared is authorization —
// being signed in here proves nothing. The console renders only after the
// backend confirms platform-admin status via /api/platform/whoami, and every
// subsequent request is checked server-side again.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { initializeApp } from "firebase/app";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
  type User,
} from "firebase/auth";
import { api, ApiError, type WhoAmI } from "./api";

const app = initializeApp({
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
});
const auth = getAuth(app);

/** authorized: backend confirmed admin. denied: signed in, not an admin. */
type Phase = "loading" | "signed-out" | "checking" | "authorized" | "denied";

interface AuthState {
  phase: Phase;
  user: User | null;
  admin: WhoAmI | null;
  error: string | null;
  getToken: () => Promise<string>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [admin, setAdmin] = useState<WhoAmI | null>(null);
  const [error, setError] = useState<string | null>(null);

  const getToken = useCallback(async () => {
    const u = auth.currentUser;
    if (!u) throw new Error("not signed in");
    return u.getIdToken();
  }, []);

  useEffect(() => {
    return onAuthStateChanged(auth, async (u) => {
      setUser(u);
      setAdmin(null);
      if (!u) {
        setPhase("signed-out");
        return;
      }
      setPhase("checking");
      try {
        // The single source of truth for whether this person may be here.
        setAdmin(await api.whoami(() => u.getIdToken()));
        setPhase("authorized");
      } catch (err) {
        // 404 is what a non-admin gets: the route does not acknowledge itself.
        if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
          setPhase("denied");
        } else {
          setError((err as Error).message);
          setPhase("denied");
        }
      }
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setError(null);
    await signInWithEmailAndPassword(auth, email, password);
  }, []);

  const signOut = useCallback(async () => {
    await fbSignOut(auth);
    setAdmin(null);
    setError(null);
  }, []);

  const value = useMemo(
    () => ({ phase, user, admin, error, getToken, signIn, signOut }),
    [phase, user, admin, error, getToken, signIn, signOut],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
