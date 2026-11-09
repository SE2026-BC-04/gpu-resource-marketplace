import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "../../api/auth";
import { JobsApiError, type JobCollectionResponse, type JobResponse, type JobsApi } from "../../api/jobs";
import { JobsPage } from "./JobsPage";

const JOB_A = "33333333-3333-4333-8333-333333333331";
const JOB_B = "33333333-3333-4333-8333-333333333332";
const LISTING_ID = "22222222-2222-4222-8222-222222222222";
const WORKER_ID = "11111111-1111-4111-8111-111111111111";
const identity = (id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"): AuthUser => ({
  id,
  loginName: "pairwise_client",
  role: "CLIENT",
});

const labels = {
  QUEUED: "Đang chờ",
  RUNNING: "Đang chạy",
  COMPLETED: "Hoàn tất",
  FAILED: "Thất bại",
  CANCELLED: "Đã hủy",
} as const;

function job(status: JobResponse["status"], id: string, durationSeconds = 60): JobResponse {
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(status);
  const started = !["QUEUED", "CANCELLED"].includes(status);
  return {
    id,
    listing_id: LISTING_ID,
    worker_id: WORKER_ID,
    gpu_count: 2,
    duration_seconds: durationSeconds,
    status,
    failure_reason: status === "FAILED" ? "WORKER_FAULT" : null,
    submitted_at: "2026-11-09T08:00:00.000000Z",
    started_at: started ? "2026-11-09T08:00:30.000000Z" : null,
    terminal_at: terminal ? "2026-11-09T08:01:00.000000Z" : null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advanceClock(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

type PollingFactors = {
  prior_status: JobResponse["status"];
  get_result: JobResponse["status"] | "TIMEOUT" | "HTTP_503";
  ui_context: "SAME_JOB" | "SWITCH_JOB" | "UNMOUNT" | "CHANGE_IDENTITY";
};
type PairwiseCase = { id: string; factors: PollingFactors };
type PairwiseDocument = { suites: { polling: { pairwise_rows: PairwiseCase[] } } };
const matrix = JSON.parse(readFileSync(resolve(process.cwd(), "../docs/coursework/vt-090/pairwise-cases.json"), "utf8")) as PairwiseDocument;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("VT-090 generated polling pairwise rows", () => {
  it.each(matrix.suites.polling.pairwise_rows)("$id executes $factors", async ({ factors }) => {
    vi.useFakeTimers();
    const pendingPoll = deferred<JobResponse>();
    let aReads = 0;
    let bReads = 0;
    let activeGets = 0;
    let maxActiveGets = 0;
    let pollSignal: AbortSignal | undefined;
    let recoveryStatus = factors.prior_status;
    const getJob = vi.fn((id: string, signal?: AbortSignal): Promise<JobResponse> => {
      activeGets += 1;
      maxActiveGets = Math.max(maxActiveGets, activeGets);
      let released = false;
      const release = () => {
        if (released) return;
        released = true;
        activeGets -= 1;
        signal?.removeEventListener("abort", release);
      };
      signal?.addEventListener("abort", release, { once: true });

      let response: Promise<JobResponse>;
      if (id === JOB_A) {
        aReads += 1;
        if (aReads === 1) response = Promise.resolve(job(factors.prior_status, JOB_A));
        else if (aReads === 2) {
          pollSignal = signal;
          if (factors.get_result === "TIMEOUT") {
            response = new Promise<JobResponse>((_, reject) => {
              signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
            });
          } else if (factors.get_result === "HTTP_503") {
            response = Promise.reject(new JobsApiError("DEPENDENCY_UNAVAILABLE", 503));
          } else {
            response = pendingPoll.promise;
          }
        } else response = Promise.resolve(job(recoveryStatus, JOB_A));
      } else {
        bReads += 1;
        response = Promise.resolve(job("QUEUED", JOB_B));
      }
      return response.finally(release);
    });
    const api: JobsApi = {
      listJobs: vi.fn().mockResolvedValue({
        items: [job(factors.prior_status, JOB_A), job("QUEUED", JOB_B)],
        next_cursor: null,
      } satisfies JobCollectionResponse),
      getJob,
      submitJob: vi.fn().mockResolvedValue(job("QUEUED", JOB_A)),
      cancelJob: vi.fn(),
    };
    const view = render(<JobsPage api={api} user={identity()} />);
    await flushPromises();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(JOB_A) }));
    await flushPromises();
    expect(aReads).toBe(1);
    await advanceClock(1999);
    expect(aReads).toBe(1);
    await advanceClock(1);
    expect(aReads).toBe(2);

    if (factors.ui_context === "SAME_JOB") {
      if (factors.get_result === "TIMEOUT") {
        await advanceClock(5000);
        expect(pollSignal?.aborted).toBe(true);
      } else if (factors.get_result === "HTTP_503") {
        await flushPromises();
      } else {
        recoveryStatus = factors.get_result;
        await act(async () => {
          pendingPoll.resolve(job(factors.get_result as JobResponse["status"], JOB_A));
          await pendingPoll.promise;
        });
        expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByText(`${job(factors.get_result, JOB_A).duration_seconds} giây`)).toBeInTheDocument();
      }

      if (factors.get_result === "TIMEOUT" || factors.get_result === "HTTP_503") {
        expect(screen.getByText(/Đang thử lại/)).toBeInTheDocument();
        await advanceClock(999);
        expect(aReads).toBe(2);
        await advanceClock(1);
        expect(aReads).toBe(3);
        expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByRole("status")).toHaveTextContent(labels[factors.prior_status]);
        await advanceClock(2000);
        expect(aReads).toBe(4);
      } else if (["QUEUED", "RUNNING"].includes(factors.get_result)) {
        await advanceClock(2000);
        expect(aReads).toBe(3);
        expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByRole("status")).toHaveTextContent(labels[factors.get_result]);
      } else {
        await advanceClock(10000);
        expect(aReads).toBe(2);
        expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByRole("status")).toHaveTextContent(labels[factors.get_result]);
      }
    } else {
      if (factors.get_result === "TIMEOUT") {
        await advanceClock(5000);
        expect(pollSignal?.aborted).toBe(true);
      } else if (factors.get_result === "HTTP_503") {
        await flushPromises();
      }

      if (factors.ui_context === "SWITCH_JOB") {
        fireEvent.click(screen.getByRole("button", { name: new RegExp(JOB_B) }));
        await flushPromises();
      } else if (factors.ui_context === "UNMOUNT") {
        view.unmount();
      } else {
        view.rerender(<JobsPage api={api} user={identity("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")} />);
        await flushPromises();
      }

      const aReadsAfterContextChange = aReads;
      if (!["TIMEOUT", "HTTP_503"].includes(factors.get_result)) {
        expect(pollSignal?.aborted).toBe(true);
        await act(async () => {
          pendingPoll.resolve(job(factors.get_result as JobResponse["status"], JOB_A, 999));
          await pendingPoll.promise;
        });
      }
      await advanceClock(1000);
      expect(aReads).toBe(aReadsAfterContextChange);
      if (factors.ui_context === "SWITCH_JOB") {
        const detail = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
        expect(detail.getByText(JOB_B)).toBeInTheDocument();
        expect(detail.getByRole("status")).toHaveTextContent(labels.QUEUED);
      } else if (factors.ui_context === "CHANGE_IDENTITY") {
        const detail = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
        expect(detail.getByText(JOB_A)).toBeInTheDocument();
        expect(detail.getByText("60 giây")).toBeInTheDocument();
        expect(detail.getByRole("status")).toHaveTextContent(labels[factors.prior_status]);
      } else {
        expect(view.container).toBeEmptyDOMElement();
      }
    }

    expect(maxActiveGets).toBe(1);
    expect(api.submitJob).not.toHaveBeenCalled();
    expect(api.cancelJob).not.toHaveBeenCalled();
    if (factors.ui_context === "SWITCH_JOB") expect(bReads).toBeGreaterThan(0);
  });
});
