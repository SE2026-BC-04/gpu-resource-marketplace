# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-07 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** @thangSy221105

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Git and PR state

| Item | State |
|---|---|
| Local branch | `feat/gpu-int-01-runtime-integration` (existing shared integration branch; no additional branch created) |
| Key integration commits | `b457c0f` — backend/runtime wiring and tests; `ccdfce6` — Jobs frontend/shared-session integration; `a3f9d26` — initial progress snapshot; `deb352c` — fix random-Job-ID reference assertion; `ce6b821` — implementation CI evidence snapshot |
| Implementation HEAD whose CI evidence is summarized here | `ce6b8218031adf1962a50747618027a9cea76514` |
| PR #39 head when implementation CI evidence was collected | `ce6b8218031adf1962a50747618027a9cea76514` |
| Local base before this work | `46e976356b83c2384f359f35b08262dfd2970f0b` |
| Main baseline | `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` |
| PR #39 before the integration extension | Open, Draft, base `main`, head `46e976356b83c2384f359f35b08262dfd2970f0b`; rechecked through GitHub on 2026-11-07 |
| Latest pushed HEAD before Playwright addition | `dd49f5c7f3acda8731d05e43ce546838fed449d0`; run #42269027796 passed Python, Frontend, and Compose jobs |
| PR #39 state verified before Playwright addition | Open, Draft, base `main`, head `dd49f5c7f3acda8731d05e43ce546838fed449d0`; not merged |
| Worktree before Playwright addition | Clean at `dd49f5c7f3acda8731d05e43ce546838fed449d0`; Playwright changes are being added to this same branch |
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
| E — full Phase 1 acceptance | **IN_PROGRESS** | Added a Chromium Playwright test for production frontend → Auth/Listings/Jobs API → disposable PostgreSQL, with persisted Job/reference assertions. Local execution is skipped by the disposable-DB safety guard; CI verification is pending. No full Phase 1 E2E PASS is claimed yet. |

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
| Earlier GitHub Actions on `a3f9d26` | **FAIL — corrected and rerun** | Run [#42266303614](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42266303614): 1,152 passed / 1 failed in Python; Frontend and Compose passed. The failed adapter assertion assumed a fixed seed for a DB-generated random Job ID; corrected in `deb352c`. Run #42267396758 on `ce6b821` then passed all jobs. |
| Earlier CI on `46e9763` | **PASS, older HEAD only** | Run [#42252304145](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42252304145) passed Python, Frontend, and Compose before this integration diff; it is not evidence for new changes. |

## Changed implementation scope

- Auth/CORS, Listings runtime composition, Jobs read/submit/cancel runtime wiring, PostgreSQL adapters, regression tests, Jobs UI integration, `.env.example`, Compose smoke/configuration, CI, README, Playwright test-only dependency/config/spec, and this progress record.
- No Requirements, API Contract, Database Design, migration, grant, ADR, Manager scheduler, Simulator execution, or Phase 2 implementation changes.

## Next actions

1. Push the Playwright test-only dependency, production frontend browser E2E, and CI browser setup to the existing integration branch; inspect the actual browser + HTTP + PostgreSQL result on that HEAD.
2. Keep PR #39 Draft. Request renewed TV2/TV3/TV4 compatibility ACKs and an independent human review on the final pushed HEAD.
3. No full Stage E PASS or merge until the browser test passes and all required compatibility/review gates are complete.
