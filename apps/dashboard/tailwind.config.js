/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Public Sans is the US Web Design System's civic typeface — a
        // deliberate choice for a regulatory product, not a neutral default.
        sans: ["Public Sans", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        display: ["Spectral", "ui-serif", "Georgia", "serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Neutral ramp: document stock. A faint green-grey cast, deliberately
        // not the blue-grey of default slate.
        slate: {
          50: "#F7F8F4",
          100: "#EDEFE9",
          200: "#DFE2DA",
          300: "#C9CEC3",
          400: "#9AA295",
          500: "#737C6F",
          600: "#575F55",
          700: "#414940",
          800: "#2A302A",
          900: "#1B201B",
          950: "#121714",
        },
        // Seal green — certification/approval, struck-stamp ink.
        brand: {
          50: "#EDF4F0",
          100: "#D6E8DE",
          200: "#AFD2C0",
          300: "#7FB49B",
          400: "#4F9375",
          500: "#2E765A",
          600: "#1D5A45",
          700: "#174A38",
          800: "#133A2C",
          900: "#102E24",
          950: "#0A1D17",
        },
        ink: "#14181C",
        stock: "#EDEFE9",
        oxide: "#9A3B2B",
        brass: "#A07A24",
        risk: {
          low: "#1D5A45",
          medium: "#A07A24",
          high: "#9A3B2B",
        },
        status: {
          good: "#1D5A45",
          warning: "#A07A24",
          serious: "#A85A2A",
          critical: "#9A3B2B",
        },
      },
      borderRadius: {
        // Registers are squared off. Nothing here is a pill.
        DEFAULT: "2px",
        sm: "1px",
        md: "2px",
        lg: "3px",
        xl: "4px",
        "2xl": "5px",
        "3xl": "6px",
      },
      boxShadow: {
        soft: "0 1px 0 0 rgba(20, 24, 28, 0.04)",
        "soft-md": "0 1px 2px 0 rgba(20, 24, 28, 0.06)",
        "soft-lg": "0 2px 8px -2px rgba(20, 24, 28, 0.10)",
        "glow-brand": "0 0 0 1px rgba(29, 90, 69, 0.20)",
        struck: "0 1px 0 0 rgba(20,24,28,0.06), inset 0 0 0 1px rgba(255,255,255,0.5)",
      },
      keyframes: {
        strike: {
          "0%": { opacity: "0", transform: "scale(1.28) rotate(-9deg)" },
          "60%": { opacity: "1", transform: "scale(0.97) rotate(-2.4deg)" },
          "100%": { opacity: "1", transform: "scale(1) rotate(-3deg)" },
        },
        "rule-draw": {
          "0%": { transform: "scaleX(0)" },
          "100%": { transform: "scaleX(1)" },
        },
      },
      animation: {
        strike: "strike 420ms cubic-bezier(0.2, 0.9, 0.3, 1) both",
        "rule-draw": "rule-draw 600ms cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },
  plugins: [],
};
