# VT-089 RED run 02

- Baseline implementation: branch commit `74b5c084248cbf9cc1689f9e7cf353800da97cd1`; no application patch was present.
- Command: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -k vt089 -q`
- Exit code: `1` (expected RED before implementation).
- Result: 9 failed, 2 passed, 91 deselected.
- Failure evidence: the route returned the nonmatching Listing Job; six malformed/duplicate query variants returned 200 instead of 400; the filtered cursor context and reader keyword are not implemented yet.
- Passing controls: the fixed baseline-signed cursor decoded and re-encoded byte-for-byte, and the unfiltered SQL/parameters matched the asserted baseline contract.
- Full output: [`pytest-red-02.log`](pytest-red-02.log).
- This is a feature-missing RED, not an environment, import, fixture, or database failure. No PostgreSQL test ran in this selected unit suite.
