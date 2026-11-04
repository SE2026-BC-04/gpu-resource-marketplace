# GPU-005-D-CANCEL-FOUNDATION Handoff

**Status:** FOUNDATION IMPLEMENTED — DRAFT — NOT APPROVED FOR MERGE

**Task:** GPU-005-D-CANCEL-FOUNDATION

**Branch:** `feat/gpu-005-d-cancel-foundation`

**Current PR:** [#33](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33) — `feat/gpu-005-d-cancel-foundation` (OPEN / Draft / HOLD)

**Current base:** `main@7fd7deaabbaaa5f2583656f201cb68dcd9944fd3` (ordinary, non-force merge into existing branch on 2026-11-05). Post-sync source/CI snapshot: `8817e512f7c84ebba56f134c1b451ca2fa194871`.

**Historical baseline (superseded):** originally stacked on GPU-005-C PR [#15](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/15) at `07acef2`; do **not** treat #15 as current base or merge dependency.

**Dependent PRs:** [#34 — SQL/trigger PostgreSQL harness](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/34), then [#40 — production adapter candidate](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/40). Preserve #33 → #34 → #40 order; these remain separate Draft reviews.
**Design references:** API Contract §§3, 8.3–8.4; Database Design §§9, 11; Phase 1E Jobs/Queue.

## Scope delivered

This slice defines the application use case and narrow persistence ports for a Client cancelling an owned `QUEUED` Job. It reuses the existing `JobRecord`, `JobPrincipal`, typed error taxonomy, and role-safe `project_job` response projection. The context-manager `__exit__` type is `Literal[False] | None`; an adapter must never suppress transaction exceptions.

The command validates CLIENT role before storage access and performs an unlocked minimal `job_id → listing_id` locator read. If found, it enters one single-use context-managed transaction, requests Listing lock before Job lock, and rechecks Job ID, Listing ID, Client ownership, and `QUEUED` status against the locked row. It validates the guarded-update result and safe response projection before calling `commit()` once. Context exit rolls back an uncommitted known-active transaction and releases its Session/connection on every path. The fake asserts that `close()` is attempted even when rollback fails, an original body exception keeps priority over rollback/close errors, and a rollback error propagates after cleanup when no body exception exists. A `CommitOutcomeUnknown` is surfaced without retry; cleanup does not claim that an uncertain commit was rolled back.

The persistence port contract requires the eventual GPU-002 adapter to use trusted PostgreSQL `clock_timestamp()` after locks, set `terminal_at`, keep `failure_reason` and `started_at` NULL, and leave allocations, Listing counters, results, reputation, and simulation references untouched. A conditional UPDATE returning zero rows must raise `CancelGuardRejected(MISSING | NOT_OWNER | NOT_QUEUED)`, mapped respectively to uniform 404, uniform 404, or 409. Known DB unavailability uses the existing `DependencyUnavailable` 503; unexpected programming errors and unknown commit outcomes are not disguised as 4xx and are never automatically retried. Listing PAUSED is not an admission condition for cancellation.

No HTTP route is registered and no production repository/UoW, SQL, migration, Auth implementation, Listing implementation, Manager, or Simulator code is included.

## Changed paths

- `backend/src/gpu_marketplace/jobs/cancel.py`
- `backend/src/gpu_marketplace/jobs/cancel_ports.py`
- `backend/src/gpu_marketplace/jobs/errors.py`
- `backend/tests/test_jobs_cancel_foundation.py`
- `docs/development/handoffs/GPU-005-D_cancel_foundation_handoff.md`

## Verification evidence

### 2026-11-05 post-main-sync evidence (PR #33 snapshot `8817e512`)

[Exact-HEAD GitHub Actions run #41888755575](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41888755575) was **COMPLETED / SUCCESS** on `8817e512f7c84ebba56f134c1b451ca2fa194871`, with all three jobs succeeding:

| Check | Actual execution and outcome | Evidence / limitations |
|---|---|---|
| Full Python backend + topology suite on a guarded disposable PostgreSQL job | `uv run --project backend --locked --group dev pytest backend/tests tests -rs`: **738 passed, 0 failed, 0 skipped** (91 warnings) | [Python CI job #126780174349](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41888755575/job/126780174349): includes 34 Cancel Foundation cases, Jobs/Auth integration, D2/D3 Job guards, D7 Listing PostgreSQL and database safety tests; not a production TX-CANCEL-adapter test |
| Simulator | **2 passed** | Same Python CI job; not real Phase 2 Manager/Cancel race |
| Frontend | `npm test`: **69 passed / 5 test files**; TypeScript typecheck and Vite build **PASS** | [Frontend CI job #126780174363](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41888755575/job/126780174363) |
| Docker Compose smoke / cleanup isolation | **SUCCESS** | [Compose CI job #126780173895](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41888755575/job/126780173895) |
| Alembic version-script graph on this exact SHA | **STATIC SOURCE GRAPH PASS**: exactly one head `0005_listing_d7`; `0001 → 0002 → 0003_phase1b_jobs_guard_update (D2) → 0004_phase1b_jobs_guard_delete (D3) → 0005_listing_d7 (D7)` | All five `backend/migrations/versions/*.py` files and `down_revision` entries inspected. **No local `alembic heads` command or persistent DB migration was performed**. CI's disposable PostgreSQL tests exercised migrated schema, but this row is not a direct CLI transcript. |

**Scope caveat:** This is post-sync PR #33 foundation evidence, **not** an accepted #40 adapter, mounted Cancel HTTP route, or real Manager allocation race. The #34/#40 reconciled SHAs require independent final-branch evidence after normal merge. Local PostgreSQL and local Alembic CLI were **NOT_RUN** by TV5 in this review environment.

### Historical pre-sync author evidence (retained for traceability; do not read as current results)

| Check | Command | Status | Evidence / limitation |
|---|---|---|---|
| Cancellation foundation unit tests | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_foundation.py -q` | PASS | 34 passed; staged/durable fake only, including suppression and cleanup-failure tests |
| Existing Jobs foundation regression | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -q` | PASS | 88 passed |
| Jobs/Auth integration regression | `timeout 45s uv run --project backend --locked --group dev pytest backend/tests/test_jobs_auth_integration.py -q` | BLOCKED | No output or final summary before bounded timeout; TestClient/Auth dependency integration remains unverified in this run. |
| Python compilation | `python3 -m compileall -q backend/src/gpu_marketplace/jobs backend/tests/test_jobs_cancel_foundation.py` | PASS | No compile errors |
| Whitespace | `git diff --check` | PASS | No whitespace errors at check time |
| Full backend suite | `timeout 180s uv run --project backend --locked --group dev pytest backend/tests -q` | BLOCKED | Previous bounded attempt emitted initial skips/one test then no progress and was interrupted without final summary. Not rerun for this remediation because the focused cancellation, Jobs, and Auth regression commands were run separately. |
| PostgreSQL TX-CANCEL | — | NOT_RUN | No production adapter or DB transaction is part of this slice |
| HTTP cancellation integration | — | NOT_RUN | No route is registered; no real Auth integration tested |
| Concurrent cancel-vs-allocation race | — | NOT_RUN | Requires real PostgreSQL multi-session barrier test; fake tests do not prove atomicity |

## Test intent and limits

Fake-based tests assert role gating, uniform missing/foreign behavior, state-transition rejection, paused Listing behavior, trusted timestamp field source at the port boundary, safe response fields, one-commit success, cleanup on begin/transaction/commit failures, typed zero-row guard mapping, unknown-commit no-retry behavior, non-suppressing `__exit__`, cleanup after rollback failure, exception priority, and the interaction order `lookup → begin → lock_listing → lock_job → recheck → update → commit → exit → cleanup`. The fake exposes `durable_record` separately from `pending_record`; only commit publishes staged data and rollback discards it.

These tests establish application policy and adapter interaction expectations only. They do not establish PostgreSQL locking, transaction isolation, allocation race correctness, HTTP behavior, or end-to-end integration.

## Cross-phase impact and required integration

**Assessment: POTENTIAL_IMPACT; scoped cross-phase ACKs RECEIVED.** The added protocols create a consumer contract for TV2 persistence and reference the existing TV3 principal type structurally; the application policy assumes the TV4 Listing row remains lockable when PAUSED. The following are **technical source/contract ACKs** on the original `a4805d4` interface, not independent human merge approvals:

- **TV2 `@TranVu2005` — `ACK_COMPATIBLE`** for the TX-CANCEL persistence port on [PR #33 at `a4805d4`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33#issuecomment-6611328038); TV2 also performed [source review on the exact pre-sync SHA](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33).
- **TV4 `@VietNguyen865` — `ACK_COMPATIBLE`** for Listing→Job lock order and PAUSED cancellation on [source review of `a4805d4`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33#pullrequestreview-5772994963).
- **TV3 / Auth:** the foundation uses existing structural `JobPrincipal` and adds no mounted HTTP/Auth boundary. A TV3 ACK may be obtained **if** post-sync interface changes affect Auth; otherwise keep the future route/mount integration gate explicit. Do not invent approval.

The ordinary merge `a4805d4 → 8817e512` brought accepted `main` D3/D7 source without editing the five original Cancel Foundation diff paths. Any later interface change must be rechecked with the affected owner. Reviewers must independently assess the eventual final diff before human L2 acceptance.

- **TV2 / Database & Persistence:** implement a single TX-CANCEL transaction adapter honoring Listing → Job lock order, fresh locked-row rechecks, guarded `QUEUED → CANCELLED`, and trusted DB terminal time. Add PostgreSQL rollback and race tests.
- **TV3 / Authentication:** provide the real authenticated principal dependency when an HTTP route is integrated; this slice only accepts the existing structural `JobPrincipal` interface.
- **TV4 / Listings:** confirm Listing lock repository/port compatibility and ensure PAUSED Listings remain lockable for cancellation.
- **Integration owner / team lead:** authorize route registration and shared app changes in a later integration slice. Generic HTTP 500 envelope/header handling remains a separate shared-app task.

## Review and rollback

This is an additive, persistence-neutral command foundation. It does not change accepted API/Database contracts. The **team lead classified this PR as L2-controlled for merge governance** because it defines a transaction lifetime, Listing→Job lock order and unknown-commit safety contract; **two independent human L2 confirmations on the final SHA** and separate lead merge permission are required. TV2/TV4 Codex-assisted comments/ACKs do not substitute. Rollback is removal of the new cancellation module, port, tests, and handoff, plus the `JobNotCancellable` typed exception; no new migration or persisted state was introduced by the original Cancel Foundation diff. The parent `main` D2/D3/D7 migrations remain accepted and must not be rolled back by reverting this feature.

## Next gate

**#33 current next gate:** The lead explicitly authorized normal `main` sync in [merge-gate decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33#issuecomment-6638659747); the sync is complete and [post-sync CI](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41888755575) is green. Handoff updated here; **recheck CI on this doc-only commit's exact SHA** before final signoff. Seek **two independent HUMAN L2** reviews of the final #33 diff and a separate team-lead merge decision. Keep #33 OPEN/Draft/HOLD; there is no PR-to-main merge authorization in this handoff.

**Downstream sequence already authorized:** TV5 may merge updated #33 **normally** into the existing `test/gpu-005-d-cancel-pg-integration-prep` branch for #34; then TV2 updates the existing #40 branch. Do **not** create new branches/PRs, rebase/reset/force-push, edit D2/D3/D7 migrations or touch persistent databases. Stop and obtain a documented cross-owner decision if a substantive contract/migration conflict appears. #34 must rerun one-head Alembic checks, guarded D2/D3/D7 PostgreSQL tests and its CI on the combined final SHA. #40 adapter must have its own real PostgreSQL/CI/review evidence; the Manager Cancel-versus-allocation race (PG-CANCEL-15) remains BLOCKED Phase 2. Cancel HTTP, `CommitOutcomeUnknown` mapping, timeout/503 policy and shared-router mounting await separate owner decisions. This handoff does not claim all GPU-005-D is complete.
