# DB_TEST_ISOLATION — Phase 2B pre-code task TV2-P2B-06

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` (TV1 + TV2) · **Date:** 2026-11-08

## 1. Where Phase 2 DB tests may run

Only a disposable PostgreSQL cluster that passes `backend/tests/db_safety.py`: variables `GPU_MARKETPLACE_TEST_DATABASE_URL`, `GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=1`, `GPU_MARKETPLACE_TEST_CLUSTER_TOKEN`; database name `gpu_marketplace_test[_x]`; port not 5432 and not the Compose port; marker database `gpm_disposable_test_cluster` whose comment is the token. Fixtures drop and recreate schema `public`. A development or shared database is never a target. Without all three variables the tests report `NOT_RUN`, and a report must say so.
- **Local:** container `gpm-pg-test` (`postgres:16.15-bookworm`, `127.0.0.1:55432`, `-c timezone=Asia/Bangkok`). Docker Desktop is started by the user; if `docker info` fails the work stops and asks (project rule). Credentials are read from the container/DB, never written to files or chat.
- **CI:** disposable PostgreSQL service in UTC (`.github/workflows/foundation.yml`, runs only for PRs into `main` and pushes to `main`; a PR whose base is another branch gets no CI, so Phase 2B stays a PR into `main`).

## 2. State that schema reset does not undo (the #42 lesson)

`reset_schema()` recreates only schema `public`. **Roles, role memberships and role passwords are cluster-wide.**
1. Any test that calls `bootstrap_roles(..., rotate_password=True)` or `ALTER ROLE ... PASSWORD` runs inside `restored_login_role_credentials(owner_engine)` (`backend/tests/role_credentials.py`), which snapshots `pg_authid.rolpassword`, restores in `finally` and reads back; a failed restore is a teardown error and the cluster must be recreated.
2. Native-login tests for `gpm_manager_app` follow the pattern of `test_native_api_login_cancels_with_default_allowlist_and_restricted_grants`: set a random password inside the restore wrapper, connect as the login, **dispose the engine before** restoring.
3. Scratch roles use random names (`gpm_t<random>_...`) and are dropped in `finally`. Observed while probing the local cluster: earlier suites left many `gpm_t*` roles behind (login roles with passwords and `stranger`/`nested` helpers). That is pre-existing clutter, not a Phase 2 problem, but Phase 2 tests must not add to it; a cleanup helper for stale scratch roles is a possible small follow-up (not part of this work package).
4. Never grant a runtime group more rights "temporarily" in a test; negative tests must run on the real matrix.
5. Run DB tests serially (no xdist); the disposable cluster is shared by the whole session.

## 3. Disposable-cluster lifecycle choices

| Option | Use when | Cost |
|---|---|---|
| A. Shared cluster + per-test schema reset + restore wrapper (current practice) | most tests | needs the wrapper discipline above |
| B. One-shot cluster per session/module | role-heavy tests (R2 grants, rotation) | slower; no state leaks by construction |
Recommendation: A for UoW/race tests, B for `P2B-DRT-02` and `-13` if the restore wrapper proves insufficient. Final choice goes to TV1 + TV2 ACK (`B-IF-09`).

## 4. Timeouts and failure injection

- Every UoW test sets `lock_timeout` and `statement_timeout` so a missed barrier fails the test instead of hanging the suite (values in `RUNTIME_BUDGET.md`).
- Failure injection uses real errors (constraint violation, killed backend via `pg_terminate_backend` from the owner session, statement raising inside the UoW), not mocks, for anything that claims atomicity or COMMIT classification.
- Barrier waits have a hard timeout; a timeout is `FAIL`, not `SKIP`.

## 5. Not allowed

Aim at a persistent/shared database; run migrations or downgrades there; use owner credentials in the application under test; print DSNs, passwords, verifiers, envelope bytes or tokens; report `NOT_RUN` as `PASS`.
