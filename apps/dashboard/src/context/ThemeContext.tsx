// Light / Dark / System, persisted to localStorage.
//
// Three bugs made the previous version unreachable in practice: it offered
// only a light/dark toggle with no System option, it read its initial value
// from a `dark` class that nothing ever set (the pre-paint script its comment
// referred to did not exist, so a saved choice never came back after a
// reload), and the one control that could change it was never rendered.
//
// The pre-paint script now lives in index.html and applies the class before
// first paint. This module deliberately reads the same storage key and uses
// the same resolution logic, so the two cannot drift.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** What the user chose. "system" defers to the OS. */
export type ThemePreference = "light" | "dark" | "system";
/** What is actually on screen — "system" has been resolved away. */
export type ResolvedTheme = "light" | "dark";

interface ThemeState {
  /** The stored preference, which is what the selector should show. */
  preference: ThemePreference;
  /** The theme in effect right now. */
  theme: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
}

const ThemeCtx = createContext<ThemeState | undefined>(undefined);

export const THEME_STORAGE_KEY = "cg_theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function systemTheme(): ResolvedTheme {
  return typeof window !== "undefined" && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Private browsing or blocked storage: fall through to the default.
  }
  // No explicit choice yet, so follow the OS. A first visit on a machine set
  // to dark should not open blinding white.
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [systemIsDark, setSystemIsDark] = useState<boolean>(() => systemTheme() === "dark");

  // Follow the OS while the preference is "system" — if someone switches
  // their machine to dark at sunset, the open tab should follow rather than
  // wait for a reload.
  useEffect(() => {
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = (e: MediaQueryListEvent) => setSystemIsDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme: ResolvedTheme =
    preference === "system" ? (systemIsDark ? "dark" : "light") : preference;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const setPreference = useCallback((p: ThemePreference) => {
    setPreferenceState(p);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, p);
    } catch {
      // Storage unavailable: the choice still applies for this session.
    }
  }, []);

  const value = useMemo(
    () => ({ preference, theme, setPreference }),
    [preference, theme, setPreference],
  );

  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
