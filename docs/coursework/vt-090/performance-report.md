# VT-090 Performance Experiment Report

## Experiment classification

**Result label: `SIMULATED_ONLY`.** The harness used an in-process local HTTP mock, not FastAPI, PostgreSQL, a production deployment, or GPU execution. Its latency cannot be used to claim the NFR/API target of p95 ≤ 2.0 seconds is met.

## Configuration and execution

- Command: `node docs/coursework/vt-090/performance/run-status-load.mjs`
- Harness commit: `ec9f4dcccbdd7665a2e5c90b6eefaad6b12d9c66`
- Mode: `mock`; `MOCK_NO_DATABASE`; one synthetic `QUEUED` DTO.
- Load: 60 concurrent client tasks, one authenticated-shape `GET /api/v1/jobs/<JOB_ID>` each.
- Mock behavior: 50 ms fixed response delay; mock checks a dummy in-process bearer value. No real user token is used or written.
- Primary metric: client-observed GET latency from request start through response body. This is different from poll interval, Job duration and Job completion time.
- Percentile: nearest-rank p95, `sorted[ceil(0.95*n)-1]`, over successful HTTP responses.
- Runtime: Node.js v22.13.0; Windows `win32/x64`; 12 logical CPUs, Intel Core i7-8850H; 16,943,120,384 bytes total RAM and 2,576,658,432 bytes free before run.
- The recorded source commit is the runner's `HEAD`; `working_tree_dirty=true` because coursework evidence files were present. The polling production code was committed in the branch before this harness run; the benchmark was not an application integration measurement.

## Observed result

| Measure | Actual result |
|---|---:|
| Users/tasks started | 60 |
| Mock requests received | 60 |
| Maximum concurrent mock requests observed | 60 |
| Successful HTTP responses | 60 |
| HTTP errors | 0 |
| Transport errors | 0 |
| Client-observed p95 | 151.155 ms |
| Overall batch elapsed | 168.743 ms |
| Process exit code | 0 |

Raw per-request outcomes and latency samples are in `performance/results-local.json`; captured runner stdout is in `evidence/performance-run.log`.

## Interpretation and limitations

The script demonstrated that this local runner can initiate 60 concurrent status-shaped requests and calculate p95 reproducibly. The synthetic p95 includes loopback HTTP, event-loop and client overhead plus the fixed mock delay. It does **not** measure the application, database, real auth, job ownership query, pool saturation or production path. Therefore the product performance target remains **NOT_RUN**, not PASS or FAIL. A real local API run is documented in `performance/README.md`; it must use a retained disposable test Job and an operator-verified safe environment. The full ADR-007 `PERF-736-V1` campaign remains out of scope.
