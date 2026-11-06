import { defineConfig } from "@playwright/test";

const baseURL = process.env.PHASE1_E2E_BASE_URL;
if (!baseURL) {
  throw new Error("PHASE1_E2E_BASE_URL must point to the running production frontend preview.");
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "phase1-runtime.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  outputDir: ".playwright-results",
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
