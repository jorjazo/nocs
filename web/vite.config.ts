import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const backend = process.env.NOCS_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2022",
    chunkSizeWarningLimit: 600,
  },
});
