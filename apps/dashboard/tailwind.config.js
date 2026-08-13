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
      fontSize: {
        hero: ["60px", { lineHeight: "1.08", letterSpacing: "-0.02em" }],
        section: ["40px", { lineHeight: "1.15", letterSpacing: "-0.015em" }],
        heading: ["30px", { lineHeight: "1.25", letterSpacing: "-0.01em" }],
        body: ["18px", { lineHeight: "1.6" }],
        caption: ["14px", { lineHeight: "1.5" }],
      },
      colors: {
        // Editorial enterprise-trust palette — no blue-grey slate default.
        //
        // Semantic tokens resolve to CSS variables declared in index.css, so
        // one class is correct in both themes. Fixed hex here is what made
        // bg-surface stay #FFFFFF in dark mode.
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        "ink-2": "rgb(var(--ink-2) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        sidebar: "rgb(var(--sidebar) / <alpha-value>)",
        input: "rgb(var(--input) / <alpha-value>)",
        slate: {
          50: "#FAF9F6",
          100: "#F6F7F9",
          200: "#E6E8EC",
          300: "#D6D9DE",
          400: "#9CA3AF",
          500: "#6B7280",
          600: "#4B5563",
          700: "#374151",
          800: "#1F2937",
          900: "#111827",
          950: "#0B0F17",
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
        audit: "#0EA5E9",
        info: "rgb(var(--info) / <alpha-value>)",
        // Risk and status carry meaning, so they have to stay legible in both
        // themes rather than keeping one fixed value. The light-theme greens
        // and reds fail contrast on charcoal; the variables lift them.
        risk: {
          low: "rgb(var(--good) / <alpha-value>)",
          medium: "rgb(var(--warning) / <alpha-value>)",
          high: "rgb(var(--critical) / <alpha-value>)",
        },
        status: {
          good: "rgb(var(--good) / <alpha-value>)",
          warning: "rgb(var(--warning) / <alpha-value>)",
          serious: "rgb(var(--serious) / <alpha-value>)",
          critical: "rgb(var(--critical) / <alpha-value>)",
        },
      },
      maxWidth: { container: "1280px" },
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
        soft: "0 1px 2px 0 rgba(17, 24, 39, 0.04)",
        "soft-md": "0 1px 3px 0 rgba(17, 24, 39, 0.07), 0 1px 2px -1px rgba(17, 24, 39, 0.05)",
        "soft-lg": "0 4px 12px -2px rgba(17, 24, 39, 0.08), 0 2px 4px -2px rgba(17, 24, 39, 0.04)",
        "glow-brand": "0 0 0 3px rgba(37, 99, 235, 0.12)",
        card: "0 1px 2px 0 rgba(17,24,39,0.05), 0 0 0 1px rgba(17,24,39,0.04)",
      },
      transitionDuration: { DEFAULT: "150ms" },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 150ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 150ms ease-out both",
      },
    },
  },
  plugins: [],
};
