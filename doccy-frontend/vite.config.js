import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // API endpoints — prefix with /api/ to avoid shadowing React Router paths
      "/patients": "http://localhost:8000",
      "/session/start":  "http://localhost:8000",
      "/session/reset":  "http://localhost:8000",
      "/session/end":    "http://localhost:8000",
      "/session/status": "http://localhost:8000",
      // WebSocket
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
