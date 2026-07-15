/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        earth: {
          50: '#f0f7f4',
          100: '#dceee6',
          200: '#b9ddcd',
          300: '#8bc5ad',
          400: '#5aa78a',
          500: '#3a8b6e',
          600: '#2b6f58',
          700: '#245947',
          800: '#1f473a',
          900: '#1a3b31',
          950: '#0b211a',
        },
        orbit: {
          400: '#7ec8e3',
          500: '#3ba3c7',
          600: '#2a7fa0',
        },
        soil: {
          400: '#c4a574',
          500: '#a8844f',
          600: '#8a6a3d',
        },
      },
      fontFamily: {
        display: ['"Sora"', 'system-ui', 'sans-serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        panel: '0 8px 32px rgba(11, 33, 26, 0.35)',
      },
    },
  },
  plugins: [],
};
