import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Operator console. A separate Vite app, not a route in the tenant dashboard,
// so none of this code or its bundle ever ships to a customer.
export default defineConfig({
  plugins: [react()],
  server: { port: 5273, strictPort: false },
});
