/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        sateye: {
          ink: '#070b14',
          panel: '#121a2a',
          line: '#1e293b',
          mist: '#e2e8f0',
          teal: '#2dd4bf',
          sky: '#38bdf8',
          amber: '#fbbf24',
        },
        // Keep earth aliases for any leftover widgets
        earth: {
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
        },
      },
      fontFamily: {
        sans: ['Space Grotesk', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};
