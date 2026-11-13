# Focused test repetition record

Feature implementation SHA: `e90627a1913550a5ea9ea224eff70b04ab99455c`.

Command repeated on the same local checkout:

```bash
uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -q
```

Two additional consecutive runs exited 0, each reporting `109 passed, 5 skipped` (0.75s and 0.76s). Full outputs: [`pytest-flaky-repeat-1.log`](pytest-flaky-repeat-1.log) and [`pytest-flaky-repeat-2.log`](pytest-flaky-repeat-2.log). All five skips are disposable PostgreSQL cases, not successful DB executions. See [`flaky-review.md`](flaky-review.md) for risk analysis.
