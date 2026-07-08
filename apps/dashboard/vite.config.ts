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
});
