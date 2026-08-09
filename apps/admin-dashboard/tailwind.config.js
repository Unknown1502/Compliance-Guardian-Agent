/** @type {import('tailwindcss').Config} */

// The operator console shares ComplianceGuardian's visual language: same
// palette, same radii, same shadows, same type family as the customer app.
// Two design systems inside one product is a tell that nobody owns the whole
// thing — and an operator who moves between the two surfaces all day should
// not have to re-learn what a border or a warning colour means.
//
// What does NOT change is density. This is still an operations console: the
// type scale stays small, tables stay tight, and colour still carries
// severity and nothing else. Adopting the customer palette is a craft
// decision, not licence to add decoration.
//
// The token NAMES are deliberately unchanged (base/panel/raised/line/fg/
// accent/ok/warn/crit). Every section already speaks in those semantics, so
// re-skinning is a change to what they resolve to rather than a rewrite of
// a thousand lines of markup.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter var", "Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Surfaces — the customer app's editorial neutrals, not blue-grey slate.
        base: "#FAF9F6",      // page
        panel: "#FFFFFF",     // card / table surface
        raised: "#F6F7F9",    // hover, selected row
        line: "#E6E8EC",
        "line-soft": "#EFF1F4",

        // Text, darkest to lightest.
        fg: "#111827",
        "fg-dim": "#374151",
        muted: "#6B7280",
        faint: "#9CA3AF",

        // One accent, for selection and links only — never decoration.
        accent: "#2563EB",
        "accent-dim": "#1D4ED8",

        // Severity. Still the only other colour permitted anywhere, and still
        // the same values the customer app uses for risk, so "critical" looks
        // identical on both sides of the product.
        ok: "#16A34A",
        warn: "#F59E0B",
        crit: "#DC2626",
        info: "#0EA5E9",
      },
      borderRadius: {
        DEFAULT: "6px",
        sm: "4px",
        md: "6px",
        lg: "8px",
        xl: "10px",
        "2xl": "12px",
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgba(17, 24, 39, 0.04)",
        "soft-md": "0 1px 3px 0 rgba(17, 24, 39, 0.07), 0 1px 2px -1px rgba(17, 24, 39, 0.05)",
        card: "0 1px 2px 0 rgba(17,24,39,0.05), 0 0 0 1px rgba(17,24,39,0.04)",
      },
      fontSize: {
        // Nudged up ~1px against the dark scale: the same size reads smaller
        // on a light background, and this console is read for hours.
        "2xs": ["11px", { lineHeight: "1.45" }],
        xs: ["12px", { lineHeight: "1.45" }],
        sm: ["13px", { lineHeight: "1.5" }],
        base: ["14px", { lineHeight: "1.55" }],
        lg: ["15.5px", { lineHeight: "1.4" }],
        xl: ["18px", { lineHeight: "1.3" }],
        "2xl": ["22px", { lineHeight: "1.25" }],
        "3xl": ["28px", { lineHeight: "1.2" }],
      },
      transitionDuration: { DEFAULT: "150ms" },
    },
  },
  plugins: [],
};
