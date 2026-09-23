import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the API lives on the FastAPI server; the proxy keeps the browser same-origin.
// In production set VITE_API_URL to the backend's public URL instead.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/health": { target: backend, changeOrigin: true },
    },
  },
});
