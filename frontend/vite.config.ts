import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/celestrak': {
        target: 'https://celestrak.org',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/celestrak/, ''),
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 5000,
  },
});
