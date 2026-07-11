/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Same-origin in production (served by the brain). In dev, proxy API calls to the local brain so the
// browser talks to one origin and no CORS is needed.
const API_PATHS = ["/dashboard", "/query", "/chat", "/state", "/memory", "/knowledge", "/approvals"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: "http://localhost:8000", changeOrigin: true }]),
    ),
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
