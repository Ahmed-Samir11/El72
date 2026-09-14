import { defineConfig } from 'vite';

// Landing page serves on port 3000 (demo checklist: localhost:3000).
export default defineConfig({
  server: { port: 3000, host: true },
  preview: { port: 3000, host: true },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
});
