import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
// Build langsung ke ../static (diserve backend FastAPI).
// Dev: proxy /api ke backend 8888 — edit layout langsung kelihatan, API tetap jalan.
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  base: "/",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8888",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
});
