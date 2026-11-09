import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import type { SessionStore } from "./session";
import {
  createJobSubmissionAttempt,
  createJobsApi,
  type JobResponse,
} from "./jobs";

const JOB_ID = "33333333-3333-4333-8333-333333333333";
const LISTING_ID = "22222222-2222-4222-8222-222222222222";
const WORKER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

type PostResult = "201_CREATED" | "200_REPLAY" | "NETWORK_LOST_AFTER_COMMIT" | "503_BEFORE_COMMIT" | "409_KEY_REUSED";
type SubmissionFactors = {
  attempt: "FIRST_SUBMISSION" | "SAME_KEY_SAME_BODY" | "SAME_KEY_CHANGED_BODY";
  post_result: PostResult;
  recovery: "NO_AUTOMATIC_POST" | "RETRY_SAME_ATTEMPT" | "EDIT_AND_NEW_ATTEMPT";
};
type PairwiseCase = { id: string; factors: SubmissionFactors };
type PairwiseDocument = { suites: { submission_retry: { pairwise_rows: PairwiseCase[] } } };
const matrix = JSON.parse(readFileSync(resolve(process.cwd(), "../docs/coursework/vt-090/pairwise-cases.json"), "utf8")) as PairwiseDocument;

function job(): JobResponse {
  return {
    id: JOB_ID,
    listing_id: LISTING_ID,
    worker_id: WORKER_ID,
    gpu_count: 2,
    duration_seconds: 60,
    status: "QUEUED",
    failure_reason: null,
    submitted_at: "2026-11-09T08:00:00.000000Z",
    started_at: null,
    terminal_at: null,
  };
}

function response(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": REQUEST_ID },
  });
}

function session(): SessionStore {
  return {
    getState: () => ({ status: "signed-out" }),
    subscribe: () => () => undefined,
    getAccessToken: () => "pairwise-test-token",
    signIn: vi.fn(),
    signOut: vi.fn(),
    handleUnauthorized: vi.fn(),
  } as unknown as SessionStore;
}

function responseFor(result: PostResult): Response | Promise<never> {
  if (result === "201_CREATED") return response(job(), 201);
  if (result === "200_REPLAY") return response(job(), 200);
  if (result === "NETWORK_LOST_AFTER_COMMIT") return Promise.reject(new TypeError("simulated connection loss after commit"));
  const code = result === "409_KEY_REUSED" ? "IDEMPOTENCY_KEY_REUSED" : "DEPENDENCY_UNAVAILABLE";
  const status = result === "409_KEY_REUSED" ? 409 : 503;
  return response({ error: { code, message: "simulated response", request_id: REQUEST_ID } }, status);
}

describe("VT-090 generated submission/retry pairwise rows", () => {
  it.each(matrix.suites.submission_retry.pairwise_rows)("$id executes $factors at the API-client boundary", async ({ id, factors }) => {
    const key = `vt090-${id.toLowerCase()}-logical-submit`;
    const original = { listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 60 };
    const edited = { ...original, gpu_count: 3 };
    const sent: Array<{ key: string | null; body: unknown; method: string | undefined }> = [];
    const plannedResults: PostResult[] = [];
    const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
      const headers = new Headers(init?.headers);
      sent.push({
        key: headers.get("Idempotency-Key"),
        body: JSON.parse(String(init?.body)),
        method: init?.method,
      });
      const next = plannedResults.shift();
      if (!next) throw new Error("Unexpected automatic POST without a planned pairwise action");
      return responseFor(next);
    });
    const api = createJobsApi(session(), fetcher);
    const attempt = createJobSubmissionAttempt(original, key);

    async function send(currentAttempt: ReturnType<typeof createJobSubmissionAttempt>, outcome: PostResult) {
      const before = sent.length;
      plannedResults.push(outcome);
      if (outcome === "201_CREATED" || outcome === "200_REPLAY") {
        const result = await api.submitJob(currentAttempt);
        expect(result).toMatchObject({ id: JOB_ID, status: "QUEUED" });
      } else {
        const expectedCode = outcome === "409_KEY_REUSED"
          ? "IDEMPOTENCY_KEY_REUSED"
          : outcome === "503_BEFORE_COMMIT" ? "DEPENDENCY_UNAVAILABLE" : "NETWORK_ERROR";
        await expect(api.submitJob(currentAttempt)).rejects.toMatchObject({ code: expectedCode });
      }
      expect(sent).toHaveLength(before + 1);
      expect(plannedResults).toHaveLength(0);
      expect(sent.at(-1)).toMatchObject({ method: "POST", key: currentAttempt.key, body: currentAttempt.request });
    }

    if (factors.attempt === "FIRST_SUBMISSION") {
      await send(attempt, factors.post_result);
      if (factors.recovery === "RETRY_SAME_ATTEMPT") {
        const retryResult = factors.post_result === "NETWORK_LOST_AFTER_COMMIT" ? "200_REPLAY" : "201_CREATED";
        await send(attempt, retryResult);
      }
      expect(sent.every((request) => request.key === key && JSON.stringify(request.body) === JSON.stringify(original))).toBe(true);
    } else if (factors.attempt === "SAME_KEY_SAME_BODY") {
      await send(attempt, "NETWORK_LOST_AFTER_COMMIT");
      await send(attempt, factors.post_result);
      if (factors.recovery === "RETRY_SAME_ATTEMPT") await send(attempt, "200_REPLAY");
      expect(sent.every((request) => request.key === key && JSON.stringify(request.body) === JSON.stringify(original))).toBe(true);
    } else {
      await send(attempt, "201_CREATED");
      const conflictingAttempt = createJobSubmissionAttempt(edited, key);
      await send(conflictingAttempt, "409_KEY_REUSED");
      expect(sent[0].key).toBe(sent[1].key);
      expect(sent[0].body).toEqual(original);
      expect(sent[1].body).toEqual(edited);
      if (factors.recovery === "EDIT_AND_NEW_ATTEMPT") {
        const nextAttempt = createJobSubmissionAttempt(edited, `${key}-edited`);
        await send(nextAttempt, "201_CREATED");
        expect(sent[2].key).not.toBe(sent[1].key);
        expect(sent[2].body).toEqual(edited);
      }
    }

    expect(fetcher).toHaveBeenCalledTimes(sent.length);
    expect(fetcher.mock.calls.every(([, init]) => init?.method === "POST")).toBe(true);
  });
});
