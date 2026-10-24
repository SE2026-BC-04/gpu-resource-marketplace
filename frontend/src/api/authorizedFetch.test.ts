import { describe, expect, it, vi } from "vitest";

import type { AuthApi, AuthUser } from "./auth";
import { createAuthorizedFetch } from "./authorizedFetch";
import { createSessionStore } from "./session";

const CLIENT: AuthUser = { id: "8bf66294-daf8-42fa-a167-50a3a43b7b66", loginName: "demo_client_01", role: "CLIENT" };

async function signedIn(...tokens: string[]) {
  const login = vi.fn<AuthApi["login"]>();
  tokens.forEach((accessToken) => login.mockResolvedValueOnce({ accessToken, expiresInSeconds: 900, user: CLIENT }));
  const session = createSessionStore({ login, me: vi.fn().mockResolvedValue(CLIENT), logout: vi.fn().mockResolvedValue(undefined) });
  await session.signIn("a", "b");
  return session;
}

describe("shared Bearer client", () => {
  it("sends the current token without cookies and keeps caller headers", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("[]", { status: 200 }));
    const send = createAuthorizedFetch(await signedIn("token.a"), fetcher);
    await send("/api/v1/gpu-listings", { headers: { Accept: "application/json" } });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/gpu-listings");
    expect(init).toMatchObject({ credentials: "omit", cache: "no-store" });
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer token.a");
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("does not send anything without a session", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const session = createSessionStore({ login: vi.fn(), me: vi.fn(), logout: vi.fn() });
    await expect(createAuthorizedFetch(session, fetcher)("/api/v1/jobs")).rejects.toMatchObject({ code: "UNAUTHORIZED" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("ends the session on 401 for the current token", async () => {
    const session = await signedIn("token.a");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 401 }));
    const response = await createAuthorizedFetch(session, fetcher)("/api/v1/jobs");
    expect(response.status).toBe(401);
    expect(session.getState()).toEqual({ status: "signed-out", reason: "unauthorized" });
  });

  it("keeps a newer session when a 401 for the old token arrives late", async () => {
    const session = await signedIn("token.a", "token.b");
    let reply!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>((resolve) => { reply = resolve; }));
    const pending = createAuthorizedFetch(session, fetcher)("/api/v1/jobs");
    await session.signIn("a", "b"); // signed in again: token B
    reply(new Response(null, { status: 401 }));
    await pending;
    expect(session.getState().status).toBe("signed-in");
    expect(session.getAccessToken()).toBe("token.b");
  });

  it("does not treat 403 as a lost session", async () => {
    const session = await signedIn("token.a");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 403 }));
    await createAuthorizedFetch(session, fetcher)("/api/v1/jobs");
    expect(session.getState().status).toBe("signed-in");
  });

  it("maps network failures, rethrows aborts and rejects absolute URLs", async () => {
    const session = await signedIn("token.a");
    const offline = createAuthorizedFetch(session, vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(offline("/api/v1/jobs")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    const abort = new DOMException("aborted", "AbortError");
    await expect(createAuthorizedFetch(session, vi.fn<typeof fetch>().mockRejectedValue(abort))("/api/v1/jobs")).rejects.toBe(abort);
    await expect(offline("https://evil.example/steal")).rejects.toBeInstanceOf(TypeError);
  });
});
