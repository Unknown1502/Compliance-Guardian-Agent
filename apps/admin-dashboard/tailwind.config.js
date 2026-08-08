/** @type {import('tailwindcss').Config} */

// Deliberately restrained. This is an operations console, not a marketing
// surface: colour carries severity and nothing else, so an operator scanning
// the screen can trust that anything coloured actually means something.
// No gradients, no decorative accents, no rounded-everything.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Neutral ramp — near-black through to readable foreground.
        base: "#0D1117",
        panel: "#161B22",
        raised: "#1C2128",
        line: "#30363D",
        "line-soft": "#21262D",
        fg: "#E6EDF3",
        "fg-dim": "#B0B8C1",
        muted: "#8B949E",
        faint: "#6E7681",

        // One accent, used for selection and links only — never decoration.
        accent: "#388BFD",
        "accent-dim": "#1F6FEB",

        // Severity. The only other colour permitted anywhere.
        ok: "#3FB950",
        warn: "#D29922",
        crit: "#F85149",
        info: "#58A6FF",
      },
      borderRadius: {
        DEFAULT: "4px",
        sm: "3px",
        md: "4px",
        lg: "6px",
        xl: "6px",
      },
      fontSize: {
        "2xs": ["10.5px", { lineHeight: "1.4" }],
        xs: ["11.5px", { lineHeight: "1.45" }],
        sm: ["12.5px", { lineHeight: "1.5" }],
        base: ["13.5px", { lineHeight: "1.55" }],
        lg: ["15px", { lineHeight: "1.4" }],
        xl: ["18px", { lineHeight: "1.3" }],
        "2xl": ["22px", { lineHeight: "1.25" }],
        "3xl": ["28px", { lineHeight: "1.2" }],
      },
    },
  },
  plugins: [],
};
