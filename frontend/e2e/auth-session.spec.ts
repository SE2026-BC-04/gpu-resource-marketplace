// GPU-003-E2 — P1C-AC-07 browser checks for Auth and the shared session.
//
// Runs against a production frontend preview, the real API process (native gpm_api_app login)
// and disposable PostgreSQL accounts created by backend/tests/test_auth_session_browser_e2e.py.
// The general Worker -> Listing -> Client -> Job journey is covered by phase1-runtime.spec.ts;
// this file checks what that journey does not: where the token goes, what survives a reload,
// and how the UI reacts when the server stops accepting a session.
//
// Secrets never reach assertion messages: every check on a token or password compares
// booleans, so a failure report cannot print them.
import { existsSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";
import type { BrowserContext, Page, Request } from "@playwright/test";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must be provided by the PostgreSQL E2E harness.`);
  return value;
}

const apiUrl = required("AUTH_E2E_API_URL");
const clientLogin = required("AUTH_E2E_CLIENT_LOGIN");
const workerLogin = required("AUTH_E2E_WORKER_LOGIN");
const disabledLogin = required("AUTH_E2E_DISABLE_LOGIN");
const password = required("AUTH_E2E_PASSWORD");
const controlDir = required("AUTH_E2E_CONTROL_DIR");

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SIGNED_OUT_NOTICE = "Bạn đã đăng xuất.";
const UNAUTHORIZED_NOTICE = "Phiên đăng nhập không còn hợp lệ. Vui lòng đăng nhập lại.";
const EXPIRED_NOTICE = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";

// Each test uses its own browser context; the config runs them one at a time, in file order.

interface SeenRequest {
  method: string;
  path: string;
  authorization: string | undefined;
  order: number;
}

/** Records every API request (with its Authorization header) and every console/page error text. */
class Recorder {
  readonly requests: SeenRequest[] = [];
  readonly consoleTexts: string[] = [];
  private pending: Promise<void>[] = [];
  private counter = 0;

  attach(context: BrowserContext): void {
    context.on("request", (request) => this.pending.push(this.record(request)));
    context.on("page", (page) => this.watch(page));
    context.pages().forEach((page) => this.watch(page));
  }

  watch(page: Page): void {
    page.on("console", (message) => this.consoleTexts.push(message.text()));
    page.on("pageerror", (error) => this.consoleTexts.push(`${error.name}: ${error.message}`));
  }

  private async record(request: Request): Promise<void> {
    const url = new URL(request.url());
    if (!request.url().startsWith(apiUrl)) return;
    const order = ++this.counter;
    // allHeaders() includes security headers such as Authorization; headers() may not.
    const headers = await request.allHeaders();
    this.requests.push({ method: request.method(), path: url.pathname, authorization: headers.authorization, order });
  }

  /** Marks "now"; later requests are those recorded after this point. */
  async mark(): Promise<number> {
    await this.settle();
    return this.counter;
  }

  async after(mark: number): Promise<SeenRequest[]> {
    await this.settle();
    return this.requests.filter((request) => request.order > mark).sort((a, b) => a.order - b.order);
  }

  async settle(): Promise<void> {
    const waiting = this.pending;
    this.pending = [];
    await Promise.all(waiting);
  }
}

async function signIn(page: Page, loginName: string, secret: string): Promise<string> {
  await expect(page.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();
  await page.getByLabel("Tên đăng nhập").fill(loginName);
  await page.getByLabel("Mật khẩu").fill(secret);
  const loginResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/auth/login",
  );
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  const response = await loginResponse;
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store"); // E2-14
  const body = await response.json() as { access_token?: unknown };
  expect(typeof body.access_token).toBe("string");
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toContainText(loginName);
  return body.access_token as string;
}

/** Everything the page could persist or expose, gathered from inside the page (E2-06). */
async function persistedState(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const entries = (storage: Storage) =>
      Array.from({ length: storage.length }, (_, index) => {
        const key = storage.key(index) ?? "";
        return `${key}=${storage.getItem(key) ?? ""}`;
      });
    const databases = typeof indexedDB.databases === "function" ? await indexedDB.databases() : [];
    const cacheNames = "caches" in window ? await caches.keys() : [];
    const cached: string[] = [];
    for (const name of cacheNames) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) {
        const response = await cache.match(request);
        cached.push(request.url, response ? await response.text() : "");
      }
    }
    const workers = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistrations() : [];
    return JSON.stringify({
      local: entries(localStorage),
      session: entries(sessionStorage),
      cookie: document.cookie,
      indexedDB: databases.map((database) => database.name),
      caches: cached,
      serviceWorkers: workers.map((worker) => worker.scope),
      url: location.href,
      history: JSON.stringify(history.state),
    });
  });
}

function expectNoSecret(haystack: string, token: string, where: string): void {
  expect(haystack.includes(token), `${where} must not contain the access token`).toBe(false);
  expect(haystack.includes(password), `${where} must not contain the password`).toBe(false);
}

function authOf(requests: SeenRequest[], method: string, path: string): (string | undefined)[] {
  return requests.filter((request) => request.method === method && request.path === path).map((r) => r.authorization);
}

test("E2-01/03/06/07/08/14: Login, Bearer use, storage, console and Logout", async ({ context, page }) => {
  const recorder = new Recorder();
  recorder.attach(context);
  await page.goto("/");

  const beforeLogin = await recorder.mark();
  const token = await signIn(page, clientLogin, password);

  // E2-01: role from the database is shown; exactly one Login, then /me confirms it.
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toContainText("Client — thuê GPU");
  await expect(page.getByRole("heading", { name: "My Jobs" })).toBeVisible();
  const afterLogin = await recorder.after(beforeLogin);
  expect(authOf(afterLogin, "POST", "/api/v1/auth/login")).toHaveLength(1);
  const loginIndex = afterLogin.findIndex((r) => r.path === "/api/v1/auth/login");
  const meIndex = afterLogin.findIndex((r) => r.path === "/api/v1/auth/me");
  expect(meIndex).toBeGreaterThan(loginIndex);

  // E2-03: no Authorization on Login; /me, Listings and Jobs all carry this Login's token.
  expect(authOf(afterLogin, "POST", "/api/v1/auth/login")[0]).toBeUndefined();
  const bearer = `Bearer ${token}`;
  const protectedCalls = afterLogin.filter((r) => r.path !== "/api/v1/auth/login");
  expect(protectedCalls.some((r) => r.path === "/api/v1/auth/me")).toBe(true);
  expect(protectedCalls.some((r) => r.path.startsWith("/api/v1/gpu-listings"))).toBe(true);
  expect(protectedCalls.some((r) => r.path.startsWith("/api/v1/jobs"))).toBe(true);
  expect(protectedCalls.every((r) => r.authorization === bearer), "every protected call uses the Login token").toBe(true);

  // E2-06 while signed in.
  expectNoSecret(await persistedState(page), token, "browser storage while signed in");

  // E2-14 on /me.
  const meResponse = await page.request.get(`${apiUrl}/api/v1/auth/me`, { headers: { Authorization: bearer } });
  expect(meResponse.status()).toBe(200);
  expect(meResponse.headers()["cache-control"]).toBe("no-store");

  // E2-08: Logout sends the token once, returns 204 and the UI forgets the session.
  const logoutResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/auth/logout",
  );
  const beforeLogout = await recorder.mark();
  await page.getByRole("button", { name: "Đăng xuất" }).click();
  const logout = await logoutResponse;
  expect(logout.status()).toBe(204);
  expect(logout.headers()["cache-control"]).toBe("no-store");
  await expect(page.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: SIGNED_OUT_NOTICE })).toBeVisible();
  await expect(page.getByRole("heading", { name: "My Jobs" })).toHaveCount(0);
  const afterLogout = await recorder.after(beforeLogout);
  expect(authOf(afterLogout, "POST", "/api/v1/auth/logout").every((value) => value === bearer)).toBe(true);
  expect(afterLogout.filter((r) => r.path !== "/api/v1/auth/logout").every((r) => r.authorization === undefined)).toBe(true);

  // E2-06 after Logout.
  expectNoSecret(await persistedState(page), token, "browser storage after Logout");

  // E2-08 (contract §4.4): Logout does not revoke server-side; the copied token still works until exp.
  const stillValid = await page.request.get(`${apiUrl}/api/v1/auth/me`, { headers: { Authorization: bearer } });
  expect(stillValid.status()).toBe(200);

  // E2-07: nothing logged by the page contains the token or the password.
  expectNoSecret(recorder.consoleTexts.join("\n"), token, "console and page errors");
});

test("E2-04/05: reload and a new tab do not restore the session", async ({ context, page }) => {
  const recorder = new Recorder();
  recorder.attach(context);
  await page.goto("/");
  const token = await signIn(page, clientLogin, password);

  // E2-05: the token lives only in this page's JavaScript; another tab starts signed out.
  const otherTab = await context.newPage();
  await otherTab.goto("/");
  await expect(otherTab.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();
  await expect(otherTab.getByRole("region", { name: "Tài khoản hiện tại" })).toHaveCount(0);
  await otherTab.close();

  // E2-04: reload returns to Login and no request is ever sent with a token again.
  const beforeReload = await recorder.mark();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Đăng nhập" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  const afterReload = await recorder.after(beforeReload);
  expect(afterReload.every((r) => r.authorization === undefined), "no request carries a token after reload").toBe(true);
  expectNoSecret(await persistedState(page), token, "browser storage after reload");
  expectNoSecret(recorder.consoleTexts.join("\n"), token, "console and page errors");
});

test("E2-09/14: the request ID is readable by the frontend origin through browser CORS", async ({ page }) => {
  await page.goto("/");
  // A real cross-origin fetch from the frontend origin: Chromium enforces CORS here, unlike TestClient.
  const result = await page.evaluate(async ({ api, login }) => {
    const response = await fetch(`${api}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ login_name: login, password: "definitely-not-the-password" }),
      credentials: "omit",
      cache: "no-store",
    });
    const body = await response.json() as { error?: { code?: string; request_id?: string } };
    return {
      status: response.status,
      header: response.headers.get("X-Request-ID"),
      cacheControl: response.headers.get("Cache-Control"),
      code: body.error?.code,
      bodyRequestId: body.error?.request_id,
    };
  }, { api: apiUrl, login: clientLogin });

  expect(result.status).toBe(401);
  expect(result.code).toBe("INVALID_CREDENTIALS");
  expect(result.header).toMatch(UUID);
  expect(result.header).toBe(result.bodyRequestId);
  expect(result.cacheControl).toBe("no-store");
});

test("E2-11: client-side expiry returns to Login without sending the old token", async ({ context, page }) => {
  await page.clock.install();
  const recorder = new Recorder();
  recorder.attach(context);
  await page.goto("/");
  await signIn(page, clientLogin, password);
  await expect(page.getByRole("heading", { name: "My Jobs" })).toBeVisible();

  const beforeExpiry = await recorder.mark();
  await page.clock.fastForward("15:01"); // 901 s, past the 900 s token lifetime
  await expect(page.getByRole("status").filter({ hasText: EXPIRED_NOTICE })).toBeVisible();
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toHaveCount(0);
  const afterExpiry = await recorder.after(beforeExpiry);
  expect(afterExpiry.every((r) => r.authorization === undefined), "no request uses the expired token").toBe(true);
});

test("E2-12: switching accounts never sends the previous account's token", async ({ context, page }) => {
  const recorder = new Recorder();
  recorder.attach(context);
  await page.goto("/");
  const workerToken = await signIn(page, workerLogin, password);
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toContainText("Worker — cho thuê GPU");
  await page.getByRole("button", { name: "Đăng xuất" }).click();

  const beforeClient = await recorder.mark();
  const clientToken = await signIn(page, clientLogin, password);
  await expect(page.getByRole("heading", { name: "My Jobs" })).toBeVisible();
  await page.waitForLoadState("networkidle");

  expect(clientToken === workerToken).toBe(false);
  const afterClient = await recorder.after(beforeClient);
  const usesWorkerToken = afterClient.some((r) => r.authorization === `Bearer ${workerToken}`);
  expect(usesWorkerToken, "no request after the switch uses the Worker token").toBe(false);
  expect(
    afterClient.filter((r) => r.authorization !== undefined).every((r) => r.authorization === `Bearer ${clientToken}`),
  ).toBe(true);
  const account = page.getByRole("region", { name: "Tài khoản hiện tại" });
  await expect(account).toContainText(clientLogin);
  await expect(account).not.toContainText(workerLogin);
  await expect(page.getByText("Worker — cho thuê GPU")).toHaveCount(0);
});

test("E2-10/02: an account disabled mid-session is signed out; failures look identical", async ({ context, page }) => {
  const recorder = new Recorder();
  recorder.attach(context);
  await page.goto("/");
  const token = await signIn(page, disabledLogin, password);
  await expect(page.getByRole("heading", { name: "My Jobs" })).toBeVisible();

  // Ask the harness to set this account DISABLED in PostgreSQL (owner connection), then wait.
  writeFileSync(join(controlDir, "disable.request"), "1", "utf8");
  await expect.poll(() => existsSync(join(controlDir, "disable.done")), { timeout: 20_000 }).toBe(true);

  // E2-10: the next protected call is rejected (401) and the UI returns to Login.
  const listingsResponse = page.waitForResponse((response) =>
    response.request().method() === "GET" && new URL(response.url()).pathname === "/api/v1/gpu-listings",
  );
  await page.getByRole("button", { name: "Tải lại", exact: true }).click();
  expect((await listingsResponse).status()).toBe(401);
  await expect(page.getByRole("status").filter({ hasText: UNAUTHORIZED_NOTICE })).toBeVisible();
  await expect(page.getByRole("region", { name: "Tài khoản hiện tại" })).toHaveCount(0);
  await expect(page.getByText(/DISABLED|vô hiệu|bị khóa/i)).toHaveCount(0);

  // E2-02: wrong password, unknown account and the disabled account show the same message.
  async function failedSignIn(loginName: string, secret: string): Promise<string> {
    await page.getByLabel("Tên đăng nhập").fill(loginName);
    await page.getByLabel("Mật khẩu").fill(secret);
    const response = page.waitForResponse((r) =>
      r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/auth/login",
    );
    await page.getByRole("button", { name: "Đăng nhập" }).click();
    const failed = await response;
    expect(failed.status()).toBe(401);
    expect(failed.headers()["cache-control"]).toBe("no-store");
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(page.getByLabel("Mật khẩu")).toHaveValue("");
    return (await alert.textContent()) ?? "";
  }

  const wrongPassword = await failedSignIn(clientLogin, `${password}-wrong`);
  const unknownAccount = await failedSignIn(`no-such-${clientLogin}`, password);
  const disabledAccount = await failedSignIn(disabledLogin, password);
  expect(wrongPassword.length).toBeGreaterThan(0);
  expect(unknownAccount).toBe(wrongPassword);
  expect(disabledAccount).toBe(wrongPassword);

  expectNoSecret(recorder.consoleTexts.join("\n"), token, "console and page errors");
});
