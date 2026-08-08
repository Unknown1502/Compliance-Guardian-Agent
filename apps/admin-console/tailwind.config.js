/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Same validated status tokens as the tenant dashboard, so a number
        // means the same thing in both places.
        status: { good: "#16A34A", warning: "#F59E0B", critical: "#DC2626" },
        brand: { 400: "#60A5FA", 500: "#3B82F6", 600: "#2563EB" },
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};
