# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-03 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Integration branch:** `feat/gpu-int-01-runtime-integration` · **Task owner:** `@thangSy221105`

This is a progress and evidence record. It does not replace the approved API, database, module, test, or ADR documents.

## Branch and baseline

| Item | State |
|---|---|
| Latest fetched `origin/main` | `ef9ddcb0b0f594e11ef6ed787c9ad58ce92a613d` |
| Integration branch HEAD | `ef9ddcb0b0f594e11ef6ed787c9ad58ce92a613d` (fast-forward synchronized from `origin/main`; no integration feature commit yet) |
| Initial worktree | Clean before this task; local integration branch was created from `origin/main` and fast-forwarded after PR #28 merged |
| Current worktree | Contains uncommitted Stage A changes listed in this file's task branch; no commit, push, or PR created |
| Git operation gate | Commit/push/PR require separate user authorization |

## Upstream PR snapshot

Statuses and HEADs were fetched from GitHub on 2026-11-03. Only merged changes are part of the integration baseline.

| PR | State at snapshot | HEAD / merge evidence | Integration relevance |
|---|---|---|---|
| [#15](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/15) Jobs API foundation | MERGED | `07acef20eb6e1b403fc13a24138575d0f490a665` | Jobs read/command core; no PostgreSQL JobReader adapter found on `main` |
| [#28](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/28) D2 Job lifecycle guard | MERGED | Merge commit `ef9ddcb0b0f594e11ef6ed787c9ad58ce92a613d` | Adds role-aware Jobs `BEFORE UPDATE` trigger/migration and DB tests; integration must preserve its API/Manager role classes |
| [#17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17) Listings API/UI | OPEN | `7aa938286bf677129ab479a6992acf9665c7d4b4` | Not integrated; do not consume unmerged branch |
| [#31](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31) Listing PostgreSQL persistence | OPEN | `99aa023b22189bed41b968f51cf355c88eba0653` | Required Listing persistence/D7 is not on `main` |
| [#32](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/32) Jobs frontend | OPEN | `2a693e428bb9e9f8f4ddfffb74c316ccf1e50ff8` | Not integrated |
| [#33](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/33) Queued cancellation foundation | OPEN | `13cd3736052321d64980e4d89c730dc612d6abe8` | Not integrated; PostgreSQL cancel implementation remains a dependency |
| [#34](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/34) PostgreSQL cancel test preparation | OPEN | `92c25424e67563bcd62b1582465eb3ec72dc19d2` | Test preparation only; not a production persistence adapter |
| [#35](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/35) Auth PostgreSQL HTTP tests | MERGED | `c3f4ecb2cdf0988f4bcc8c39f7ba663101069c02` | 16 PostgreSQL-backed E1 tests; mounted production app/E2/E3 remain separate gates |
| [#23](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/23) Auth routes/principal (L2) | MERGED | Team lead and TV2 approved reviewed HEAD before merge | Approved Auth routes and shared principal contract |
| [#25](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/25) PostgreSQL AccountReader | MERGED | Merged 2026-10-25 | Auth's PostgreSQL adapter |
| [#27](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/27) D1 role bootstrap/grants | MERGED | Merged 2026-10-25 | Approved least-privilege API/Manager role grants |

## Dependency matrix

| Consumer/module | Required interface or artifact | State on `main` | GPU-INT-01 status / next gate |
|---|---|---|---|
| GPU-002 Database | AccountReader, D1 grants, Listing and Job persistence adapters | Auth AccountReader #25, D1 #27 and D2 #28 merged; Listing #31 open; JobReader adapter absent | **PARTIAL** — Stage A can use AccountReader and separate API/Manager DSN configuration; Stage B/C/D wait for accepted adapters |
| GPU-003 Identity | AuthService, token profile, Auth router, shared principal, PostgreSQL tests and UI | #23, #25 and #35 merged; frontend already has Login/Me/Logout UI and a single volatile SessionStore in `main.tsx` | **PARTIAL** — Stage A production composition implemented locally; runtime/browser test execution still not run here |
| GPU-004 Listings | Listings core/API/UI plus PostgreSQL persistence/D7 | #17 and #31 open | **BLOCKED** — wait for merged PRs and cross-phase ACKs |
| GPU-005 Jobs | Jobs read/command UI and PostgreSQL readers/transactions | #15 merged; #32–#34 open; production Job persistence adapters absent | **PARTIAL/BLOCKED** — read foundation exists; runtime integration waits for accepted DB adapters and command gates |

## Stage status

| Stage | Status | Evidence / blocker |
|---|---|---|
| A — Auth runtime integration | **IMPLEMENTED** | `create_app()` now composes Engine/sessionmaker, `PostgresAccountReader`, `AccessTokenCodec`, one `ScryptPasswordHasher`, shared `AuthService`, Auth router and shared principal dependency. JWT secret fails closed and is held as `SecretStr`. HTTP/DB regression tests were changed to use `create_app()`. Test execution is **NOT_RUN** in this environment (see Verification). |
| B — Jobs read | **BLOCKED** | JobReader PostgreSQL adapter is not present on `main`; do not mount a fake production adapter. |
| C — Listings | **BLOCKED** | #17 and #31 remain open; no branch code consumed. |
| D — Jobs commands/frontend | **BLOCKED** | D2 role-aware lifecycle trigger #28 is now on `main`; required PostgreSQL submit/cancel implementations and acceptance gates are not merged; #32–#34 remain open. |
| E — Full Phase 1 acceptance | **BLOCKED** | Depends on verified completion of A–D with real HTTP, PostgreSQL, frontend and CI evidence. |

## Stage A implementation and contract mapping

- Change class: **L1**, implementation within the merged Auth and D1 decisions. No JWT profile, route, DTO, error mapping, schema, grant, or business rule was changed. Auth route/policy decisions remain those reviewed on #18/#23 and synchronized in API Contract v0.9; D1 least-privilege roles/grants were approved and merged on #27.
- `backend/src/gpu_marketplace/api/app.py`: builds the PostgreSQL account reader and shared AuthService once per app process; mounts `/api/v1/auth`; saves the same service/principal dependency on `app.state`; retains engine disposal in lifespan.
- `backend/src/gpu_marketplace/identity/router.py`: stores its server-generated request ID in request state so the sanitized app-level Auth 500 path can preserve it.
- Frontend Auth already exists on `main`: `frontend/src/main.tsx` constructs one `AuthApi` and one volatile `SessionStore`, then passes it to `App`; Stage A did not add a second store or alter the UI.
- `backend/src/gpu_marketplace/common/config.py`: adds optional redacted `GPU_MARKETPLACE_JWT_SECRET` setting for shared Settings consumers; API startup requires it and rejects values shorter than 32 UTF-8 bytes. It is not generated by application startup and is never logged.
- `compose.yaml`, `.env.example`, `.github/workflows/foundation.yml`, `tools/compose_smoke.py`, `README.md`: require an operator-supplied local key; CI and disposable Compose smoke each generate a temporary random key. Smoke inspection key is only used to render/inspect Compose configuration, not to start the existing local project.
- Database use: Compose maps `GPU_MARKETPLACE_API_DATABASE_URL` and `GPU_MARKETPLACE_MANAGER_DATABASE_URL` separately to the internal `GPU_MARKETPLACE_DATABASE_URL` setting for each process. The checked-in example uses the local bootstrap account for local development only; nonlocal deployment must use the D1 `gpm_api_app` / `gpm_manager_app` logins. No grant, schema or migration change was made. Existing #35 tests exercise queries under `gpm_api_rw` via `SET LOCAL ROLE` in a shared outer transaction; the new production-factory test uses a separate Engine/pool with `SET ROLE gpm_api_rw`. These tests do **not** prove direct `gpm_api_app` login credentials or production deployment configuration.
- API contract: route paths and response semantics are unchanged; router continues to generate trusted UUIDv4 request IDs, `Cache-Control: no-store`, and the Bearer challenge on 401. Client `X-Request-ID` is ignored.
- Cross-phase impact: **CONFIRMED_IMPACT / ACK pending** for GPU-002 because Compose now routes API and Manager through independently configurable DSNs; GPU-002 owner ACK is required before merge. GPU-003 source and GPU-004/GPU-005 consumers must confirm the shared principal wiring before merge. No teammate branch or consumer implementation was changed.

## Verification

| Check | Result | Evidence / reason |
|---|---|---|
| `git diff --check` | **PASS** | Ran on current worktree; no whitespace errors |
| Latest `origin/main` sync | **PASS** | Fetched `ef9ddcb`; inspected #28 delta (migration README, D2 trigger migration, DB guard tests); fast-forwarded the same integration branch; no overlap with Stage A working files |
| Backend: `uv run --project backend --locked --group dev pytest backend/tests tests -rs` | **NOT_RUN** | `uv` is not available; the only Python launcher lists Python 3.11, while the project requires Python 3.12. The launcher execution was denied by the environment |
| PostgreSQL Auth HTTP tests / runtime role | **NOT_RUN** | Depends on the unavailable Python/uv test environment and a disposable marked PostgreSQL cluster; no test database was configured or touched |
| Simulator: `uv run --project simulator --locked --group dev pytest simulator/tests` | **NOT_RUN** | `uv` and the required Python 3.12 runtime unavailable |
| Frontend Vitest/typecheck/build | **NOT_RUN** | Node is 22.13.0, below required Node 24; `npm` launcher points to a missing user npm CLI |
| `docker compose config` | **NOT_RUN** | Docker CLI/Compose unavailable in this shell |
| Compose smoke (5 healthy services, API/frontend host access, PostgreSQL host query, Simulator DB isolation, cleanup) | **NOT_RUN** | Docker CLI unavailable; no Compose resources were started or cleaned |
| GitHub Actions for this diff | **NOT_RUN** | Changes are uncommitted/unpushed, so there is no CI run for this worktree |
| Python tests added in this diff | **NOT_RUN** | Includes app-mount/401/500-header/config tests and PostgreSQL Auth tests through `create_app()`, including an Engine/sessionmaker path; no PASS is claimed |

### Stage A acceptance case status

| Case | Status | Evidence boundary |
|---|---|---|
| INT-A01 startup | NOT_RUN | Production composition now requires a valid configured secret; no runtime available |
| INT-A02 liveness | NOT_RUN | Existing health test retained, execution unavailable |
| INT-A03 readiness | NOT_RUN | Existing probe test retained; it is not live PostgreSQL evidence |
| INT-A04–A07 login, disabled account, `/me`, account refresh | NOT_RUN | PostgreSQL HTTP tests cover these paths through `create_app()`; disposable cluster not configured |
| INT-A08 401/Bearer | NOT_RUN | New app-mount test and PostgreSQL suite cover header behavior; not executed |
| INT-A09 status/role recheck | NOT_RUN | Existing PostgreSQL test cases; no runtime execution here |
| INT-A10–A11 logout/no revocation | NOT_RUN | Existing PostgreSQL test case; no runtime execution here |
| INT-A12 database unavailable | NOT_RUN | Existing sanitized-503 test uses an unreachable test port; not executed |
| INT-A13 missing/short secret | NOT_RUN | New fail-closed app/config tests; not executed |
| INT-A14 forged request ID | NOT_RUN | New test covers server UUIDv4 and ignores client value; not executed |
| INT-A15 private/error headers | NOT_RUN | New app-mount tests check 401 and unexpected 500 envelopes, no-store, server UUIDv4, and Bearer on 401; not executed |
| INT-A16 frontend Login → Me → Logout | NOT_RUN | Auth UI and one volatile SessionStore exist on `main`; real browser → mounted API → PostgreSQL E2 evidence is unavailable in this shell |
| INT-A17 runtime database role | NOT_RUN | Existing test uses `SET LOCAL ROLE gpm_api_rw`; new Engine-path test uses a separate pool and `SET ROLE gpm_api_rw`. Independent `gpm_api_app` login credentials remain unverified |
| INT-A18 regression | NOT_RUN | Backend/full-project suites unavailable in this shell |

## Remaining blockers and next actions

1. Run the backend suite, including marked disposable PostgreSQL tests, with Python 3.12 and locked uv dependencies. PostgreSQL tests must use the disposable safety markers; do not point them at the local persistent Compose volume.
2. Run simulator/frontend checks with supported runtimes; run Compose config and smoke when Docker is available.
3. Confirm D1 runtime DSN/provisioning for the environment used to demonstrate real Auth requests. The local foundation `.env.example` remains explicitly local-development-only and uses its existing local DB bootstrap configuration.
4. Obtain required inter-phase ACKs from GPU-003/004/005 owners before merge; obtain an independent human review for the L1 PR.
5. Re-fetch `origin/main` and upstream PR states before continuing. Merge `origin/main` into this same branch normally if it advanced; resolve conflicts without discarding member changes.
6. Commit, push and create/update the draft PR only after separate user authorization. Do not merge.
