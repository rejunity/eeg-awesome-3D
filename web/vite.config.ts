import { defineConfig } from "vite";

// During `npm run dev`, proxy API + WebSocket calls to the Python backend so
// the frontend can be developed live against real (or synthetic) data.
const BACKEND = "http://127.0.0.1:8765";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
