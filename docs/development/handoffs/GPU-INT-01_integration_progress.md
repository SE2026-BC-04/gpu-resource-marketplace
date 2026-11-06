# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-07 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** @thangSy221105

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Git and PR state

| Item | State |
|---|---|
| Local branch | `feat/gpu-int-01-runtime-integration` (existing shared integration branch; no additional branch created) |
| Integration commits | `b457c0f` — backend/runtime wiring and tests; `ccdfce6` — Jobs frontend/shared-session integration; `a3f9d26` — progress snapshot; `deb352c` — fix random-Job-ID reference assertion |
| Local HEAD before this progress update | `deb352c` |
| PR #39 remote head before this update | `a3f9d261da060c07ef3616de598fb37da6e45417` |
| Local base before this work | `46e976356b83c2384f359f35b08262dfd2970f0b` |
| Main baseline | `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` |
| PR #39 before this work | Open, Draft, base `main`, head `46e976356b83c2384f359f35b08262dfd2970f0b`; rechecked through GitHub on 2026-11-07 |
| Working tree | Backend/frontend changes and the PostgreSQL assertion fix are committed locally; this progress update is not yet committed/pushed. |
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
| A — Auth runtime | **IMPLEMENTED** | `create_app()` wires one AuthService, PostgreSQL AccountReader, configured JWT codec, one Scrypt hasher, shared principal dependency, and engine lifespan. The real HTTP/PostgreSQL E2E test passed on GitHub Actions run #42266303614. |
| B — Jobs read | **IMPLEMENTED** | `PostgresJobReader` enforces Client/Worker/Admin visibility in SQL; all three PostgreSQL reader tests passed in run #42266303614. |
| C — Listings | **IMPLEMENTED** | Production Listing UoW/router and `SessionListingsPage` use the shared Auth principal and SessionStore. Worker create + Client browse passed in the real HTTP/PostgreSQL E2E test in run #42266303614. |
| D — Jobs submit/view/cancel | **IMPLEMENTED** | HTTP E2E Submit → View → Cancel → PostgreSQL verification passed in run #42266303614. One separate TX-SUBMIT adapter assertion failed because it expected the fixed-vector seed for a randomly generated Job ID; corrected in local commit `deb352c`, CI rerun pending. |
| E — full Phase 1 acceptance | **BLOCKED** | Browser E2E has not run. The first new-head Python job also had the adapter assertion failure above; the fix is committed locally and awaits CI. No full Phase 1 E2E PASS is claimed. |

## Decisions and compatibility gates

- On 2026-11-07 the owner approved, in PR comment [#6690901724](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6690901724), the exact existing reference draft `docs/architecture/phases/phase1e_gpu005_reference_technical_specification.md`, including `demo-v1-public1`, byte rules and vectors V1–V4. This approval is limited to storing the protected Phase 1 reference; it does not authorize Simulator execution, Manager scheduling, or other Phase 2 work.
- The same owner decision resolves retained idempotency replay: same `(client_id, key)` and normalized body returns the original Job with HTTP 200 even if its Listing is now PAUSED. A changed body conflicts; a new key still requires ACTIVE and locked admission checks.
- API Contract, Database Design, schema, migrations, grants, ADRs, routes, and DTOs were not changed. Reference data is excluded from public DTOs and Simulator input.
- Required renewed cross-phase checks on the new HEAD remain pending: TV2 for schema/D1 runtime permissions/adapter, TV4 for Listing locking and pause/replay ordering, TV3 for authenticated Client/shared-session behavior, and the assigned Phase 2 owner for compatibility with ADR-004/Signed Result V1. The Phase 2 owner is not recorded in the current handoff.
- These checks do not replace an independent human review. PR #39 remains Draft; no reviewer has approved this new diff.

## Verification evidence

Commands used existing local venvs directly because `uv` is not on PATH. Docker CLI is not installed/available. Node dependencies already existed; `npm` itself could not be used, so installed Node entry points ran the same Vitest/typecheck/build tasks.

| Check | Result | Evidence / limitation |
|---|---|---|
| Full local backend regression after `deb352c` | **PASS — 798 passed, 355 skipped, 0 failed** | `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -rs`; exit 0, 48.08s. PostgreSQL tests, including the new HTTP E2E and adapter suite, skip because the disposable database safety variables are unavailable locally. |
| Simulator regression | **PASS — 2 passed** | `simulator/.venv/Scripts/python.exe -m pytest simulator/tests`; exit 0. This tests Simulator regression only, not Phase 2 execution. |
| Frontend Vitest | **PASS — 158 passed, 10 files** | `node node_modules/vitest/vitest.mjs run --reporter=dot`; exit 0. |
| Frontend typecheck | **PASS** | `node node_modules/typescript/bin/tsc -b --pretty false`; exit 0. |
| Frontend production build | **PASS** | `node node_modules/vite/bin/vite.js build`; exit 0. |
| Docker Compose config and smoke | **NOT_RUN** | Docker CLI not found. No local Compose, HTTP, PostgreSQL `SELECT 1`, runtime-role, five-service health, or cleanup result is claimed for this worktree. |
| `uv` locked install/run | **NOT_RUN** | `uv` CLI not found; tests used repository-provided virtual environments. |
| Browser + real HTTP + PostgreSQL acceptance | **NOT_RUN** | No local browser E2E or disposable database was run. |
| `git diff --check` | **PASS** | Exit 0; Git only warns that an existing test file with LF will convert to CRLF on a future checkout write. |
| Secret scan | **PASS** | Changed-file scan found no private-key block, GitHub token, or AWS access-key pattern. `.env.example` contains blank signing keys and local-only sample DB credentials. |
| GitHub Actions on pushed `a3f9d26` | **FAIL — 1 Python assertion; Frontend and Compose PASS** | Run [#42266303614](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42266303614): 1,152 passed / 1 failed in Python. The network HTTP E2E test passed using real Auth, Listing, Jobs, native `gpm_api_app`, and disposable PostgreSQL; the only failure was the test's fixed seed expectation for a DB-generated Job ID. Frontend and Compose jobs passed. Corrected in local commit `deb352c`; rerun is pending push. |
| Earlier CI on `46e9763` | **PASS, older HEAD only** | Run [#42252304145](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42252304145) passed Python, Frontend, and Compose before this integration diff; it is not evidence for new changes. |

## Changed implementation scope

- Auth/CORS, Listings runtime composition, Jobs read/submit/cancel runtime wiring, PostgreSQL adapters, regression tests, Jobs UI integration, `.env.example`, Compose smoke/configuration, CI, README, and this progress record.
- No Requirements, API Contract, Database Design, migration, grant, ADR, Manager scheduler, Simulator execution, or Phase 2 implementation changes.

## Next actions

1. Commit this progress update, then push the local assertion fix and progress commits only to `feat/gpu-int-01-runtime-integration`; keep PR #39 Draft.
2. Wait for and inspect all GitHub Actions on the new SHA, including the safety-marked disposable PostgreSQL adapter tests and Compose smoke.
3. Ask TV2/TV3/TV4 and the Phase 2 owner to renew the applicable compatibility ACKs on the new SHA.
4. Obtain the required independent human review and address review findings; ACKs do not count as PR approval.
5. Execute a successful browser → HTTP → PostgreSQL flow before declaring Stage E verified. No merge until all required evidence and review gates are complete.
