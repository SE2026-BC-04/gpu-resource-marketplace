# VT-090 Coverage and Flaky-Test Review

## Coverage status

**Line/branch coverage: NOT_RUN.** Neither `@vitest/coverage-v8` nor `@vitest/coverage-istanbul` exists in the installed workspace. Running Vitest with `--coverage` exited 1 before tests because `@vitest/coverage-v8` is missing; no dependency was installed. The exact availability check and command output are recorded in `evidence/review-p3-coverage.log`. No coverage percentage is claimed; coverage instrumentation remains an explicit evidence gap.

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
| Branch/line coverage percentage | Provider absent | NOT_RUN |
| Live Manager-driven state transition | Manager is idle foundation on baseline | NOT_RUN / outside scope |

## Flaky risks reviewed

**F1 — timers/retry delays.** Poll intervals, request timeout and retry backoff are driven by Vitest fake timers. Tests advance to 1999/2000 ms, 4999/5000 ms, and the 1/2/4-second backoff boundaries. They do not sleep on wall-clock time.

**F2 — ordering/concurrency.** Poll overlap, Job switch and identity change use deferred promises and an abort-aware stalled request. Tests assert exact request counts and that an obsolete response cannot replace current detail.

The seven high-risk tests (overlap, Job switch, identity change, timeout, retry threshold, terminal Cancel cleanup, and mismatched response ID) were executed in five separate Vitest runs. Each run passed 7/7 selected tests (35 test executions total), with exit code 0. Raw output is in `evidence/flaky-repeats.log`. The Cancel-409 reconciliation regressions additionally passed 2/2 focused tests and are recorded in `evidence/review-p1-green.log`. The final frontend suite passed 215 tests; see `evidence/review-final-frontend.log`. This is a bounded repeat check, not proof that flakiness is impossible.

## Remaining untested risks

- No test can demonstrate a real Manager transition on this baseline because Manager does not execute Jobs.
- No real API+PostgreSQL load test was run; the mock harness has no DB.
- Coverage tooling was unavailable, so unvisited source branches are not quantified.
- The frontend unit tests do not validate a live browser/network integration against FastAPI; that remains a later end-to-end check.
