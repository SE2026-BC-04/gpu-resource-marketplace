# VT-089 repeatability and flaky-risk review

**Implementation under review:** `e90627a1913550a5ea9ea224eff70b04ab99455c`
**Command:** `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -q`

| Run | Actual result | Log |
|---|---|---|
| Initial final focused run | 109 passed, 5 skipped | `pytest-green-focused.log` |
| Repeat 1 | 109 passed, 5 skipped | `pytest-flaky-repeat-1.log` |
| Repeat 2 | 109 passed, 5 skipped | `pytest-flaky-repeat-2.log` |

The five skipped cases in every run require the opt-in disposable PostgreSQL environment. Repetition therefore covers the available unit/recording-session tests, not database concurrency behavior.

## Risks checked

1. **Timestamp and timezone dependence:** the baseline cursor fixture uses a fixed UTC timestamp and fixed UUIDs; SQL-order recording tests use stable fixtures. The pagination order explicitly includes `id` as the tie-breaker. No wall-clock sleep is used as an assertion in the focused suite.
2. **Mutable shared state and test order:** HTTP fakes and recording sessions are created per test; no test depends on execution order in the observed focused runs. The suite was repeated without random-order tooling, so order independence is not exhaustively established.
3. **Async frontend stale results:** frontend tests exercise deferred responses and request-key/filter changes; the full frontend suite passed once at 160 tests. It was not repeated, so timing stability is not established by a repetition sample.
4. **PostgreSQL locks, role session state and concurrent pages:** these are the largest untested flake risks because all five disposable PostgreSQL tests were skipped and the runtime E2E was skipped. No claim is made for lock timing, real role isolation, page stability under concurrent writes, or production pool behavior.

**Conclusion:** no failure appeared in three focused local runs. This is bounded repeatability evidence, not a general “flaky-free” claim. PostgreSQL, runtime E2E and frontend repeat runs remain outstanding.
