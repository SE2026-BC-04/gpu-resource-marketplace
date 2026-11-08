# P2B_TEST_MATRIX — Phase 2B pre-code task TV2-P2B-06

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` (TV1 + TV2) · **Date:** 2026-11-08
**Everything below is `NOT_RUN`.** Phase 1 CI being green is not Phase 2 evidence. A test that is skipped, xfail, mocked or run on a non-disposable database is `NOT_RUN`/`BLOCKED`, never `PASS`.

## 1. Rules every test follows

- Real PostgreSQL 16 on a disposable, marker-checked cluster (`backend/tests/db_safety.py`); native logins for role tests; two or more independent connections for any race, with explicit barriers (the pattern in `test_listing_submit_concurrency_postgres.py`: separate UoWs, `threading.Event` gates at lock acquisition points, both commit orders).
- Fixed UUIDv4 fixtures; before/after row snapshots; assertions on rows, not on log text.
- Time: tests that depend on `received_at` vs `hard_deadline_at` need a controllable clock. Proposal **T-D1**: UoW constructors take a `clock_sql` fragment defaulting to `clock_timestamp()`; only test composition passes a fixed expression; API/Manager wiring never does. Exact-equality boundary (`received_at == hard_deadline_at` is late) is tested with that injection; without T-D1 only strictly-before/strictly-after can be tested and the equality case stays `NOT_RUN`.
- Any test that sets role passwords uses `restored_login_role_credentials` (from #42). See `DB_TEST_ISOLATION.md`.
- Timestamps are timezone-aware; local cluster runs in `Asia/Bangkok`, CI in UTC; assertions compare instants, not wall-clock strings.
- Per-test evidence record (template at the end).

## 2. Mandatory tests (handoff §9) mapped to files

| ID | Case | Proposed file | Technique | PASS oracle |
|---|---|---|---|---|
| `P2B-DRT-01` | accepted Phase 1 head → Phase 2 upgrade | `test_phase2_migration_postgres.py` | fresh disposable DB, `alembic upgrade head` twice (R1, R2) | exactly 6 new tables, no `disputes`, one head, names match `PHASE2_SCHEMA_MATRIX.md` |
| `P2B-DRT-02` | native roles + ORM emitted SQL | `test_phase2_role_grants_postgres.py` | log in as `gpm_api_app` / `gpm_manager_app`, run each UoW statement; negative statements | positive: no `42501`; negative: `42501`; grant inventory equals checked-in expectation |
| `P2B-DRT-03` | two concurrent identical callbacks | `test_inbox_ingress_postgres.py` | two sessions, barrier at Job lock | one row, both `202`, bytes and `received_at` unchanged |
| `P2B-DRT-04` | same `result_id`, other bytes or context | same | sequential + cross-Job race | `409`, no overwrite, one eligible row |
| `P2B-DRT-05` | retained duplicate after terminal / lost ACK | same | replay after finalize | `202 DUPLICATE`, no new event/effect/timestamp |
| `P2B-DRT-06` | invalid candidate in batch 1, valid in batch 2 | `test_finalize_postgres.py` | bound = 1, two PENDING rows | valid one finalizes; no `SYSTEM_FAULT` |
| `P2B-DRT-07` | two result ids, two concurrent finalizers | same | two sessions, barrier | one signed result, one release, one contribution, one aggregate delta |
| `P2B-DRT-08` | stale Outbox lease takeover + PAUSED Listing | `test_outbox_postgres.py` | expire lease, second claimer, stale ACK | stale update rowcount 0; same `event_id/attempt_id`; no new allocation |
| `P2B-DRT-09` | Cancel↔Allocate, 2 Managers, capacity | `test_allocate_postgres.py` | barriers, both commit orders, head 3 / free 2 / tail 1 | FIFO kept, no allocation for a cancelled Job, `allocated_gpu_count = SUM(active)` |
| `P2B-DRT-10` | crash inside `TX-FINALIZE`, replay | same as 07 | inject failure before each statement and before/after COMMIT | no partial row; each effect once |
| `P2B-DRT-11` | lost COMMIT ack and async cancellation | `test_uow_failure_postgres.py` | connection kill after COMMIT sent; cancel the awaiting task with a worker running | `CommitOutcomeUnknown`, reconcile reads DB, no blind retry, no Session across threads |
| `P2B-DRT-12` | K1 retired / K2 active, old proof | `test_signed_results_keys_postgres.py` | retire K1, finalize with K1 receipt | old receipt kept; `DELETE` of K1 row fails (`23503`) while referenced |
| `P2B-DRT-13` | role-password rotation + failing teardown | `test_role_credentials_restore.py` (exists) + a Phase 2 case | fail the test body after rotation | verifiers restored or cluster declared dirty |
| `P2B-DRT-14` | executor / pool / lock saturation | `test_runtime_budget_postgres.py` | fill pool and executor with slow UoWs | queue bounded, timeouts fire, finalization not starved; numbers go to `RUNTIME_BUDGET.md` |
| `P2B-DRT-15` | fake a Phase 3 correction | `test_contribution_phase2_guard_postgres.py` | insert/update with `correction_version=1`, dispute id, changed category | `23514` / `42501` |

## 3. Additional design-listed tests

`P2B-MIG-01..05`, `P2B-FK-01..05`, `P2B-GUARD-01..10` (see `GUARDS_TRIGGER_PLAN.md`), `P2B-UOW-01..07`, `G-01..06` (`PHASE2_ROLE_GRANTS.md`), plus `P2B-DRT-16` (new): Phase 1 regressions `Submit↔Pause` and `Submit↔Resize` in **both** commit orders stay green after R1/R2.

## 4. Order of work once the docs gate (G1) is closed

1. R1 migration + `P2B-DRT-01`, `-15`, `P2B-MIG-*`.
2. R2 grants/guards + `P2B-DRT-02`, `P2B-GUARD-*`, `G-*`.
3. UoWs in dependency order: allocate (`-09`), outbox (`-08`), ingress (`-03..05`), candidates (`-06`), finalize/fallback (`-07`, `-10`, `-11`), then runtime budget (`-14`).
Per the lead's 2026-11-08 process notice, **one task = one branch = one PR into `main`**, each cut from the latest `main` and merged as soon as it passes CI and review, without waiting for the whole Phase. The numbered steps above are the intended task slices (step 3 splits further, one PR per transaction port); the order is fixed by dependencies: R1 before R2, R2 before any UoW test that logs in as a native role.

## 5. Evidence record (per test, per exact HEAD)

```text
Test ID:
Git SHA / branch:
Alembic revision(s):
PostgreSQL version / cluster (disposable? markers ok?):
current_user / session_user used:
Fixture + clock mechanism:
Sessions + barrier points / commit order:
Before rows (SQL) / After rows (SQL):
Expected vs observed:
Command + output tail / CI URL:
Verdict: PASS | FAIL | BLOCKED | ERROR | NOT_RUN
```
