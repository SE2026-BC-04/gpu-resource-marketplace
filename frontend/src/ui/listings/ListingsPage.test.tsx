import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Listing, ListingPage } from "../../api/listings";
import { ListingsApiError } from "../../api/listings";
import { ListingsPage } from "./ListingsPage";
import { fakeApi, LISTING_ID, sample, USER_ID } from "./__tests__/fixtures";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const worker = { userId: USER_ID, role: "WORKER" as const };

async function mine() {
  fireEvent.change(screen.getByLabelText("Phạm vi"), { target: { value: "mine" } });
  await screen.findByRole("button", { name: "Chỉnh sửa" });
}

describe("Listings UI with injected session and test API", () => {
  it("requires the real shell session instead of offering a fake login", () => {
    const api = fakeApi();
    render(<ListingsPage session={null} api={api} />);
    expect(screen.getByText(/Vui lòng đăng nhập/)).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
  });

  it.each(["CLIENT", "ADMIN"] as const)("keeps %s read-only", async role => {
    const api = fakeApi();
    render(<ListingsPage session={{ userId: USER_ID, role }} api={api} />);
    await screen.findByText("A100 simulated");
    expect(screen.queryByRole("button", { name: "Tạo Listing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Chỉnh sửa" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạm dừng" })).not.toBeInTheDocument();
    if (role === "ADMIN") {
      fireEvent.change(screen.getByLabelText("Phạm vi"), { target: { value: "all" } });
      await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ scope: "all" }), expect.anything()));
    }
  });

  it("shows details, exact mock price, reputation and snapshot caveat", async () => {
    const api = fakeApi();
    render(<ListingsPage session={worker} api={api} />);
    fireEvent.click(await screen.findByRole("button", { name: "Xem chi tiết" }));
    await screen.findByText("0.7000");
    expect(api.get).toHaveBeenCalledWith(LISTING_ID, expect.anything());
    expect(screen.getByText(/không phải giữ chỗ GPU/)).toBeInTheDocument();
    expect(screen.getAllByText("12.50")).toHaveLength(2);
  });

  it("creates a Listing using strict integer fields and an exact decimal string", async () => {
    const api = fakeApi();
    render(<ListingsPage session={worker} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Tạo Listing" }));
    fireEvent.change(screen.getByLabelText("Model GPU"), { target: { value: " A100 " } });
    fireEvent.change(screen.getByLabelText("VRAM (GB)"), { target: { value: "80" } });
    fireEvent.change(screen.getByLabelText("Tổng GPU"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Giá mô phỏng mỗi giờ (tùy chọn)"), { target: { value: "12.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu Listing" }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ gpu_model: "A100", vram_gb: 80, total_gpu_count: 8, mock_price_per_hour: "12.50" }, expect.anything()));
    await waitFor(() => expect(screen.getByLabelText("Phạm vi")).toHaveValue("mine"));
  });

  it.each(["1.5", "1e2", "0", "-1", "2147483648"])("rejects invalid integer input %s before sending", async value => {
    const api = fakeApi();
    render(<ListingsPage session={worker} api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Tạo Listing" }));
    fireEvent.change(screen.getByLabelText("Model GPU"), { target: { value: "A100" } });
    fireEvent.change(screen.getByLabelText("VRAM (GB)"), { target: { value } });
    fireEvent.change(screen.getByLabelText("Tổng GPU"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu Listing" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("số nguyên dương");
    expect(api.create).not.toHaveBeenCalled();
  });

  it("sends only changed PATCH fields, including null to clear price", async () => {
    const api = fakeApi();
    render(<ListingsPage session={worker} api={api} />);
    await mine();
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh sửa" }));
    fireEvent.change(screen.getByLabelText("Giá mô phỏng mỗi giờ (tùy chọn)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu Listing" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(LISTING_ID, { mock_price_per_hour: null }, expect.anything()));
  });

  it("keeps the edit form and original data on capacity conflict", async () => {
    const api = fakeApi();
    vi.mocked(api.patch).mockRejectedValue(new ListingsApiError("LISTING_CAPACITY_BELOW_ALLOCATED", 409));
    render(<ListingsPage session={worker} api={api} />);
    await mine();
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh sửa" }));
    fireEvent.change(screen.getByLabelText("Tổng GPU"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu Listing" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("đang được cấp phát");
    expect(screen.getByRole("heading", { name: "Chỉnh sửa Listing" })).toBeInTheDocument();
    expect(screen.getByText("5 / 8")).toBeInTheDocument();
  });

  it("prevents duplicate pause submissions while waiting for the server", async () => {
    const api = fakeApi();
    let finish!: (value: Listing) => void;
    vi.mocked(api.pause).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<ListingsPage session={worker} api={api} />);
    await mine();
    const pause = screen.getByRole("button", { name: "Tạm dừng" });
    fireEvent.click(pause);
    fireEvent.click(pause);
    expect(api.pause).toHaveBeenCalledOnce();
    expect(pause).toBeDisabled();
    finish(sample({ status: "PAUSED", accepting_jobs: false }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tạm dừng" })).not.toBeDisabled());
  });

  it("uses opaque cursors for next/previous pages", async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValue({ items: [sample()], next_cursor: "opaque-next-page" });
    render(<ListingsPage session={worker} api={api} />);
    await screen.findByText("A100 simulated");
    fireEvent.click(screen.getByRole("button", { name: "Trang sau" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "opaque-next-page" }), expect.anything()));
    await screen.findByText("A100 simulated");
    fireEvent.click(screen.getByRole("button", { name: "Trang trước" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: undefined }), expect.anything()));
  });

  it("does not restore stale data after a scope change or logout", async () => {
    const api = fakeApi();
    let finishFirst!: (value: ListingPage) => void;
    vi.mocked(api.list).mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve; }))
      .mockResolvedValue({ items: [sample({ gpu_model: "Current private Listing" })], next_cursor: null });
    const view = render(<ListingsPage session={worker} api={api} />);
    fireEvent.change(screen.getByLabelText("Phạm vi"), { target: { value: "mine" } });
    await screen.findByText("Current private Listing");
    finishFirst({ items: [sample({ gpu_model: "Stale previous data" })], next_cursor: null });
    await waitFor(() => expect(screen.queryByText("Stale previous data")).not.toBeInTheDocument());
    view.rerender(<ListingsPage session={null} api={api} />);
    expect(screen.queryByText("Current private Listing")).not.toBeInTheDocument();
  });

  it("shows empty and failure states without creating hardcoded Listings", async () => {
    const api = fakeApi();
    vi.mocked(api.list).mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockRejectedValueOnce(new ListingsApiError("DEPENDENCY_UNAVAILABLE", 503));
    render(<ListingsPage session={worker} api={api} />);
    await screen.findByText("Chưa có Listing phù hợp.");
    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("chưa sẵn sàng");
    expect(screen.queryByText("A100 simulated")).not.toBeInTheDocument();
  });
});
