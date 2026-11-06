import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthApi, AuthUser } from "../../api/auth";
import { createSessionListingsApi } from "../../api/listings";
import { createSessionStore } from "../../api/session";
import { SessionListingsPage } from "./SessionListingsPage";
import { sample, USER_ID } from "./__tests__/fixtures";

function setup(role: AuthUser["role"] = "WORKER") {
  let user: AuthUser = { id: USER_ID, loginName: "worker-one", role };
  let token = "test-only-first-token";
  let now = 0;
  const auth: AuthApi = {
    login: vi.fn(async () => ({ accessToken: token, expiresInSeconds: 900, user })),
    me: vi.fn(async () => user),
    logout: vi.fn(async () => undefined),
  };
  // Real session store; Auth HTTP and clock are test doubles, not browser/API E2E.
  const session = createSessionStore(auth, { now: () => now, setTimeout: () => 0, clearTimeout: () => undefined });
  return {
    session, auth,
    expire: () => { now = 900_000; },
    replace: (next: AuthUser) => { user = next; token = "test-only-second-token"; },
  };
}

function page() { return Response.json({ items: [sample()], next_cursor: null }); }

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Listings consumer of the merged GPU-003 session", () => {
  it("does not send protected requests while signed out", async () => {
    const { session } = setup();
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    render(<SessionListingsPage session={session} />);
    expect(screen.getByText(/Vui lòng đăng nhập/)).toBeInTheDocument();
    await expect(createSessionListingsApi(session, fetcher).list({ scope: "marketplace" })).rejects.toMatchObject({ status: 401 });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["CLIENT", "WORKER", "ADMIN"] as const)("maps confirmed %s identity and sends the current token", async role => {
    const { session } = setup(role);
    await session.signIn("worker-one", "test-only-password");
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => page());
    vi.stubGlobal("fetch", fetcher);
    const view = render(<SessionListingsPage session={session} />);
    await screen.findByText("A100 simulated");
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/api/v1/gpu-listings?"), expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer test-only-first-token" }),
      cache: "no-store", credentials: "omit",
    }));
    expect(Boolean(screen.queryByRole("button", { name: "Tạo Listing" }))).toBe(role === "WORKER");
    expect(Boolean(screen.queryByRole("option", { name: "Listings của tôi" }))).toBe(role === "WORKER");
    expect(Boolean(screen.queryByRole("option", { name: "Tất cả Listings" }))).toBe(role === "ADMIN");
    view.rerender(<SessionListingsPage session={session} />);
    expect(fetcher).toHaveBeenCalledTimes(1); // API instance is stable across renders.
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("removes private detail/form state on logout and a later role change", async () => {
    const env = setup();
    await env.session.signIn("worker-one", "test-only-password");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(async () => page()));
    render(<SessionListingsPage session={env.session} />);
    await screen.findByText("A100 simulated");
    fireEvent.click(screen.getByRole("button", { name: "Tạo Listing" }));
    expect(screen.getByLabelText("Model GPU")).toBeInTheDocument();
    await act(async () => { await env.session.signOut(); });
    expect(screen.getByText(/Vui lòng đăng nhập/)).toBeInTheDocument();
    expect(screen.queryByText("A100 simulated")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Model GPU")).not.toBeInTheDocument();
    env.replace({ id: USER_ID, loginName: "now-client", role: "CLIENT" });
    await act(async () => { await env.session.signIn("now-client", "test-only-password"); });
    await screen.findByText("A100 simulated");
    expect(screen.queryByRole("button", { name: "Tạo Listing" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Model GPU")).not.toBeInTheDocument();
  });

  it("a current 401 clears the real store and unmounts the protected workspace", async () => {
    const { session } = setup();
    await session.signIn("worker-one", "test-only-password");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 401 })));
    render(<SessionListingsPage session={session} />);
    await screen.findByText(/Vui lòng đăng nhập/);
    expect(session.getState()).toEqual({ status: "signed-out", reason: "unauthorized" });
  });

  it("an old request's 401 cannot clear a newer token", async () => {
    const env = setup();
    await env.session.signIn("worker-one", "test-only-password");
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>(done => { resolve = done; }));
    const api = createSessionListingsApi(env.session, fetcher);
    const pending = api.list({ scope: "marketplace" });
    const checked = expect(pending).rejects.toMatchObject({ status: 401 });
    env.replace({ id: USER_ID, loginName: "new-session", role: "WORKER" });
    await env.session.signIn("new-session", "test-only-password");
    resolve(new Response(null, { status: 401 }));
    await checked;
    expect(env.session.getAccessToken()).toBe("test-only-second-token");
    expect(env.session.getState().status).toBe("signed-in");
  });

  it("a 403 keeps the session intact", async () => {
    const { session } = setup();
    await session.signIn("worker-one", "test-only-password");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: { code: "FORBIDDEN" } }, { status: 403 }));
    await expect(createSessionListingsApi(session, fetcher).list({ scope: "all" })).rejects.toMatchObject({ status: 403 });
    expect(session.getState().status).toBe("signed-in");
    expect(session.getAccessToken()).toBe("test-only-first-token");
  });

  it("guides the Worker to refresh mine after create 503 without replaying POST", async () => {
    const { session } = setup();
    await session.signIn("worker-one", "test-only-password");
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => init?.method === "POST"
      ? Response.json({ error: { code: "DEPENDENCY_UNAVAILABLE", message: "private-sql-password" } }, { status: 503 })
      : page());
    vi.stubGlobal("fetch", fetcher);
    render(<SessionListingsPage session={session} />);
    await screen.findByText("A100 simulated");
    fireEvent.click(screen.getByRole("button", { name: "Tạo Listing" }));
    fireEvent.change(screen.getByLabelText("Model GPU"), { target: { value: "A100" } });
    fireEvent.change(screen.getByLabelText("VRAM (GB)"), { target: { value: "80" } });
    fireEvent.change(screen.getByLabelText("Tổng GPU"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu Listing" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("chọn Listings của tôi và Tải lại để kiểm tra trước khi tạo lại");
    expect(alert).not.toHaveTextContent("private-sql-password");
    expect(session.getState().status).toBe("signed-in");
    fireEvent.change(screen.getByLabelText("Phạm vi"), { target: { value: "mine" } });
    await screen.findByText("A100 simulated");
    expect(screen.queryByLabelText("Model GPU")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    await waitFor(() => expect(fetcher.mock.calls.filter(call => call[1]?.method === "GET")).toHaveLength(3));
    expect(fetcher.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
    expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain("scope=mine");
  });

  it("at the 900 s deadline it clears the UI and sends nothing, even if the timer did not fire", async () => {
    const env = setup();
    await env.session.signIn("worker-one", "test-only-password");
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => page());
    vi.stubGlobal("fetch", fetcher);
    render(<SessionListingsPage session={env.session} />);
    await screen.findByText("A100 simulated");
    env.expire();
    await act(async () => {
      await expect(createSessionListingsApi(env.session, fetcher).list({ scope: "marketplace" })).rejects.toMatchObject({ status: 401 });
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(env.session.getState()).toEqual({ status: "signed-out", reason: "expired" });
    expect(screen.getByText(/Vui lòng đăng nhập/)).toBeInTheDocument();
    expect(screen.queryByText("A100 simulated")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Tạo Listing" })).not.toBeInTheDocument());
  });
});
