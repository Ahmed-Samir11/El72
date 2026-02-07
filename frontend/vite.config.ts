import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/tools': 'http://localhost:8080',
      '/session': 'http://localhost:8080',
      '/ws': { target: 'ws://localhost:8080', ws: true },
      '/health': 'http://localhost:8080',
    },
  },
});
