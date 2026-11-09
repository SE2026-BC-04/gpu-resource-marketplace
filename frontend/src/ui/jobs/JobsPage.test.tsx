import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, UserRole } from "../../api/auth";
import { JobsApiError } from "../../api/jobs";
import type { JobCollectionResponse, JobResponse, JobsApi } from "../../api/jobs";
import { JobsPage } from "./JobsPage";

const JOB_ID = "33333333-3333-4333-8333-333333333333";
const JOB_A = "33333333-3333-4333-8333-333333333331";
const JOB_B = "33333333-3333-4333-8333-333333333332";
const LISTING_ID = "22222222-2222-4222-8222-222222222222";
const WORKER_ID = "11111111-1111-4111-8111-111111111111";

function job(status: JobResponse["status"] = "QUEUED", id = JOB_ID): JobResponse {
  return {
    id,
    listing_id: LISTING_ID,
    worker_id: WORKER_ID,
    gpu_count: 2,
    duration_seconds: 60,
    status,
    failure_reason: status === "FAILED" ? "WORKER_FAULT" : null,
    submitted_at: "2026-10-26T08:00:00.000000Z",
    started_at: status === "QUEUED" ? null : "2026-10-26T08:00:30.000000Z",
    terminal_at: ["COMPLETED", "FAILED", "CANCELLED"].includes(status) ? "2026-10-26T08:01:00.000000Z" : null,
  };
}

function user(role: UserRole): AuthUser {
  return { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", loginName: `test_${role.toLowerCase()}`, role };
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

function setup(role: UserRole = "CLIENT", overrides: Partial<JobsApi> = {}) {
  const api: JobsApi = {
    listJobs: vi.fn().mockResolvedValue({ items: [job()], next_cursor: null } satisfies JobCollectionResponse),
    getJob: vi.fn().mockResolvedValue(job()),
    submitJob: vi.fn().mockResolvedValue(job()),
    cancelJob: vi.fn().mockResolvedValue(job("CANCELLED")),
    ...overrides,
  };
  render(<JobsPage api={api} user={user(role)} />);
  return api;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("GPU-005 Jobs frontend foundation", () => {
  it("shows loading then empty state and keeps retry available on list error", async () => {
    let resolve!: (value: JobCollectionResponse) => void;
    const listJobs = vi.fn(() => new Promise<JobCollectionResponse>((done) => { resolve = done; }));
    const api = setup("ADMIN", { listJobs });
    expect(screen.getByRole("status")).toHaveTextContent("Đang tải danh sách");
    resolve({ items: [], next_cursor: null });
    expect(await screen.findByText("Chưa có công việc nào.")).toBeInTheDocument();
    expect(api.listJobs).toHaveBeenCalledWith({ scope: "all", limit: 20, cursor: undefined }, expect.any(AbortSignal));

    cleanup();
    setup("ADMIN", { listJobs: vi.fn().mockRejectedValue(new JobsApiError("DEPENDENCY_UNAVAILABLE", 503)) });
    expect(await screen.findByRole("alert")).toHaveTextContent("Dịch vụ tạm thời chưa sẵn sàng");
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it.each([
    ["CLIENT", "My Jobs", "mine"],
    ["WORKER", "Assigned Jobs", "assigned"],
    ["ADMIN", "All Jobs", "all"],
  ] as const)("uses role-scoped list reads for %s", async (role, title, scope) => {
    const api = setup(role);
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledWith({ scope, limit: 20, cursor: undefined }, expect.any(AbortSignal)));
    expect(screen.getByText(JOB_ID)).toBeInTheDocument();
    expect(screen.queryByText(WORKER_ID)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("client_id");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not render a previous identity's list while the next role-scoped request is pending", async () => {
    let finishWorkerList!: (value: JobCollectionResponse) => void;
    const api: JobsApi = {
      listJobs: vi.fn()
        .mockResolvedValueOnce({ items: [job()], next_cursor: null })
        .mockImplementationOnce(() => new Promise((resolve) => { finishWorkerList = resolve; })),
      getJob: vi.fn().mockResolvedValue(job()),
      submitJob: vi.fn().mockResolvedValue(job()),
      cancelJob: vi.fn().mockResolvedValue(job("CANCELLED")),
    };
    const view = render(<JobsPage api={api} user={user("CLIENT")} />);
    expect(await screen.findByText(JOB_ID)).toBeInTheDocument();
    view.rerender(<JobsPage api={api} user={{ ...user("WORKER"), id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }} />);
    expect(screen.getByRole("heading", { name: "Assigned Jobs" })).toBeInTheDocument();
    expect(screen.queryByText(JOB_ID)).not.toBeInTheDocument();
    expect(screen.getByText("Đang tải danh sách công việc…")).toBeInTheDocument();
    finishWorkerList({ items: [], next_cursor: null });
  });

  it("keeps pagination cursor opaque and resets it when filters change", async () => {
    const listJobs = vi.fn()
      .mockResolvedValueOnce({ items: [job()], next_cursor: "opaque-cursor-2" })
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockResolvedValueOnce({ items: [], next_cursor: null });
    const api = setup("CLIENT", { listJobs });
    await screen.findByText(JOB_ID);
    fireEvent.click(screen.getByRole("button", { name: "Trang tiếp" }));
    await waitFor(() => expect(api.listJobs).toHaveBeenNthCalledWith(2,
      { scope: "mine", limit: 20, cursor: "opaque-cursor-2" }, expect.any(AbortSignal)));
    fireEvent.change(screen.getByLabelText("Lọc trạng thái"), { target: { value: "COMPLETED" } });
    await waitFor(() => expect(api.listJobs).toHaveBeenNthCalledWith(3,
      { scope: "mine", limit: 20, cursor: undefined, status: "COMPLETED" }, expect.any(AbortSignal)));
  });

  it("recovers an invalid server cursor by restarting pagination from page one", async () => {
    const listJobs = vi.fn()
      .mockResolvedValueOnce({ items: [job()], next_cursor: "cursor-page-2" })
      .mockRejectedValueOnce(new JobsApiError("INVALID_CURSOR", 400))
      .mockResolvedValueOnce({ items: [], next_cursor: null });
    const api = setup("CLIENT", { listJobs });
    await screen.findByText(JOB_ID);
    fireEvent.click(screen.getByRole("button", { name: "Trang tiếp" }));
    await screen.findByRole("button", { name: "Tải lại từ đầu" });
    fireEvent.click(screen.getByRole("button", { name: "Tải lại từ đầu" }));
    await waitFor(() => expect(api.listJobs).toHaveBeenNthCalledWith(3,
      { scope: "mine", limit: 20, cursor: undefined }, expect.any(AbortSignal)));
  });

  it("loads a safe detail projection and shows Cancel only for a Client's QUEUED Job", async () => {
    setup("CLIENT");
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_ID) }));
    expect(await screen.findByRole("region", { name: "Chi tiết công việc" })).toBeInTheDocument();
    expect(screen.getByText(WORKER_ID)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hủy công việc" })).toBeInTheDocument();

    cleanup();
    setup("WORKER", { getJob: vi.fn().mockResolvedValue(job("RUNNING")) });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_ID) }));
    expect(await screen.findByText("Đang chạy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
    expect(screen.queryByText(WORKER_ID)).not.toBeInTheDocument();

    cleanup();
    setup("CLIENT", { getJob: vi.fn().mockResolvedValue(job("RUNNING")) });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_ID) }));
    expect(await screen.findByText("Đang chạy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });

  it("P2-02C preserves successful cancellation behavior and refreshes the list", async () => {
    const listJobs = vi.fn().mockResolvedValue({ items: [job()], next_cursor: null });
    const api = setup("CLIENT", { listJobs });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_ID) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith(JOB_ID));
    await waitFor(() => expect(screen.getAllByText("Đã hủy").length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2));
    expect(api.cancelJob).toHaveBeenCalledTimes(1);
  });

  it("P2-01A selects and shows the submitted Job instead of leaving the previous selection", async () => {
    const api = setup("CLIENT", {
      listJobs: vi.fn()
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A)], next_cursor: null })
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob: vi.fn().mockImplementation((id: string) => Promise.resolve(job("QUEUED", id))),
      submitJob: vi.fn().mockResolvedValue(job("QUEUED", JOB_B)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    const detailRegion = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailRegion).findByText(JOB_A)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));

    const selectedB = await screen.findByRole("button", { name: new RegExp(JOB_B) });
    await waitFor(() => expect(selectedB).toHaveAttribute("aria-current", "true"));
    expect(screen.getByRole("button", { name: new RegExp(JOB_A) })).not.toHaveAttribute("aria-current", "true");
    await waitFor(() => expect(screen.getByRole("region", { name: "Chi tiết công việc" })).toHaveTextContent(JOB_B));
    expect(api.listJobs).toHaveBeenCalledTimes(2);
  });

  it("P2-01B ignores a stale detail response that completes after a successful new submission", async () => {
    const detailA = deferred<JobResponse>();
    const api = setup("CLIENT", {
      listJobs: vi.fn()
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A)], next_cursor: null })
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob: vi.fn().mockImplementation((id: string) => id === JOB_A
        ? detailA.promise
        : Promise.resolve(job("QUEUED", JOB_B))),
      submitJob: vi.fn().mockResolvedValue(job("QUEUED", JOB_B)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    await waitFor(() => expect(api.getJob).toHaveBeenCalledWith(JOB_A, expect.any(AbortSignal)));
    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    expect(await within(await screen.findByRole("region", { name: "Chi tiết công việc" })).findByText(JOB_B)).toBeInTheDocument();

    await act(async () => {
      detailA.resolve(job("QUEUED", JOB_A));
      await detailA.promise;
    });

    const currentDetail = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
    expect(currentDetail.getByText(JOB_B)).toBeInTheDocument();
    expect(currentDetail.queryByText(JOB_A)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(JOB_B) })).toHaveAttribute("aria-current", "true");
    expect(screen.queryByText("Đang tải chi tiết…")).not.toBeInTheDocument();
  });

  it("P2-01C keeps the same Job selected after cancel and refreshes its list state", async () => {
    const listJobs = vi.fn()
      .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A)], next_cursor: null })
      .mockResolvedValueOnce({ items: [job("CANCELLED", JOB_A)], next_cursor: null });
    const api = setup("CLIENT", {
      listJobs,
      getJob: vi.fn().mockResolvedValue(job("QUEUED", JOB_A)),
      cancelJob: vi.fn().mockResolvedValue(job("CANCELLED", JOB_A)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: new RegExp(JOB_A) })).toHaveAttribute("aria-current", "true");
    expect(await within(screen.getByRole("region", { name: "Chi tiết công việc" })).findByText("Đã hủy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });

  it("P2-02A reconciles a Cancel 409 against the server and removes the stale Cancel action", async () => {
    const listJobs = vi.fn()
      .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A)], next_cursor: null })
      .mockResolvedValueOnce({ items: [job("RUNNING", JOB_A)], next_cursor: null });
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockResolvedValueOnce(job("RUNNING", JOB_A));
    const cancelJob = vi.fn().mockRejectedValue(new JobsApiError("JOB_NOT_CANCELLABLE", 409));
    setup("CLIENT", { listJobs, getJob, cancelJob });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));

    expect(await within(screen.getByRole("region", { name: "Chi tiết công việc" })).findByText("Đang chạy")).toBeInTheDocument();
    expect(getJob).toHaveBeenCalledTimes(2);
    expect(listJobs).toHaveBeenCalledTimes(2);
    expect(cancelJob).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });

  it("P2-02B locks Cancel when conflict reconciliation fails and allows an explicit status reload", async () => {
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockRejectedValueOnce(new JobsApiError("DEPENDENCY_UNAVAILABLE", 503))
      .mockResolvedValueOnce(job("RUNNING", JOB_A));
    const api = setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A)], next_cursor: null }),
      getJob,
      cancelJob: vi.fn().mockRejectedValue(new JobsApiError("JOB_NOT_CANCELLABLE", 409)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Dịch vụ tạm thời chưa sẵn sàng");
    expect(screen.getByRole("button", { name: "Tải lại trạng thái" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hủy công việc" })).toBeDisabled();
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).queryByText("Đã hủy")).not.toBeInTheDocument();
    expect(api.cancelJob).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Tải lại trạng thái" }));
    expect(await within(screen.getByRole("region", { name: "Chi tiết công việc" })).findByText("Đang chạy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });

  it("P2-02D reconciles an uncertain Cancel without automatically posting Cancel again", async () => {
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockResolvedValueOnce(job("RUNNING", JOB_A));
    const cancelJob = vi.fn().mockRejectedValue(new JobsApiError("NETWORK_ERROR", 0));
    const api = setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A)], next_cursor: null }),
      getJob,
      cancelJob,
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    expect(await within(screen.getByRole("region", { name: "Chi tiết công việc" })).findByText("Đang chạy")).toBeInTheDocument();
    expect(api.getJob).toHaveBeenCalledTimes(2);
    expect(cancelJob).toHaveBeenCalledTimes(1);
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).queryByText("Đã hủy")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });

  it("P2-03A ignores a late successful Cancel for A after selecting B", async () => {
    const cancelA = deferred<JobResponse>();
    const listJobs = vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null });
    const api = setup("CLIENT", {
      listJobs,
      getJob: vi.fn().mockImplementation((id: string) => Promise.resolve(job("QUEUED", id))),
      cancelJob: vi.fn().mockReturnValue(cancelA.promise),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    const detailRegion = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailRegion).findByText(JOB_A)).toBeInTheDocument();
    fireEvent.click(within(detailRegion).getByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith(JOB_A));

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_B) }));
    const selectedB = screen.getByRole("button", { name: new RegExp(JOB_B) });
    await waitFor(() => expect(selectedB).toHaveAttribute("aria-current", "true"));
    const detailB = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailB).findByText(JOB_B)).toBeInTheDocument();
    cancelA.resolve(job("CANCELLED", JOB_A));

    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2));
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByText(JOB_B)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(JOB_B) })).toHaveAttribute("aria-current", "true");
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByRole("button", { name: "Hủy công việc" })).toBeEnabled();
    expect(api.cancelJob).toHaveBeenCalledTimes(1);
  });

  it("P2-03B ignores a late 409 reconciliation for A after selecting B", async () => {
    const reconciliationA = deferred<JobResponse>();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockReturnValueOnce(reconciliationA.promise)
      .mockImplementation((id: string) => Promise.resolve(job("QUEUED", id)));
    const api = setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob,
      cancelJob: vi.fn().mockRejectedValue(new JobsApiError("JOB_NOT_CANCELLABLE", 409)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(2));

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_B) }));
    const selectedB = screen.getByRole("button", { name: new RegExp(JOB_B) });
    await waitFor(() => expect(selectedB).toHaveAttribute("aria-current", "true"));
    const detailB = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailB).findByText(JOB_B)).toBeInTheDocument();
    await act(async () => {
      reconciliationA.resolve(job("RUNNING", JOB_A));
      await reconciliationA.promise;
    });

    const currentDetailB = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
    expect(currentDetailB.getByText(JOB_B)).toBeInTheDocument();
    expect(currentDetailB.queryByText(JOB_A)).not.toBeInTheDocument();
    expect(currentDetailB.getByRole("button", { name: "Hủy công việc" })).toBeEnabled();
    expect(currentDetailB.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(JOB_B) })).toHaveAttribute("aria-current", "true");
    expect(api.cancelJob).toHaveBeenCalledTimes(1);
  });

  it("P2-03C keeps A's failed reconciliation state isolated after selecting B", async () => {
    const reconciliationA = deferred<JobResponse>();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockReturnValueOnce(reconciliationA.promise)
      .mockImplementation((id: string) => Promise.resolve(job("QUEUED", id)));
    const api = setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob,
      cancelJob: vi.fn().mockRejectedValue(new JobsApiError("NETWORK_ERROR", 0)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(2));

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_B) }));
    const selectedB = screen.getByRole("button", { name: new RegExp(JOB_B) });
    await waitFor(() => expect(selectedB).toHaveAttribute("aria-current", "true"));
    const detailB = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailB).findByText(JOB_B)).toBeInTheDocument();
    await act(async () => {
      reconciliationA.reject(new JobsApiError("DEPENDENCY_UNAVAILABLE", 503));
      await reconciliationA.promise.catch(() => undefined);
    });

    const currentDetailB = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
    expect(currentDetailB.getByText(JOB_B)).toBeInTheDocument();
    expect(currentDetailB.queryByText(JOB_A)).not.toBeInTheDocument();
    expect(currentDetailB.queryByRole("alert")).not.toBeInTheDocument();
    expect(currentDetailB.getByRole("button", { name: "Hủy công việc" })).toBeEnabled();
    expect(screen.getByRole("button", { name: new RegExp(JOB_B) })).toHaveAttribute("aria-current", "true");
    expect(api.cancelJob).toHaveBeenCalledTimes(1);
  });

  it("P2-03D starts a fresh A detail request after A to B to A and ignores old reconciliation", async () => {
    const reconciliationA = deferred<JobResponse>();
    const currentDetailA = deferred<JobResponse>();
    let aReads = 0;
    const getJob = vi.fn((id: string) => {
      if (id === JOB_A) {
        aReads += 1;
        if (aReads === 1) return Promise.resolve(job("QUEUED", JOB_A));
        if (aReads === 2) return reconciliationA.promise;
        return currentDetailA.promise;
      }
      return Promise.resolve(job("QUEUED", JOB_B));
    });
    const api = setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob,
      cancelJob: vi.fn().mockRejectedValue(new JobsApiError("JOB_NOT_CANCELLABLE", 409)),
    });

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    const initialDetailA = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(initialDetailA).findByText(JOB_A)).toBeInTheDocument();
    fireEvent.click(within(initialDetailA).getByRole("button", { name: "Hủy công việc" }));
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(2));
    expect(getJob).toHaveBeenLastCalledWith(JOB_A);

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_B) }));
    const detailB = await screen.findByRole("region", { name: "Chi tiết công việc" });
    expect(await within(detailB).findByText(JOB_B)).toBeInTheDocument();
    expect(within(detailB).getByRole("button", { name: "Hủy công việc" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: new RegExp(JOB_A) }));
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(4));
    expect(screen.getByText("Đang tải chi tiết…")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Chi tiết công việc" })).not.toBeInTheDocument();

    await act(async () => {
      currentDetailA.resolve(job("RUNNING", JOB_A));
      await currentDetailA.promise;
    });
    const freshDetailA = within(screen.getByRole("region", { name: "Chi tiết công việc" }));
    expect(freshDetailA.getByText(JOB_A)).toBeInTheDocument();
    expect(freshDetailA.getByRole("status")).toHaveTextContent("Đang chạy");
    expect(freshDetailA.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();

    await act(async () => {
      reconciliationA.resolve(job("QUEUED", JOB_A));
      await reconciliationA.promise;
    });
    expect(freshDetailA.getByText(JOB_A)).toBeInTheDocument();
    expect(freshDetailA.getByRole("status")).toHaveTextContent("Đang chạy");
    expect(freshDetailA.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
    expect(api.cancelJob).toHaveBeenCalledTimes(1);
    expect(getJob).toHaveBeenCalledTimes(4);
  });

  it("prevents a double submit and retains the same key and payload after an uncertain response", async () => {
    const resolveRetry = (() => {
      let finish!: (value: JobResponse) => void;
      const pending = new Promise<JobResponse>((resolve) => { finish = resolve; });
      return { pending, finish: () => finish(job()) };
    })();
    const submitJob = vi.fn()
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockReturnValueOnce(resolveRetry.pending);
    setup("CLIENT", { submitJob });

    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.change(screen.getByLabelText("Số GPU"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Thời lượng (giây)"), { target: { value: "60" } });
    const submit = screen.getByRole("button", { name: "Gửi công việc" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await screen.findByRole("button", { name: "Thử lại cùng yêu cầu" });
    expect(submitJob).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Số GPU")).toBeDisabled();

    const firstAttempt = submitJob.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", { name: "Thử lại cùng yêu cầu" }));
    await waitFor(() => expect(submitJob).toHaveBeenCalledTimes(2));
    expect(submitJob.mock.calls[1][0]).toBe(firstAttempt);
    expect(submitJob.mock.calls[1][0].key).toBe(firstAttempt.key);
    expect(submitJob.mock.calls[1][0].request).toEqual({ listing_id: LISTING_ID, gpu_count: 2, duration_seconds: 60 });
    resolveRetry.finish();
    expect(await screen.findByText(new RegExp(`Đã gửi công việc ${JOB_ID}`))).toBeInTheDocument();
  });

  it("reuses the key for the same rejected logical submission and creates a new one only after input changes", async () => {
    const submitJob = vi.fn()
      .mockRejectedValueOnce(new JobsApiError("IDEMPOTENCY_KEY_REUSED", 409))
      .mockRejectedValueOnce(new JobsApiError("IDEMPOTENCY_KEY_REUSED", 409))
      .mockResolvedValueOnce(job());
    setup("CLIENT", { submitJob });
    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    await screen.findByText("Khóa gửi đã được dùng với nội dung khác.");
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    await waitFor(() => expect(submitJob).toHaveBeenCalledTimes(2));
    expect(submitJob.mock.calls[1][0].key).toBe(submitJob.mock.calls[0][0].key);

    fireEvent.change(screen.getByLabelText("Số GPU"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    await screen.findByText(new RegExp(`Đã gửi công việc ${JOB_ID}`));
    expect(submitJob).toHaveBeenCalledTimes(3);
    expect(submitJob.mock.calls[2][0].key).not.toBe(submitJob.mock.calls[0][0].key);
    expect(submitJob.mock.calls[2][0].request.gpu_count).toBe(2);
  });

  it("does not expose Submit to Worker/Admin or protected Job fields", async () => {
    const unsafe = { ...job(), client_id: "private-client-id", simulation_reference: { expected_digest: "secret" } };
    setup("ADMIN", { listJobs: vi.fn().mockResolvedValue({ items: [unsafe], next_cursor: null }) });
    expect(await screen.findByText(JOB_ID)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Gửi công việc" })).not.toBeInTheDocument();
    expect(screen.queryByText("private-client-id")).not.toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy công việc" })).not.toBeInTheDocument();
  });
});

async function flushReactPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function selectJob(id = JOB_ID) {
  await flushReactPromises();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(id) }));
  await flushReactPromises();
}

function detailStatus() {
  return within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByRole("status");
}

async function advanceClock(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

describe("VT-090 async status tracking and retry safety", () => {
  it("polls a selected queued Job at the 2-second boundary and displays RUNNING", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockResolvedValueOnce(job("RUNNING"));
    const api = setup("CLIENT", { getJob });
    await selectJob();

    expect(getJob).toHaveBeenCalledTimes(1);
    await advanceClock(1999);
    expect(getJob).toHaveBeenCalledTimes(1);
    await advanceClock(1);
    expect(getJob).toHaveBeenCalledTimes(2);
    expect(detailStatus()).toHaveTextContent("Đang chạy");
    expect(api.submitJob).not.toHaveBeenCalled();
  });

  it.each([
    ["COMPLETED", "Hoàn tất"],
    ["FAILED", "Thất bại"],
    ["CANCELLED", "Đã hủy"],
  ] as const)("stops polling when the server reports terminal status %s", async (terminalStatus, label) => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockResolvedValueOnce(job(terminalStatus));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(detailStatus()).toHaveTextContent(label);
    await advanceClock(12000);
    expect(getJob).toHaveBeenCalledTimes(2);
  });

  it("never starts an overlapping poll while the previous GET is pending", async () => {
    vi.useFakeTimers();
    const pendingPoll = deferred<JobResponse>();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockReturnValueOnce(pendingPoll.promise)
      .mockResolvedValue(job("RUNNING"));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(4999);
    expect(getJob).toHaveBeenCalledTimes(2);
    await act(async () => { pendingPoll.resolve(job("RUNNING")); await pendingPoll.promise; });
    await advanceClock(1999);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(1);
    expect(getJob).toHaveBeenCalledTimes(3);
  });

  it("ignores a delayed response from Job A after the user selects Job B", async () => {
    vi.useFakeTimers();
    const delayedA = deferred<JobResponse>();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED", JOB_A))
      .mockReturnValueOnce(delayedA.promise)
      .mockResolvedValueOnce(job("RUNNING", JOB_B));
    setup("CLIENT", {
      listJobs: vi.fn().mockResolvedValue({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob,
    });
    await selectJob(JOB_A);
    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(JOB_B) }));
    await flushReactPromises();
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByText(JOB_B)).toBeInTheDocument();

    await act(async () => { delayedA.resolve(job("COMPLETED", JOB_A)); await delayedA.promise; });
    expect(within(screen.getByRole("region", { name: "Chi tiết công việc" })).getByText(JOB_B)).toBeInTheDocument();
    expect(detailStatus()).toHaveTextContent("Đang chạy");
  });

  it("clears the scheduled GET when the component unmounts", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn().mockResolvedValue(job("QUEUED"));
    const api: JobsApi = {
      listJobs: vi.fn().mockResolvedValue({ items: [job()], next_cursor: null }),
      getJob,
      submitJob: vi.fn(),
      cancelJob: vi.fn(),
    };
    const view = render(<JobsPage api={api} user={user("CLIENT")} />);
    await selectJob();
    expect(getJob).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    view.unmount();
    await advanceClock(10000);
    expect(getJob).toHaveBeenCalledTimes(1);
  });

  it("invalidates an in-flight response when identity changes", async () => {
    vi.useFakeTimers();
    const delayedPoll = deferred<JobResponse>();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockReturnValueOnce(delayedPoll.promise)
      .mockResolvedValueOnce(job("RUNNING"));
    const api: JobsApi = {
      listJobs: vi.fn().mockResolvedValue({ items: [job()], next_cursor: null }),
      getJob,
      submitJob: vi.fn(),
      cancelJob: vi.fn(),
    };
    const view = render(<JobsPage api={api} user={user("CLIENT")} />);
    await selectJob();
    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    const otherIdentity = { ...user("CLIENT"), id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" };
    view.rerender(<JobsPage api={api} user={otherIdentity} />);
    await flushReactPromises();
    await act(async () => { delayedPoll.resolve(job("COMPLETED")); await delayedPoll.promise; });
    expect(detailStatus()).toHaveTextContent("Đang chạy");
  });

  it.each([
    ["network timeout", new JobsApiError("NETWORK_ERROR", 0)],
    ["HTTP 503", new JobsApiError("DEPENDENCY_UNAVAILABLE", 503)],
  ])("retries a transient %s with GET only", async (_label, transientError) => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValueOnce(transientError)
      .mockResolvedValueOnce(job("RUNNING"));
    const api = setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(999);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(1);
    expect(getJob).toHaveBeenCalledTimes(3);
    expect(detailStatus()).toHaveTextContent("Đang chạy");
    expect(api.submitJob).not.toHaveBeenCalled();
  });

  it("times out a stalled status GET after five seconds and retries GET only", async () => {
    vi.useFakeTimers();
    let timedSignal: AbortSignal | undefined;
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockImplementationOnce((_jobId: string, signal?: AbortSignal) => new Promise<JobResponse>((_, reject) => {
        timedSignal = signal;
        signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }))
      .mockResolvedValueOnce(job("RUNNING"));
    const api = setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(4999);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(1);
    expect(timedSignal?.aborted).toBe(true);
    await advanceClock(1000);
    expect(getJob).toHaveBeenCalledTimes(3);
    expect(detailStatus()).toHaveTextContent("Đang chạy");
    expect(api.submitJob).not.toHaveBeenCalled();
  });

  it("allows the fourth poll after exactly three transient failures", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockResolvedValueOnce(job("RUNNING"));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(1000);
    expect(getJob).toHaveBeenCalledTimes(3);
    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(4);
    await advanceClock(4000);
    expect(getJob).toHaveBeenCalledTimes(5);
    expect(detailStatus()).toHaveTextContent("Đang chạy");
  });

  it("stops after the fourth consecutive transient failure and keeps explicit reload", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValue(new JobsApiError("NETWORK_ERROR", 0));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    await advanceClock(1000);
    await advanceClock(2000);
    await advanceClock(4000);
    expect(getJob).toHaveBeenCalledTimes(5);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(detailStatus()).toHaveTextContent("Đang chờ");
    await advanceClock(20000);
    expect(getJob).toHaveBeenCalledTimes(5);
  });

  it("does not retry a non-transient 404 automatically", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValueOnce(new JobsApiError("JOB_NOT_FOUND", 404));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(10000);
    expect(getJob).toHaveBeenCalledTimes(2);
  });

  it("resets the transient failure counter after a successful poll", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockResolvedValueOnce(job("RUNNING"))
      .mockResolvedValueOnce(job("RUNNING"));
    setup("CLIENT", { getJob });
    await selectJob();

    await advanceClock(2000);
    await advanceClock(1000);
    expect(getJob).toHaveBeenCalledTimes(3);
    await advanceClock(1999);
    expect(getJob).toHaveBeenCalledTimes(3);
    await advanceClock(1);
    expect(getJob).toHaveBeenCalledTimes(4);
  });

  it("does not create a second Job or duplicate success notice when polling fails then recovers", async () => {
    vi.useFakeTimers();
    const getJob = vi.fn()
      .mockResolvedValueOnce(job("QUEUED"))
      .mockRejectedValueOnce(new JobsApiError("NETWORK_ERROR", 0))
      .mockResolvedValueOnce(job("COMPLETED"));
    const submitJob = vi.fn().mockResolvedValue(job("QUEUED"));
    setup("CLIENT", { getJob, submitJob });
    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    await flushReactPromises();

    expect(submitJob).toHaveBeenCalledTimes(1);
    expect(getJob).toHaveBeenCalledTimes(1);
    await advanceClock(2000);
    expect(getJob).toHaveBeenCalledTimes(2);
    await advanceClock(1000);
    expect(getJob).toHaveBeenCalledTimes(3);
    expect(submitJob).toHaveBeenCalledTimes(1);
    expect(detailStatus()).toHaveTextContent("Hoàn tất");
    expect(screen.getAllByText(new RegExp(`Đã gửi công việc ${JOB_ID}`))).toHaveLength(1);
  });
});
