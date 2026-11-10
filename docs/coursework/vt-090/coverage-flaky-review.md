# VT-090 Coverage and Flaky-Test Review

## Coverage status

**Historical status:** the earlier PR evidence at HEAD `6daeea368e6add6aefefe8540e637f938698cba4` reported coverage `NOT_RUN` because no provider was installed. That record remains in `evidence/review-p3-coverage.log` and is not rewritten.

**E1 measured status:** installed `@vitest/coverage-v8@5.0.5`, matching the locked Vitest `5.0.5`, and ran the four focused Jobs test files (103 tests passed). Node was `v22.13.0` on Windows; the repository expects Node 24, so treat this as local engineering evidence on the available runtime. Exact command and stdout are in `evidence/coverage-review-20261111/coverage-run.log`; machine-readable files are `coverage-summary.json` and `coverage-final.json`. No threshold was set and no test was added or changed to raise the percentage.

| Included source module | Lines | Branches | Context |
|---|---:|---:|---|
| `src/ui/jobs/JobsPage.tsx` | 93.38% (240/257) | 86.57% (187/216) | Main VT-090 UI target |
| `src/api/jobs.ts` | 90.58% (77/85) | 80.45% (107/133) | Jobs API implementation |
| `src/api/authorizedFetch.ts` | 100.00% (12/12) | 75.00% (9/12) | Shared authenticated transport used by Jobs API |
| `src/api/auth.ts` | 24.32% (9/37) | 1.96% (1/51) | Transitive `AuthApiError`/abort helper module; most Auth endpoint code is outside this Jobs-focused run |
| **Jobs-focused three-module aggregate** | **92.94% (329/354)** | **83.93% (303/361)** | JobsPage + Jobs API + authorized fetch; excludes shared Auth endpoint module |
| Four-file run aggregate | 86.44% (338/391) | 73.78% (304/412) | Includes the shared Auth module above; not a whole-frontend measure |

### Uncovered branch analysis

- `JobsPage.tsx`: remaining arcs cluster around duplicate/in-flight Cancel and Submit guards, non-transient Cancel/reconciliation errors, fallback error/request-ID display, pagination edges, role-specific submit blocking, invalid-cursor recovery, and lifecycle/stale-request guards. These are meaningful risks for duplicate-action prevention and error recovery; the focused suite covers the core pending/terminal/reconciliation paths, but it does not prove every defensive UI branch. Do not add tests solely to improve the ratio.
- `jobs.ts`: remaining arcs are concentrated in malformed DTO/error payload alternatives, optional/invalid request-ID handling, fallback HTTP error-code selection, and invalid query/job-ID/idempotency input rejection. The risk is incorrect handling of malformed server data or unvalidated caller input; the current API tests cover representative contract paths, not every malformed combination.
- `authorizedFetch.ts`: unvisited arcs include invalid relative paths, AbortError/lifecycle-abort handling and 401 session invalidation. These affect protected-request cancellation and expired-session behavior and warrant dedicated tests if this shared transport is changed.
- `auth.ts`: this low score is incidental to importing `AuthApiError`/`isAbortError`; login, `/me`, logout and their DTO branches were not the purpose of this Jobs-only run. It must not be interpreted as Auth module acceptance coverage.

For auditability, the measured V8 report has at least one zero-hit branch arm at these source lines (source HEAD `6daeea3`): `JobsPage.tsx` 39, 52, 128, 145, 152, 157, 167, 236, 259, 368, 393, 402, 414, 426, 474, 480, 524, 576; `jobs.ts` 89, 151, 158, 160, 162, 169, 172, 181, 192, 193, 216, 220, 226, 235, 240, 249, 256; `authorizedFetch.ts` 14, 26, 29. These line numbers identify branch locations with an unvisited arm in the generated JSON; they do not mean the whole source line was never executed. The JSON is the detailed authority.

Coverage is a measurement of executed source arcs, not a completeness score. The exact uncovered arcs are inspectable in `coverage-final.json`; the text reporter provides the current summary.

### Risk-to-test coverage review

| Risk/criterion | Tests/evidence | Status |
|---|---|---|
| AC-01 accepted async Job ID/status | Existing submit flow plus revised real-submit/poll-recovery test | Covered by tests |
| AC-02 queued/running refresh and terminal stop | `VT-090` component tests for pending transition, all terminal GET states, and explicit Cancel returning `CANCELLED` | Covered by tests |
| AC-03 transient GET recovery without duplicate POST | Network/503, real 5-second timeout, three-failure boundary, four-failure stop, same attempt/idempotency regressions | Covered by tests |
| AC-04 overlap, stale Job, identity switch, unmount | Deferred promises, fake clock and AbortSignal assertion cases | Covered by tests |
| Cancel 409 reconciliation stops the old timer/request and resumes a fresh poll | `VT090-P1-01` and `VT090-P1-02`, first run RED then GREEN | Covered by regression tests; 2/2 PASS |
| Persisted lifecycle fixture correctness | Explicit CANCELLED fixture assertion; generated pairwise excludes invalid persisted transitions | Covered by frontend fixture tests; PostgreSQL guard test NOT_RUN without a verified disposable cluster |
| Pairwise scenarios correspond to test cases | Generator calculates feasible/covered pair sets and one test executes each selected row | 36/36 generated rows executed; excluded configurations have reasons; PostgreSQL transition guard remains NOT_RUN |
| AC-05 60 concurrent status requests | Mock HTTP harness and raw output | Simulated only; no production/API claim |
| Jobs-focused line/branch coverage | Vitest V8 provider 5.0.5; 4 focused test files, 103 passed | Measured; per-file results and uncovered-branch risks above |
| Live Manager-driven state transition | Manager is idle foundation on baseline | NOT_RUN / outside scope |

## Flaky risks reviewed

**F1 — timers/retry delays.** Poll intervals, request timeout and retry backoff are driven by Vitest fake timers. Tests advance to 1999/2000 ms, 4999/5000 ms, and the 1/2/4-second backoff boundaries. They do not sleep on wall-clock time.

**F2 — ordering/concurrency.** Poll overlap, Job switch and identity change use deferred promises and an abort-aware stalled request. Tests assert exact request counts and that an obsolete response cannot replace current detail.

The seven high-risk tests (overlap, Job switch, identity change, timeout, retry threshold, terminal Cancel cleanup, and mismatched response ID) were executed in five separate Vitest runs. Each run passed 7/7 selected tests (35 test executions total), with exit code 0. Raw output is in `evidence/flaky-repeats.log`. The Cancel-409 reconciliation regressions additionally passed 2/2 focused tests and are recorded in `evidence/review-p1-green.log`. The final frontend suite passed 215 tests; see `evidence/review-final-frontend.log`. This is a bounded repeat check, not proof that flakiness is impossible.

## Remaining untested risks

- No test can demonstrate a real Manager transition on this baseline because Manager does not execute Jobs.
- No real API+PostgreSQL load test was run; the mock harness has no DB.
- Coverage is limited to JobsPage/API Jobs and their shared transport dependencies; full frontend coverage and real database-backed lifecycle behavior remain unmeasured.
- The frontend unit tests do not validate a live browser/network integration against FastAPI; that remains a later end-to-end check.
