import type { Config } from "tailwindcss";

/**
 * Bhale Bullodu 1.0 — "Command Center" design system.
 * Source: Docs/stitch_extract/.../bhale_bullodu_1.0/DESIGN.md (Stitch export).
 *
 * Two token layers coexist:
 *  - Material-style semantic tokens (surface-container-*, on-surface, primary,
 *    secondary, tertiary, error, outline-variant) used by the redesigned shell.
 *  - Legacy aliases (surface.DEFAULT/raised/border, accent, status.*) kept so
 *    existing pages/components keep rendering while they are migrated.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // --- Material semantic palette (Bhale Bullodu) ---
        background: "#10131a",
        "on-background": "#e1e2ec",
        surface: {
          // NOTE: `surface` is also referenced as a color (bg-surface) AND as a
          // nested scale below. Tailwind resolves `bg-surface` to DEFAULT.
          DEFAULT: "#0f1419",
          dim: "#10131a",
          bright: "#363941",
          // legacy aliases (kept for un-migrated components)
          raised: "#1a2332",
          border: "#2d3a4f",
        },
        "surface-container-lowest": "#0b0e15",
        "surface-container-low": "#191b23",
        "surface-container": "#1d2027",
        "surface-container-high": "#272a31",
        "surface-container-highest": "#32353c",
        "surface-variant": "#32353c",
        "on-surface": "#e1e2ec",
        "on-surface-variant": "#c2c6d6",
        "inverse-surface": "#e1e2ec",
        "inverse-on-surface": "#2e3038",
        outline: "#8c909f",
        "outline-variant": "#2d3a4f",
        "surface-tint": "#adc6ff",
        primary: {
          DEFAULT: "#adc6ff",
          container: "#4d8eff",
        },
        "on-primary": "#002e6a",
        "on-primary-container": "#00285d",
        "inverse-primary": "#005ac2",
        secondary: {
          DEFAULT: "#4ae176",
          container: "#00b954",
        },
        "on-secondary": "#003915",
        "on-secondary-container": "#eafff0",
        tertiary: {
          DEFAULT: "#ffb95f",
          container: "#ca8100",
        },
        "on-tertiary": "#472a00",
        "on-tertiary-container": "#3e2400",
        error: {
          DEFAULT: "#ffb4ab",
          container: "#93000a",
        },
        "on-error": "#690005",
        "on-error-container": "#ffdad6",

        // --- Legacy aliases (do not remove until pages migrated) ---
        accent: {
          DEFAULT: "#3b82f6",
          muted: "#1e3a5f",
        },
        status: {
          pass: "#4ae176",
          warn: "#ffb95f",
          fail: "#ffb4ab",
          pending: "#ffb95f",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "JetBrains Mono", "monospace"],
      },
      fontSize: {
        "headline-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "body-md": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "label-caps": ["12px", { lineHeight: "16px", letterSpacing: "0.05em", fontWeight: "700" }],
        "data-lg": ["24px", { lineHeight: "32px", fontWeight: "500" }],
        "data-md": ["14px", { lineHeight: "20px", fontWeight: "500" }],
        "data-sm": ["12px", { lineHeight: "16px", fontWeight: "400" }],
      },
      spacing: {
        "sidebar-width": "240px",
        "topbar-height": "64px",
        gutter: "16px",
        "margin-page": "24px",
      },
      maxWidth: {
        "container-max": "1440px",
      },
      borderRadius: {
        DEFAULT: "0.5rem",
        sm: "0.25rem",
        md: "0.75rem",
        lg: "1rem",
        xl: "1.5rem",
      },
      boxShadow: {
        "kill-glow": "0 0 15px rgba(239, 68, 68, 0.4)",
      },
    },
  },
  plugins: [],
};

export default config;
