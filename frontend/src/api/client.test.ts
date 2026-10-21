import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiLiveness } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("uses the API boundary and checks the health response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok" }) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await getApiLiveness()).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/health/live", { signal: undefined });
  });

  it("reports non-success responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(getApiLiveness()).rejects.toThrow("503");
  });
});
