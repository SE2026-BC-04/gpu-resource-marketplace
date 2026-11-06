# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-06 · **Repository:** SE2026-BC-04/gpu-resource-marketplace · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** @thangSy221105

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Current Git and PR state

| Item | State |
|---|---|
| Local branch / HEAD | `feat/gpu-int-01-runtime-integration` / `bdc7c63670f70db19d9bc5c6bed0df39b945109f` (Compose smoke fix is now being prepared on this same branch) |
| Current main baseline | `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` (main branch tip confirmed locally and through GitHub commit search) |
| Local integration merge | `267168d` merges current `main` into the existing integration branch; no new branch was created. |
| PR #39 | Open, Draft; pushed head `bdc7c63670f70db19d9bc5c6bed0df39b945109f`. GitHub open-PR search found #39 as the only open PR in this repository. |
| GitHub fetch | Initial sandboxed fetch could not connect to `github.com:443`; authorized network fetch then succeeded. Current `main` and PR branch tracking refs were fetched before staging. |
| Local edits | Auth/CORS and Listings integration are pushed as `bdc7c63`. A Compose smoke environment-isolation fix and its regression test are local and uncommitted. |
| Git gate | Owner authorized push to this branch. Do not push `main`, update PR metadata, approve, or merge PR #39. |

## Upstream PRs on current main

| PR | Main history | Integration relevance |
|---|---|---|
| #15 | Merged | Jobs API foundation; no PostgreSQL `JobReader` adapter is present. |
| #17 | Merged | Listings API/UI source is available for integration. |
| #31 | Merged | PostgreSQL Listings UoW and D7 are available. |
| #32 | Merged | Jobs frontend foundation; still cannot wire production Jobs without backend dependencies. |
| #33 / #34 | Merged | TX-CANCEL ports and PostgreSQL test preparation. |
| #35 | Merged | Auth PostgreSQL HTTP tests. |
| #40 | Merged | PostgreSQL TX-CANCEL adapter is available. |
| #41 | Merged | Listing repository timestamp test fix. |

Only work present on `main` is consumed. No unmerged member branch has been merged or cherry-picked.

## Dependency and stage status

| Stage | Status | Evidence / blocker |
|---|---|---|
| A — Auth runtime integration | **IMPLEMENTED** | `create_app()` composes one AuthService, PostgreSQL AccountReader, JWT codec, password hasher, shared principal dependency, and lifespan engine cleanup. CORS regression fixes are local and tested. Real disposable-PostgreSQL runtime evidence and new-head CI are still required before VERIFIED. |
| B — Jobs read | **BLOCKED** | Jobs read service/router exist, but current `backend/src/gpu_marketplace/repositories/jobs.py` contains the TX-CANCEL adapters only; no PostgreSQL JobReader adapter is on `main`. No fake production reader is mounted. |
| C — Listings | **IMPLEMENTED** | Main FastAPI app mounts Listings using `PostgresListingUnitOfWork`, `ListingCursorCodec`, and the same Auth principal dependency. Frontend mounts `SessionListingsPage` using the existing SessionStore. Disposable-PostgreSQL and Compose runtime acceptance is NOT_RUN because Docker CLI is unavailable on this workstation. |
| D — Jobs commands/frontend | **BLOCKED** | TX-CANCEL PostgreSQL adapter and Jobs UI are merged, but TX-SUBMIT PostgreSQL implementation / approved deterministic reference vectors and Jobs read adapter are still missing. Do not mount fake adapters or claim Submit/View/Cancel E2E. |
| E — Full Phase 1 acceptance | **BLOCKED** | Requires verified A–D using real HTTP, PostgreSQL, frontend, and CI evidence. |

## Current implementation details

- `api/app.py` now builds one `ListingService` over `PostgresListingUnitOfWork` with the existing API sessionmaker and model factories, then mounts the six approved Listing routes with the same `principal_dependency` used by Auth.
- `GPU_MARKETPLACE_LISTING_CURSOR_SECRET` is a separate, stable HMAC key. Configuration rejects keys shorter than 32 UTF-8 bytes and redacts secret values. Compose, `.env.example`, README, CI, and Compose smoke configuration pass it to the API independently from the JWT secret.
- `App.tsx` mounts `SessionListingsPage` only after sign-in and passes the existing SessionStore; the Listings workspace avoids a nested `<main>` landmark.
- CORS still uses explicit allowlisted origins and the approved GET/POST/PATCH methods/headers, and exposes `X-Request-ID` to allowed browser origins. No API paths, DTOs, business rules, database schema, migrations, grants, or ADR decisions were changed.
- `test_api_listings_mount.py` verifies all six routes are mounted, each uses the exact shared principal dependency, and an unauthenticated request returns the approved Bearer/no-store 401.

## Cross-phase and remaining review gates

- TV4's earlier `ACK_WITH_ACTIONS` requested Listings runtime wiring and renewed confirmation after the reconciled change. This local implementation has not yet been pushed, so renewed ACK is pending.
- TV2's earlier Auth compatibility ACK was on the older pushed HEAD. The separate native `gpm_api_app` login/effective role evidence remains required for restricted PostgreSQL runtime acceptance.
- TV5's earlier CORS action requiring `Access-Control-Expose-Headers: X-Request-ID` is implemented locally and covered by regression tests; renewed confirmation is pending a pushed HEAD.
- Cross-phase ACKs do not count as the independent human L1 review required for PR #39. The current new diff has not received that review.
- C1 scrypt load evidence (736 benchmark users) remains NOT_RUN/open; no scrypt profile or concurrency configuration was changed.
- The existing PR remains Draft. No reviewer was self-selected, and no approval or merge was performed.

## Verification on local working tree

**Python:** 3.12.15 / pytest 9.1.1. `uv` is not on PATH, so the repository's existing locked virtual environments were invoked directly. **Node:** 22.13.0; frontend dependencies were already present. The `npm` launcher fails because it points to a missing per-user npm CLI, so Vitest/TypeScript/Vite were invoked with their installed Node entry points.

| Check | Result | Evidence |
|---|---|---|
| Targeted API/Auth/CORS/Listings backend regression | **PASS — 270 passed** | `python -m pytest` over API auth mount, CORS, health, config, Listings mount, and Listings auth/contract/HTTP integration tests; exit 0. One Starlette `httpx` deprecation warning. |
| Full backend regression | **PASS — 777 passed, 346 skipped, 0 failed** | `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -rs`; exit 0. PostgreSQL tests skipped because the required safety-marked disposable cluster variables were not configured. |
| Simulator pytest | **PASS — 2 passed** | `simulator/.venv/Scripts/python.exe -m pytest simulator/tests`; exit 0. |
| Frontend Vitest | **PASS — 158 passed, 10 files** | `node node_modules/vitest/vitest.mjs run --reporter=dot`; exit 0. |
| Frontend TypeScript typecheck | **PASS** | `node node_modules/typescript/bin/tsc -b --pretty false`; exit 0. |
| Frontend production build | **PASS** | `node node_modules/vite/bin/vite.js build`; exit 0; Vite 8.3.4. |
| Docker Compose config validation | **NOT_RUN** | Docker CLI is not found on PATH; checks for the standard Docker Desktop executable locations also found none. Attempted `docker compose --env-file .env.example config --quiet`; PowerShell reported `docker` not recognized (exit 1). |
| Compose smoke / PostgreSQL HTTP and role checks | **NOT_RUN** | Docker CLI is unavailable. No claim is made for real PostgreSQL Listing or Compose runtime behavior. |
| `git diff --check` | **PASS** | Exit 0 after the implementation and progress update. |
| GitHub Actions on pushed `bdc7c63` | **PARTIAL / compose failed** | Run [#42249960600](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42249960600): `python` and `frontend` passed; `compose` failed at the new separate-cursor-key assertion. Docker Compose inherited CI process variables ahead of the smoke project's `--env-file`, so the smoke config saw the workflow-level key instead of its disposable key. A fix now clears process variables defined in the isolated env file; root Compose topology/environment regression: **4 passed**; full backend regression: **778 passed, 346 skipped**. The fix is not yet pushed or verified by Actions. |

## Next actions and blockers

1. Make Docker CLI/runtime available, then run Compose validation and isolated Compose smoke, including real PostgreSQL Listing paths and role boundaries.
2. Obtain disposable PostgreSQL evidence for Auth and Listings; keep persistent user databases untouched.
3. Wait for an approved PostgreSQL JobReader and TX-SUBMIT adapter/reference-vector implementation before wiring Jobs stages.
4. Push the local Compose smoke fix to PR #39 on this same branch and wait for CI; then request renewed TV2/TV4/TV5 compatibility ACKs and obtain one independent human L1 review.
5. Keep PR #39 Draft and do not merge while Stages B–E are blocked or required evidence/review gates are pending.
