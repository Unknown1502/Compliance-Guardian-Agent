import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dashboard dev server. Proxying is not used — the dashboard calls the API
// Gateway directly via VITE_API_BASE_URL and reads Firestore in real time.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
  },
  build: {
    // Split the vendor weight apart from app code. Firebase dominates the
    // bundle and changes rarely, so isolating it means an app deploy no
    // longer invalidates ~200KB of cached vendor code in every browser.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // Firestore is roughly two-thirds of the Firebase weight and is only
          // used by the live-data hooks, while auth is needed on every screen.
          // Separate chunks so each caches on its own lifecycle.
          if (id.includes("@firebase/firestore") || id.includes("firebase/firestore")) {
            return "firebase-firestore";
          }
          if (id.includes("@firebase/auth") || id.includes("firebase/auth")) {
            return "firebase-auth";
          }
          if (id.includes("firebase") || id.includes("@firebase")) return "firebase-core";
          if (id.includes("react-router")) return "router";
          if (id.includes("framer-motion")) return "motion";
          if (id.includes("react-dom") || id.includes("/react/") || id.includes("scheduler")) {
            return "react";
          }
          return "vendor";
        },
      },
    },
    // Fail loudly if a single chunk grows past this again, rather than
    // letting the warning become background noise.
    chunkSizeWarningLimit: 400,
  },
});
