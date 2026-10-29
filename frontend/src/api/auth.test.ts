import { describe, expect, it, vi } from "vitest";

import { AuthApiError, createAuthApi } from "./auth";

const USER = { id: "8bf66294-daf8-42fa-a167-50a3a43b7b66", login_name: "demo_client_01", role: "CLIENT" };
const TOKEN = "eyJhbGciOiJIUzI1NiJ9.payload.signature";
const REQUEST_ID = "a3f70e25-559a-444f-8226-a667aa401e6c";

function reply(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers });
}

function api(response: Response | Error | DOMException) {
  const fetcher = vi.fn<typeof fetch>();
  // jsdom's DOMException is not an Error subclass, so branch on Response instead.
  if (response instanceof Response) fetcher.mockResolvedValue(response);
  else fetcher.mockRejectedValue(response);
  return { client: createAuthApi(fetcher), fetcher };
}

describe("Auth API client", () => {
  it("sends Login exactly as typed and parses the approved response", async () => {
    const { client, fetcher } = api(reply(200, { access_token: TOKEN, token_type: "Bearer", expires_in: 900, user: USER }));
    const result = await client.login("  demo_client_01 ", " pass word ");
    expect(result).toEqual({
      accessToken: TOKEN,
      expiresInSeconds: 900,
      user: { id: USER.id, loginName: "demo_client_01", role: "CLIENT" },
    });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/auth/login");
    expect(init).toMatchObject({ method: "POST", credentials: "omit", cache: "no-store" });
    expect(init?.headers).toEqual({ Accept: "application/json", "Content-Type": "application/json" });
    // Neither field is trimmed on the client: the server owns the DEC-P1-03 rule.
    expect(JSON.parse(init?.body as string)).toEqual({ login_name: "  demo_client_01 ", password: " pass word " });
  });

  it("returns a fixed generic message for rejected credentials", async () => {
    const { client } = api(reply(401, { error: { code: "INVALID_CREDENTIALS", message: "x", request_id: REQUEST_ID } },
      { "X-Request-ID": REQUEST_ID }));
    const error = await client.login("demo_client_01", "secret-password").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AuthApiError);
    expect(error).toMatchObject({ code: "INVALID_CREDENTIALS", status: 401, requestId: REQUEST_ID });
    expect((error as Error).message).toBe("Tên đăng nhập hoặc mật khẩu không đúng.");
    expect((error as Error).message).not.toContain("secret-password");
  });

  it.each([
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 900, user: { ...USER, role: "ROOT" } }],
    [{ access_token: TOKEN, token_type: "bearer", expires_in: 900, user: USER }],
    [{ access_token: "", token_type: "Bearer", expires_in: 900, user: USER }],
    [{ access_token: "a b", token_type: "Bearer", expires_in: 900, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: "900", user: USER }],
    // P2-01: the contract fixes expires_in at exactly 900.
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 899, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 901, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 2 ** 31, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: Number.MAX_SAFE_INTEGER, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 900.5, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: null, user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", user: USER }],
    [{ access_token: TOKEN, token_type: "Bearer", expires_in: 900, user: { ...USER, id: "not-a-uuid" } }],
  ])("rejects a malformed Login response %#", async (body) => {
    const { client } = api(reply(200, body));
    await expect(client.login("a", "b")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("keeps only a UUIDv4 request ID and falls back on the status without a JSON error", async () => {
    const { client } = api(reply(503, undefined, { "X-Request-ID": "caller<script>" }));
    await expect(client.login("a", "b")).rejects.toMatchObject({ code: "INTERNAL_ERROR", status: 503, requestId: undefined });
  });

  it("maps a network failure and rethrows an abort", async () => {
    await expect(api(new TypeError("Failed to fetch")).client.login("a", "b")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    const abort = new DOMException("aborted", "AbortError");
    await expect(api(abort).client.login("a", "b")).rejects.toBe(abort);
  });

  it("reads /me with the bearer token", async () => {
    const { client, fetcher } = api(reply(200, USER));
    expect(await client.me(TOKEN)).toEqual({ id: USER.id, loginName: "demo_client_01", role: "CLIENT" });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/auth/me");
    expect(init).toMatchObject({ method: "GET", headers: { Accept: "application/json", Authorization: `Bearer ${TOKEN}` } });
  });

  it("maps a 401 from /me without a JSON body to UNAUTHORIZED", async () => {
    await expect(api(reply(401)).client.me(TOKEN)).rejects.toMatchObject({ code: "UNAUTHORIZED", status: 401 });
  });

  it("calls Logout without a body and requires 204", async () => {
    const { client, fetcher } = api(reply(204));
    await client.logout(TOKEN);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/auth/logout");
    expect(init?.method).toBe("POST");
    expect(init).not.toHaveProperty("body");
    expect(init?.headers).not.toHaveProperty("Content-Type");
    await expect(api(reply(200, {})).client.logout(TOKEN)).rejects.toBeInstanceOf(AuthApiError);
  });
});
