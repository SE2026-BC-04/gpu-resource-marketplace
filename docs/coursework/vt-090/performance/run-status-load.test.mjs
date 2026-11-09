import assert from "node:assert/strict";
import test from "node:test";

import {
  createSyntheticClientJobDto,
  isPublicJobDto,
  nearestRankP95,
} from "./run-status-load.mjs";

test("nearest-rank p95 uses ceil(0.95*n)-1 and does not mutate the input", () => {
  const values = Array.from({ length: 60 }, (_, index) => 60 - index);
  const original = [...values];
  assert.equal(nearestRankP95(values), 57);
  assert.deepEqual(values, original);
  assert.equal(nearestRankP95([]), null);
});

test("nearest-rank p95 rejects non-finite samples", () => {
  assert.throws(() => nearestRankP95([1, Number.NaN]), /finite numbers/);
});

test("synthetic Client response matches the public Job DTO with consistent QUEUED timestamps", () => {
  const dto = createSyntheticClientJobDto();
  assert.equal(isPublicJobDto(dto, { requireWorkerId: true }), true);
  assert.deepEqual(Object.keys(dto).sort(), [
    "duration_seconds", "failure_reason", "gpu_count", "id", "listing_id", "started_at", "status",
    "submitted_at", "terminal_at", "worker_id",
  ]);
  assert.equal(dto.started_at, null);
  assert.equal(dto.terminal_at, null);
  assert.equal(dto.failure_reason, null);
});

test("public Job DTO validation rejects missing IDs, invalid UUIDs, and timestamp contradictions", () => {
  const valid = createSyntheticClientJobDto();
  const { listing_id: _listingId, ...missingListingId } = valid;
  assert.equal(isPublicJobDto(missingListingId, { requireWorkerId: true }), false);
  assert.equal(isPublicJobDto({ ...valid, worker_id: "not-a-uuid" }, { requireWorkerId: true }), false);
  assert.equal(isPublicJobDto({ ...valid, started_at: "2026-11-09T08:00:30.000000Z" }, { requireWorkerId: true }), false);
  assert.equal(isPublicJobDto({ ...valid, submitted_at: "not-a-time" }, { requireWorkerId: true }), false);
});
