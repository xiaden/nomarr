import path from "path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: "/",
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "./src/shared"),
    },
  },
  build: {
    outDir: "../nomarr/public_html",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Proxy all /web/* and /api/* requests to backend during dev
      "/web": {
        target: "http://localhost:8081",
        changeOrigin: true,
      },
      "/api": {
        target: "http://localhost:8081",
        changeOrigin: true,
      },
      "/admin": {
        target: "http://localhost:8081",
        changeOrigin: true,
      },
    },
  },
});
