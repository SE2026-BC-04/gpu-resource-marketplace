import { config } from "../config";

export interface ApiLiveness {
  status: "ok";
}

// Operational endpoint only. Business DTOs/routes will follow the approved API contract.
export async function getApiLiveness(signal?: AbortSignal): Promise<ApiLiveness> {
  const response = await fetch(`${config.apiBaseUrl}/health/live`, { signal });
  if (!response.ok) throw new Error(`API health request failed (${response.status})`);
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null || !("status" in payload) || payload.status !== "ok") {
    throw new Error("API health response is invalid");
  }
  return { status: "ok" };
}
