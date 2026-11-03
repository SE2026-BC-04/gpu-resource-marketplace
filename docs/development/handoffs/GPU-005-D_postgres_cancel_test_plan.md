# GPU-005-D PostgreSQL TX-CANCEL Integration Test Plan

**Status:** PREPARATION — DRAFT — NOT APPROVED FOR MERGE
**Parent:** PR #33, `feat/gpu-005-d-cancel-foundation`
**Parent before sync:** PR #33 `13cd3736052321d64980e4d89c730dc612d6abe8`
**PR #34 before sync:** `92c25424e67563bcd62b1582465eb3ec72dc19d2`
**Synchronized main:** `ef9ddcb0b0f594e11ef6ed787c9ad58ce92a613d` (includes merged PR #28 / D2)
**Parent after sync:** `a4805d4773f09a32153e919288a1a733f2dc27bf`
**Assessment:** SQL-level D2 tests are added separately from production TX-CANCEL integration. Every PG-CANCEL service/adapter scenario below remains `BLOCKED` until TV2 delivers the PostgreSQL adapter. No PostgreSQL scenario is called passed unless run on a guarded disposable cluster.

## Dependency gates

- `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED`: the parent branch contains cancellation service/ports, but no production PostgreSQL TX-CANCEL adapter.
- `JOB_LIFECYCLE_D2_AVAILABLE`: PR #28 is merged; migration `0003_phase1b_jobs_guard_update.py` is in this branch and `alembic heads` must show one valid head.
- `JOB_LIFECYCLE_D3_NOT_MERGED`: PR #29 remains open and unmerged at this review point. The harness performs no row-level DELETE, so its cleanup remains compatible with the D3 guarded-delete trigger if that migration is added later.
- `PHASE2_MANAGER_NOT_IMPLEMENTED`: there is no Manager allocation implementation/schema on this baseline. No query against Phase 2 allocation, signed-result, or contribution tables is included.
- TV2's production PostgreSQL TX-CANCEL adapter has not been delivered. TV2 ACK for the consumer port: **NOT PROVIDED**.

PostgreSQL tests use the repository's `migrated_database`, `cluster_roles`, `test_database`, `db_engine`, `reset_schema()`, `resolve_test_database()` and `verify_cluster()` safety path. Each test starts from a reset disposable schema, runs migrations to `head`, commits fixtures for cross-connection visibility, and resets the schema in teardown after rechecking the cluster marker. This avoids direct `DELETE`, does not disable triggers, and is never allowed against a persistent database. No SQLite substitute is used. The helper reads snapshots through independent connections and fingerprints protected reference values. Its bounded lock probe sets PostgreSQL `lock_timeout`/`statement_timeout`, observes `pg_blocking_pids()`, and bounds thread join time.

`READY` refers only to SQL-level test code prepared against D2. It does not mean a test ran or that JobCancelService integration works. The matrix below records service/adapter cases separately; those remain `BLOCKED` on the missing adapter.

## D2 SQL-level PostgreSQL coverage (separate evidence class)

`backend/tests/test_jobs_cancel_d2_postgres.py` issues SQL against the real D2 trigger using `SET LOCAL ROLE gpm_api_app` or a transaction-scoped unknown role. These tests verify PostgreSQL trigger behavior only; they do **not** exercise JobCancelService, the TX-CANCEL port, HTTP, or adapter error mapping.

| Test | SQL-level behavior | Isolation and persisted-state assertion | Runtime status |
|---|---|---|---|
| D2-CANCEL-01 | API role may transition `QUEUED → CANCELLED`; Listing is `ACTIVE` | Fresh-connection Job snapshot; checks DB-set terminal timestamp, null started/failure fields; Listing allocation counter, simulation-reference fingerprint, and reputation unchanged | SKIPPED — disposable PostgreSQL opt-ins absent |
| D2-CANCEL-02 | API role cannot take `QUEUED → RUNNING` Manager edge | Asserts SQLSTATE/constraint/reason and unchanged independent snapshot | SKIPPED — disposable PostgreSQL opt-ins absent |
| D2-CANCEL-03 | Unknown role cannot issue even a no-op UPDATE | Temporary role/ACL are transaction-scoped; rejected statement rolls back; independent snapshot unchanged | SKIPPED — disposable PostgreSQL opt-ins absent |
| D2-CANCEL-04 | Successful SQL transition followed by transaction rollback | Fresh connection still sees `QUEUED`; all existing-schema snapshots unchanged | SKIPPED — disposable PostgreSQL opt-ins absent |
| D2-CANCEL-05 | D2 permits `QUEUED → CANCELLED` when Listing is `PAUSED` | Fresh connection verifies status transition; allocation counter, reference, reputation unchanged | SKIPPED — disposable PostgreSQL opt-ins absent |
| D2-CANCEL-06 | First PostgreSQL session holds Listing lock while a second connection waits; API-role SQL cancellation uses DB clock before first commit | Wait is observed through `pg_stat_activity`/`pg_blocking_pids()` with bounded timeouts; second connection acquires Listing lock after commit; independent snapshot verifies terminal timestamp bounds and unchanged side effects | SKIPPED — disposable PostgreSQL opt-ins absent |

The existing `backend/tests/test_jobs_guard_update.py` also runs the D2 migration's broader legal/illegal transition, role classification, no-op, and concurrency tests. Those are likewise SQL-level trigger tests.

## Scenario matrix

| ID | Preconditions | Database fixtures | Role | Transaction sequence | Expected return/error | Persisted before → after | Dependencies | Status |
|---|---|---|---|---|---|---|---|---|
| PG-CANCEL-01 | Owned Job is `QUEUED`; Listing `ACTIVE` | Committed Client, Worker, Listing, Job; independent snapshot | Owning CLIENT via API role | Locator; TX locks Listing then Job; recheck; guarded update using DB clock; commit once; fresh read | Success projection; `CANCELLED`, `terminal_at` set after lock, `started_at` and `failure_reason` NULL | QUEUED/null terminal → CANCELLED/DB terminal; allocation, reference, reputation unchanged | Adapter; D2 trigger; API DB role | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` (D2 SQL-level equivalent is tracked separately) |
| PG-CANCEL-02 | Job belongs to another Client | Two committed Clients and one owned queued Job | Non-owner CLIENT | Attempt cancel; verify uniform missing/foreign handling; fresh snapshot | `404 JOB_NOT_FOUND` | All existing-schema state unchanged | Adapter; D2 trigger | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-03 | Job ID does not exist | Committed baseline fixture; random absent UUID | CLIENT | Attempt locator/cancel; fresh snapshot of fixture | `404 JOB_NOT_FOUND` | Fixture unchanged | Adapter | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-04 | Job separately seeded as `RUNNING`, `COMPLETED`, `FAILED`, or `CANCELLED` | One valid lifecycle fixture per status | Owning CLIENT | Attempt cancel; fresh independent snapshot | `409 JOB_NOT_CANCELLABLE` | Each row and side-effect snapshot unchanged | Adapter; D2 | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-05 | Job `QUEUED`; Listing `PAUSED` | Committed paused Listing and queued Job | Owning CLIENT | Lock Listing then Job; do not apply admission check; guarded update; commit | Cancellation succeeds | QUEUED → CANCELLED; Listing remains PAUSED; other state unchanged | Adapter; D2 trigger | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-06 | Same owner invokes cancellation twice | Committed queued Job; fresh transaction per invocation | Owning CLIENT | First call commits; second uses a new transaction and reads persisted state | First succeeds; second returns `409 JOB_NOT_CANCELLABLE` | QUEUED → CANCELLED; no second transition/effect | Adapter; D2 trigger | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-07 | Injected failure after guarded write but before commit | Committed queued fixture; failure injection at adapter/service boundary | Owning CLIENT/API role | Begin; lock Listing then Job; stage update; raise; rollback; read on independent connection | Original operation failure propagated/mapped per contract; never success | QUEUED remains QUEUED; all existing-schema side effects unchanged | Adapter; safe fault injection | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-08 | Exercise zero-row guarded UPDATE causes | Fixtures for absent Job, foreign owner, and non-QUEUED Job | Owning or non-owner CLIENT as applicable | Lock in order; execute conditional update; inspect adapter guard classification | `MISSING` → 404; `NOT_OWNER` → uniform 404; `NOT_QUEUED` → 409 | No durable mutation in all cases | Adapter; D2 trigger | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-09 | Runtime DB role has only approved grants | Migrated disposable DB; seeded fixtures via privileged test setup; switch to API role | API database role on behalf of owning CLIENT | Inspect role; cancel; attempt/verify no unauthorized field or table writes | Allowed Job transition only; privilege violations remain denied | Job lifecycle may change; allocation, reputation, reference and identity fields unchanged | Adapter; grants and least-privilege role | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-10 | DB clock available; lock acquisition observable | Committed queued fixture; second independent connection for lock observation | Owning CLIENT/API role | Hold Listing lock in A; start bounded B lock attempt; release A; adapter obtains lock then reads `clock_timestamp()` and updates | Success; terminal time is DB-generated after lock and not client supplied | QUEUED → CANCELLED with `terminal_at` between post-lock DB clock bounds | Adapter; two real PostgreSQL connections | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-11 | Two concurrent cancel attempts for same Job | One committed queued fixture; two CLIENT request transactions and fresh observer connection | Owning CLIENT in both requests | Synchronize on actual Listing lock wait; allow A to commit; B resumes and rechecks/guards | Exactly one success; other cannot report another successful transition (normally 409) | One QUEUED → CANCELLED transition; no duplicate side effect | Adapter; deterministic barriers and bounded locks | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-12 | Service uses Listing-first lock protocol | Committed queued fixture; A holds Listing lock, B executes cancel; DB activity observer | Owning CLIENT/API role | Observe B blocked on Listing before Job lock; release A; complete and inspect | Success without lock-order deadlock | Valid single cancellation; unchanged unrelated state | Adapter; Listing lock contract (TV4/TV2) | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-13 | Disposable DB outage can be injected without unsafe teardown | Adapter configured against vetted test target; controlled connection failure | Owning CLIENT/API role | Cause known connectivity failure during operation; verify rollback/cleanup; no credential or driver text in public error | `DependencyUnavailable` / HTTP 503 | No success response; durable state unchanged unless outcome is explicitly unknown | Adapter; controlled fault injection | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-14 | Commit failure mode can distinguish known rollback from unknown outcome | Disposable DB; adapter commit fault injection | Owning CLIENT/API role | Fail commit with outcome classified unknown; observe response and durable state from fresh connection; do not retry mutation | No false success and no automatic write retry; unknown outcome surfaced per contract | State may be QUEUED or CANCELLED depending on commit result; exactly one possible transition | Adapter; commit fault injection | BLOCKED: `POSTGRES_CANCEL_ADAPTER_NOT_DELIVERED` |
| PG-CANCEL-15 | Real Phase 2 Manager allocation and cancel paths available | Shared disposable PostgreSQL with real Manager and valid queued Job/Listing | Owning CLIENT plus Manager worker role | Barrier both real transactions at Listing lock; commit one, then let other re-read and finish; inspect capacity and lifecycle | Lock winner determines valid final outcome; no over-allocation or invalid transition | Either cancelled before allocation, or valid allocation/run state; capacity invariant preserved | Adapter; D2; Phase 2 Manager/allocation schema and code | BLOCKED: `PHASE2_MANAGER_NOT_IMPLEMENTED` |

## Reusable support and intended assertions

- `seed_committed_job()` reuses `add_user`, `add_worker`, `add_listing`, and `add_job` from `test_schema_constraints.py`, taking DB time from `clock_timestamp()` and committing setup for cross-connection visibility.
- `job_state_fields()` seeds only valid existing lifecycle combinations; it rejects unknown statuses.
- `read_persisted_snapshot()` uses a fresh connection and compares Job lifecycle, Listing allocated count, a non-reversible fingerprint of protected reference fields, and Worker reputation aggregates. It intentionally queries no Phase 2-only table.
- `assert_snapshot_unchanged()` checks zero durable effects where required. `read_database_clock()` supports trusted-time assertions.
- `ListingLockAttempt` uses a distinct connection/thread, bounded PostgreSQL timeouts, actual `pg_stat_activity`/`pg_blocking_pids()` observation, rollback, close, and bounded join. It is a low-level lock helper, not proof of service concurrency correctness by itself.
- The `cancel_postgres` fixture resets schema through `reset_schema()` only after `verify_cluster()` revalidates the disposable marker. Test rows are not individually deleted; migrations rebuild the schema per test. No trigger is disabled or bypassed.
- Side-effect checks include `gpu_listings.allocated_gpu_count`, a SHA-256 fingerprint of the protected simulation reference, and both Worker reputation counters. The current schema has no Phase 2 allocation table, so no claim about that table is made.

## Verification record

The helper contract tests in `backend/tests/test_jobs_cancel_pg_support.py` check lifecycle fixture validity and snapshot comparison without claiming PostgreSQL integration. The following are separate evidence categories:

| Check | Status | Boundary |
|---|---|---|
| Alembic graph | PASS | `uv run --project backend --locked --group dev alembic heads` → one head, `0003_phase1b_jobs_guard_update` |
| Helper contract tests | PASS — 8 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_pg_support.py -q`; pure Python assertions, not database evidence |
| D2 SQL-level PostgreSQL cancellation + existing D2 trigger tests | SKIPPED — 73 skipped (6 new + 67 existing) | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_d2_postgres.py backend/tests/test_jobs_guard_update.py -q`; opt-ins absent, therefore no database was touched |
| Cancellation foundation tests | PASS — 34 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_foundation.py -q`; service/port test doubles only |
| Jobs foundation tests | PASS — 88 passed | `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -q`; not PostgreSQL integration |
| Python compilation | PASS | `python3 -m compileall -q backend/tests` |
| Diff whitespace check | PASS | `git diff --check` |
| Production PostgreSQL TX-CANCEL scenarios | BLOCKED | TV2 adapter absent; D2 migration is present |
| Phase 2 cancel-vs-allocation | BLOCKED | Real Manager path/schema absent |
| CI for updated PR #34 HEAD | update after push and GitHub check | A stacked PR may have no workflow run; report actual result only |

## Transition gate to real PostgreSQL integration

1. TV2 delivers and ACKs a production TX-CANCEL adapter implementing the current `JobCancelTransaction` port, Listing-before-Job lock, locked rechecks, trusted post-lock database timestamp, rollback/cleanup and uncertain-commit behavior.
2. Run the D2 SQL-level tests on a verified disposable PostgreSQL cluster using repository opt-ins; verify the one-head Alembic chain and restricted API role.
3. TV4/TV2 confirm the Listing locking contract, including cancellation when Listing is PAUSED.
4. Keep fixture reset behind `reset_schema()`/`verify_cluster()`; never use direct row DELETE to bypass D3.
5. Implement PG-CANCEL-15 only after a real Phase 2 Manager/allocation path exists. Obtain required cross-phase ACKs; this preparation branch creates none.
