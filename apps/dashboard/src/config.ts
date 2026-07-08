// Runtime configuration derived from Vite env vars.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";

export const AUTH_MODE: "dev" | "firebase" =
  (import.meta.env.VITE_AUTH_MODE as "dev" | "firebase") ?? "dev";

export const GCP_PROJECT = import.meta.env.VITE_GCP_PROJECT ?? "cg-local";

export const FIRESTORE_EMULATOR_HOST =
  import.meta.env.VITE_FIRESTORE_EMULATOR_HOST ?? "";

export const FIREBASE_CONFIG = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY ?? "",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID ?? GCP_PROJECT,
};
