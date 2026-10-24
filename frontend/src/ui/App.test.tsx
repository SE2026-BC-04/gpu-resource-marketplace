import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthApiError } from "../api/auth";
import type { AuthApi, AuthUser, LoginResult, UserRole } from "../api/auth";
import { createSessionStore } from "../api/session";
import { App } from "./App";
import { SIGN_IN_TIMEOUT_MS } from "./auth/LoginForm";

const PASSWORD = "correct horse battery staple";
const TOKEN = "header.payload.signature";

function account(role: UserRole): AuthUser {
  return { id: "8bf66294-daf8-42fa-a167-50a3a43b7b66", loginName: `demo_${role.toLowerCase()}_01`, role };
}

function setup(overrides: Partial<AuthApi> = {}, role: UserRole = "CLIENT") {
  const user = account(role);
  const api = {
    login: vi.fn<AuthApi["login"]>().mockResolvedValue({ accessToken: TOKEN, expiresInSeconds: 900, user }),
    me: vi.fn<AuthApi["me"]>().mockResolvedValue(user),
    logout: vi.fn<AuthApi["logout"]>().mockResolvedValue(undefined),
    ...overrides,
  };
  const session = createSessionStore(api);
  render(<App session={session} />);
  return { api, session, user };
}

function fillAndSubmit(loginName: string, password = PASSWORD) {
  fireEvent.change(screen.getByLabelText("Tên đăng nhập"), { target: { value: loginName } });
  fireEvent.change(screen.getByLabelText("Mật khẩu"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("App shell with Login", () => {
  it("keeps the foundation page and starts at Login", () => {
    setup();
    expect(screen.getByRole("heading", { name: "GPU Resource Marketplace" })).toBeInTheDocument();
    expect(screen.getByText("Development preview", { selector: ".status" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("type", "password");
  });

  it.each([
    ["CLIENT", "Client — thuê GPU"],
    ["WORKER", "Worker — cho thuê GPU"],
    ["ADMIN", "Admin — chỉ xem"],
  ] as const)("runs Login -> Me -> Logout for %s", async (role, label) => {
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((name) => vi.spyOn(console, name));
    const { api, user } = setup({}, role);
    fillAndSubmit(user.loginName);
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText(user.loginName)).toBeInTheDocument();
    expect(api.login).toHaveBeenCalledWith(user.loginName, PASSWORD, expect.any(AbortSignal));
    expect(api.me).toHaveBeenCalledWith(TOKEN, expect.any(AbortSignal));
    expect(document.body.textContent).not.toContain(PASSWORD);
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(screen.getByText(/Máy chủ không thu hồi mã đã cấp/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByText("Bạn đã đăng xuất.")).toBeInTheDocument();
    expect(api.logout).toHaveBeenCalledWith(TOKEN);
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
    consoleSpies.forEach((spy) => expect(spy).not.toHaveBeenCalled());
  });

  it("asks for both fields without calling the API", () => {
    const { api } = setup();
    fillAndSubmit(" \t ", PASSWORD);
    expect(screen.getByRole("alert")).toHaveTextContent("Vui lòng nhập tên đăng nhập và mật khẩu.");
    fillAndSubmit("demo_client_01", "");
    expect(screen.getByRole("alert")).toHaveTextContent("Vui lòng nhập tên đăng nhập và mật khẩu.");
    expect(api.login).not.toHaveBeenCalled();
  });

  it("shows the generic credential message, clears the password and logs nothing", async () => {
    const consoleSpies = (["log", "info", "warn", "error", "debug"] as const).map((name) => vi.spyOn(console, name));
    setup({ login: vi.fn().mockRejectedValue(new AuthApiError("INVALID_CREDENTIALS", 401)) });
    fillAndSubmit("demo_client_01");
    expect(await screen.findByRole("alert")).toHaveTextContent("Tên đăng nhập hoặc mật khẩu không đúng.");
    expect(screen.getByLabelText("Mật khẩu")).toHaveValue("");
    expect(screen.getByLabelText("Tên đăng nhập")).toHaveValue("demo_client_01");
    expect(document.body.textContent).not.toContain(PASSWORD);
    consoleSpies.forEach((spy) => expect(spy).not.toHaveBeenCalled());
  });

  it.each([
    ["INVALID_JSON", 400, "Yêu cầu không hợp lệ. Hãy tải lại trang và thử lại."],
    ["PAYLOAD_TOO_LARGE", 413, "Thông tin nhập quá dài."],
    ["VALIDATION_ERROR", 422, "Vui lòng nhập tên đăng nhập và mật khẩu hợp lệ."],
    ["DEPENDENCY_UNAVAILABLE", 503, "Dịch vụ tạm thời chưa sẵn sàng. Hãy thử lại sau."],
    ["NETWORK_ERROR", 0, "Không kết nối được máy chủ. Kiểm tra mạng và thử lại."],
  ])("shows the fixed message for %s", async (code, status, message) => {
    setup({ login: vi.fn().mockRejectedValue(new AuthApiError(code, status)) });
    fillAndSubmit("demo_client_01");
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeEnabled();
  });

  it("explains a sign-in that /me could not confirm", async () => {
    setup({ me: vi.fn().mockRejectedValue(new AuthApiError("UNAUTHORIZED", 401)) });
    fillAndSubmit("demo_client_01");
    expect(await screen.findByRole("alert")).toHaveTextContent("Không xác nhận được tài khoản. Vui lòng đăng nhập lại.");
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).not.toBeInTheDocument();
  });

  it("gives up on a hanging Login after the timeout", async () => {
    vi.useFakeTimers();
    const hang = vi.fn((_name: string, _password: string, signal?: AbortSignal) => new Promise<LoginResult>((_, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    setup({ login: hang });
    fillAndSubmit("demo_client_01");
    expect(screen.getByRole("button", { name: "Đang đăng nhập…" })).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(SIGN_IN_TIMEOUT_MS); });
    expect(screen.getByRole("alert")).toHaveTextContent("Máy chủ không phản hồi. Vui lòng thử lại.");
    expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeEnabled();
  });

  it("lets the user cancel a pending Login without an error", async () => {
    const hang = vi.fn((_name: string, _password: string, signal?: AbortSignal) => new Promise<LoginResult>((_, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    setup({ login: hang });
    fillAndSubmit("demo_client_01");
    fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
    expect(await screen.findByRole("button", { name: "Đăng nhập" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hủy" })).not.toBeInTheDocument();
  });

  it("does not show raw text from an unexpected error", async () => {
    setup({ login: vi.fn().mockRejectedValue(new Error(`boom ${PASSWORD}`)) });
    fillAndSubmit("demo_client_01");
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể đăng nhập lúc này.");
    expect(document.body.textContent).not.toContain(PASSWORD);
  });

  it("disables the form while signing in", async () => {
    let finish!: () => void;
    const user = account("CLIENT");
    setup({
      login: vi.fn(() => new Promise<LoginResult>((resolve) => {
        finish = () => resolve({ accessToken: TOKEN, expiresInSeconds: 900, user });
      })),
    });
    fillAndSubmit(user.loginName);
    expect(screen.getByRole("button", { name: "Đang đăng nhập…" })).toBeDisabled();
    expect(screen.getByLabelText("Tên đăng nhập")).toBeDisabled();
    await act(async () => finish());
    expect(await screen.findByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });

  it("returns to Login with a notice when the session expires", async () => {
    vi.useFakeTimers();
    const { user } = setup();
    fillAndSubmit(user.loginName);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(900_000); });
    expect(screen.getByRole("status")).toHaveTextContent("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  });

  it("returns to Login when another API client reports 401", async () => {
    const { session, user } = setup();
    fillAndSubmit(user.loginName);
    await screen.findByRole("button", { name: "Đăng xuất" });
    act(() => session.handleUnauthorized(TOKEN));
    expect(screen.getByRole("status")).toHaveTextContent("Phiên đăng nhập không còn hợp lệ.");
    expect(session.getAccessToken()).toBeNull();
  });
});
