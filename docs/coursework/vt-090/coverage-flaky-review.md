# VT-090 Coverage and Flaky-Test Review

## Coverage status

**Line/branch coverage: NOT_RUN.** The existing `frontend/node_modules/@vitest/coverage-v8` provider is absent. The installed npm shim cannot run (`npm --version` errors because its `npm-cli.js` target is missing), and network installation was not available. No coverage percentage is claimed. The final source/test/typecheck/build results are recorded in `evidence/`; coverage instrumentation remains an explicit evidence gap.

### Risk-to-test coverage review

| Risk/criterion | Tests/evidence | Status |
|---|---|---|
| AC-01 accepted async Job ID/status | Existing submit flow plus revised real-submit/poll-recovery test | Covered by tests |
| AC-02 queued/running refresh and terminal stop | `VT-090` component tests for pending transition, all terminal GET states, and explicit Cancel returning `CANCELLED` | Covered by tests |
| AC-03 transient GET recovery without duplicate POST | Network/503, real 5-second timeout, three-failure boundary, four-failure stop, same attempt/idempotency regressions | Covered by tests |
| AC-04 overlap, stale Job, identity switch, unmount | Deferred promises, fake clock and AbortSignal assertion cases | Covered by tests |
| AC-05 60 concurrent status requests | Mock HTTP harness and raw output | Simulated only; no production/API claim |
| Branch/line coverage percentage | Provider absent | NOT_RUN |
| Live Manager-driven state transition | Manager is idle foundation on baseline | NOT_RUN / outside scope |

## Flaky risks reviewed

**F1 — timers/retry delays.** Poll intervals, request timeout and retry backoff are driven by Vitest fake timers. Tests advance to 1999/2000 ms, 4999/5000 ms, and the 1/2/4-second backoff boundaries. They do not sleep on wall-clock time.

**F2 — ordering/concurrency.** Poll overlap, Job switch and identity change use deferred promises and an abort-aware stalled request. Tests assert exact request counts and that an obsolete response cannot replace current detail.

The seven high-risk tests (overlap, Job switch, identity change, timeout, retry threshold, terminal Cancel cleanup, and mismatched response ID) were executed in five separate Vitest runs. Each run passed 7/7 selected tests (35 test executions total), with exit code 0. Raw output is in `evidence/flaky-repeats.log`. This is a bounded repeat check, not proof that flakiness is impossible.

## Remaining untested risks

- No test can demonstrate a real Manager transition on this baseline because Manager does not execute Jobs.
- No real API+PostgreSQL load test was run; the mock harness has no DB.
- Coverage tooling was unavailable, so unvisited source branches are not quantified.
- The frontend unit tests do not validate a live browser/network integration against FastAPI; that remains a later end-to-end check.
