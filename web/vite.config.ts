import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    globals: true,
    // The landing is a non-secret build flag (VITE_SHOW_LANDING). These tests
    // exercise both the public landing and the console, so it must be ON here —
    // otherwise every landing route falls through to the login gate and the
    // landing tests only ever see the access gate.
    env: { VITE_SHOW_LANDING: "true" },
  },
});
