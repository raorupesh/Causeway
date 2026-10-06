import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const API = process.env.CAUSEWAY_API ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': API,
      '/demo': API,
      '/health': API,
    },
  },
});
