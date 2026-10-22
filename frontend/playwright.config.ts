import { defineConfig } from "@playwright/test";
// Explicit local-only tests: never run mutation tests on the deployed demo.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 1100 },
    trace: "off",
    screenshot: "off",
  },
});
