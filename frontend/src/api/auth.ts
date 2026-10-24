import { config } from "../config";

export type UserRole = "CLIENT" | "WORKER" | "ADMIN";

/** Identity from Login and /auth/me (API Contract section 4.2, section 4.3). */
export interface AuthUser {
  id: string;
  loginName: string;
  role: UserRole;
}

export interface LoginResult {
  accessToken: string;
  expiresInSeconds: number;
  user: AuthUser;
}

export interface AuthApi {
  login(loginName: string, password: string, signal?: AbortSignal): Promise<LoginResult>;
  me(token: string, signal?: AbortSignal): Promise<AuthUser>;
  logout(token: string, signal?: AbortSignal): Promise<void>;
}

const messages: Record<string, string> = {
  INVALID_CREDENTIALS: "Tên đăng nhập hoặc mật khẩu không đúng.",
  VALIDATION_ERROR: "Vui lòng nhập tên đăng nhập và mật khẩu hợp lệ.",
  INVALID_JSON: "Yêu cầu không hợp lệ. Hãy tải lại trang và thử lại.",
  PAYLOAD_TOO_LARGE: "Thông tin nhập quá dài.",
  UNAUTHORIZED: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
  DEPENDENCY_UNAVAILABLE: "Dịch vụ tạm thời chưa sẵn sàng. Hãy thử lại sau.",
  NETWORK_ERROR: "Không kết nối được máy chủ. Kiểm tra mạng và thử lại.",
};

export class AuthApiError extends Error {
  constructor(public readonly code: string, public readonly status: number, public readonly requestId?: string) {
    // Never built from server text or user input, so it cannot echo a password or token.
    super(messages[code] ?? "Không thể xử lý yêu cầu lúc này.");
    this.name = "AuthApiError";
  }
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const roles: readonly string[] = ["CLIENT", "WORKER", "ADMIN"];
// Same cap as the API's bearer extraction (PR #18 C4): printable ASCII, at most 4096 characters.
const token = /^[\x21-\x7e]{1,4096}$/;

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidResponse(): AuthApiError {
  return new AuthApiError("INVALID_RESPONSE", 502);
}

function user(value: unknown): AuthUser {
  if (
    !object(value) || typeof value.id !== "string" || !uuid.test(value.id) ||
    typeof value.login_name !== "string" || value.login_name === "" ||
    typeof value.role !== "string" || !roles.includes(value.role)
  ) throw invalidResponse();
  return { id: value.id, loginName: value.login_name, role: value.role as UserRole };
}

function loginResult(value: unknown): LoginResult {
  if (
    !object(value) || typeof value.access_token !== "string" || !token.test(value.access_token) ||
    value.token_type !== "Bearer" || !Number.isInteger(value.expires_in) || (value.expires_in as number) <= 0
  ) throw invalidResponse();
  return { accessToken: value.access_token, expiresInSeconds: value.expires_in as number, user: user(value.user) };
}

/** HTTP client for the three Auth routes. Holds no state: the token lives only in the session store. */
export function createAuthApi(fetcher: typeof fetch = fetch): AuthApi {
  async function send(path: string, bearer: string | null, body: unknown, signal?: AbortSignal): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (bearer !== null) headers.Authorization = `Bearer ${bearer}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    try {
      return await fetcher(`${config.apiBaseUrl}/api/v1/auth${path}`, {
        method: path === "/me" ? "GET" : "POST", headers, credentials: "omit", cache: "no-store", signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (error) {
      // DOMException is not an Error subclass in every runtime, so match the name only.
      if (signal?.aborted || (error as { name?: unknown } | null)?.name === "AbortError") throw error;
      throw new AuthApiError("NETWORK_ERROR", 0);
    }
  }

  async function failure(response: Response): Promise<AuthApiError> {
    let code = response.status === 401 ? "UNAUTHORIZED" : "INTERNAL_ERROR";
    try {
      const payload: unknown = await response.json();
      if (object(payload) && object(payload.error) && typeof payload.error.code === "string") code = payload.error.code;
    } catch { /* keep the status-based code */ }
    const requestId = response.headers.get("X-Request-ID") ?? undefined;
    return new AuthApiError(code, response.status, requestId && uuid.test(requestId) ? requestId : undefined);
  }

  async function json(response: Response): Promise<unknown> {
    if (!response.ok) throw await failure(response);
    try { return await response.json(); } catch { throw invalidResponse(); }
  }

  return {
    async login(loginName, password, signal) {
      // Sent exactly as typed: the server trims the login name (DEC-P1-03) and never the password.
      return loginResult(await json(await send("/login", null, { login_name: loginName, password }, signal)));
    },
    async me(bearer, signal) {
      return user(await json(await send("/me", bearer, undefined, signal)));
    },
    async logout(bearer, signal) {
      // No body: API Contract section 4.4 / section 14.5 B5 rejects any Logout body.
      const response = await send("/logout", bearer, undefined, signal);
      if (response.status !== 204) throw await failure(response);
    },
  };
}
