# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-07 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** @thangSy221105

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Git and PR state

| Item | State |
|---|---|
| Local branch | `feat/gpu-int-01-runtime-integration` (existing shared integration branch; no additional branch created) |
| Integration commits | `b457c0f` — backend/runtime wiring and tests; `ccdfce6` — Jobs frontend/shared-session integration; `a3f9d26` — initial progress snapshot; `deb352c` — fix random-Job-ID reference assertion; `ce6b821` — CI evidence snapshot |
| Local HEAD before this progress update | `ce6b821` |
| PR #39 remote head before this update | `ce6b8218031adf1962a50747618027a9cea76514` |
| Local base before this work | `46e976356b83c2384f359f35b08262dfd2970f0b` |
| Main baseline | `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` |
| PR #39 before the integration extension | Open, Draft, base `main`, head `46e976356b83c2384f359f35b08262dfd2970f0b`; rechecked through GitHub on 2026-11-07 |
| PR #39 current state before this progress update | Open, Draft, base `main`, head `ce6b8218031adf1962a50747618027a9cea76514`; GitHub Actions run #42267396758 has all 3 jobs successful |
| Working tree | Backend/frontend changes, test fix, and the prior progress snapshot are pushed. This post-CI progress update is not yet committed/pushed. |
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
| E — full Phase 1 acceptance | **BLOCKED** | HTTP E2E and CI pass. Browser E2E has not run; the current CI workflow has no browser automation. No full Phase 1 E2E PASS is claimed. |

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
| GitHub Actions on pushed `ce6b821` | **PASS — all 3 jobs** | Run [#42267396758](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42267396758): Python **PASS** (backend 1,153 passed; Simulator 2 passed), Frontend **PASS** (Vitest/typecheck/build), Compose **PASS** (config/smoke). PostgreSQL submit/cancel adapter tests and the real HTTP + disposable PostgreSQL E2E test passed. |
| Earlier GitHub Actions on `a3f9d26` | **FAIL — corrected and rerun** | Run [#42266303614](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42266303614): 1,152 passed / 1 failed in Python; Frontend and Compose passed. The failed adapter assertion assumed a fixed seed for a DB-generated random Job ID; corrected in `deb352c`. Run #42267396758 on `ce6b821` then passed all jobs. |
| Earlier CI on `46e9763` | **PASS, older HEAD only** | Run [#42252304145](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42252304145) passed Python, Frontend, and Compose before this integration diff; it is not evidence for new changes. |

## Changed implementation scope

- Auth/CORS, Listings runtime composition, Jobs read/submit/cancel runtime wiring, PostgreSQL adapters, regression tests, Jobs UI integration, `.env.example`, Compose smoke/configuration, CI, README, and this progress record.
- No Requirements, API Contract, Database Design, migration, grant, ADR, Manager scheduler, Simulator execution, or Phase 2 implementation changes.

## Next actions

1. Obtain the owner's decision on adding a test-only Playwright/browser toolchain; the repository CI currently has no browser automation package or runner.
2. Keep PR #39 Draft. Request renewed TV2/TV3/TV4 compatibility ACKs and an independent human review on the final pushed HEAD.
3. Run browser → HTTP → PostgreSQL acceptance after the browser-toolchain decision. No merge until all required evidence and review gates are complete.
