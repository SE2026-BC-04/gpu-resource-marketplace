# GPU-005-D-CANCEL-FOUNDATION Handoff

**Status:** FOUNDATION IMPLEMENTED — DRAFT — NOT APPROVED FOR MERGE

**Task:** GPU-005-D-CANCEL-FOUNDATION

**Branch:** `feat/gpu-005-d-cancel-foundation`

**Base:** `feat/gpu-005-c-job-api-foundation` at `07acef20eb6e1b403fc13a24138575d0f490a665`

**Parent PR:** [#15](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/15)
**Design references:** API Contract §§3, 8.3–8.4; Database Design §§9, 11; Phase 1E Jobs/Queue.

## Scope delivered

This slice defines the application use case and narrow persistence ports for a Client cancelling an owned `QUEUED` Job. It reuses the existing `JobRecord`, `JobPrincipal`, typed error taxonomy, and role-safe `project_job` response projection.

The command validates CLIENT role before storage access, performs an unlocked minimal `job_id → listing_id` locator read, begins the unit of work only after a locator is found, then requests Listing lock before Job lock. It rechecks Job ID, Listing ID, Client ownership, and `QUEUED` status against the locked row. The guarded persistence operation must return the DB-timestamped `CANCELLED` row. The service validates terminal fields, builds the existing safe projection, commits once, and rolls back on exceptions.

The persistence port contract requires the eventual GPU-002 adapter to use trusted PostgreSQL `clock_timestamp()` after locks, set `terminal_at`, keep `failure_reason` and `started_at` NULL, and leave allocations, Listing counters, results, reputation, and simulation references untouched. Listing PAUSED is not an admission condition for cancellation.

No HTTP route is registered and no production repository/UoW, SQL, migration, Auth implementation, Listing implementation, Manager, or Simulator code is included.

## Changed paths

- `backend/src/gpu_marketplace/jobs/cancel.py`
- `backend/src/gpu_marketplace/jobs/cancel_ports.py`
- `backend/src/gpu_marketplace/jobs/errors.py`
- `backend/tests/test_jobs_cancel_foundation.py`
- `docs/development/handoffs/GPU-005-D_cancel_foundation_handoff.md`

## Verification evidence

| Check | Command | Status | Evidence / limitation |
|---|---|---|---|
| Cancellation foundation unit tests | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_foundation.py -q` | PASS | 14 passed; fake ports only |
| Existing Jobs foundation regression | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -q` | PASS | 88 passed |
| Python compilation | `python3 -m compileall -q backend/src/gpu_marketplace/jobs backend/tests/test_jobs_cancel_foundation.py` | PASS | No compile errors |
| Whitespace | `git diff --check` | PASS | No whitespace errors at check time |
| Full backend suite | `timeout 180s uv run --project backend --locked --group dev pytest backend/tests -q` | BLOCKED | After initial skipped tests and one reported test, execution produced no further output for about a minute; the process was interrupted. No final summary/count was produced. The new focused tests and Jobs regression completed separately. |
| PostgreSQL TX-CANCEL | — | NOT_RUN | No production adapter or DB transaction is part of this slice |
| HTTP cancellation integration | — | NOT_RUN | No route is registered; no real Auth integration tested |
| Concurrent cancel-vs-allocation race | — | NOT_RUN | Requires real PostgreSQL multi-session barrier test; fake tests do not prove atomicity |

## Test intent and limits

Fake-based tests assert role gating, uniform missing/foreign behavior, state-transition rejection, paused Listing behavior, trusted timestamp field source at the port boundary, safe response fields, one-commit success, rollback on exceptions, and the interaction order `lookup → begin → lock_listing → lock_job → recheck → update → commit`.

These tests establish application policy and adapter interaction expectations only. They do not establish PostgreSQL locking, transaction isolation, allocation race correctness, HTTP behavior, or end-to-end integration.

## Cross-phase impact and required integration

**Assessment: POTENTIAL_IMPACT. Cross-phase ACK: NOT PROVIDED.** The added protocols create a consumer contract for the TV2 persistence adapter and reference the existing TV3 principal type structurally. The application policy also assumes the TV4 Listing row remains lockable even when PAUSED. No source-owner ACK is asserted by this handoff.

- **TV2 / Database & Persistence:** implement a single TX-CANCEL transaction adapter honoring Listing → Job lock order, fresh locked-row rechecks, guarded `QUEUED → CANCELLED`, and trusted DB terminal time. Add PostgreSQL rollback and race tests.
- **TV3 / Authentication:** provide the real authenticated principal dependency when an HTTP route is integrated; this slice only accepts the existing structural `JobPrincipal` interface.
- **TV4 / Listings:** confirm Listing lock repository/port compatibility and ensure PAUSED Listings remain lockable for cancellation.
- **Integration owner / team lead:** authorize route registration and shared app changes in a later integration slice. Generic HTTP 500 envelope/header handling remains a separate shared-app task.

## Review and rollback

This is an additive, persistence-neutral command foundation. It does not change accepted API/Database contracts. Rollback is removal of the new cancellation module, port, tests, and handoff, plus the `JobNotCancellable` typed exception; no data migration or persisted state was introduced by this branch.

## Next gate

Review this stacked Draft PR against parent PR #15. Before exposing a cancellation endpoint, TV2 must implement and pass real PostgreSQL TX-CANCEL tests, including cancel-versus-allocation concurrency and rollback behavior; TV3/TV4 interfaces must be confirmed; and the integration owner must authorize shared router mounting. This handoff does not claim all GPU-005-D is complete.
