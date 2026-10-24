import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthApiError } from "./auth";
import type { AuthApi, AuthUser, LoginResult } from "./auth";
import { createSessionStore } from "./session";

const CLIENT: AuthUser = { id: "8bf66294-daf8-42fa-a167-50a3a43b7b66", loginName: "demo_client_01", role: "CLIENT" };
const TOKEN = "header.payload.signature";

function fakeApi(overrides: Partial<AuthApi> = {}) {
  return {
    login: vi.fn<AuthApi["login"]>().mockResolvedValue({ accessToken: TOKEN, expiresInSeconds: 900, user: CLIENT }),
    me: vi.fn<AuthApi["me"]>().mockResolvedValue(CLIENT),
    logout: vi.fn<AuthApi["logout"]>().mockResolvedValue(undefined),
    ...overrides,
  };
}

afterEach(() => vi.useRealTimers());

describe("volatile session store", () => {
  it("signs in through Login then /me and exposes the token only in memory", async () => {
    const api = fakeApi();
    const store = createSessionStore(api);
    expect(store.getState()).toEqual({ status: "signed-out" });
    expect(await store.signIn("demo_client_01", "pw")).toEqual(CLIENT);
    expect(api.me).toHaveBeenCalledWith(TOKEN, undefined);
    expect(store.getState()).toEqual({ status: "signed-in", user: CLIENT });
    expect(store.getAccessToken()).toBe(TOKEN);
    // P1C-AC-07: nothing persisted anywhere the browser keeps across a reload.
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
  });

  it("starts signed out after a reload (a new store)", async () => {
    await createSessionStore(fakeApi()).signIn("demo_client_01", "pw");
    const reloaded = createSessionStore(fakeApi());
    expect(reloaded.getState()).toEqual({ status: "signed-out" });
    expect(reloaded.getAccessToken()).toBeNull();
  });

  it("keeps no token when /me rejects it or names another user, and logs the issued token out", async () => {
    const rejectedApi = fakeApi({ me: vi.fn().mockRejectedValue(new AuthApiError("UNAUTHORIZED", 401)) });
    const rejected = createSessionStore(rejectedApi);
    // Not "session expired": the user never had a session.
    await expect(rejected.signIn("a", "b")).rejects.toMatchObject({ code: "SIGN_IN_UNCONFIRMED", status: 401 });
    expect(rejected.getAccessToken()).toBeNull();
    expect(rejected.getState().status).toBe("signed-out");
    expect(rejectedApi.logout).toHaveBeenCalledWith(TOKEN);

    const other = { ...CLIENT, id: "0cbce840-2b5b-4eb8-83dc-968e5d47871b" };
    const mismatchApi = fakeApi({ me: vi.fn().mockResolvedValue(other) });
    const mismatch = createSessionStore(mismatchApi);
    await expect(mismatch.signIn("a", "b")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(mismatch.getAccessToken()).toBeNull();
    expect(mismatchApi.logout).toHaveBeenCalledWith(TOKEN);
  });

  it("counts the lifetime from before Login was sent", async () => {
    vi.useFakeTimers();
    const api = fakeApi({
      login: vi.fn(() => new Promise<LoginResult>((resolve) => {
        setTimeout(() => resolve({ accessToken: TOKEN, expiresInSeconds: 900, user: CLIENT }), 5_000);
      })),
    });
    const store = createSessionStore(api);
    const pending = store.signIn("a", "b");
    await vi.advanceTimersByTimeAsync(5_000);
    await pending;
    await vi.advanceTimersByTimeAsync(894_999);
    expect(store.getState().status).toBe("signed-in");
    await vi.advanceTimersByTimeAsync(1);
    expect(store.getState()).toEqual({ status: "signed-out", reason: "expired" });
  });

  it("never publishes a session whose deadline passed during /me (P2-02)", async () => {
    let now = 1_000_000;
    const api = fakeApi({
      me: vi.fn(async () => {
        now += 900_000; // device slept: exactly the conservative deadline
        return CLIENT;
      }),
    });
    const store = createSessionStore(api, { now: () => now, setTimeout: () => 0, clearTimeout: () => undefined });
    const seen: string[] = [];
    store.subscribe(() => seen.push(store.getState().status));
    await expect(store.signIn("a", "b")).rejects.toMatchObject({ code: "SIGN_IN_EXPIRED" });
    expect(seen).not.toContain("signed-in");
    expect(store.getState().status).toBe("signed-out");
    expect(store.getAccessToken()).toBeNull();
    expect(api.logout).toHaveBeenCalledWith(TOKEN); // the issued token is discarded best-effort
  });

  it("still publishes when /me finishes 1 ms before the deadline", async () => {
    let now = 1_000_000;
    const api = fakeApi({ me: vi.fn(async () => { now += 899_999; return CLIENT; }) });
    const store = createSessionStore(api, { now: () => now, setTimeout: () => 0, clearTimeout: () => undefined });
    await store.signIn("a", "b");
    expect(store.getAccessToken()).toBe(TOKEN);
    now += 1;
    expect(store.getAccessToken()).toBeNull();
  });

  it("checks a superseded attempt before the deadline", async () => {
    let now = 1_000_000;
    let store!: ReturnType<typeof createSessionStore>;
    const api = fakeApi({
      me: vi.fn(async () => {
        now += 900_000;
        await store.signOut();
        return CLIENT;
      }),
    });
    store = createSessionStore(api, { now: () => now, setTimeout: () => 0, clearTimeout: () => undefined });
    await expect(store.signIn("a", "b")).rejects.toMatchObject({ name: "AbortError" });
    expect(store.getAccessToken()).toBeNull();
  });

  it("refuses the token after the deadline even if the timer never ran (device sleep)", async () => {
    let now = 1_000_000;
    const store = createSessionStore(fakeApi(), { now: () => now, setTimeout: () => 0, clearTimeout: () => undefined });
    await store.signIn("a", "b");
    now += 899_999;
    expect(store.getAccessToken()).toBe(TOKEN);
    now += 1;
    expect(store.getAccessToken()).toBeNull();
    expect(store.getState()).toEqual({ status: "signed-out", reason: "expired" });
  });

  it("returns to Login when the 900-second lifetime ends", async () => {
    vi.useFakeTimers();
    const store = createSessionStore(fakeApi());
    await store.signIn("a", "b");
    vi.advanceTimersByTime(899_999);
    expect(store.getState().status).toBe("signed-in");
    vi.advanceTimersByTime(1);
    expect(store.getState()).toEqual({ status: "signed-out", reason: "expired" });
    expect(store.getAccessToken()).toBeNull();
  });

  it("forgets the token before calling Logout, even if Logout fails", async () => {
    let tokenDuringCall: string | null = "unset";
    const store = createSessionStore(fakeApi({
      logout: vi.fn(async () => {
        tokenDuringCall = store.getAccessToken();
        throw new AuthApiError("NETWORK_ERROR", 0);
      }),
    }));
    await store.signIn("a", "b");
    await store.signOut();
    expect(tokenDuringCall).toBeNull();
    expect(store.getState()).toEqual({ status: "signed-out", reason: "signed-out" });
  });

  it("calls Logout with the issued token and cancels the expiry timer", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    const store = createSessionStore(api);
    await store.signIn("a", "b");
    await store.signOut();
    expect(api.logout).toHaveBeenCalledWith(TOKEN);
    vi.advanceTimersByTime(900_000);
    expect(store.getState()).toEqual({ status: "signed-out", reason: "signed-out" });
  });

  it("clears the session when an API client reports 401", async () => {
    const store = createSessionStore(fakeApi());
    store.handleUnauthorized(TOKEN); // no session: no change
    expect(store.getState()).toEqual({ status: "signed-out" });
    await store.signIn("a", "b");
    store.handleUnauthorized(TOKEN);
    expect(store.getState()).toEqual({ status: "signed-out", reason: "unauthorized" });
    expect(store.getAccessToken()).toBeNull();
  });

  it("ignores a late 401 for an older token after signing in again", async () => {
    const api = fakeApi();
    const store = createSessionStore(api);
    await store.signIn("a", "b");
    const tokenA = store.getAccessToken()!;
    vi.mocked(api.login).mockResolvedValueOnce({ accessToken: "token.b.value", expiresInSeconds: 900, user: CLIENT });
    await store.signIn("a", "b");
    store.handleUnauthorized(tokenA);
    expect(store.getState()).toEqual({ status: "signed-in", user: CLIENT });
    expect(store.getAccessToken()).toBe("token.b.value");
  });

  it("does not let a slow sign-in finish after sign-out", async () => {
    let release!: () => void;
    const api = fakeApi({ me: vi.fn(() => new Promise<AuthUser>((resolve) => { release = () => resolve(CLIENT); })) });
    const store = createSessionStore(api);
    const pending = store.signIn("a", "b");
    await vi.waitFor(() => expect(api.me).toHaveBeenCalled());
    await store.signOut();
    release();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(store.getAccessToken()).toBeNull();
    expect(api.logout).toHaveBeenCalledWith(TOKEN); // the discarded token is still logged out
  });

  it("stops a sign-in whose signal was aborted", async () => {
    const controller = new AbortController();
    const api = fakeApi({ me: vi.fn(async () => { controller.abort(); return CLIENT; }) });
    const store = createSessionStore(api);
    await expect(store.signIn("a", "b", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(store.getAccessToken()).toBeNull();
    expect(api.login).toHaveBeenCalledWith("a", "b", controller.signal);
  });

  it("notifies subscribers and stops after unsubscribe", async () => {
    const store = createSessionStore(fakeApi());
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    await store.signIn("a", "b");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    await store.signOut();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
