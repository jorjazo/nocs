import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// In development the API runs separately (uv run nocsd); proxy it so the app
// uses same-origin URLs exactly as when nocsd serves the built files.
const api = process.env.NOCS_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      "/api": { target: api, ws: true },
    },
  },
});
