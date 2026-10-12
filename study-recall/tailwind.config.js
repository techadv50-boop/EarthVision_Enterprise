/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        paper: "var(--bg)",
        ink: "var(--ink)",
        card: "var(--card)",
        line: "var(--line)",
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        muted: "var(--muted)",
        danger: "var(--danger)",
        warn: "var(--warn)",
        ok: "var(--ok)",
      },
      boxShadow: {
        card: "0 1px 2px rgba(28, 36, 48, 0.06), 0 12px 32px rgba(28, 36, 48, 0.06)",
      },
    },
  },
  plugins: [],
};
