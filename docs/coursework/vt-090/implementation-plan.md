# VT-090 Implementation Plan

**Baseline:** `bee832eaf5463df20f6c6815174322871eb6685a`

**Branch:** `bt3/vt-090-async-job-progress`

**Created:** 2026-11-09

## AI prompt and assumptions

**Prompt used:** “Implement the approved VT-090 Async Job Progress & Retry Safety coursework as the smallest runnable vertical slice. Audit the current repository and contracts first. Add safe frontend status polling using the existing Jobs GET endpoint; keep POST idempotency behavior unchanged; add pairwise test design, RED/GREEN evidence, a `>`→`>=` mutation experiment, flaky/coverage review and a reproducible 60-concurrent mock harness. Do not implement Phase 2 or invent progress percentages. Record only commands and results actually observed.”

Assumptions to verify in code/tests:

1. The selected Job detail effect is the right UI lifecycle boundary because it already owns the selected ID, identity, abort signal and generation checks.
2. API Contract §8.1–8.2 and `JobsApi.getJob` are sufficient; no new endpoint or DTO is needed.
3. `QUEUED` and `RUNNING` are the only nonterminal public states; `COMPLETED`, `FAILED` and `CANCELLED` are terminal.
4. Automatic polling is a read operation and must not alter the existing submit-attempt object, idempotency key or request payload.
5. Because Manager is still an idle foundation, state transitions must be exercised with controlled frontend API responses, not presented as real local execution.

## Evidence-based AI proposals changed/rejected

### Proposal 1 — Repeat the POST after a status-read timeout

- **Initial AI proposal:** if a status request times out after submission, POST the same payload again to “ensure” the job exists.
- **Evidence:** `GET /api/v1/jobs/{job_id}` already exists and `JobsApi.getJob` accepts an abort signal. `JobSubmitService` and the retained `(client_id, idempotency_key)` index protect submissions; the UI already stores/retries the same attempt after an uncertain POST. A status-read failure does not mean the submission failed.
- **Decision:** rejected. Polling retries only `GET`; an uncertain original POST continues to use the existing same-key/same-body path. No polling error can call `submitJob`.

### Proposal 2 — Add a Manager/Scheduler/Simulator loop so the demo can reach COMPLETED

- **Initial AI proposal:** implement a minimal background Manager loop to move demo Jobs through execution states, making the polling demo visually convincing.
- **Evidence:** `manager/service.py` is explicitly a stoppable idle foundation. Phase 2A describes Manager orchestration and Simulator dispatch as design-level scope with dependencies; the user task expressly excludes full Phase 2 and the project contract gives Manager sole ownership of allocation and terminal transitions.
- **Decision:** rejected. This slice only renders states returned by the existing GET contract. Tests use deterministic API fixtures; the report will say a local Job will remain queued on this baseline unless changed by an authorized runtime.

## Scope and planned files

### Production and test files

- `frontend/src/ui/jobs/JobsPage.tsx` — sequential selected-Job polling, bounded transient-error retry, lifecycle cleanup, and truthful status feedback.
- `frontend/src/ui/jobs/JobsPage.test.tsx` — controlled-timer/request tests for pending/terminal states, no overlap, stale response, cleanup, retry boundary and GET-vs-POST safety. Existing idempotency tests remain authoritative; strengthen/rewrite two weak cases only after documenting their exact weakness.

### Coursework evidence and harness

- `docs/coursework/vt-090/specification.md`
- `docs/coursework/vt-090/test-strategy.md`
- `docs/coursework/vt-090/pairwise-cases.json` and deterministic generator
- `docs/coursework/vt-090/evidence/` — actual RED/GREEN, mutation and repeated-run logs
- `docs/coursework/vt-090/ai-test-review.md`
- `docs/coursework/vt-090/mutation-report.md`
- `docs/coursework/vt-090/coverage-flaky-review.md`
- `docs/coursework/vt-090/performance/` — mock server/runner and raw measurement output
- `docs/coursework/vt-090/performance-report.md`
- `docs/coursework/vt-090/traceability.md`
- `docs/coursework/vt-090/ai-usage-log.md`
- `docs/coursework/vt-090/reflection.md` — clearly marked draft for student confirmation
- `docs/coursework/vt-090/README.md`

No backend, migration, API contract, ADR, DB grants, Manager or Simulator file is planned.

## Vertical-slice design

1. Keep the existing Job submit API and frozen idempotency attempt behavior unchanged.
2. When detail is loaded, display the safe status DTO. While status is `QUEUED` or `RUNNING`, schedule one `getJob` after the configured polling delay.
3. Schedule the next request only after the previous request settles; do not use overlapping `setInterval` requests.
4. Retry only transient status-read errors, with a small bounded backoff. Allow three consecutive transient failures; stop on failure four (`failures > MAX_CONSECUTIVE_FAILURES`) and expose explicit reload. A successful GET resets the counter.
5. Abort requests and clear timers on unmount, selected Job/identity change, or dependency change. Keep the existing request-key/generation guard so late responses cannot overwrite the current detail.
6. Stop automatic polling immediately when a GET returns `COMPLETED`, `FAILED` or `CANCELLED`. Render only actual API status/timestamps; no percentage or inferred execution progress.

## Acceptance and test map

| Acceptance | Planned evidence |
|---|---|
| AC-01 submission remains asynchronous and displays accepted Job ID/status | Existing submit flow tests plus status-tracking component test; no API change |
| AC-02 queued/running follows GET; terminal stops | Fake-timer component tests for transitions and each terminal status |
| AC-03 retry does not duplicate Job/side effects | Existing same-key/body uncertain-submit test; changed-body conflict test; new GET-failure test asserts POST count remains one |
| AC-04 timeout/503/out-of-order/switch/unmount remain safe | Controlled promise, fake clock, error and cleanup tests |
| AC-05 60 concurrent latency experiment | Reproducible local mock HTTP harness; report is `SIMULATED_ONLY`, never production PASS |

Test levels: unit/helper and React component tests; current API client tests; backend regression as environment permits; mock-only performance experiment. Physical GPU execution, full signed-result pipeline and Phase 3 disputes are outside this slice.

## Risks and controls

- Polling too fast creates request load: fixed interval/backoff; no overlap.
- Old identity/Job response overwrites new state: abort + existing key/generation guard, with deterministic race tests.
- A GET outage causes duplicate submission: GET-only retry and explicit POST-call-count assertion.
- “Progress” could be misread as actual GPU execution: display backend status only and disclose the Manager limitation.
- Real p95 cannot be inferred from a fake server: mark harness output simulated, include environment and nearest-rank calculation.
- Test tooling may not run: use direct installed package entrypoints where possible; record Node/npm/uv/Docker limitations and exact exit codes.

## Stage and commit sequence

1. Commit audit, plan and specification/test strategy/pairwise design before application code.
2. Commit generated baseline test cases; run focused tests and save actual RED output.
3. Commit minimal polling implementation; run focused tests, typecheck/build and backend regressions available in the environment.
4. Perform two real test-strengthening changes, mutation experiment, repeated flaky checks and mock load run; save raw evidence.
5. Complete traceability and coursework README; run final diff/secret/status review.
6. Commit with Conventional Commits and push this personal branch. If GitHub access permits, open a Draft PR titled `BT3 VT-090 — INDIVIDUAL COURSEWORK — DO NOT MERGE`.

No merge, self-approval, schema/contract change, live DB benchmark or Phase 2 implementation is authorized or planned.
