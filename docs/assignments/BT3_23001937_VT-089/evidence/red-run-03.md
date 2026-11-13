# VT-089 RED run 03

- Baseline implementation: `713b618` (test-only commit); no application patch was present.
- Command: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -k vt089 -q`
- Exit code: `1` (expected RED before implementation).
- Result: 10 failed, 2 passed, 1 skipped, 91 deselected.
- The failures are the missing route/service filter, strict query validation, cursor context binding and adapter keyword/SQL behavior. The pass controls are baseline cursor compatibility and exact unfiltered SQL/parameters.
- The disposable PostgreSQL scenario was skipped because the required opt-in database URL, destructive-test opt-in, and cluster token are not configured. It did not run against a fake database.
- Full command output: [`pytest-red-03.log`](pytest-red-03.log).
