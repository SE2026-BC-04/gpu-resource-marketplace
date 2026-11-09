# VT-090 Traceability Matrix

**Baseline:** `bee832eaf5463df20f6c6815174322871eb6685a`

**Branch:** `bt3/vt-090-async-job-progress`

**PR:** Pending push and Draft PR creation.

| Criterion/risk | Test ID / check | Test file / artifact | Commit reference | Result and evidence |
|---|---|---|---|---|
| AC-01 accepted Job ID/status remains asynchronous | Existing submit flow and VT090 accepted-submit retry/recovery | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `972071f` | PASS, final frontend suite in `evidence/frontend-final-tests.log`; existing public API contract unchanged |
| AC-02 queued/running refreshes from GET | 2-second boundary, pending transition, sequential polling | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `86845a0` | PASS, final frontend suite |
| AC-02 terminal GET stops | `COMPLETED`, `FAILED`, `CANCELLED` parameter cases | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `86845a0` | PASS, final frontend suite |
| AC-02 explicit cancel response is terminal | Stop scheduled timer after Cancel returns `CANCELLED` | `frontend/src/ui/jobs/JobsPage.test.tsx` | `ae66919` | Focused PASS; included in final suite |
| AC-03 GET failures do not duplicate submit | Real submission then transient GET failure/recovery; POST remains exactly once | `frontend/src/ui/jobs/JobsPage.test.tsx` | `972071f` | PASS; `evidence/ai-test-review-focused.log`, final frontend suite |
| AC-03 idempotency contract retained | Same frozen key/body on uncertain POST; changed-body key conflict | `frontend/src/ui/jobs/JobsPage.test.tsx`, `frontend/src/api/jobs.test.ts` | baseline plus `972071f` | PASS, final frontend suite; backend service/foundation tests 93 passed in `evidence/backend-jobs-unit.log` |
| AC-03 timeout/network/503 recovery | 5-second aborted GET, status 0 and 503 cases | `frontend/src/ui/jobs/JobsPage.test.tsx` | `86845a0`, `972071f` | PASS, final frontend suite |
| AC-03 retry boundary | Three consecutive failures allow next GET; fourth failure stops | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `86845a0` | PASS; mutation `>=` killed in `evidence/mutation-mutant-failure.log`; restored `>` passes in `evidence/mutation-restored-pass.log` |
| AC-04 no overlapping GET | Deferred in-flight request, fake timers | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `86845a0` | PASS in final suite and all 5 repeated runs |
| AC-04 stale Job/identity/unmount | Delayed A after B, identity change, cleanup, aborted timeout | `frontend/src/ui/jobs/JobsPage.test.tsx` | `b9d2d9d`, `86845a0` | PASS in final suite and five-run evidence |
| AC-04 mismatched response ID | Retry safe GET when response names a different Job | `frontend/src/ui/jobs/JobsPage.test.tsx` | `7eaef59` | Focused PASS; included in final suite |
| AC-05 60 concurrent read experiment | 60 tasks, 60 responses, nearest-rank p95 | `performance/run-status-load.mjs`, `performance/results-local.json` | `774a2f9`, `ec9f4dc` | Harness PASS, `SIMULATED_ONLY`; 60/60, zero errors, p95 151.155 ms; not production/API evidence |
| Pairwise requirement | Deterministic constrained covering array | `generate-pairwise.mjs`, `pairwise-cases.json` | `59e6e49` and follow-up pairwise coverage update | PASS: polling 50/50 pairs, submit/retry 30/30; deterministic regeneration hash in `evidence/pairwise-regeneration.log` |
| Human review of AI tests | Delete weak duplicate; replace vacuous no-POST assertion | `ai-test-review.md`, `frontend/src/ui/jobs/JobsPage.test.tsx` | `972071f` | PASS; visible deletion/replacement diff; revised focused case PASS |
| Coverage and flaky risk | Seven selected race/timer tests repeated five times | `coverage-flaky-review.md`, `evidence/flaky-repeats.log` | Current branch | 35/35 selected executions PASS; line/branch coverage NOT_RUN because coverage provider absent |

No production database, migration, API contract, ADR, Manager or Simulator implementation is changed by this slice.
