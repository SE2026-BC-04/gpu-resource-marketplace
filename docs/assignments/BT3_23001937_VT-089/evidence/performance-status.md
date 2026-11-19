# VT-089 120-VU performance status

- Acceptance target: 120 concurrent tasks, p95 <= 3.5 seconds.
- Harness: `tools/vt089_load.py`; invocation help ran successfully with the pinned backend environment. Captured options: `evidence/load-harness-help.log`.
- Runtime/API/PostgreSQL execution: **NOT_RUN**. No disposable PostgreSQL cluster or representative Job/Listing/account dataset was available. Docker returned `permission denied` for `/var/run/docker.sock`.
- Dataset counts, token-account count, warm-up duration, measurement duration, sample count, observed concurrency, p50/p95/p99, throughput, errors/timeouts, pool/runtime/hardware: **NOT MEASURED**.
- No acceptance result is inferred from the script, its help output, unit tests, CI baseline, or a mock service. No index/migration is proposed by this run.

The benchmark remains a delivery blocker. Run only against the approved disposable environment and record all harness output before evaluating the threshold.
