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
    // Disposable build output owned by frontend/. The Dockerfile builds the
    // bundle here and copies it into the runtime image (see dockerfile). The
    // generated tree is no longer committed under nomarr/public_html/.
    outDir: "dist",
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
