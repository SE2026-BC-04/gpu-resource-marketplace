import { createAuthorizedFetch } from "./authorizedFetch";
import type { AuthorizedFetch } from "./authorizedFetch";
import { AuthApiError } from "./auth";
import type { UserRole } from "./auth";
import type { SessionStore } from "./session";

export const JOB_STATUSES = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"] as const;
export type JobStatus = typeof JOB_STATUSES[number];
export type JobFailureReason = "WORKER_FAULT" | "JOB_FAULT" | "SYSTEM_FAULT";
export type JobScope = "mine" | "assigned" | "all";

export interface SubmitJobRequest {
  listing_id: string;
  gpu_count: number;
  duration_seconds: number;
}

/** Only the public fields specified by API Contract §8 are represented here. */
export interface JobResponse {
  id: string;
  listing_id: string;
  worker_id?: string;
  gpu_count: number;
  duration_seconds: number;
  status: JobStatus;
  failure_reason: JobFailureReason | null;
  submitted_at: string;
  started_at: string | null;
  terminal_at: string | null;
}

export interface JobCollectionResponse {
  items: JobResponse[];
  next_cursor: string | null;
}

export interface JobListQuery {
  scope?: JobScope;
  status?: JobStatus;
  limit?: number;
  cursor?: string;
}

export interface JobSubmissionAttempt {
  readonly key: string;
  readonly request: Readonly<SubmitJobRequest>;
}

export interface JobsApi {
  listJobs(query?: JobListQuery, signal?: AbortSignal): Promise<JobCollectionResponse>;
  getJob(jobId: string, signal?: AbortSignal): Promise<JobResponse>;
  submitJob(attempt: JobSubmissionAttempt, signal?: AbortSignal): Promise<JobResponse>;
  cancelJob(jobId: string, signal?: AbortSignal): Promise<JobResponse>;
}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const IDEMPOTENCY_KEY = /^[\x20-\x7e]{8,128}$/;
const MAX_PG_INTEGER = 2_147_483_647;
const failureReasons: readonly string[] = ["WORKER_FAULT", "JOB_FAULT", "SYSTEM_FAULT"];
const scopes: readonly string[] = ["mine", "assigned", "all"];

const errorMessages: Record<string, string> = {
  IDEMPOTENCY_KEY_REQUIRED: "Yêu cầu thiếu khóa chống gửi trùng.",
  INVALID_JSON: "Dữ liệu yêu cầu không hợp lệ.",
  UNKNOWN_FIELD: "Yêu cầu chứa trường không được hỗ trợ.",
  INVALID_CURSOR: "Trang dữ liệu không còn hợp lệ. Hãy tải lại danh sách.",
  INVALID_FILTER: "Bộ lọc công việc không hợp lệ.",
  UNAUTHENTICATED: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
  UNAUTHORIZED: "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
  FORBIDDEN: "Bạn không có quyền thực hiện thao tác này.",
  LISTING_NOT_FOUND: "Không tìm thấy GPU Listing.",
  JOB_NOT_FOUND: "Không tìm thấy công việc.",
  LISTING_PAUSED: "GPU Listing đang tạm dừng, chưa thể gửi công việc.",
  JOB_NOT_CANCELLABLE: "Chỉ có thể hủy công việc đang QUEUED.",
  IDEMPOTENCY_KEY_REUSED: "Khóa gửi đã được dùng với nội dung khác.",
  VALIDATION_ERROR: "Thông tin công việc không hợp lệ.",
  JOB_GPU_EXCEEDS_LISTING_TOTAL: "Số GPU yêu cầu vượt tổng GPU của Listing.",
  DEPENDENCY_UNAVAILABLE: "Dịch vụ tạm thời chưa sẵn sàng.",
  NETWORK_ERROR: "Không kết nối được máy chủ.",
  INVALID_RESPONSE: "Máy chủ trả về dữ liệu không hợp lệ.",
};

export class JobsApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    public readonly requestId?: string,
  ) {
    super(errorMessages[code] ?? "Không thể xử lý yêu cầu lúc này.");
    this.name = "JobsApiError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length && actual.every((key, i) => key === sortedExpected[i]);
}

function invalidResponse(): JobsApiError {
  return new JobsApiError("INVALID_RESPONSE", 502);
}

export function validateSubmitJobRequest(value: unknown): SubmitJobRequest {
  if (!isObject(value) || !exactKeys(value, ["listing_id", "gpu_count", "duration_seconds"])) {
    throw new TypeError("SubmitJobRequest has an invalid shape");
  }
  if (typeof value.listing_id !== "string" || !UUID_V4.test(value.listing_id)) {
    throw new TypeError("listing_id must be a canonical lowercase UUIDv4");
  }
  for (const field of ["gpu_count", "duration_seconds"] as const) {
    const number = value[field];
    if (typeof number !== "number" || !Number.isInteger(number) || number < 1 || number > MAX_PG_INTEGER) {
      throw new TypeError(`${field} must be a positive PostgreSQL integer`);
    }
  }
  return {
    listing_id: value.listing_id,
    gpu_count: value.gpu_count as number,
    duration_seconds: value.duration_seconds as number,
  };
}

export function createJobSubmissionAttempt(
  request: SubmitJobRequest,
  key: string = globalThis.crypto.randomUUID(),
): JobSubmissionAttempt {
  const checked = validateSubmitJobRequest(request);
  if (!IDEMPOTENCY_KEY.test(key)) throw new TypeError("Idempotency-Key must be printable ASCII, 8..128 characters");
  return Object.freeze({ key, request: Object.freeze({ ...checked }) });
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function parseJob(value: unknown): JobResponse {
  const keys = [
    "id", "listing_id", "worker_id", "gpu_count", "duration_seconds", "status", "failure_reason",
    "submitted_at", "started_at", "terminal_at",
  ];
  if (
    !isObject(value) ||
    !keys.filter((key) => key !== "worker_id").every((key) => key in value) ||
    Object.keys(value).some((key) => !keys.includes(key))
  ) throw invalidResponse();
  if (
    typeof value.id !== "string" || !UUID_V4.test(value.id) ||
    typeof value.listing_id !== "string" || !UUID_V4.test(value.listing_id) ||
    (value.worker_id !== undefined && (typeof value.worker_id !== "string" || !UUID_V4.test(value.worker_id))) ||
    typeof value.gpu_count !== "number" || !Number.isInteger(value.gpu_count) || value.gpu_count < 1 || value.gpu_count > MAX_PG_INTEGER ||
    typeof value.duration_seconds !== "number" || !Number.isInteger(value.duration_seconds) || value.duration_seconds < 1 || value.duration_seconds > MAX_PG_INTEGER ||
    typeof value.status !== "string" || !JOB_STATUSES.includes(value.status as JobStatus) ||
    !(value.failure_reason === null || (typeof value.failure_reason === "string" && failureReasons.includes(value.failure_reason))) ||
    !validTimestamp(value.submitted_at) ||
    !(value.started_at === null || validTimestamp(value.started_at)) ||
    !(value.terminal_at === null || validTimestamp(value.terminal_at)) ||
    (value.status === "FAILED" ? value.failure_reason === null : value.failure_reason !== null)
  ) throw invalidResponse();

  return value as unknown as JobResponse;
}

function parseCollection(value: unknown): JobCollectionResponse {
  if (!isObject(value) || !exactKeys(value, ["items", "next_cursor"]) || !Array.isArray(value.items)) {
    throw invalidResponse();
  }
  if (!(value.next_cursor === null || (typeof value.next_cursor === "string" && value.next_cursor.length > 0))) {
    throw invalidResponse();
  }
  return { items: value.items.map(parseJob), next_cursor: value.next_cursor };
}

function requestId(response: Response, payload: unknown): string | undefined {
  const headerId = response.headers.get("X-Request-ID");
  if (headerId && UUID_V4.test(headerId)) return headerId;
  if (isObject(payload) && isObject(payload.error) && typeof payload.error.request_id === "string" && UUID_V4.test(payload.error.request_id)) {
    return payload.error.request_id;
  }
  return undefined;
}

async function parseFailure(response: Response): Promise<JobsApiError> {
  let payload: unknown;
  try { payload = await response.json(); } catch { payload = undefined; }
  const code = isObject(payload) && isObject(payload.error) && typeof payload.error.code === "string"
    ? payload.error.code
    : ({ 400: "INVALID_JSON", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "JOB_NOT_FOUND", 409: "JOB_NOT_CANCELLABLE", 422: "VALIDATION_ERROR", 503: "DEPENDENCY_UNAVAILABLE" } as Record<number, string>)[response.status]
      ?? "INTERNAL_ERROR";
  return new JobsApiError(code, response.status, requestId(response, payload));
}

async function jsonSuccess(response: Response): Promise<unknown> {
  if (!response.ok) throw await parseFailure(response);
  try { return await response.json(); } catch { throw invalidResponse(); }
}

export function createJobsApiFromAuthorizedFetch(send: AuthorizedFetch): JobsApi {
  async function authorizedRequest(path: string, init: RequestInit): Promise<Response> {
    try {
      return await send(path, init);
    } catch (error) {
      if (error instanceof AuthApiError) throw new JobsApiError(error.code, error.status, error.requestId);
      throw error;
    }
  }

  return {
    async listJobs(query = {}, signal) {
      const params = new URLSearchParams();
      if (query.scope !== undefined) {
        if (!scopes.includes(query.scope)) throw new TypeError("scope is invalid");
        params.set("scope", query.scope);
      }
      if (query.status !== undefined) {
        if (!JOB_STATUSES.includes(query.status)) throw new TypeError("status is invalid");
        params.set("status", query.status);
      }
      if (query.limit !== undefined && (!Number.isInteger(query.limit) || query.limit < 1 || query.limit > 100)) {
        throw new TypeError("limit must be an integer from 1 to 100");
      }
      if (query.cursor !== undefined && (typeof query.cursor !== "string" || query.cursor.length === 0)) {
        throw new TypeError("cursor must be a non-empty opaque string");
      }
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor !== undefined) params.set("cursor", query.cursor);
      const suffix = params.size ? `?${params.toString()}` : "";
      return parseCollection(await jsonSuccess(await authorizedRequest(`/api/v1/jobs${suffix}`, { method: "GET", signal })));
    },
    async getJob(jobId, signal) {
      if (!UUID_V4.test(jobId)) throw new TypeError("job_id must be a canonical lowercase UUIDv4");
      return parseJob(await jsonSuccess(await authorizedRequest(`/api/v1/jobs/${jobId}`, { method: "GET", signal })));
    },
    async submitJob(attempt, signal) {
      const request = validateSubmitJobRequest(attempt.request);
      if (!IDEMPOTENCY_KEY.test(attempt.key)) throw new TypeError("Idempotency-Key is invalid");
      return parseJob(await jsonSuccess(await authorizedRequest("/api/v1/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.key },
        body: JSON.stringify(request),
        signal,
      })));
    },
    async cancelJob(jobId, signal) {
      if (!UUID_V4.test(jobId)) throw new TypeError("job_id must be a canonical lowercase UUIDv4");
      return parseJob(await jsonSuccess(await authorizedRequest(`/api/v1/jobs/${jobId}/cancel`, { method: "POST", signal })));
    },
  };
}

export function createJobsApi(session: SessionStore, fetcher?: typeof fetch): JobsApi {
  const send = fetcher === undefined ? createAuthorizedFetch(session) : createAuthorizedFetch(session, fetcher);
  return createJobsApiFromAuthorizedFetch(send);
}

export function jobsScopeForRole(role: UserRole): JobScope {
  if (role === "CLIENT") return "mine";
  if (role === "WORKER") return "assigned";
  return "all";
}
