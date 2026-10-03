import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Arc items import as @/components/arc/* (registry convention). decodeURI
    // undoes %20 in paths like "Digital Brain" (URL.pathname keeps it encoded).
    alias: { "@": decodeURI(new URL("./src", import.meta.url).pathname) },
  },
  server: { port: 5173 },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    globals: true,
    // The landing is a non-secret build flag (VITE_SHOW_LANDING). These tests
    // exercise both the public landing and the console, so it must be ON here —
    // otherwise every landing route falls through to the login gate and the
    // landing tests only ever see the access gate. VITE_GOOGLE_CLIENT_ID is the
    // public OAuth client id (never a secret) so the sign-in link renders too.
    env: {
      VITE_SHOW_LANDING: "true",
      VITE_GOOGLE_CLIENT_ID: "test-client-id.apps.googleusercontent.com",
    },
  },
});
