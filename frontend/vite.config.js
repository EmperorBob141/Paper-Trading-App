import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the UI on :5173 with hot reload and forwards /api to the Python server on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1000,
    // Fixed file names so each rebuild replaces the previous files instead of piling up new ones.
    rollupOptions: { output: { entryFileNames: "assets/[name].js", chunkFileNames: "assets/[name].js", assetFileNames: "assets/[name][extname]" } },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
