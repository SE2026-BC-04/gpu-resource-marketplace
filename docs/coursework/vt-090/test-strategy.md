# VT-090 Test Strategy and Pairwise Design

## Test levels

| Level | Goal | Evidence |
|---|---|---|
| Unit/helper | Retry boundary and deterministic backoff decisions | Vitest focused tests with fake timers |
| Component | Status changes, selected identity, lifecycle cleanup, no overlapping GETs, no POST from polling | React Testing Library with controlled promises and fake timers |
| API contract regression | Existing safe GET DTO, key/body preservation, changed-body conflict, no duplicate submission | `frontend/src/api/jobs.test.ts` and existing Jobs page tests |
| Backend regression | Confirm no backend contract/idempotency regression | Existing Jobs submit/read/auth test groups if the environment supports them; these are not necessary to implement UI-only polling |
| Performance experiment | Exercise 60 concurrent status-shaped reads and calculate p95 | Local built-in HTTP mock harness; clearly `SIMULATED_ONLY` |

Physical GPU execution, the full signed-result pipeline, Manager scheduling, and Phase 3 disputes are not needed to test this UI read slice and remain out of scope.

## Case catalog

| ID | AC/Risk | Test level | Preconditions/Input | Expected result | Priority |
|---|---|---|---|---|---|
| VT090-01 | AC-02 | Component | Selected Job starts `QUEUED`; GET returns `QUEUED` | Exactly one next GET after 2 seconds; none before | P1 |
| VT090-02 | AC-02 | Component | Selected Job `QUEUED`; next GET returns `RUNNING` | UI shows `RUNNING`, remains selected, schedules next poll | P1 |
| VT090-03 | AC-02 | Component | GET returns `COMPLETED` | UI shows `COMPLETED`; no later GET | P1 |
| VT090-04 | AC-02 | Component | GET returns `FAILED` | UI shows `FAILED`; failure reason remains server-provided; polling stops | P1 |
| VT090-05 | AC-02 | Component | GET returns `CANCELLED` | UI shows `CANCELLED`; polling stops | P1 |
| VT090-06 | AC-04 | Component/race | A poll promise remains pending while timers advance | No second poll starts before the first settles | P1 |
| VT090-07 | AC-04 | Component/race | A pending poll for Job A resolves after selecting Job B | A's response cannot overwrite B; the new detail remains visible | P1 |
| VT090-08 | AC-04 | Component | A poll is scheduled, then component unmounts | Timer is cleared; no later GET or state update | P1 |
| VT090-09 | AC-04 | Component | A poll is in flight, then identity changes | Request is aborted/invalidated; old identity response is ignored | P1 |
| VT090-10 | AC-03 | Component/failure | GET rejects with network/timeout (`status=0`) | Only GET is retried; POST count remains zero (or one if initiated by submit) | P1 |
| VT090-11 | AC-03 | Component/failure | GET returns 503 then succeeds | Retry occurs at the specified delay; success resets failure count and pending polling resumes | P1 |
| VT090-12 | AC-03 | Component/boundary | Three consecutive GET failures, then GET succeeds | Fourth GET is attempted after the third retry delay; status recovers | P1 |
| VT090-13 | AC-03 | Component/boundary | Four consecutive GET failures | Automatic polling stops after failure four; last confirmed status stays visible; explicit reload works | P1 |
| VT090-14 | AC-03 | API/component | POST response is uncertain after commit | Existing same-key/same-body retry returns original logical Job; no new key/body | P1 |
| VT090-15 | AC-03 | API/component negative | Reuse key with changed submit payload | Existing API contract returns `409 IDEMPOTENCY_KEY_REUSED`; UI does not silently retry with changed body | P1 |
| VT090-16 | AC-04 | Component/boundary | Advance clock to 1999 ms, then 1 ms | No early request; exactly one request at 2000 ms | P2 |
| VT090-17 | AC-03 | Component | Job accepted once; later GET fails/retries | `submitJob` remains at one call; no duplicate success/terminal notification is emitted by polling | P1 |
| VT090-18 | AC-05 | Performance | Mock HTTP server, 60 simulated users, one GET each | 60 outcomes recorded; p95 uses nearest-rank; report explicitly says `SIMULATED_ONLY` | P2 |

`VT090-14` and `VT090-15` reuse existing, independently useful submit/idempotency tests rather than reimplementing the backend contract. `VT090-01..13`, `VT090-16..17` are the new polling behavior tests. `VT090-18` is an experiment, not an application performance pass.

## Pairwise factors and constraints

The deterministic generator in `generate-pairwise.mjs` emits two separate constrained matrices so that an HTTP GET outcome is never conflated with a POST outcome.

### Polling matrix

- `prior_status`: `QUEUED`, `RUNNING`.
- `get_result`: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`, `HTTP_503`.
- `ui_context`: `SAME_JOB`, `SWITCH_JOB`, `UNMOUNT`, `CHANGE_IDENTITY`.
- Persisted business transitions are constrained to `QUEUED → QUEUED/RUNNING/CANCELLED` and `RUNNING → RUNNING/COMPLETED/FAILED`. `TIMEOUT` and `HTTP_503` are transient GET outcomes, not Job states. Invalid persisted edges are excluded row by row with a reason and mapped to the PostgreSQL lifecycle guard test; that database-backed test is `NOT_RUN` here because no disposable cluster was verified. A late `QUEUED` response after `RUNNING` is a stale response, covered separately by the component race tests rather than treated as a valid state transition.
- Every generated row executes as one Vitest case in `frontend/src/ui/jobs/JobsPage.pairwise.test.tsx`. The test checks UI/lifecycle outcome, stale response handling, bounded request activity, and that polling emits no POST.

### Submission/retry matrix

- `attempt`: `FIRST_SUBMISSION`, `SAME_KEY_SAME_BODY`, `SAME_KEY_CHANGED_BODY`.
- `post_result`: `201_CREATED`, `200_REPLAY`, `NETWORK_LOST_AFTER_COMMIT`, `503_BEFORE_COMMIT`, `409_KEY_REUSED`.
- `recovery`: `NO_AUTOMATIC_POST`, `RETRY_SAME_ATTEMPT`, `EDIT_AND_NEW_ATTEMPT`.
- Constraints exclude outcomes that violate the API semantics: a first submit cannot be a replay/conflict; same-key/same-body cannot be a second create or changed-body conflict; same-key/changed-body must return the key-reuse conflict; success cannot cause another submit; uncertain outcomes must preserve the frozen key/body; and a changed-body conflict cannot retry the same attempt.
- Every generated row executes as one API-client test in `frontend/src/api/jobs.pairwise.test.ts`. It verifies the client request/result mapping with mocked HTTP; it does **not** prove PostgreSQL idempotency. Backend/DB behavior remains supported only by the existing service/guard tests.

The deterministic greedy covering-array generator (seed `VT090-2026-11-09-23001940`) records the complete Cartesian count, executable configurations, excluded rows and reasons, generated rows, explicit execution target, feasible pair set and measured covered pair set. It throws if generated rows fail to cover every feasible pair; the percentage is calculated from these sets, not hardcoded. Each suite's `execution_target` is exercised with one test per emitted row. Run `node docs/coursework/vt-090/generate-pairwise.mjs` to regenerate and validate the JSON.

Current generated result: polling has 28 selected rows from 40 executable configurations (16/56 invalid rows excluded), covering 46/46 feasible pairs. Submission/retry has 8 selected rows from 12 executable configurations (33/45 invalid rows excluded), covering 21/21 feasible pairs. The final recorded execution runs all 28 polling rows and all 8 API-client rows; pairwise coverage does not mean all valid configurations were individually executed. See `evidence/review-p2-pairwise.log` for regeneration and test counts. Dedicated boundary, concurrency, ordering, terminal and identity tests remain in the component suite.
