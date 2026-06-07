import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build into ../../pydantic_deep-served static dir so the gateway can serve the
// SPA directly (no separate web server needed in production).
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
});
