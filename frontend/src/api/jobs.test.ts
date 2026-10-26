import { describe, expect, it, vi } from "vitest";

import type { SessionStore } from "./session";
import {
  createJobSubmissionAttempt,
  createJobsApi,
  createJobsApiFromAuthorizedFetch,
  JobsApiError,
  validateSubmitJobRequest,
} from "./jobs";

const JOB_ID = "33333333-3333-4333-8333-333333333333";
const LISTING_ID = "22222222-2222-4222-8222-222222222222";
const WORKER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function job(status = "QUEUED") {
  return {
    id: JOB_ID,
    listing_id: LISTING_ID,
    worker_id: WORKER_ID,
    gpu_count: 2,
    duration_seconds: 60,
    status,
    failure_reason: status === "FAILED" ? "WORKER_FAULT" : null,
    submitted_at: "2026-10-26T08:00:00.000000Z",
    started_at: null,
    terminal_at: status === "CANCELLED" ? "2026-10-26T08:01:00.000000Z" : null,
  };
}

function response(value: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function session(token: string | null = "test-only-token"): SessionStore {
  return {
    getState: () => ({ status: "signed-out" }),
    subscribe: () => () => undefined,
    getAccessToken: () => token,
    signIn: vi.fn(),
    signOut: vi.fn(),
    handleUnauthorized: vi.fn(),
  } as unknown as SessionStore;
}

describe("Jobs API client", () => {
  it("uses the shared authorized fetch and encodes approved list filters/cursor", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ items: [job()], next_cursor: "opaque+cursor" }));
    const api = createJobsApi(session(), fetcher);
    const result = await api.listJobs({ scope: "mine", status: "QUEUED", limit: 20, cursor: "opaque+cursor" });

    expect(result.items[0].id).toBe(JOB_ID);
    expect(result.next_cursor).toBe("opaque+cursor");
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toContain("/api/v1/jobs?");
    const params = new URL(String(url)).searchParams;
    expect([...params.entries()]).toEqual([
      ["scope", "mine"], ["status", "QUEUED"], ["limit", "20"], ["cursor", "opaque+cursor"],
    ]);
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-only-token");
    expect(init?.credentials).toBe("omit");
    expect(init?.cache).toBe("no-store");
  });

  it("uses contract defaults when optional list filters are absent and validates bounds", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ items: [], next_cursor: null }));
    const api = createJobsApi(session(), fetcher);
    await api.listJobs();
    expect(fetcher.mock.calls[0][0]).toContain("/api/v1/jobs");
    expect(fetcher.mock.calls[0][0]).not.toContain("?");
    await expect(api.listJobs({ limit: 0 })).rejects.toThrow(TypeError);
    await expect(api.listJobs({ limit: 101 })).rejects.toThrow(TypeError);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("loads a validated detail and posts cancel without a body", async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response(job()))
      .mockResolvedValueOnce(response(job("CANCELLED")));
    const api = createJobsApi(session(), fetcher);
    expect((await api.getJob(JOB_ID)).id).toBe(JOB_ID);
    expect((await api.cancelJob(JOB_ID)).status).toBe("CANCELLED");
    expect(new URL(String(fetcher.mock.calls[0][0])).pathname).toBe(`/api/v1/jobs/${JOB_ID}`);
    expect(new URL(String(fetcher.mock.calls[1][0])).pathname).toBe(`/api/v1/jobs/${JOB_ID}/cancel`);
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST" });
    expect(fetcher.mock.calls[1][1]?.body).toBeUndefined();
  });

  it("keeps the same frozen key and payload when an uncertain submit is retried", async () => {
    const send = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(response(job(), 201));
    const api = createJobsApi(session(), send);
    const mutableRequest = { listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 60 };
    const attempt = createJobSubmissionAttempt(mutableRequest, "logical-submit-0001");
    mutableRequest.gpu_count = 7;

    await expect(api.submitJob(attempt)).rejects.toMatchObject({ name: "JobsApiError", status: 0, code: "NETWORK_ERROR" });
    expect((await api.submitJob(attempt)).id).toBe(JOB_ID);
    expect(send.mock.calls).toHaveLength(2);
    for (const [, init] of send.mock.calls) {
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("logical-submit-0001");
      expect(JSON.parse(String(init?.body))).toEqual({ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 60 });
    }
    expect(attempt.request).toEqual({ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 60 });
  });

  it("surfaces a conflicting key/body response once without automatically retrying", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({
      error: { code: "IDEMPOTENCY_KEY_REUSED", message: "do not expose", request_id: REQUEST_ID },
    }, 409, { "X-Request-ID": REQUEST_ID }));
    const api = createJobsApi(session(), fetcher);
    const conflictingAttempt = createJobSubmissionAttempt(
      { listing_id: LISTING_ID, gpu_count: 3, duration_seconds: 60 },
      "logical-submit-0001",
    );
    await expect(api.submitJob(conflictingAttempt)).rejects.toMatchObject({
      code: "IDEMPOTENCY_KEY_REUSED", status: 409, requestId: REQUEST_ID,
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).get("Idempotency-Key")).toBe("logical-submit-0001");
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({ gpu_count: 3 });
  });

  it.each([
    [{ listing_id: LISTING_ID, gpu_count: true, duration_seconds: 10 }],
    [{ listing_id: LISTING_ID, gpu_count: 1.5, duration_seconds: 10 }],
    [{ listing_id: LISTING_ID, gpu_count: "2", duration_seconds: 10 }],
    [{ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: false }],
    [{ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: "60" }],
    [{ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 1.5 }],
    [{ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 2_147_483_648 }],
    [{ listing_id: "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF", gpu_count: 2, duration_seconds: 10 }],
    [{ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 10, status: "QUEUED" }],
  ])("rejects invalid/extra submit data before issuing a request: %j", async (payload) => {
    expect(() => validateSubmitJobRequest(payload)).toThrow(TypeError);
  });

  it("accepts the contract's printable-ASCII idempotency key range and rejects invalid keys", () => {
    const request = { listing_id: LISTING_ID, gpu_count: 1, duration_seconds: 1 };
    expect(createJobSubmissionAttempt(request, "key with space").key).toBe("key with space");
    expect(() => createJobSubmissionAttempt(request, "short")).toThrow(TypeError);
    expect(() => createJobSubmissionAttempt(request, "unicode-é-key")).toThrow(TypeError);
  });

  it("rejects response fields outside the approved public Job projection", async () => {
    const unsafe = { ...job(), client_id: "44444444-4444-4444-8444-444444444444", simulation_reference: { seed_value: 123 } };
    const api = createJobsApiFromAuthorizedFetch(vi.fn().mockResolvedValue(response(unsafe)));
    await expect(api.getJob(JOB_ID)).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 502 });
  });

  it.each([
    [400, "UNKNOWN_FIELD"], [401, "UNAUTHENTICATED"], [403, "FORBIDDEN"], [404, "JOB_NOT_FOUND"],
    [409, "IDEMPOTENCY_KEY_REUSED"], [422, "JOB_GPU_EXCEEDS_LISTING_TOTAL"], [503, "DEPENDENCY_UNAVAILABLE"],
  ])("maps HTTP %i from the error envelope without exposing server text", async (status, code) => {
    const api = createJobsApiFromAuthorizedFetch(vi.fn().mockResolvedValue(response({
      error: { code, message: "database secret must not be shown", request_id: REQUEST_ID },
    }, status, { "X-Request-ID": REQUEST_ID })));
    try {
      await api.listJobs();
      throw new Error("expected failure");
    } catch (error) {
      expect(error).toBeInstanceOf(JobsApiError);
      expect(error).toMatchObject({ status, code, requestId: REQUEST_ID });
      expect((error as Error).message).not.toContain("database secret");
    }
  });

  it("does not send requests without a volatile session", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const api = createJobsApi(session(null), fetcher);
    await expect(api.listJobs()).rejects.toMatchObject({ code: "UNAUTHORIZED", status: 401 });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
