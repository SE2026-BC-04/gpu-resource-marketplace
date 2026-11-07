# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-07 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** @thangSy221105

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Git and PR state

| Item | State |
|---|---|
| Local branch | `feat/gpu-int-01-runtime-integration` (existing shared integration branch; no additional branch created) |
| Key integration commits | `b457c0f` — runtime wiring; `ccdfce6` — Jobs frontend; `deb352c` — adapter assertion fix; `ce6b821` — first green implementation CI; `1255831` — Playwright browser E2E and CI setup; `0f48b4d` — final remediation; `b6b851e` — local database URL hardening |
| Latest implementation HEAD with browser E2E evidence | `a701866ca8e2d5b5530662219224d09d8becd1bf` |
| CI run for the latest implementation HEAD | [#42350587295](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42350587295) — all 4 jobs passed, including disposable PostgreSQL, Compose restart persistence, browser E2E, and PowerShell setup regression |
| Local base before this work | `46e976356b83c2384f359f35b08262dfd2970f0b` |
| Main baseline | `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` |
| PR #39 before the integration extension | Open, Draft, base `main`, head `46e976356b83c2384f359f35b08262dfd2970f0b`; rechecked through GitHub on 2026-11-07 |
| Latest pushed implementation HEAD before this progress update | `a701866ca8e2d5b5530662219224d09d8becd1bf`; Actions run #42350587295 passed all 4 jobs |
| PR #39 state verified before this progress update | Open, Draft, base `main`, implementation head `a701866ca8e2d5b5530662219224d09d8becd1bf`; not merged |
| Worktree before this progress update | Clean at `a701866ca8e2d5b5530662219224d09d8becd1bf`; this evidence update is being added to the same branch |
| Git gate | Owner authorized work on this branch and PR #39. Do not push `main`, force-push, approve, mark Ready, or merge. |

## Upstream dependencies

| PR | State on current main | Integration relevance |
|---|---|---|
| #15 | Merged | Jobs API foundation |
| #17 | Merged | Listings API/UI source |
| #31 | Merged | PostgreSQL Listings UoW and D7 |
| #32 | Merged | Jobs frontend foundation |
| #33 / #34 | Merged | TX-CANCEL ports and PostgreSQL test preparation |
| #35 | Merged | Auth PostgreSQL HTTP tests |
| #40 | Merged | PostgreSQL TX-CANCEL adapter |
| #41 | Merged | Listing repository timestamp test fix |

Only code already merged to `main` was integrated. No unmerged member branch was cherry-picked.

## Dependency matrix and stage status

| Stage | Status | Evidence / blocker |
|---|---|---|
| A — Auth runtime | **IMPLEMENTED** | `create_app()` wires one AuthService, PostgreSQL AccountReader, configured JWT codec, one Scrypt hasher, shared principal dependency, and engine lifespan. Real HTTP/PostgreSQL E2E passed on run #42267396758. |
| B — Jobs read | **IMPLEMENTED** | `PostgresJobReader` enforces Client/Worker/Admin visibility in SQL; PostgreSQL reader tests passed in run #42267396758. |
| C — Listings | **IMPLEMENTED** | Production Listing UoW/router and `SessionListingsPage` use the shared Auth principal and SessionStore. Worker create + Client browse passed in the real HTTP/PostgreSQL E2E test. |
| D — Jobs submit/view/cancel | **IMPLEMENTED** | TX-SUBMIT/Cancel/Job reads and PostgreSQL verification passed in the real HTTP E2E. The first CI run exposed an incorrect fixed-seed assertion for a random Job ID; it was fixed in `deb352c`, and the full PostgreSQL suite then passed. |
| E — full Phase 1 acceptance | **VERIFIED** | On `125583170829421d5ea5be5022465f715a5b3d2a`, GitHub Actions run #42274038230 passed the production frontend Chromium flow through Auth/Listings/Jobs and disposable PostgreSQL. The browser creates a Listing, submits/views/cancels a Job, and PostgreSQL confirms the final Job and protected reference. All 3 CI jobs passed. Human review and cross-phase ACKs remain separate merge gates. |

## Decisions and compatibility gates

- On 2026-11-07 the owner approved, in PR comment [#6690901724](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6690901724), the exact existing reference draft `docs/architecture/phases/phase1e_gpu005_reference_technical_specification.md`, including `demo-v1-public1`, byte rules and vectors V1–V4. This approval is limited to storing the protected Phase 1 reference; it does not authorize Simulator execution, Manager scheduling, or other Phase 2 work.
- The same owner decision resolves retained idempotency replay: same `(client_id, key)` and normalized body returns the original Job with HTTP 200 even if its Listing is now PAUSED. A changed body conflicts; a new key still requires ACTIVE and locked admission checks.
- On 2026-11-07 the owner also approved a Playwright-only test dependency and Chromium browser runner to verify Stage E. This adds no production runtime dependency or application behavior.
- API Contract, Database Design, schema, migrations, grants, ADRs, routes, and DTOs were not changed. Reference data is excluded from public DTOs and Simulator input.
- Required renewed cross-phase checks on the new HEAD remain pending: TV2 for schema/D1 runtime permissions/adapter, TV4 for Listing locking and pause/replay ordering, TV3 for authenticated Client/shared-session behavior, and the assigned Phase 2 owner for compatibility with ADR-004/Signed Result V1. The Phase 2 owner is not recorded in the current handoff.
- These checks do not replace an independent human review. PR #39 remains Draft; no reviewer has approved this new diff.

## Verification evidence

Local backend and Simulator commands used the repository venvs because `uv` and a global Python 3.12 launcher are unavailable. Docker CLI is not installed/available. Frontend checks used Node 22.13.0/npm 10.9.2; package downloads used `D:\gpu-marketplace-npm-cache`.

| Check | Result | Evidence / limitation |
|---|---|---|
| Full local backend regression after browser E2E addition | **PASS — 798 passed, 355 skipped, 0 failed** | `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -rs`; exit 0, 70.01s. PostgreSQL tests, including HTTP/browser E2E and adapter suites, skip because disposable database safety variables are unavailable locally. |
| Full local backend regression after final-remediation test changes | **PASS — 821 passed, 358 skipped, 0 failed** | `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -rs`; exit 0, 36.18s. Python 3.12.15; the guarded PostgreSQL adapter and HTTP/E2E suites remain skipped because the safety-marked disposable database variables are not configured locally. |
| CORS unexpected-auth-failure regression | **PASS — 7 passed** | `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api_cors.py -q`; exit 0, 1.67s. Includes an allowed-Origin unexpected Auth 500 response, `Access-Control-Allow-Origin`, `X-Request-ID`, `Cache-Control: no-store`, and sanitized error body. |
| Simulator regression | **PASS — 2 passed** | `simulator/.venv/Scripts/python.exe -m pytest simulator/tests`; exit 0. This tests Simulator regression only, not Phase 2 execution. |
| Frontend dependency install | **PASS** | `npm ci --cache D:\gpu-marketplace-npm-cache`; 115 packages installed, 0 vulnerabilities. Node 22.13.0/npm 10.9.2 local. |
| Frontend Vitest | **PASS — 158 passed, 10 files** | `npm test`; exit 0. Vitest is scoped to `src/`; it no longer loads Playwright specs. |
| Frontend typecheck | **PASS** | `npm run typecheck`; exit 0, including `tsconfig.e2e.json` for Playwright config/spec. |
| Frontend production build | **PASS** | `node node_modules/vite/bin/vite.js build`; exit 0. |
| Docker Compose config and smoke | **NOT_RUN** | Docker CLI not found. No local Compose, HTTP, PostgreSQL `SELECT 1`, runtime-role, five-service health, or cleanup result is claimed for this worktree. |
| `uv` locked install/run | **NOT_RUN** | `uv` CLI not found; tests used repository-provided virtual environments. |
| Playwright discovery | **PASS — 1 browser test found** | `node node_modules/@playwright/test/cli.js test --config=playwright.config.ts --list`; confirms the Worker → Client journey is collected. |
| Browser + real HTTP + PostgreSQL acceptance (local) | **NOT_RUN** | The integrated pytest test skipped under its safety guard because no disposable test cluster was configured locally. GitHub Actions on the upcoming pushed HEAD will run the real browser against disposable PostgreSQL. |
| `git diff --check` | **PASS** | Exit 0; Git only warns that an existing test file with LF will convert to CRLF on a future checkout write. |
| Secret scan | **PASS** | Changed-file scan found no private-key block, GitHub token, or AWS access-key pattern. Test credentials are synthetic fixture values; `.env.example` contains blank signing keys and local-only sample DB credentials. |
| GitHub Actions on pushed `ce6b821` | **PASS — all 3 jobs** | Run [#42267396758](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42267396758): Python **PASS** (backend 1,153 passed; Simulator 2 passed), Frontend **PASS** (Vitest/typecheck/build), Compose **PASS** (config/smoke). PostgreSQL submit/cancel adapter tests and the real HTTP + disposable PostgreSQL E2E test passed. |
| GitHub Actions on pushed `6dff518` | **PASS — all 3 jobs** | Run [#42268439328](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42268439328): Python, Frontend, and Compose jobs all completed successfully after the progress-documentation update. |
| GitHub Actions on browser E2E HEAD `1255831` | **PASS — all 3 jobs** | Run [#42274038230](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42274038230): Python **PASS** (1,153 passed; Simulator 2 passed), Frontend **PASS**, Compose **PASS**. Python logs show Chromium/Playwright installed and `test_phase1_runtime_http_postgres_e2e.py` passed against the safety-marked disposable PostgreSQL cluster; this includes the Worker → Client browser flow and DB assertions. |
| GitHub Actions on final-remediation implementation HEAD `0f48b4d` | **PASS — all 3 jobs** | Run [#42343339313](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42343339313): Python **1,179 passed** (plus Simulator **2 passed**), Frontend **158 passed / 10 files**, TypeScript typecheck and production build **PASS**, Compose smoke **PASS**. Compose used dynamic host ports while detecting an existing local stack; verified all 5 services healthy, production frontend + SPA fallback, host PostgreSQL `SELECT 1`, API/Manager runtime roles, Auth unready before migrations and available after, Simulator DB isolation, and cleanup leaving the existing stack unchanged. |
| Earlier GitHub Actions on `a3f9d26` | **FAIL — corrected and rerun** | Run [#42266303614](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42266303614): 1,152 passed / 1 failed in Python; Frontend and Compose passed. The failed adapter assertion assumed a fixed seed for a DB-generated random Job ID; corrected in `deb352c`. Run #42267396758 on `ce6b821` then passed all jobs. |
| Earlier CI on `46e9763` | **PASS, older HEAD only** | Run [#42252304145](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42252304145) passed Python, Frontend, and Compose before this integration diff; it is not evidence for new changes. |

## Changed implementation scope

- Auth/CORS, Listings runtime composition, Jobs read/submit/cancel runtime wiring, PostgreSQL adapters, regression tests, Jobs UI integration, `.env.example`, Compose smoke/configuration, CI, README, Playwright test-only dependency/config/spec, and this progress record.
- No Requirements, API Contract, Database Design, migration, grant, ADR, Manager scheduler, Simulator execution, or Phase 2 implementation changes.

## Final remediation update — 2026-11-07

Before editing, `git fetch origin` succeeded. The shared branch and PR #39 were both at `9ba7d6d7e4abc229d8476c87023f51e21d48837e`; `origin/main` was `1d8b1b2c52b759d99a072c3d0d889b375083a8c4`. The working tree had only the local remediation changes described below. No upstream commits appeared during the fetch.

| Finding / area | Result on this remediation | Evidence / remaining gate |
|---|---|---|
| Auth schema missing on a fresh Compose volume | **Addressed by existing runtime readiness + Compose smoke coverage** | `/health/ready` reports Auth schema unavailable and Auth login fails closed before migrations; after migration, the smoke checks the real mounted Auth route. Compose smoke has not run locally (Docker unavailable); GitHub Actions must recheck the pushed head. |
| CORS on unexpected Auth 500 | **Regression covered** | Added `test_unexpected_auth_failure_keeps_cors_and_private_error_headers`; HTTP test confirms an allowed Origin can read the sanitized 500 and request ID. Seven CORS tests pass locally. |
| Cancel request contract / blocking DB call | **Implemented** | Cancel rejects any non-empty body before service invocation and calls the synchronous transaction service via `run_in_threadpool`; empty-body behavior and auth/response headers are covered by HTTP tests. |
| PostgreSQL COMMIT uncertainty | **Implemented** | Only SQLSTATE class 23 and the explicit definite-rollback allowlist (`40000`, `40001`, `40002`, `40P01`) are definite aborts. `40003`, connection failures, and unknown codes remain uncertain and are not retried. Fault tests pass; durable/lost-ACK PostgreSQL tests are guarded and need CI's disposable database. |
| Local V1 demo setup | **Implemented as explicit local-only provisioning** | README gives setup steps; the account tool requires explicit local-development confirmation, loopback `gpu_marketplace`, database-owner identity, hidden passwords, and insert-only behavior. Nine local guard tests pass. No credentials are committed. |
| GPU-005 protected reference status | **Owner decision synchronized** | The exact reference algorithm/vectors and paused-listing replay rule are recorded as Phase 1 approved via decision comment #6690901724. Phase 2 output schema/execution remains unapproved. |
| FIX-03 — readiness for complete V1 Listings/Jobs dependency set | **BLOCKED — L2 owner decision required; no code changed** | Current accepted Foundation §4.1 covers database/Auth readiness. Expanding it to Listings/Jobs relations and runtime privileges changes operational readiness. CR `CR-GPU-INT-01-READY-01` is recorded as **PROPOSED** in [PR comment #6702856516](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6702856516). It proposes catalog-only checks (including INSERT privilege only for `simulation_references`, never reading protected rows) or retaining current semantics. Owner decision and normative/test-design update are required before implementation. |
| C1 scrypt work-factor evidence | **PENDING** | No fresh benchmark/load evidence was run in this remediation. The existing accepted Option A decision remains in force; do not claim the evidence gate has passed. |

This remediation was tested locally with Python 3.12.15 from the repository venv. `uv` and Docker are unavailable in the local PATH; Node 22.13.0 is available, but `npm`'s global shim is broken, so previously installed frontend dependencies were used. Full backend regression passed at **821 passed, 358 skipped, 0 failed**; the skipped PostgreSQL tests require a safety-marked disposable database. Simulator, frontend Vitest, TypeScript, and production build checks previously passed on the unchanged implementation; Compose, local PostgreSQL, and local browser E2E remain **NOT_RUN**. GitHub Actions run [#42343339313](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42343339313) on implementation commit `0f48b4d67573cb32a01f88a4a4ba7dd0a40ea7f4` passed all three CI jobs, including full disposable PostgreSQL/browser E2E and isolated Compose smoke.

## Final local-database security remediation — 2026-11-07

Before editing, local `HEAD` and the PR #39 branch were `142eac332cd15c33aa312cf456261ad849ca90fc`; the worktree contained no pre-existing changes. A direct `git fetch origin` was blocked by this workstation's network, so the connected GitHub integration was used to confirm PR #39 was still open and Draft at that exact head, with no new owner decision. Commit `b6b851eebbdb31ddd552eb692480ef59dcb936d1` was pushed as a fast-forward to the existing branch. No branch or PR was created.

| Finding / check | Result | Evidence |
|---|---|---|
| P2 — local demo database URL bypass | **FIXED** | `validate_local_owner_url()` rejects every query parameter, accepts only the explicit PostgreSQL psycopg driver, loopback host, explicit username and valid TCP port, and the exact `gpu_marketplace` database. Before engine creation, the CLI rejects ambient `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSERVICE`, and `PGSERVICEFILE`. Errors report names/types only and do not expose URL credentials, routing values, SQL, or exception details. |
| LOCAL-01..12 regressions | **PASS** | Tests cover accepted loopback forms, remote/wrong-database/wrong-driver/malformed/no-port/no-user URLs, `host`, `hostaddr`, `service` and other query overrides, non-owner rejection, environment overrides, and that an override is rejected before `create_engine`; no test connects to a remote host. |
| P3 — demo account PostgreSQL integration tests | **PASS in CI; locally guarded** | Four disposable-database tests cover Worker/Client provisioning, roles/profile, Scrypt hashes, actual `AuthService` logins, duplicate no-mutation, transaction rollback, and database/owner mismatch with no insert. They skipped locally under the repository safety guard and all ran in CI's disposable PostgreSQL job. |
| Cancel / COMMIT / Auth-CORS regressions | **PASS** | Targeted local suite and the full CI Python suite passed. CI also passed `test_phase1_runtime_http_postgres_e2e.py` against disposable PostgreSQL. |
| Readiness decision CR-GPU-INT-01-READY-01 | **NEEDS_OWNER_DECISION** | The latest PR comments still contain only the proposal. No Option B or readiness-contract change was implemented. |
| C1 Scrypt decision | **Option A — integration only** | Benchmark/load evidence remains `NOT_RUN / PENDING`; no production deployment claim is made. |

Local verification used Python 3.12.15 from the repository venv because `uv` is unavailable. The focused command for `test_local_demo_accounts.py`, `test_jobs_auth_integration.py`, and `test_api_cors.py` passed **46 tests**, skipped **4** guarded PostgreSQL tests, and exited 0 in 2.41s. Full backend regression passed **839**, skipped **362**, failed **0**, with 2 warnings; exit 0 in 27.94s. Simulator passed **2** (exit 0). Frontend Vitest passed **158 / 10 files**; TypeScript checks and production build passed. Local `npm ci` could not run because the global npm shim points to a missing `npm-cli.js`; existing `node_modules` were used for Vitest, `tsc`, and build. Docker/Compose and local PostgreSQL/browser E2E were `NOT_RUN` because Docker is unavailable and no guarded disposable database is configured.

GitHub Actions run [#42346424133](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42346424133) on `b6b851e` passed all 3 jobs. Python: **1,201 passed** in backend/topology tests, including `test_phase1_runtime_http_postgres_e2e.py`; Simulator: **2 passed**. Frontend: **158 passed**, typecheck and production build passed. Compose smoke verified five healthy services, production frontend and SPA fallback, the runtime API URL with a dynamically reserved port, host-to-PostgreSQL `SELECT 1`, API/Manager database access, Auth fail-closed before disposable migrations and available after, Simulator PostgreSQL isolation, and cleanup that left the pre-existing local stack unchanged.

`git diff --check`, changed-file secret-pattern scan, README relative-link check, and the PowerShell cryptographic secret-generation helper check passed locally. Independent human review, renewed TV2/TV3/TV4/TV5 ACKs for the latest head, and the owner L2 readiness decision remain pending; prior ACKs and reviews do not count as confirmation on this new head. Existing Auth-schema and CORS review threads remain open. PR #39 stays Draft; no self-approval, Ready conversion, or merge was performed.

## Local V1 setup remediation — 2026-11-07

The owner-authorized setup remediation started from reviewed HEAD `2431aa9752863f9da1620be0fede676e0f9f7a5e`. The local branch and `origin/feat/gpu-int-01-runtime-integration` were aligned and clean before edits. `git fetch origin` could not reach GitHub from this workstation; PR #39 was rechecked through the connected GitHub account and remained open, Draft, unmerged, and at the reviewed HEAD with no newer owner decision.

| Finding / check | Result | Evidence |
|---|---|---|
| FIX-01 — stale owner DSN in PowerShell process | **FIXED** | `tools/local_setup.ps1` builds role-specific API/Manager DSNs and synchronizes each to both process environment and `.env`. The README parses the effective Compose JSON in memory, checks the configured usernames, and does not print resolved DSNs. |
| FIX-02 — Alembic config path from repository root | **FIXED** | Root README and `backend/migrations/README.md` now use `alembic -c backend/alembic.ini`; `tools/verify_alembic_head.py` requires one repository head and checks the database `alembic_version` matches it. Local Alembic discovery reports one head: `0005_listing_d7`. A disposable PostgreSQL execution is pending CI. |
| FIX-03 — fail-fast local setup | **IMPLEMENTED** | Setup waits for PostgreSQL health, uses create-only role bootstrap, keeps owner credentials for migrations, verifies migration current/head and native runtime logins before demo accounts, and stops safely on failed bootstrap/migration. Secrets and full DSNs are suppressed from command output. |
| FIX-04 — runtime role proof | **IMPLEMENTED** | `tools/verify_runtime_roles.py` checks native `current_user = session_user`, role/database identity, database owner separation, restricted role flags and no database/schema CREATE. Compose smoke runs this from the host through its dynamically reserved loopback port and repeats checks after stack recreation. |
| FIX-05 — full V1 E2E regression | **PASS in CI** | Compose smoke verified five healthy services, production frontend assets/SPA route, host API and PostgreSQL access, native API/Manager roles, Simulator isolation, and committed data persistence after `down`/`up`. The HTTP + Chromium browser flow passed against disposable PostgreSQL. |
| Schema, grants, contracts, readiness and C1 | **UNCHANGED** | No migration, database schema/grant, API contract, business rule, readiness L2, Phase 2 or C1 Option A change is included. `CR-GPU-INT-01-READY-01` remains `PROPOSED — NEEDS_OWNER_DECISION`. |

Local verification for this remediation used the checked-in backend and simulator virtual environments because `uv` is not installed. Backend: **841 passed, 362 skipped, 0 failed**, 2 warnings, exit 0; skipped tests require a safety-marked disposable PostgreSQL database. Simulator: **2 passed**, exit 0. The PowerShell setup regression passed, including stale owner DSN replacement in the process and `.env`, URI escaping, ambient PostgreSQL routing rejection, fail-fast bootstrap/migration errors and redaction. Compose topology tests: **6 passed**, exit 0. Python compile checks passed and Alembic reports exactly one head. Local Docker/Compose, PostgreSQL and HTTP/browser E2E are **NOT_RUN** because Docker and a safety-marked disposable database are unavailable.

Local frontend `npm ci` was rerun through the npm CLI installed on D: with cache `D:\gpu-marketplace-npm-cache`; **115 packages installed, 0 vulnerabilities**, exit 0. Vitest: **158 passed / 10 files**; TypeScript typecheck and production build both passed, exit 0. Playwright discovery found the single Worker → Client flow after setting `PHASE1_E2E_BASE_URL`; the browser E2E itself is **NOT_RUN locally** because no Compose/PostgreSQL runtime is available. The initial sandbox-only package download attempt was denied (`EACCES`); the D: install above completed successfully.

The setup remediation and integration evidence are on implementation commit `a701866ca8e2d5b5530662219224d09d8becd1bf`. Actions run [#42350587295](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42350587295) completed **PASS on all four jobs**. Python used Python 3.12.15 and reported **1,203 passed, 140 warnings**; it also ran the browser/HTTP/PostgreSQL E2E and verified that migration `0005_listing_d7` matches the single Alembic head. Simulator reported **2 passed, 1 warning**. Frontend reported **158 passed / 10 files**, with typecheck and production build passing. Compose smoke confirmed all five services healthy, host HTTP/PostgreSQL reachability, API/Manager native restricted roles, Simulator isolation, persistence across Compose recreation, and cleanup that left the pre-existing local stack unchanged. The Windows PowerShell setup job passed.

The first run [#42350446058](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42350446058) passed Python, Frontend, and Compose but reported the PowerShell job failed because the test's intentional nonzero probes left a stale `$LASTEXITCODE` after all assertions passed. Commit `a701866` resets the process exit code only after successful assertions; both file and GitHub-style dot-source invocation pass locally, and the Windows job passed in run #42350587295.

PR #39 remains Draft. Independent human review, renewed TV2/TV3/TV4/TV5 compatibility ACKs on the final code, C1 performance evidence, and the owner decision for readiness expansion remain separate gates. No self-approval, Ready conversion, or merge was performed.

## Next actions

1. Keep PR #39 Draft and obtain renewed TV2/TV3/TV4/TV5 compatibility ACKs plus one independent human review on the latest head.
2. Obtain the owner's L2 decision for CR-GPU-INT-01-READY-01 before implementing any readiness expansion.
3. Address any review findings on this same branch and rerun CI; approvals for older SHAs do not carry over.
4. Do not mark Ready or merge until the required review confirmations and applicable gates are complete.

## PR #39 final finding remediation — 2026-11-07 (pre-push verification)

PR #42 is included in the integration branch. `git fetch origin` succeeded before final validation; local HEAD and `origin/feat/gpu-int-01-runtime-integration` both remain at baseline `6788505cbb68e09ad08ea2b96728bc6c69e8a32e` (main: `1d8b1b2c52b759d99a072c3d0d889b375083a8c4`). The PR remains open and Draft. The latest GitHub review-thread read found the three in-scope P2 threads still open: Listing mutation audit (TV4), Jobs mutation audit (TV5), and PostgreSQL role credential restoration (TV5). No review thread was resolved by this work.

| Finding | Implementation status | Local evidence / remaining gate |
|---|---|---|
| P2-PGROLE | **FIXED in code** | The HTTP/browser/PostgreSQL E2E uses PR #42's `restored_login_role_credentials` fixture around the whole test. It snapshots both login verifiers before rotation and restores/verifies exact values, including `NULL`, after runtime engines and API/frontend processes have closed. Failure/restore tests are in `test_role_credentials_restore.py`. The disposable PostgreSQL tests were skipped locally; CI must execute them on a safety-marked disposable cluster. |
| P2-LISTING-AUDIT | **IMPLEMENTED** | Create/update/pause/resume success events use the existing `audit_events` table/grants in the Listing mutation transaction. Rejections are distinct; dependency failures are recorded as `ERROR` when outcome is known. Unknown COMMIT is not followed by a contradictory side-channel failure row. Guarded PostgreSQL adapter tests assert the success audit persists with a durable lost-ack COMMIT and leaves no audit row after rollback; the HTTP E2E also checks correlated outcomes. These PostgreSQL tests await CI. |
| P2-JOBS-AUDIT | **IMPLEMENTED** | Submit and Cancel success events are atomic with their Job mutation; rejected/error outcomes use redacted reason codes. Replay does not add duplicate success events. Adapter regression assertions cover rollback, durable lost-ack, rejected replay, and cancellation conflict; PostgreSQL cases are guarded and await CI. |
| R3 Submit ↔ Pause/Resize | **TESTS ADDED; runtime proof pending** | Four PostgreSQL concurrency cases use independent sessions and `threading.Event` barriers for both lock/commit orders, then check Job/reference/audit counts and fresh capacity. The suite contains no `sleep` to select a winner. All four tests skip locally until a disposable PostgreSQL cluster is configured; GitHub Actions must provide the actual race evidence. |

Implementation changes touch the API composition, Listing and Jobs services/routes/adapters, the shared audit writer, the E2E and PostgreSQL race tests, and their focused unit/fake tests. No API contract, database schema/migration/grant, JWT, approved reference algorithm, lock order, idempotency rule, or Phase 2 behavior was changed.

Local checks on Python 3.12.15 used the repository virtual environments because `uv` is unavailable:

- Targeted audit/Listing/Submit/Cancel/E2E/race selection: **356 passed, 40 skipped**, 1 warning, exit 0. The skips are PostgreSQL tests blocked by the missing safety-marked disposable database.
- Full backend/topology regression: **851 passed, 372 skipped, 0 failed**, 2 warnings, exit 0 in 42.47s. PostgreSQL tests, including the HTTP/browser E2E and four races, are included among the guarded skips.
- Simulator: **2 passed**, 1 warning, exit 0.
- Frontend Vitest: **158 passed / 10 files**, exit 0; TypeScript typecheck (including E2E config) and production Vite build passed.
- PowerShell local setup regression: **PASS**, exit 0.
- Python compile check: **PASS**, exit 0.
- Local Docker/Compose smoke and real HTTP/browser/PostgreSQL E2E: **NOT_RUN** because Docker and a configured disposable PostgreSQL cluster are unavailable. `npm`'s global shim and `uv` are also unavailable; frontend checks used the installed Node 22.13 dependencies directly.
- GitHub Actions run [#42384516429](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42384516429) on `9b7ffa06feca60a593eda24db561e9deb16992e8`: **Python FAIL**, while Frontend, Compose, and PowerShell **PASS**. The disposable PostgreSQL HTTP E2E returned 503 on Listing create because the ORM-generated INSERT included `RETURNING audit_events.id`, which requires a SELECT privilege excluded by the accepted column-scoped audit grants. The fix uses an inline INSERT with no `RETURNING`; a regression assertion compiles the statement and verifies that no RETURNING clause is emitted. Local audit/Listing tests pass **317**, exit 0. Push the fix on this same branch and rerun all CI before changing this disposition.
- Follow-up Actions run [#42384916449](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42384916449) on `a9d294eb277ca6ed32d7acbbae18ecd2ede0ee76`: Frontend, Compose, and PowerShell **PASS**; Python **FAIL** in `test_postgres_same_key_same_body_replays_after_listing_is_paused` because its new audit assertion referenced an undefined local `key`. The disposable HTTP/browser E2E progressed beyond the previous Listing INSERT failure. The fixture now binds and reuses the replay key explicitly; all CI must complete again on the next pushed SHA.

**Provisional disposition: `BLOCKED_TECHNICAL` pending the safety-guarded PostgreSQL/browser/Compose jobs and final GitHub Actions on the pushed SHA.** After successful CI, request renewed scoped human review from `@TranVu2005`, `@giakhanh-hub`, `@VietNguyen865`, and `@NguyenDucThang-tb`. Keep PR #39 Draft and leave its review threads open until reviewers confirm. Existing `CR-GPU-INT-01-READY-01`, C1 Scrypt evidence, independent human review, and compatibility ACKs remain separate gates.
