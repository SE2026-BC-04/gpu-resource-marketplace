import { afterEach, describe, expect, it, vi } from "vitest";

import { createListingsApi, ListingsApiError } from "./listings";
import { LISTING_ID, sample } from "../ui/listings/__tests__/fixtures";

afterEach(() => vi.restoreAllMocks());

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

describe("Listings authenticated API boundary", () => {
  it("implements exactly the six approved operations with current memory token and decimal strings", async () => {
    let token = "test-only-token-1";
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(json({ items: [sample()], next_cursor: "cursor-example" }))
      .mockImplementation(async () => json(sample()));
    const api = createListingsApi(() => token, vi.fn(), fetcher);
    const signal = new AbortController().signal;
    expect((await api.list({ scope: "mine", status: "ACTIVE", limit: 20, cursor: "opaque+/=" }, signal)).next_cursor).toBe("cursor-example");
    token = "test-only-token-2";
    await api.get(LISTING_ID);
    await api.create({ gpu_model: "A100", vram_gb: 80, total_gpu_count: 8, mock_price_per_hour: "12.50" });
    await api.patch(LISTING_ID, { mock_price_per_hour: null });
    await api.pause(LISTING_ID);
    await api.resume(LISTING_ID);
    const calls = fetcher.mock.calls;
    expect(calls).toHaveLength(6);
    expect(String(calls[0][0])).toContain("scope=mine&limit=20&status=ACTIVE&cursor=opaque%2B%2F%3D");
    expect(calls.map(call => call[1]?.method)).toEqual(["GET", "GET", "POST", "PATCH", "POST", "POST"]);
    expect(calls[0][1]?.headers).toMatchObject({ Authorization: "Bearer test-only-token-1" });
    expect(calls[1][1]?.headers).toMatchObject({ Authorization: "Bearer test-only-token-2" });
    expect(calls[0][1]).toMatchObject({ credentials: "omit", cache: "no-store", signal });
    expect(calls[2][1]?.body).toContain('"mock_price_per_hour":"12.50"');
    expect(calls[3][1]?.body).toBe('{"mock_price_per_hour":null}');
    expect(calls[4][1]?.body).toBeUndefined();
    expect(String(calls[4][0]).endsWith(`${LISTING_ID}/pause`)).toBe(true);
    expect(String(calls[5][0]).endsWith(`${LISTING_ID}/resume`)).toBe(true);
    for (const call of calls) expect(String(call[0])).not.toContain("test-only-token");
  });

  it("does not send a request without an authenticated token", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const api = createListingsApi(() => null, vi.fn(), fetcher);
    await expect(api.list({ scope: "marketplace" })).rejects.toMatchObject({ code: "UNAUTHORIZED" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("clears the shared session through the supplied handler on 401", async () => {
    const onUnauthorized = vi.fn();
    const api = createListingsApi(() => "test-token", onUnauthorized, vi.fn(async () => new Response("not JSON", { status: 401 })));
    await expect(api.get(LISTING_ID)).rejects.toMatchObject({ code: "UNAUTHORIZED", status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("maps public error codes without displaying raw server messages", async () => {
    const api = createListingsApi(() => "test-token", vi.fn(), vi.fn(async () => json({ error: { code: "LISTING_CAPACITY_BELOW_QUEUED_MAX", message: "secret-sql-password" } }, 409)));
    await expect(api.patch(LISTING_ID, { total_gpu_count: 2 })).rejects.toThrow("yêu cầu lớn nhất đang chờ");
    try { await api.patch(LISTING_ID, { total_gpu_count: 2 }); } catch (error) {
      expect(String(error)).not.toContain("secret-sql-password");
    }
  });

  it("does not clear a new session when an old request returns 401", async () => {
    let token = "old-test-token";
    let finish!: (value: Response) => void;
    const onUnauthorized = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const api = createListingsApi(() => token, onUnauthorized, fetcher);
    const pending = api.get(LISTING_ID);
    token = "new-test-token";
    finish(new Response("", { status: 401 }));
    await expect(pending).rejects.toMatchObject({ code: "UNAUTHORIZED" });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it.each(["create", "patch"] as const)("shows a safe body-size error for %s without logout or retry", async method => {
    const unauthorized = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ error: { code: "PAYLOAD_TOO_LARGE", message: "private-body-secret" } }, 413));
    const api = createListingsApi(() => "test-token", unauthorized, fetcher);
    const input = { gpu_model: "A100", vram_gb: 80, total_gpu_count: 8 };
    const action = method === "create" ? api.create(input) : api.patch(LISTING_ID, input);
    await expect(action).rejects.toMatchObject({ code: "PAYLOAD_TOO_LARGE", status: 413, message: "Dữ liệu gửi quá lớn. Vui lòng rút gọn nội dung và thử lại." });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("does not automatically retry a failed create", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("connection lost"));
    const api = createListingsApi(() => "test-token", vi.fn(), fetcher);
    await expect(api.create({ gpu_model: "A100", vram_gb: 80, total_gpu_count: 8 })).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("preserves aborts and never saves tokens to browser storage", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const controller = new AbortController();
    controller.abort();
    const failure = new DOMException("aborted", "AbortError");
    const api = createListingsApi(() => "test-token", vi.fn(), vi.fn<typeof fetch>().mockRejectedValue(failure));
    await expect(api.list({ scope: "marketplace" }, controller.signal)).rejects.toBe(failure);
    expect(storage).not.toHaveBeenCalled();
  });

  it("rejects malformed DTOs and resource identifiers", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ ...sample(), available_gpu_count: -1 }));
    const api = createListingsApi(() => "test-token", vi.fn(), fetcher);
    await expect(api.get(LISTING_ID)).rejects.toBeInstanceOf(ListingsApiError);
    await expect(api.get("../../auth/logout")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
