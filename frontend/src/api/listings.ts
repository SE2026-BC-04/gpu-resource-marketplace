import { config } from "../config";
import type { SessionStore } from "./session";

export type UserRole = "CLIENT" | "WORKER" | "ADMIN";
export type ListingStatus = "ACTIVE" | "PAUSED";
export type ListingScope = "marketplace" | "mine" | "all";

export interface Listing {
  id: string;
  worker: {
    id: string;
    display_name: string;
    reputation: { successful_jobs: number; worker_fault_jobs: number; success_rate: string | null };
  };
  gpu_model: string;
  vram_gb: number;
  total_gpu_count: number;
  allocated_gpu_count: number;
  available_gpu_count: number;
  status: ListingStatus;
  accepting_jobs: boolean;
  mock_price_per_hour: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListingInput {
  gpu_model: string;
  vram_gb: number;
  total_gpu_count: number;
  mock_price_per_hour?: string | null;
}

export interface ListingQuery {
  scope: ListingScope;
  status?: ListingStatus;
  limit?: number;
  cursor?: string;
}

export interface ListingPage { items: Listing[]; next_cursor: string | null }

export interface ListingsApi {
  list(query: ListingQuery, signal?: AbortSignal): Promise<ListingPage>;
  get(id: string, signal?: AbortSignal): Promise<Listing>;
  create(input: ListingInput, signal?: AbortSignal): Promise<Listing>;
  patch(id: string, input: Partial<ListingInput>, signal?: AbortSignal): Promise<Listing>;
  pause(id: string, signal?: AbortSignal): Promise<Listing>;
  resume(id: string, signal?: AbortSignal): Promise<Listing>;
}

const messages: Record<string, string> = {
  UNAUTHORIZED: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.",
  FORBIDDEN: "Bạn không có quyền thực hiện thao tác này.",
  LISTING_NOT_FOUND: "Không tìm thấy Listing hoặc bạn không có quyền chỉnh sửa.",
  WORKER_PROFILE_MISSING: "Tài khoản chưa có hồ sơ Worker. Hãy liên hệ người phụ trách.",
  LISTING_HARDWARE_LOCKED: "Không thể đổi model/VRAM khi còn Job đang chờ hoặc đang chạy.",
  LISTING_CAPACITY_BELOW_ALLOCATED: "Tổng GPU không được nhỏ hơn số GPU đang được cấp phát.",
  LISTING_CAPACITY_BELOW_QUEUED_MAX: "Tổng GPU không đủ cho yêu cầu lớn nhất đang chờ.",
  VALIDATION_ERROR: "Dữ liệu chưa hợp lệ. Kiểm tra lại các trường nhập.",
  PAYLOAD_TOO_LARGE: "Dữ liệu gửi quá lớn. Vui lòng rút gọn nội dung và thử lại.",
  INVALID_CURSOR: "Trang dữ liệu đã không còn hợp lệ. Hãy tải lại danh sách.",
  INVALID_FILTER: "Bộ lọc không hợp lệ.",
  DEPENDENCY_UNAVAILABLE: "Dịch vụ tạm thời chưa sẵn sàng. Hãy kiểm tra lại sau.",
  NETWORK_ERROR: "Không xác nhận được kết quả từ máy chủ. Kiểm tra danh sách trước khi gửi lại thao tác tạo.",
};

export class ListingsApiError extends Error {
  constructor(public readonly code: string, public readonly status: number, public readonly requestId?: string) {
    super(messages[code] ?? "Không thể xử lý yêu cầu lúc này.");
    this.name = "ListingsApiError";
  }
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function listing(value: unknown): Listing {
  if (!object(value) || typeof value.id !== "string" || !uuid.test(value.id)
    || !object(value.worker) || typeof value.worker.id !== "string" || !uuid.test(value.worker.id)
    || typeof value.worker.display_name !== "string" || !object(value.worker.reputation)
    || typeof value.gpu_model !== "string"
    || !["ACTIVE", "PAUSED"].includes(String(value.status))
    || typeof value.accepting_jobs !== "boolean" || value.accepting_jobs !== (value.status === "ACTIVE")
    || !["created_at", "updated_at"].every(key => typeof value[key] === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(value[key] as string))
    || !(value.mock_price_per_hour === null || (typeof value.mock_price_per_hour === "string" && /^[0-9]+\.[0-9]{2}$/.test(value.mock_price_per_hour)))) {
    throw new ListingsApiError("INVALID_RESPONSE", 502);
  }
  for (const key of ["vram_gb", "total_gpu_count", "allocated_gpu_count", "available_gpu_count"]) {
    if (typeof value[key] !== "number" || !Number.isInteger(value[key]) || value[key] < 0) throw new ListingsApiError("INVALID_RESPONSE", 502);
  }
  if ((value.vram_gb as number) < 1 || (value.total_gpu_count as number) < 1
    || value.available_gpu_count !== (value.total_gpu_count as number) - (value.allocated_gpu_count as number)) {
    throw new ListingsApiError("INVALID_RESPONSE", 502);
  }
  const reputation = value.worker.reputation;
  if (![reputation.successful_jobs, reputation.worker_fault_jobs].every(count => typeof count === "number" && Number.isInteger(count) && count >= 0)
    || !(reputation.success_rate === null || (typeof reputation.success_rate === "string" && /^(0\.[0-9]{4}|1\.0000)$/.test(reputation.success_rate)))) {
    throw new ListingsApiError("INVALID_RESPONSE", 502);
  }
  return value as unknown as Listing;
}

/** Reads the current GPU-003 volatile token on every request; never persists it.
 * The integration owner supplies the existing session getter and 401 handler.
 */
export function createListingsApi(
  getAccessToken: () => string | null,
  onUnauthorized: () => void,
  fetcher: typeof fetch = fetch,
): ListingsApi {
  async function request(path: string, method: string, input?: unknown, signal?: AbortSignal): Promise<unknown> {
    const token = getAccessToken();
    if (!token) throw new ListingsApiError("UNAUTHORIZED", 401);
    const headers: Record<string, string> = { Accept: "application/json", Authorization: `Bearer ${token}` };
    if (input !== undefined) headers["Content-Type"] = "application/json";
    let response: Response;
    try {
      response = await fetcher(`${config.apiBaseUrl}/api/v1/gpu-listings${path}`, {
        method, headers, credentials: "omit", cache: "no-store", signal,
        ...(input === undefined ? {} : { body: JSON.stringify(input) }),
      });
    } catch (error) {
      if (signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw error;
      throw new ListingsApiError("NETWORK_ERROR", 0);
    }
    if (signal?.aborted) throw new DOMException("Request canceled", "AbortError");
    if (response.status === 401) {
      // An old request must not log out a different, newly authenticated session.
      if (getAccessToken() === token) onUnauthorized();
      throw new ListingsApiError("UNAUTHORIZED", 401);
    }
    let payload: unknown;
    try { payload = await response.json(); } catch { throw new ListingsApiError("INVALID_RESPONSE", response.status); }
    if (!response.ok) {
      const code = object(payload) && object(payload.error) && typeof payload.error.code === "string" ? payload.error.code : "INTERNAL_ERROR";
      const requestId = response.headers.get("X-Request-ID") ?? undefined;
      // Do not display server-provided raw error text (it could contain secrets/SQL).
      throw new ListingsApiError(code, response.status, requestId && uuid.test(requestId) ? requestId : undefined);
    }
    return payload;
  }
  function resource(id: string): string {
    if (!uuid.test(id)) throw new ListingsApiError("VALIDATION_ERROR", 422);
    return `/${id}`;
  }
  return {
    async list(query, signal) {
      const params = new URLSearchParams({ scope: query.scope, limit: String(query.limit ?? 20) });
      if (query.status) params.set("status", query.status);
      if (query.cursor) params.set("cursor", query.cursor);
      const payload = await request(`?${params}`, "GET", undefined, signal);
      if (!object(payload) || !Array.isArray(payload.items) || !(payload.next_cursor === null || typeof payload.next_cursor === "string")) throw new ListingsApiError("INVALID_RESPONSE", 502);
      return { items: payload.items.map(listing), next_cursor: payload.next_cursor };
    },
    async get(id, signal) { return listing(await request(resource(id), "GET", undefined, signal)); },
    async create(input, signal) { return listing(await request("", "POST", input, signal)); },
    async patch(id, input, signal) { return listing(await request(resource(id), "PATCH", input, signal)); },
    async pause(id, signal) { return listing(await request(`${resource(id)}/pause`, "POST", undefined, signal)); },
    async resume(id, signal) { return listing(await request(`${resource(id)}/resume`, "POST", undefined, signal)); },
  };
}

/** Bridge agreed with GPU-003-D; the shell and Listings must share this store. */
export function createSessionListingsApi(session: SessionStore, fetcher: typeof fetch = fetch): ListingsApi {
  return createListingsApi(
    () => session.getAccessToken(),
    () => {
      // Runs synchronously after createListingsApi's sent-token/current-token guard.
      const current = session.getAccessToken();
      if (current !== null) session.handleUnauthorized(current);
    },
    fetcher,
  );
}
