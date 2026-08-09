import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * The backend (FastAPI) listens on :8000. In dev we proxy `/api` and `/ws` to it so the
 * browser only ever talks to the Vite origin — no CORS configuration is needed anywhere.
 * In production the FastAPI app serves the built bundle from the same origin, so the same
 * relative paths keep working unchanged.
 */
// 127.0.0.1, not `localhost`: uvicorn binds IPv4 only (server/deps.py defaults the host
// to 0.0.0.0), while Node resolves `localhost` to ::1 first on Windows. The connection is
// then refused against a server that is demonstrably running.
const BACKEND_HTTP = 'http://127.0.0.1:8000';
const BACKEND_WS = 'ws://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bound to all interfaces: the instructor uses this from an iPad on the LAN.
    host: true,
    proxy: {
      '/api': { target: BACKEND_HTTP, changeOrigin: true },
      '/ws': { target: BACKEND_WS, ws: true, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    // No implicit globals: every test imports what it uses. Keeps tsconfig honest.
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
