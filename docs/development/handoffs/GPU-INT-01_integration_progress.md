# GPU-INT-01 — Phase 1 Runtime Integration Progress

**Updated:** 2026-11-04 · **Repository:** `SE2026-BC-04/gpu-resource-marketplace` · **Branch:** `feat/gpu-int-01-runtime-integration` · **Owner:** `@thangSy221105`

This file records integration progress and evidence. It does not replace approved contracts, architecture, database, module, or test-design documents.

## Current Git and PR state

| Item | State |
|---|---|
| Latest fetched `origin/main` | `7fd7deaabbaaa5f2583656f201cb68dcd9944fd3` |
| Integration branch local HEAD | `5f4da1d7d12682ab2a6b1993deccb9a6bc807245` — normal merge of `origin/main`, no conflicts |
| Remote PR #39 head | `03c9b9adc03d357728cec43a2a90cd13a66fb0a2`; remediation changes are not committed or pushed |
| Working tree | Contains uncommitted Stage A remediation changes; no unrelated local changes were present before editing |
| PR #39 | Open and Draft. Base is `main`; GitHub has not yet received the merge commit or remediation changes |
| Git operation gate | Commit and push require separate owner authorization. No merge to `main` is authorized |

The integration branch was behind `main` after PR #31 merged. The change set from the merge base `ef9ddcb` was inspected; it added the accepted D3/D7 database work and handoff files without overlapping the Stage A edits. `origin/main` was merged normally as local commit `5f4da1d`.

## Upstream PR snapshot (2026-11-04)

| PR | Current state | Integration relevance |
|---|---|---|
| #15 | MERGED | Jobs API foundation; no PostgreSQL JobReader adapter on `main` |
| #17 | OPEN / Draft, head `c09b886` | Listings API/UI is not on `main`; Stage C remains blocked |
| #28 | MERGED | D2 Jobs lifecycle guard |
| #29 | MERGED | D3 guarded Job deletion |
| #30 | MERGED | D1/D2/D3/D8 decision-status documentation |
| #31 | MERGED at `7fd7dea` | Listing PostgreSQL persistence and D7 are now on `main` |
| #32 | OPEN / Draft | Jobs frontend foundation |
| #33 | OPEN / Draft | Queued cancellation command foundation |
| #34 | OPEN / Draft | PostgreSQL cancellation test preparation; not a production adapter |
| #35 | MERGED | Auth PostgreSQL HTTP tests |
| #38 | MERGED | D2 pseudocode documentation sync |

Only merged upstream work is used by this branch. No unmerged member branch has been consumed.

## Stage status

| Stage | Status | Evidence / blocker |
|---|---|---|
| A — Auth runtime integration | **IMPLEMENTED / VERIFICATION_PENDING** | Auth composition is in the remote PR head. Remediation adds validation redaction, schema readiness, 500 CORS handling, and disposable Compose checks. None of the new checks has run locally yet. |
| B — Jobs read | **BLOCKED** | PostgreSQL JobReader adapter is not on `main`. |
| C — Listings | **BLOCKED** | PR #31 merged, but PR #17 remains open; do not consume its branch. |
| D — Jobs commands/frontend | **BLOCKED** | Required command adapters and acceptance gates are incomplete; #32–#34 remain open. |
| E — Full Phase 1 acceptance | **BLOCKED** | Requires verified completion of A–D using real HTTP, PostgreSQL, frontend, and CI evidence. |

## Stage A remediation findings

| Finding | Current handling | Evidence boundary |
|---|---|---|
| P1 — Pydantic validation leaked rejected JWT input | Added `hide_input_in_errors=True`, removed the chained SQLAlchemy parser cause, and added JWT/DSN sentinel tests. | Source and tests changed locally; required pytest has not run. |
| P1 — fresh Compose database could appear ready before Auth tables existed | API readiness now checks query access to `users` and `user_roles`. Isolated Compose smoke starts API before migrations and expects readiness and Auth to fail closed; it then provisions only its random smoke project. | Smoke code added; Docker is unavailable locally, so runtime evidence is NOT_RUN. |
| P2 — unexpected Auth 500 lost CORS headers | Auth 500 handler returns the exact configured origin and `Vary: Origin`; tests cover allowed and disallowed origins and secret redaction. | Tests added; pytest has not run. |
| P2 — runtime DB-role evidence | `.env.example` now labels its bootstrap/owner DSNs as local-only. Isolated Compose smoke creates random D1 login passwords and checks `current_user` and absence of CREATE privileges for API and Manager. | No real deployment credentials were provided. TV2 confirmation of actual `gpm_api_app` / `gpm_manager_app` provisioning remains BLOCKED; no persistent DB was touched. |
| P3 — test row cleanup after abrupt process termination | Retained the separate Engine/sessionmaker test and its `finally` cleanup. Reusing the fixture transaction would bypass the default Engine/sessionmaker path under review. | Follow-up: consider a separately disposable database per test to contain forced-termination leftovers without reducing Engine-path coverage. |

No schema, migration, D1 grant, JWT policy, or public API contract was edited. The smoke procedure runs existing role bootstrap and migrations only inside its uniquely named, disposable Compose project and removes that project's volume during cleanup.

## Auth, database, and cross-phase gates

- JWT remains HS256, 900 seconds, dedicated configured secret of at least 32 UTF-8 bytes, fail-closed. No refresh/session behavior changed.
- `create_app()` composes one `AuthService`, the PostgreSQL AccountReader, token codec, password hasher, and the shared principal dependency. Engine lifecycle remains tied to app lifespan.
- Runtime-role evidence must distinguish `SET ROLE gpm_api_rw` tests from a real login as `gpm_api_app`. The former does not prove D1 login credentials or deployment configuration.
- The default `.env.example` uses the local bootstrap/owner account only. Do not use that stack as D1/D2/D3 production evidence.
- TV2 posted `ACK_WITH_ACTIONS` on PR #39 for HEAD `03c9b9a` ([comment](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6610112854)): fix the P1 secret leak and keep owner DSNs out of runtime acceptance evidence.
- GPU-003, GPU-004, and GPU-005 consumer ACKs for the shared principal/configuration wiring are still missing. The merged #31 persistence work does not itself provide a Stage A consumer ACK.
- PR #39 currently has no independent human review submission. Codex findings do not count as human review. L1 requires one independent human reviewer after the final diff is pushed.

## Verification

### Existing remote evidence

| Check | Result | Evidence |
|---|---|---|
| GitHub Actions on old PR #39 HEAD `03c9b9a` | Python **FAIL: 623 passed, 1 failed**; frontend PASS; Compose PASS | [Run #41662546603](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41662546603). The failing test was `test_config_and_imports.py::test_jwt_secret_must_contain_at_least_256_bits`; Pydantic printed the rejected input value. |
| Independent Codex PR review on `03c9b9a` | Two findings: P1 missing schema readiness/provisioning; P2 CORS headers absent on unexpected Auth 500 | PR timeline; both are addressed in the local remediation diff and await verification. |
| GitHub Actions after remediation commit `6c841d1` | Python **success** (backend, PostgreSQL, Simulator); frontend **success**; Compose **failure** | [Run #41832981735](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/41832981735). Compose smoke reached its post-migration Auth CORS assertion and failed because the script looked up an HTTP header in a case-sensitive Python `dict`; HTTP field names are case-insensitive. Smoke cleanup passed and confirmed the local CI stack resources were unchanged. A follow-up normalizes response header keys and awaits a new CI run. |

### Local remediation verification

| Check | Result | Notes |
|---|---|---|
| `git fetch origin` | PASS | Fetched current refs before merge |
| Normal merge of `origin/main` | PASS | Local merge commit `5f4da1d`; no conflicts |
| `git diff --check` | PASS (exit 0) | No whitespace errors; Git emitted only LF-to-CRLF working-copy warnings |
| Python syntax check | NOT_RUN (exit 1 before Python started) | `py -3.11 -m py_compile ...` could not launch the WindowsApps Python executable (`Access is denied`); Python 3.12 and `uv` are unavailable |
| Security regression tests (`test_config_and_imports.py`) | NOT_RUN (exit 1 before pytest started) | Attempted locked `uv run`; PowerShell reports `uv` is not recognized |
| Auth mount/health/CORS tests | NOT_RUN (exit 1 before pytest started) | Same missing `uv` executable; targeted command was attempted |
| PostgreSQL Auth tests | NOT_RUN | No working Python/uv runtime and no safety-marked disposable PostgreSQL test cluster configured; no persistent database was touched |
| Full backend pytest | NOT_RUN (exit 1 before pytest started) | Required `uv run --project backend --locked --group dev pytest backend/tests tests -rs`; `uv` is not installed |
| Simulator pytest | NOT_RUN (exit 1 before pytest started) | Required locked `uv` runner is unavailable |
| Frontend Vitest | PASS (69 passed, 0 failed; exit 0) | Ran `node_modules/.bin/vitest.cmd run` with Node 22.13.0; repository's container pins Node 24, so this is not locked-runtime evidence |
| Frontend typecheck | PASS (exit 0) | Ran `node_modules/.bin/tsc.cmd -b --pretty false` with Node 22.13.0; not locked-runtime evidence |
| Frontend production build | PASS (exit 0) | Ran `node_modules/.bin/vite.cmd build` with Node 22.13.0; not locked-runtime evidence |
| Compose config and smoke | NOT_RUN (exit 1 before Compose started) | `docker` is not recognized; no Docker daemon was available |
| GitHub Actions on `6c841d1` | PARTIAL / Compose FAIL | Python and Frontend jobs passed; Compose failed at the smoke CORS-header lookup, which is fixed locally and needs a new run |

The CI Python job passed, including backend/PostgreSQL and Simulator tests; CI Frontend passed. CI Compose is not fully verified until the follow-up header-normalization change passes. Local frontend checks also passed on Node 22.13.0, but the exact locked Node 24 run is the CI result.

## Remaining blockers and next actions

1. Push the case-insensitive CORS header lookup follow-up and confirm a green Compose smoke run on the new HEAD.
2. Keep security, Auth mount/health/CORS, PostgreSQL Auth, and full backend CI evidence attached to the final pushed HEAD.
3. Ask TV2 to confirm the real D1 runtime login/provisioning procedure; keep it isolated from persistent database provisioning.
4. Obtain GPU-003/004/005 ACKs for the final shared wiring and one independent human L1 review on the pushed final diff.
5. Keep PR #39 Draft while Stages B–E are incomplete; do not merge.
