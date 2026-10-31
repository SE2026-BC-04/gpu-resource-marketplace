# GPU-005-D PostgreSQL TX-CANCEL Integration Test Plan

**Status:** PREPARATION — DRAFT — NOT APPROVED FOR MERGE
**Parent:** PR #33, `feat/gpu-005-d-cancel-foundation`
**Baseline:** `33c7b336d0d905381eba5a469ac8d4b37e1c5f9e`
**Assessment:** every production PostgreSQL TX-CANCEL scenario below is `BLOCKED` until the TV2 adapter is delivered. D2-dependent scenarios also require the PR #28 lifecycle migration to be merged and applied to the disposable test database. No scenario is reported as passed or run by this preparation branch.

## Dependency gates

- `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED`: the parent branch contains cancellation service/ports, but no production PostgreSQL TX-CANCEL adapter.
- `JOB_LIFECYCLE_D2_NOT_AVAILABLE`: this branch has migrations `0001_phase1b_baseline.py` and `0002_phase1b_grants.py`; the D2 trigger from PR #28 is not present here.
- `PHASE2_MANAGER_NOT_IMPLEMENTED`: there is no Manager allocation implementation/schema on this baseline. No query against Phase 2 allocation, signed-result, or contribution tables is included.
- PR #28 (D2) and PR #31 (Listing UoW) were open Draft dependencies at preparation time. Their code is not copied into this branch. TV2 ACK: **NOT PROVIDED**.

The helper in `backend/tests/jobs_cancel_pg_support.py` is designed for the existing guarded `baseline_database` fixture only. That fixture uses `test_database`, `db_engine`, `cluster_roles`, `resolve_test_database()` and `verify_cluster()` from `conftest.py`/`db_safety.py`. No SQLite substitute is used. This work did not connect to or mutate a database. The helper commits fixture setup so separate PostgreSQL sessions can see it, reads snapshots via independent connections, fingerprints protected reference values, and cleans rows in `finally`. Its bounded lock probe sets PostgreSQL `lock_timeout` and `statement_timeout`, observes `pg_blocking_pids()`, and bounds thread join time.

`READY` means only that the scenario's setup/assertion intent can be implemented from the stated contract; it does not mean the production integration test can run. Because the adapter gate is absent, all scenario execution statuses remain `BLOCKED`.

## Scenario matrix

| ID | Preconditions | Database fixtures | Role | Transaction sequence | Expected return/error | Persisted before → after | Dependencies | Status |
|---|---|---|---|---|---|---|---|---|
| PG-CANCEL-01 | Owned Job is `QUEUED`; Listing `ACTIVE` | Committed Client, Worker, Listing, Job; independent snapshot | Owning CLIENT via API role | Locator; TX locks Listing then Job; recheck; guarded update using DB clock; commit once; fresh read | Success projection; `CANCELLED`, `terminal_at` set after lock, `started_at` and `failure_reason` NULL | QUEUED/null terminal → CANCELLED/DB terminal; allocation, reference, reputation unchanged | Adapter; D2 for guarded lifecycle update; API DB role | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED`, `JOB_LIFECYCLE_D2_NOT_AVAILABLE` |
| PG-CANCEL-02 | Job belongs to another Client | Two committed Clients and one owned queued Job | Non-owner CLIENT | Attempt cancel; verify uniform missing/foreign handling; fresh snapshot | `404 JOB_NOT_FOUND` | All existing-schema state unchanged | Adapter; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-03 | Job ID does not exist | Committed baseline fixture; random absent UUID | CLIENT | Attempt locator/cancel; fresh snapshot of fixture | `404 JOB_NOT_FOUND` | Fixture unchanged | Adapter | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-04 | Job separately seeded as `RUNNING`, `COMPLETED`, `FAILED`, or `CANCELLED` | One valid lifecycle fixture per status | Owning CLIENT | Attempt cancel; fresh independent snapshot | `409 JOB_NOT_CANCELLABLE` | Each row and side-effect snapshot unchanged | Adapter; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-05 | Job `QUEUED`; Listing `PAUSED` | Committed paused Listing and queued Job | Owning CLIENT | Lock Listing then Job; do not apply admission check; guarded update; commit | Cancellation succeeds | QUEUED → CANCELLED; Listing remains PAUSED; other state unchanged | Adapter; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-06 | Same owner invokes cancellation twice | Committed queued Job; fresh transaction per invocation | Owning CLIENT | First call commits; second uses a new transaction and reads persisted state | First succeeds; second returns `409 JOB_NOT_CANCELLABLE` | QUEUED → CANCELLED; no second transition/effect | Adapter; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-07 | Injected failure after guarded write but before commit | Committed queued fixture; failure injection at adapter/service boundary | Owning CLIENT/API role | Begin; lock Listing then Job; stage update; raise; rollback; read on independent connection | Original operation failure propagated/mapped per contract; never success | QUEUED remains QUEUED; all existing-schema side effects unchanged | Adapter; D2; safe fault injection | BLOCKED: adapter and D2 |
| PG-CANCEL-08 | Exercise zero-row guarded UPDATE causes | Fixtures for absent Job, foreign owner, and non-QUEUED Job | Owning or non-owner CLIENT as applicable | Lock in order; execute conditional update; inspect adapter guard classification | `MISSING` → 404; `NOT_OWNER` → uniform 404; `NOT_QUEUED` → 409 | No durable mutation in all cases | Adapter; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-09 | Runtime DB role has only approved grants | Migrated disposable DB; seeded fixtures via privileged test setup; switch to API role | API database role on behalf of owning CLIENT | Inspect role; cancel; attempt/verify no unauthorized field or table writes | Allowed Job transition only; privilege violations remain denied | Job lifecycle may change; allocation, reputation, reference and identity fields unchanged | Adapter; D2; grants and least-privilege role | BLOCKED: adapter and D2 |
| PG-CANCEL-10 | DB clock available; lock acquisition observable | Committed queued fixture; second independent connection for lock observation | Owning CLIENT/API role | Hold Listing lock in A; start bounded B lock attempt; release A; service obtains lock then reads `clock_timestamp()` and updates | Success; terminal time is DB-generated after lock and not client supplied | QUEUED → CANCELLED with `terminal_at` between post-lock DB clock bounds | Adapter; D2; two real PostgreSQL connections | BLOCKED: adapter and D2 |
| PG-CANCEL-11 | Two concurrent cancel attempts for same Job | One committed queued fixture; two CLIENT request transactions and fresh observer connection | Owning CLIENT in both requests | Synchronize on actual Listing lock wait; allow A to commit; B resumes and rechecks/guards | Exactly one success; other cannot report another successful transition (normally 409) | One QUEUED → CANCELLED transition; no duplicate side effect | Adapter; D2; deterministic barriers and bounded locks | BLOCKED: adapter and D2 |
| PG-CANCEL-12 | Service uses Listing-first lock protocol | Committed queued fixture; A holds Listing lock, B executes cancel; DB activity observer | Owning CLIENT/API role | Observe B blocked on Listing before Job lock; release A; complete and inspect | Success without lock-order deadlock | Valid single cancellation; unchanged unrelated state | Adapter; Listing lock contract (TV4/TV2); D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-13 | Disposable DB outage can be injected without unsafe teardown | Adapter configured against vetted test target; controlled connection failure | Owning CLIENT/API role | Cause known connectivity failure during operation; verify rollback/cleanup; no credential or driver text in public error | `DependencyUnavailable` / HTTP 503 | No success response; durable state unchanged unless outcome is explicitly unknown | Adapter; controlled fault injection | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-14 | Commit failure mode can distinguish known rollback from unknown outcome | Disposable DB; adapter commit fault injection | Owning CLIENT/API role | Fail commit with outcome classified unknown; observe response and durable state from fresh connection; do not retry mutation | No false success and no automatic write retry; unknown outcome surfaced per contract | State may be QUEUED or CANCELLED depending on commit result; exactly one possible transition | Adapter; commit fault injection; D2 | BLOCKED: adapter and D2 |
| PG-CANCEL-15 | Real Phase 2 Manager allocation and cancel paths available | Shared disposable PostgreSQL with real Manager and valid queued Job/Listing | Owning CLIENT plus Manager worker role | Barrier both real transactions at Listing lock; commit one, then let other re-read and finish; inspect capacity and lifecycle | Lock winner determines valid final outcome; no over-allocation or invalid transition | Either cancelled before allocation, or valid allocation/run state; capacity invariant preserved | Adapter; D2; Phase 2 Manager/allocation schema and code | BLOCKED: `PHASE2_MANAGER_NOT_IMPLEMENTED` |

## Reusable support and intended assertions

- `seed_committed_job()` reuses `add_user`, `add_worker`, `add_listing`, and `add_job` from `test_schema_constraints.py`, taking DB time from `clock_timestamp()` and committing setup for cross-connection visibility.
- `job_state_fields()` seeds only valid existing lifecycle combinations; it rejects unknown statuses.
- `read_persisted_snapshot()` uses a fresh connection and compares Job lifecycle, Listing allocated count, a non-reversible fingerprint of protected reference fields, and Worker reputation aggregates. It intentionally queries no Phase 2-only table.
- `assert_snapshot_unchanged()` checks zero durable effects where required. `read_database_clock()` supports trusted-time assertions.
- `ListingLockAttempt` uses a distinct connection/thread, bounded PostgreSQL timeouts, actual `pg_stat_activity`/`pg_blocking_pids()` observation, rollback, close, and bounded join. It is a low-level lock helper, not proof of service concurrency correctness by itself.
- `committed_job_fixture()` always attempts cleanup in `finally`. All SQL writes must run only through the repository's guarded disposable PostgreSQL fixtures.

## Verification record

The helper contract tests in `backend/tests/test_jobs_cancel_pg_support.py` check lifecycle fixture validity and snapshot comparison without claiming PostgreSQL integration. The following are separate evidence categories:

| Check | Status | Boundary |
|---|---|---|
| Helper contract tests | PASS — 7 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_pg_support.py -q`; pure Python assertions, not database evidence |
| Existing cancellation foundation tests | PASS — 34 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_foundation.py -q`; service/port test doubles only |
| Existing Jobs foundation tests | PASS — 88 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -q`; not PostgreSQL integration |
| Python compilation | PASS | `python3 -m compileall -q backend/tests` |
| Diff whitespace check | PASS | `git diff --check` before staging; staged check is part of final pre-commit verification |
| Disposable PostgreSQL TX-CANCEL scenarios | BLOCKED | Adapter absent; D2 absent; no database was used for this preparation |
| Phase 2 cancel-vs-allocation | BLOCKED | Real Manager path/schema absent |
| CI for stacked Draft PR | NOT_RUN | Draft PR not yet created; GitHub CLI authentication is currently invalid |

## Transition gate to real PostgreSQL integration

1. TV2 delivers and ACKs a production TX-CANCEL adapter implementing the current `JobCancelTransaction` port, Listing-before-Job lock, locked rechecks, trusted post-lock database timestamp, rollback/cleanup and uncertain-commit behavior.
2. PR #28 D2 is merged into the integration base and applied by the guarded `baseline_database` fixture; API-role grants are verified rather than replaced with owner credentials.
3. TV4/TV2 confirm the Listing locking contract, including cancellation when Listing is PAUSED.
4. Run targeted disposable PostgreSQL tests with the repository safety opt-ins and verify cluster identity before any destructive operation. Never expose DSN/token in logs.
5. Implement PG-CANCEL-15 only after a real Phase 2 Manager/allocation path exists. Obtain required cross-phase ACKs; this preparation branch creates none.
