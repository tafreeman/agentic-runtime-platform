/** @type {import('tailwindcss').Config} */
// Color tokens are defined as space-separated RGB triplets (e.g. "217 119 87")
// in tokens.css, so Tailwind's `/<alpha-value>` opacity modifier works.
const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        b: {
          bg0: c("b-bg0"),
          bg1: c("b-bg1"),
          bg2: c("b-bg2"),
          bg3: c("b-bg3"),
          line: c("b-line"),
          "line-soft": c("b-line-soft"),
          text: c("b-text"),
          "text-mid": c("b-text-mid"),
          "text-dim": c("b-text-dim"),
          "text-faint": c("b-text-faint"),
          clay: c("b-clay"),
          "clay-soft": "var(--b-clay-soft)",
          green: c("b-green"),
          amber: c("b-amber"),
          blue: c("b-blue"),
          red: c("b-red"),
          purple: c("b-purple"),
        },
        surface: {
          0: c("b-bg0"),
          1: c("b-bg1"),
          2: c("b-bg2"),
          3: c("b-bg3"),
        },
        accent: {
          blue: c("b-blue"),
          green: c("b-green"),
          red: c("b-red"),
          amber: c("b-amber"),
          purple: c("b-purple"),
          clay: c("b-clay"),
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Geist Mono", "ui-monospace", "monospace"],
        heading: ["Geist", "-apple-system", "system-ui", "sans-serif"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "dash-flow": "b-dash-flow 0.5s linear infinite",
        "b-pulse": "b-pulse-slow 2s ease-in-out infinite",
        "b-blink": "b-blink 1s step-end infinite",
      },
      keyframes: {
        "b-dash-flow": {
          to: { "stroke-dashoffset": "-20" },
        },
        "b-pulse-slow": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "b-blink": {
          "0%, 50%": { opacity: "1" },
          "51%, 100%": { opacity: "0" },
        },
      },
    },
  },
  plugins: [],
};
