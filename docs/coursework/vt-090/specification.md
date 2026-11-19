# VT-090 Specification — Async Job Status Tracking with Safe Retry

**Baseline:** `bee832eaf5463df20f6c6815174322871eb6685a`

**Variant:** VT-090

**Date:** 2026-11-09

## Problem statement

Submitting a Job is already an asynchronous API operation: the accepted response contains a Job ID and initial `QUEUED` status, while the client must not wait for GPU execution. The current Jobs page loads the selected Job once and requires a user action or another workflow event to read it again. This vertical slice adds bounded, automatic status reads for the selected Job without changing the submission contract or claiming that this baseline executes GPU work.

## Scope

- Use only the existing `GET /api/v1/jobs/{job_id}` endpoint and its safe Job projection.
- Automatically poll the selected Job while its latest confirmed status is `QUEUED` or `RUNNING`.
- Display only server-returned status/timestamps. Do not estimate a percentage, remaining time, or GPU execution progress.
- Keep each GET sequential; schedule the next one only after the previous request has settled.
- Retry transient status-read failures with bounded delays. Stop automatic retries after the fourth consecutive failure and allow explicit reload.
- Abort outstanding reads and clear timers when the selected Job or identity changes, the component unmounts, or polling is no longer needed.
- A GET failure must never issue or repeat a Job submission. Existing POST retry behavior remains same-key/same-body and unchanged.

## Measurable acceptance criteria

**AC-01 — Asynchronous acceptance.** A successful existing submit displays its Job ID and accepted status without waiting for a terminal state. No API route/DTO or backend behavior changes.

**AC-02 — Status tracking.** After the initial detail GET, the selected `QUEUED`/`RUNNING` Job is read again every 2 seconds after successful pending responses. A response showing `COMPLETED`, `FAILED`, or `CANCELLED` updates the visible status and stops further automatic GETs.

**AC-03 — Retry safety.** A status GET timeout/network failure or HTTP 5xx schedules only GET retries at 1, 2, and 4 seconds for consecutive failures 1, 2, and 3. A fourth consecutive failure stops automatic polling, keeps the last confirmed Job projection, shows recovery guidance, and leaves explicit reload available. A successful GET resets the failure count. No polling branch calls POST.

**AC-04 — Lifecycle and ordering.** There is never more than one active polling GET for the selected Job. A response from an old Job/identity is ignored; timers and reads are cleaned up on selection change and unmount. Terminal state has no follow-up timer.

**AC-05 — Performance evidence.** A reproducible harness issues one authenticated-status-shaped GET for each of 60 concurrent simulated clients and records latency samples, response/error counts, runtime and nearest-rank p95. If only a mock server can be run, the result is `SIMULATED_ONLY` and makes no claim about production/API latency.

## Non-functional requirements

- **Retry/duplicate safety:** polling is read-only. It must not create a Job, reference, transaction, or completion side effect. A logical submit continues to use one frozen idempotency key and request body.
- **Responsiveness:** a slow Job does not block the page. A poll timeout or server failure does not cause an automatic POST. Retry is bounded.
- **Resource cleanup:** no periodic timer or pending response may keep updating the page after selection change/unmount.

## Invariants and semantics

1. `QUEUED` and `RUNNING` are the only nonterminal statuses on the current Job contract; `COMPLETED`, `FAILED`, and `CANCELLED` are terminal.
2. The server is authoritative. The UI cannot transition Job state; it only renders the latest valid GET response.
3. One logical submission plus the same retained idempotency key and normalized payload returns the original Job. Reusing that key with another payload is a contract conflict.
4. “Exactly once” in this coursework means one logical committed Job effect under the existing idempotency contract. It does not mean exactly-once network delivery or physical GPU execution.
5. The current Manager is idle foundation code. This coursework does not claim a local Job will move to `RUNNING` or terminal without a future authorized execution implementation.

## Out of scope

New API endpoints/fields; new status values; progress percentages; Manager/Scheduler/Worker/Simulator implementation; schema, migration, grants, or API-contract changes; real GPU execution; full signed-result pipeline; Phase 3 dispute flow; production load claims from a mock harness.
