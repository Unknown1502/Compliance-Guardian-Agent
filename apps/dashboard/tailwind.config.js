/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter var",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9ebff",
          200: "#b8dcff",
          300: "#86c4ff",
          400: "#4da3fa",
          500: "#2a78d6",
          600: "#1d4ed8",
          700: "#1e40af",
          800: "#1e3a75",
          900: "#1c3361",
          950: "#132047",
        },
        risk: {
          low: "#0ca30c",
          medium: "#fab219",
          high: "#d03b3b",
        },
        status: {
          good: "#0ca30c",
          warning: "#fab219",
          serious: "#ec835a",
          critical: "#d03b3b",
        },
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgba(15, 23, 42, 0.04), 0 1px 3px 0 rgba(15, 23, 42, 0.06)",
        "soft-md":
          "0 2px 4px -1px rgba(15, 23, 42, 0.05), 0 4px 12px -2px rgba(15, 23, 42, 0.08)",
        "soft-lg":
          "0 4px 8px -2px rgba(15, 23, 42, 0.06), 0 12px 32px -6px rgba(15, 23, 42, 0.12)",
        "glow-brand": "0 0 0 1px rgba(29, 78, 216, 0.08), 0 8px 24px -8px rgba(29, 78, 216, 0.35)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        blob: {
          "0%, 100%": { transform: "translate(0px, 0px) scale(1)" },
          "33%": { transform: "translate(30px, -40px) scale(1.08)" },
          "66%": { transform: "translate(-20px, 20px) scale(0.94)" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(29, 78, 216, 0.35)" },
          "100%": { boxShadow: "0 0 0 10px rgba(29, 78, 216, 0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s ease-in-out infinite",
        blob: "blob 12s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      backgroundImage: {
        "shimmer-gradient":
          "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.55) 50%, rgba(255,255,255,0) 100%)",
      },
    },
  },
  plugins: [],
};
