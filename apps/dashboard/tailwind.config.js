/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter var", "Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        display: ["Inter var", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Warm neutral ramp — the off-white of the reference, not blue-grey.
        slate: {
          50: "#FAFAF9",
          100: "#F5F4F1",
          200: "#E7E5E1",
          300: "#D6D3CE",
          400: "#A8A29B",
          500: "#78716C",
          600: "#57534E",
          700: "#44403C",
          800: "#292524",
          900: "#1C1917",
          950: "#0C0A09",
        },
        brand: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          400: "#60A5FA",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
          800: "#1E40AF",
          900: "#1E3A8A",
          950: "#172554",
        },
        risk: { low: "#16A34A", medium: "#EA580C", high: "#DC2626" },
        status: {
          good: "#16A34A",
          warning: "#EA580C",
          serious: "#EA580C",
          critical: "#DC2626",
        },
      },
      borderRadius: {
        DEFAULT: "6px",
        sm: "4px",
        md: "6px",
        lg: "8px",
        xl: "10px",
        "2xl": "12px",
        "3xl": "16px",
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgba(28, 25, 23, 0.04)",
        "soft-md": "0 1px 3px 0 rgba(28, 25, 23, 0.07), 0 1px 2px -1px rgba(28, 25, 23, 0.05)",
        "soft-lg": "0 4px 12px -2px rgba(28, 25, 23, 0.08), 0 2px 4px -2px rgba(28, 25, 23, 0.04)",
        "glow-brand": "0 0 0 3px rgba(37, 99, 235, 0.12)",
        card: "0 1px 2px 0 rgba(28,25,23,0.05), 0 0 0 1px rgba(28,25,23,0.04)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 240ms cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },
  plugins: [],
};
