import { defineConfig } from "@playwright/test";

// GPU-003-E2 (P1C-AC-07). Started only by backend/tests/test_auth_session_browser_e2e.py, which
// provides a production frontend preview, a real API and disposable PostgreSQL accounts.
const baseURL = process.env.AUTH_E2E_BASE_URL;
if (!baseURL) {
  throw new Error("AUTH_E2E_BASE_URL must point to the running production frontend preview.");
}

export default defineConfig({
  testDir: ".",
  testMatch: "auth-session.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  outputDir: "../.playwright-results/auth",
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    // Traces, screenshots and videos would store the test password and live tokens on disk.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
