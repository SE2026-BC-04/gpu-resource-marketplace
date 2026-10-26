import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    started_at: null,
    terminal_at: status === "CANCELLED" ? "2026-10-26T08:01:00.000000Z" : null,
  };
}

function user(role: UserRole): AuthUser {
  return { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", loginName: `test_${role.toLowerCase()}`, role };
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
    let finishA!: (value: JobResponse) => void;
    const api = setup("CLIENT", {
      listJobs: vi.fn()
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A)], next_cursor: null })
        .mockResolvedValueOnce({ items: [job("QUEUED", JOB_A), job("QUEUED", JOB_B)], next_cursor: null }),
      getJob: vi.fn().mockImplementation((id: string) => id === JOB_A
        ? new Promise<JobResponse>((resolve) => { finishA = resolve; })
        : Promise.resolve(job("QUEUED", JOB_B))),
      submitJob: vi.fn().mockResolvedValue(job("QUEUED", JOB_B)),
    });
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(JOB_A) }));
    await waitFor(() => expect(api.getJob).toHaveBeenCalledWith(JOB_A, expect.any(AbortSignal)));
    fireEvent.change(screen.getByLabelText("Listing ID (UUIDv4)"), { target: { value: LISTING_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi công việc" }));
    expect(await within(await screen.findByRole("region", { name: "Chi tiết công việc" })).findByText(JOB_B)).toBeInTheDocument();
    finishA(job("QUEUED", JOB_A));
    const detailRegion = screen.getByRole("region", { name: "Chi tiết công việc" });
    await waitFor(() => expect(within(detailRegion).getByText(JOB_B)).toBeInTheDocument());
    expect(within(detailRegion).queryByText(JOB_A)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(JOB_B) })).toHaveAttribute("aria-current", "true");
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
