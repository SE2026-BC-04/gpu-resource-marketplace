# VT-090 Performance Experiment Report

## Experiment classification

**Result label: `SIMULATED_ONLY`.** The harness used an in-process local HTTP mock, not FastAPI, PostgreSQL, a production deployment, or GPU execution. Its latency cannot be used to claim the NFR/API target of p95 ≤ 2.0 seconds is met.

## Configuration and execution

- Command: `node docs/coursework/vt-090/performance/run-status-load.mjs`
- Harness source commit: `836dae7c211f3df56494d3a6b0e6764b8873d8ea` (recorded in the result metadata)
- Mode: `mock`; `MOCK_NO_DATABASE`; one synthetic `QUEUED` DTO.
- Load: 60 concurrent client tasks, one authenticated-shape `GET /api/v1/jobs/<JOB_ID>` each.
- Mock behavior: 50 ms fixed response delay; mock checks a dummy in-process bearer value. No real user token is used or written.
- Primary metric: client-observed GET latency from request start through response body. This is different from poll interval, Job duration and Job completion time.
- Percentile: nearest-rank p95, `sorted[ceil(0.95*n)-1]`, over successful HTTP responses.
- Runtime: Node.js v22.13.0; Windows `win32/x64`; 12 logical CPUs, Intel Core i7-8850H; 16,943,120,384 bytes total RAM and 773,939,200 bytes free before this run.
- The result records `working_tree_dirty=false` and the exact committed source SHA before the run. The polling production code was committed in the branch before this harness run; the benchmark was not an application integration measurement.

## Observed result

| Measure | Actual result |
|---|---:|
| Users/tasks started | 60 |
| Mock requests received | 60 |
| Successful HTTP responses | 60 |
| HTTP errors | 0 |
| Transport errors | 0 |
| Public DTO schema errors | 0 |
| Maximum concurrent mock requests observed | 60 |
| Client-observed p95 | 215.261 ms |
| Overall batch elapsed | 247.470 ms |
| Process exit code | 0 |

Raw outcomes and latency samples from the review rerun are in `performance/results-review.json`; the synthetic Client DTO was checked against required fields, UUIDs, status/timestamp consistency and forbidden extra fields. Captured runner stdout, command, runtime, commit SHA, timestamp and exit code are in `evidence/review-p3-performance-run.log`.

## Historical result retained

The earlier experiment remains unchanged in `performance/results-local.json` and `evidence/performance-run.log`: source commit `ec9f4dcccbdd7665a2e5c90b6eefaad6b12d9c66`, 60 mock responses, p95 151.155 ms. The review rerun above is a separate evidence stage with stricter DTO checks and its own source SHA/artifacts; its 215.261 ms p95 should not overwrite or be confused with that historical result. Both are `SIMULATED_ONLY`.

## Interpretation and limitations

The script demonstrated that this local runner can initiate 60 concurrent status-shaped requests and calculate p95 reproducibly. The synthetic p95 includes loopback HTTP, event-loop and client overhead plus the fixed mock delay. It does **not** measure the application, database, real auth, job ownership query, pool saturation or production path. Therefore the product performance target remains **NOT_RUN**, not PASS or FAIL. A real local API run is documented in `performance/README.md`; it must use a retained disposable test Job and an operator-verified safe environment. The full ADR-007 `PERF-736-V1` campaign remains out of scope.
