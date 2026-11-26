import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Vite server proxies API calls to FastAPI, so the browser talks to one
// origin and the backend needs no CORS. In production FastAPI serves the built files itself.
const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": backend, "/health": backend },
  },
});
