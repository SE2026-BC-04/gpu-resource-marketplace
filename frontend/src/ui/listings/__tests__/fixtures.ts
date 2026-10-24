import { vi } from "vitest";

import type { Listing, ListingsApi } from "../../../api/listings";

export const LISTING_ID = "22222222-2222-4222-8222-222222222222";
export const USER_ID = "33333333-3333-4333-8333-333333333333";

export function sample(overrides: Partial<Listing> = {}): Listing {
  return {
    id: LISTING_ID,
    worker: { id: "11111111-1111-4111-8111-111111111111", display_name: "Demo Worker",
      reputation: { successful_jobs: 7, worker_fault_jobs: 3, success_rate: "0.7000" } },
    gpu_model: "A100 simulated", vram_gb: 80, total_gpu_count: 8,
    allocated_gpu_count: 3, available_gpu_count: 5, status: "ACTIVE", accepting_jobs: true,
    mock_price_per_hour: "12.50", created_at: "2026-10-24T09:00:00.000000Z", updated_at: "2026-10-24T09:00:00.000000Z",
    ...overrides,
  };
}

export function fakeApi(): ListingsApi {
  return {
    list: vi.fn(async () => ({ items: [sample()], next_cursor: null })),
    get: vi.fn(async (id: string) => sample({ id })),
    create: vi.fn(async () => sample({ allocated_gpu_count: 0, available_gpu_count: 8 })),
    patch: vi.fn(async (id, input) => sample({ id, ...input })),
    pause: vi.fn(async id => sample({ id, status: "PAUSED", accepting_jobs: false })),
    resume: vi.fn(async id => sample({ id, status: "ACTIVE", accepting_jobs: true })),
  };
}
