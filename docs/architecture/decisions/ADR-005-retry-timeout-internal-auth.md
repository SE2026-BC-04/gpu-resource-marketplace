# ADR-005 - Execution retry, timeout, backoff and internal HTTP authentication

**Status:** ACCEPTED (2026-10-18) - Option B, exact retry/timeout/authentication parameters and 18 deterministic test designs approved; implementation `NOT_RUN`  
**Version:** 0.2 (approved design; documentation-only status update, no MVP scope change)  
**Date:** 2026-10-18  
**Project:** GPU Resource Marketplace (simulation-only MVP)  
**Proposed repository path:** `docs/architecture/decisions/ADR-005-retry-timeout-internal-auth.md`  
**Design/test status:** 18 test designs `APPROVED`; all implementation tests `NOT_RUN` (no implementation or performance results claimed).

## 1. Goal and existing decisions

Set the smallest deterministic, recoverable policy for delivery and execution deadlines across **Manager -> Worker Simulator -> Backend API**, without adding a broker, new user-facing features, a new Job state or a real GPU. Make its time boundaries and security behavior testable before database/API design or coding.

Binding inputs (already APPROVED/ACCEPTED; NOT changed here):

- ADR-001/002: modular monolith, distinct API/Manager/Simulator processes, only API/Manager directly use PostgreSQL; Simulator has no application DB credentials.
- ADR-003: PostgreSQL transactionally persisted Execution Outbox and Result Inbox plus internal HTTP; at-least-once message delivery, exactly-once **committed business effects**; stable `attempt_id` for resend; `202` for accepted dispatch and durable callback ingestion, not final Job success.
- ADR-004: canonical Ed25519 Signed Result V1 with context binding; signature verification belongs to Manager, not mere HTTP authentication.
- ADR-006: dispute evidence retention and **900-second dispute retry** are separate from execution transport retries in this ADR.
- FR-JL-01/05, FR-SR-03/04, NFR-R01/02/04/07/08, NFR-S01/03/05: positive `duration_seconds` is submitted, committed Job/attempt/deadlines survive restart; on bounded lack of a valid result Manager may finish `FAILED/SYSTEM_FAULT` with one GPU release and **zero Worker reputation penalty**. Manager recovery action <=120 seconds is a **target**, not an achieved result.

**Explicit non-goals:** physical PostgreSQL schema/DDL, full internal HTTP request/response JSON Schema, user authentication, production mTLS or multi-host zero-trust setup, autoscaling, additional failure classifications, different retention windows, or a new Dispute policy.

## 2. Alternatives and accepted decision

| Option | Mechanism | Trade-off | Review result |
|---|---|---|---|
| A | Fixed immediate retry count and fail as soon as attempts are exhausted | Small but can falsely time out a Job that is legitimately executing after an ACK is lost | NOT SELECTED |
| **B** | Persisted due instants, bounded exponential retry spacing, one fixed hard execution deadline relative to requested duration, independent Inbox race serialization | Recoverable, deterministic and compatible with ADR-003; extra durable timestamps and claim logic | **ACCEPTED (2026-10-18)** |
| C | Background broker/time-based workflow engine | Extra deployment/component and changes ADR-003 | NOT SELECTED |

### 2.1. Accepted parameter register (design-approved, not benchmarked)

| Name | Approved value | Interpretation |
|---|---:|---|
| `DISPATCH_POLL_INTERVAL` | 2 seconds | Manager scans due outbox / receipt / fallback work; poll tick is not a deadline authority |
| `CLAIM_LEASE` | 30 seconds | Recover an abandoned outbox/inbox claim; lease ownership must use a fencing token/version |
| `HTTP_CONNECT_TIMEOUT` | 2 seconds | Per outbound internal HTTP call |
| `HTTP_TOTAL_TIMEOUT` | 5 seconds | Includes connect and response; never hold DB listing/job locks during a network call |
| `BACKOFF_AFTER_FAILURE_N` | `min(2^n, 30)` seconds, `n=1,2,...` | Retry delays **2,4,8,16,30,30,...** measured from the trusted failure-recording instant; no jitter in MVP fixture |
| `FIRST_MISSING_RECEIPT_PROBE` | `finish_due_at + 10 seconds` | Even after a `202` dispatch ACK, re-send **same logical attempt** if neither an accepted result nor an on-time pending Inbox candidate exists |
| `EXECUTION_GRACE` | 120 seconds | Fixed grace after the requested simulated duration |
| `EXECUTION_HARD_DEADLINE` | `finish_due_at + 120 seconds` | Absolute upper boundary for *new receipt ingestion and new dispatch attempts* |
| `CALLBACK_AUTH_SECRET_STRENGTH` | At least 256 bits random | Distinct credential for the Simulator -> API direction |
| `DISPATCH_AUTH_SECRET_STRENGTH` | At least 256 bits random | Distinct credential for Manager -> Simulator direction |

These numerical values are **accepted engineering settings for the simulation-only MVP**, not inherited SRS product SLAs or measured performance guarantees. NFR-R02 Manager recovery target `<=120.0 s` is an independent measurement and is not the same as `EXECUTION_GRACE=120 s`.

### 2.2. Deadline, trusted time, and acceptance rule

Persist, in the initial allocation transaction:

```text
started_at        = PostgreSQL-trusted allocation timestamp after Listing/Job locks (UTC)
finish_due_at     = started_at + duration_seconds
hard_deadline_at  = finish_due_at + 120 seconds
attempt_id        = stable logical execution attempt UUIDv4
outbox_event_id   = stable persisted event identifier
```

- `duration_seconds` is the validated, positive simulated Job duration from the existing Job submission; this ADR does not add a new range or change the meaning of the duration.
- The Manager/DB clock determines due work and final outcome; NEVER use the Worker-supplied signed `finished_at`, HTTP client date or an in-memory timer to grant extra time.
- A callback is **on time only when its trusted durable Inbox-ingress decision timestamp `received_at < hard_deadline_at`**, after the API has acquired the relevant Job row lock. `received_at == hard_deadline_at` is **late**. A valid on-time Inbox receipt can be cryptographically verified and terminalized *after* the deadline if Manager processing was delayed.
- `received_at` is recorded using the DB trusted clock after the Job lock is obtained and is committed with the Inbox row; a pre-deadline external request whose transaction only acquires the lock after deadline is NOT backdated.
- The Manager fallback transaction must serialize with Callback ingress for that Job: lock the affected Listing and Job in the established ordering, then examine and verify already-committed, on-time eligible Inbox entries before declaring `FAILED/SYSTEM_FAULT`. A callback that wins/commits first is visible to the subsequent fallback; a fallback that wins first makes a blocked callback stale. Use transaction isolation / retries adequate to avoid stale snapshot reads; the final lock order and SQL statements belong in Database Design.
- If no eligible, valid signed result exists at or after the deadline, Manager commits exactly one `RUNNING -> FAILED` transition classified `SYSTEM_FAULT`, releases the one active allocation, makes no Worker reputation contribution and closes outstanding retry work. Invalid receipts alone never cause an immediate penalty or unconditional early Job failure.
- On restart, reconstruct pending deadlines and due work from PostgreSQL. A DB outage prevents a committed decision until connectivity is restored; no false success or unconditional wall-clock recovery guarantee during outage.

**Fixed example using a fake DB clock:**

```text
started_at       = 2026-10-18T00:00:00.000000Z
requested duration_seconds = 60
finish_due_at    = 2026-10-18T00:01:00.000000Z
hard_deadline_at = 2026-10-18T00:03:00.000000Z
received_at = 00:02:59.999999Z -> ON TIME
received_at = 00:03:00.000000Z -> LATE
```

No `terminal_at`, Dispute filing cutoff or retention period is based on the Worker's `finished_at`; the established trusted terminal timestamp policy remains intact.

## 3. Delivery state and retry behavior

### 3.1. Manager dispatch (Outbox)

1. Allocate Job and persist one `EXECUTE_JOB` outbox record in the same transaction, with `RUNNING`, immutable logical `attempt_id`, and the three timestamps above. The first dispatch is due immediately.
2. At every due scan (2-second nominal poll), claim with an expiring 30-second DB lease and fencing token (e.g., claim version); commit claim before calling HTTP. No listing locks or other long-running DB transaction are held while waiting for the Simulator.
3. Send the command with **the same** `job_id`, `attempt_id`, `outbox_event_id` and simulated input. HTTP `202` indicates command **accepted** by Simulator, not execution completed. Mark dispatch delivery acknowledged (only the current lease owner can do so) and await callback.
4. On a retryable transport error, record the failed attempt, update `next_retry_at` using the fixed backoff sequence, release claim and retry while `next_retry_at < hard_deadline_at` and Job is `RUNNING`. This is a **time-bounded** retry policy; the total retry count can depend on configured `duration_seconds`, but no retry is scheduled beyond the hard deadline.
5. **Lost-result repair after ACK:** if the Job remains RUNNING and no accepted result or on-time Inbox candidate exists by `finish_due_at + 10 s`, schedule another dispatch for that **same attempt**. Give already-persisted on-time Inbox evidence processing priority over a repair resend. Continue with the proposed backoff until a valid result arrives or the hard deadline is reached. An ACK does not suppress all future repair requests.
6. A stale dispatcher whose lease expired cannot overwrite a newer claim's database state (fencing); duplicate HTTP delivery is nonetheless possible and handled idempotently.

### 3.2. Simulator -> API result callback (Inbox)

1. The Simulator signs one ADR-004 V1 result, uses the existing authenticated internal callback route, and retains **the exact signed bytes and `result_id`** for all callback retries of that produced result during its lifetime.
2. The API authenticates the service, validates an intelligible envelope and Job identity, serializes ingress with terminal fallback using the Job lock, checks on-time eligibility by DB clock, and inserts the raw signed result and metadata into durable Inbox. API sends `202` only after commit, and only Manager later verifies/accepts Ed25519 signature and context.
3. If a `202` response is lost, re-send the same callback bytes; Inbox identity `result_id` + signed-byte digest makes it a no-op. Same `result_id` with different bytes is a conflict; there is never an overwrite.
4. Retry callbacks after network timeout / connection loss / temporary server failure with the same `2,4,8,16,30...` schedule, **only while before the trusted execution deadline provided by Manager**. The provided deadline is a retry hint to Simulator, never a trust input to the API. On permanent malformed/conflicting input, stop that callback and record a redacted error. A Simulator restarted without its previous in-memory receipt may regenerate deterministic mock work with a **new UUIDv4 `result_id`**; Manager still allows at most one accepted final result for the Job, preserving ADR-003 honesty about execution duplicates.
5. After Job finalization or expiry, a newly delivered callback must not be inserted as an eligible new receipt or mutate the Job/Reputation. Operational rejection logging may remain, subject to existing audit TTL.

### 3.3. Error category matrix (policy, not complete public API specification)

| Transport observation | Proposed sender reaction | Persistent business effect |
|---|---|---|
| `202` from Simulator dispatch endpoint | Record command accepted; wait for result; later repair probe if missing | No Job finalization by ACK |
| `202` from API callback endpoint | Receipt durably accepted or identical duplicate | Manager separately verifies/finalizes |
| Connection error, HTTP timeout, `408`, `429`, or `5xx` | Retry with capped exponential backoff while before hard deadline | No duplicate allocation or result effects |
| `401` / `403` | Reject request before Inbox/Simulator acceptance, record security/configuration fault; retry at a rate limited to **once per 30 seconds** until configured deadline so fixed external secrets can recover | No unauthorized acceptance; no reputation effect |
| Malformed `400` / `422`, result-ID collision `409`, stale/expired attempt | Do not loop same bad input; retain rejection reason; wait for different valid evidence or final fallback | No acceptance or overwrite |

Exact response bodies and the final mapping for non-`202` response codes are **API Contract** details; the authorization, retry/non-retry and no-business-effect invariants above are the proposed ADR policy. In particular `202` is not proof of a valid Ed25519 signature.

## 4. Internal HTTP service authentication

### 4.1. Accepted MVP mechanism

- Use **two independently generated, direction-scoped Bearer service tokens**: `MANAGER_DISPATCH_TOKEN` only for Manager -> Simulator execution endpoint; `SIMULATOR_CALLBACK_TOKEN` only for Simulator -> API signed-receipt endpoint. Each has at least 256 bits of cryptographically secure random entropy.
- Load from environment-injected secrets / untracked local `.env` or local secret files; fail closed on missing/malformed required secret. Never hardcode credentials, embed them in JSON body, commit them or log their values. Perform constant-time equality checking where practical and avoid echoing `Authorization` headers in traces.
- Verify token **before accepting execution, persisting Inbox, or disclosing sensitive internal data**. Missing, bad or opposite-direction service token -> unauthenticated (`401`), because each receiver stores only its own expected secret. Scope is separate from client/worker/admin login sessions. An independently authenticated principal without the required route permission -> `403`.
- The API verifies Simulator's service identity before Inbox ingress; **Manager still verifies Worker Ed25519 identity, signature and expected Worker/Listing/Job/attempt context**. Service token **never substitutes** for cryptographic receipt verification.
- The Simulator is isolated on an internal service network without externally published execution port. It gets only signing secrets for its simulation role and the callback token, **never** Manager DB credentials or protected oracle data. Expose no direct Browser -> Simulator path.
- For the Docker Compose MVP, this bearer-over-HTTP profile assumes a **trusted, isolated single-host internal network**. It is not protection against packet capture by a compromised same-network container. Never claim this alone is production-grade transport confidentiality; connecting over an untrusted network requires TLS/mTLS in a later deployment decision, not a hidden MVP requirement.

### 4.2. Failure behavior and instrumentation

- Misconfigured token does not create an Inbox entry, an accepted dispatch, a Job transition, a GPU release, or a reputation effect. A known due Job still reaches the same persisted timeout fallback if no valid result becomes available.
- Record `job_id`, `attempt_id`, `outbox_event_id` / `result_id`, delivery attempt number, redacted error class, `next_retry_at`, deadline, lease owner/version and authorization-failure counters, **never token/private-key/Oracle secret values**.
- Configuration rotation is an operations action; no key-management UI, secret store service or manual Admin arbitration is introduced by this ADR.

## 5. Transaction and concurrency invariants

1. `ALLOCATE + RUNNING + ATTEMPT + OUTBOX` is **one committed transaction**. Zero duplicated allocation and no orphan outbox without its committed attempt.
2. HTTP calls happen **outside** DB transactions holding Listing/Job locks.
3. `received_at` for callback is recorded with durable Inbox insert **after** the Job lock is acquired. The Manager must process a committed on-time Inbox receipt before timeout fallback, including when its worker was down during the deadline.
4. Final result acceptance, Job terminal state, GPU release, one effective reputation contribution and Inbox consumption are one idempotent transaction per ADR-003.
5. If deadline fallback wins, only `FAILED/SYSTEM_FAULT`, one release, zero reputation contribution; no later callback can rewrite terminal state.
6. Retry only the same logical `attempt_id` for a given Job. Outbox/inbox processing can be at least once; exactly-once *physical simulation* is NOT promised.
7. Time and lease recovery survive Manager restart. The 120-second Manager action-recovery target is evaluated by QA-REL-01/`REL-07` only in a documented healthy environment; not an automatic pass.

## 6. Accepted deterministic verification cases (implementation `NOT_RUN`)

**Status:** all 18 test designs APPROVED on 2026-10-18; **every implementation test `NOT_RUN`**. Each test restores an independent DB snapshot, uses a fake DB clock / forced commit and network barriers, fixed Worker signing fixtures, and checks committed row-level effects. All listed cases must eventually PASS for this ADR implementation to be VERIFIED; approving the ADR alone is not execution evidence.

Fixture F: Worker W1; ACTIVE Listing L1 with 4 simulated GPUs; Job J1 requests 2 GPUs for 60s; committed allocation with `started_at=T0=2026-10-18T00:00:00.000000Z`, `finish_due_at=T0+60s`, `hard_deadline_at=T0+180s`, stable `attempt_id=A1`; one `EXECUTE_JOB` outbox. Expected eligible SUCCESS effect = Job COMPLETED, allocation count 0, one accepted signed result and `successful_jobs +1`, `worker_fault_jobs +0`. Expected fallback = Job FAILED/SYSTEM_FAULT, allocation count 0, zero accepted result, zero Worker reputation effect. UUID fixture IDs are proper UUIDv4 in the real contract; short labels are conceptual aliases.

| ID | Injected situation | Binary PASS oracle |
|---|---|---|
| `RT-01-ATOMIC-COMMIT` | Kill Manager before then after allocation+outbox commit in two separate snapshots. | Before: neither RUNNING/allocation/outbox committed. After: all committed together; on restart same A1 is dispatched; no duplicate allocation. |
| `RT-02-BACKOFF` | Inject first five retryable HTTP dispatch failures using fake clock. | Persisted next delay after failure 1..5 is exactly `2,4,8,16,30` seconds; no retry happens before due instant or after hard deadline. |
| `RT-03-LOST-DISPATCH-ACK` | Simulator accepts command; drop the `202` response; retry. | Same `attempt_id=A1`, one accepted terminal result, exactly one allocation release, one successful reputation contribution. |
| `RT-04-MISSING-RECEIPT` | Dispatch returns `202`, drop all callbacks until `finish_due_at+10s`, then allow repair. | Manager re-dispatches A1 no earlier than that due time if no Inbox candidate is pending; valid callback can complete J1 once; ACK alone never terminalizes J1. |
| `RT-05-LEASE-FENCING` | Claim outbox by M1; crash before ACK; move fake clock past 30s lease, claim with M2, then let stale M1 update. | M2 can re-claim A1; stale M1 update affects 0 rows; no double finalization or allocation. |
| `RT-06-RESTART-TARGET` | Restart Manager with DB healthy and a due item. | First persisted recovery/claim action is measurable within `120.0s` from process start (NFR TARGET, separately reported); mandatory: A1 and allocations unchanged, no missing job. |
| `RT-07-LOST-CALLBACK-ACK` | Persist valid callback, drop API `202`; Simulator sends byte-identical payload again. | One Inbox logical receipt, `result_id` unchanged, one result acceptance/finalization/release/reputation effect. |
| `RT-08-PRE-DEADLINE-INBOX` | Commit valid callback with `received_at=T0+179.999999s`; kill Manager until `T0+190s`. | Manager accepts/verifies stored on-time receipt after restart, J1 COMPLETED once; it must not incorrectly choose SYSTEM_FAULT. |
| `RT-09-EXACT-DEADLINE` | Attempt callback ingress at `T0+180.000000s` while J1 still RUNNING. | Late receipt is not eligible; after Manager fallback J1 FAILED/SYSTEM_FAULT; no accepted signed result, zero reputation change, one release. |
| `RT-10-FORGED-TIME` | At `T0+180s`, Worker sends a correctly signed payload with earlier `finished_at` and/or forged HTTP timestamp. | DB trusted ingress timestamp controls; old Worker timestamp cannot bypass RT-09; zero new accepted receipt. |
| `RT-11-CONCURRENT-CALLBACK-FALLBACK` | Force two ordered cases: (A) callback Job lock+commit at T0+179.999999s, then timeout tries Job lock at T0+180s; (B) timeout locks at T0+180s, then callback waits. | Callback-first: if `received_at < hard_deadline`, valid receipt wins once. Fallback-first at/after deadline: SYSTEM_FAULT wins once; blocked late callback cannot reverse it. Both cases: exactly one release and no duplicated reputation. |
| `RT-12-INVALID-RECEIPT` | On-time signed envelope has invalid Ed25519/context; advance to hard deadline without valid replacement. | Manager rejects invalid receipt with no immediate Job/reputation mutation; at deadline uses exactly one SYSTEM_FAULT fallback and release. |
| `RT-13-TERMINAL-LATE` | Deliver authentic late callback for a Job already finalized (COMPLETED or SYSTEM_FAULT), both fixtures. | Original terminal state and signed evidence unchanged; no additional accepted receipt/release/reputation effect. |
| `RT-14-RETRY-CALLBACK-5XX` | API is temporarily unavailable; Simulator receives two `503`/timeout failures, then `202`. | Retry due instants are failure+2s and subsequent failure+4s; exactly one durable Inbox receipt after recovered API; same signed callback bytes are resent. |
| `AUTH-01-MISSING-BAD` | Call each internal endpoint with no token, wrong token and Client session token. | Unauthenticated each time; no accepted dispatch/inbox/event or business effects. |
| `AUTH-02-WRONG-DIRECTION` | Use valid Manager dispatch token on Simulator->API callback route; valid Simulator callback token on dispatch route. | Both are rejected as `401` (receiver knows only its expected token); no Inbox/dispatch acceptance. |
| `AUTH-03-TWO-LAYERS` | Authenticated Simulator submits tampered/wrong-Worker Ed25519 receipt. | HTTP service auth passes and raw envelope can be durably inboxed, but Manager verification rejects; zero acceptance/reputation changes. |
| `AUTH-04-SECRET-BOUNDARY` | Scan runtime logs/repository/API payloads for both test tokens and Ed25519 private key; attempt DB connection from Simulator. | No secret leak; no Simulator DB access; authorized happy-path delivery still works. |

Test reports must record job/attempt/result/outbox IDs, trusted timestamp at lock and commit boundaries, fake-clock timeline, HTTP result, lease version, persisted before/after rows, authorized service identity, expected vs actual outcomes, exact test status (`PASS/FAIL/BLOCKED/NOT_RUN/ERROR`) and implementation commit SHA.

## 7. Consequences and remaining boundaries

- Compatible with the previously accepted Outbox/Inbox communication; no extra message broker or worker DB client.
- Repeated simulation and signed callbacks can occur, but unique terminal effects and original evidence remain authoritative; CPU overhead and database polling remain performance items for later measurement.
- A hard execution deadline bounds allocated-GPU exposure from missing/invalid receipts without penalizing Worker. Long simulated Job durations imply correspondingly long total execution windows by design; no additional hard cap is invented here.
- 2s scans / 30s leases are intended to support recovery and bounded dispatch latency; they are not proof of a 120s recovery result under real load.
- Bearer tokens on isolated in-host HTTP are a conscious simulation-MVP security trade-off; they do not claim confidentiality against a compromised internal network. Worker Ed25519 verification is still mandatory.
- Acceptance synchronized into `system-architecture.md` ADR-005 decision register and its runtime/security/failure-policy cross references; ADR-003/004/006, FR/NFR baselines and all `NOT_RUN` statuses are unchanged. Database schema, HTTP API contracts, ADR-007/008 and coding remain **out of scope of this decision**.

## 8. Explicit review decision (accepted 2026-10-18)

**Accepted decision:** adopt Option B and the exact parameter register in Section 2.1; deadline and pre-deadline Inbox ordering rule in Section 2.2; dispatch/callback retry and error category policy in Section 3; distinct scoped 256-bit service Bearer tokens for trusted single-host MVP HTTP in Section 4; and the 18 deterministic test *designs* in Section 6.

**Current state: ACCEPTED FOR DESIGN (2026-10-18) / 18 TEST DESIGNS APPROVED / ALL IMPLEMENTATION TESTS `NOT_RUN`.** Approval is not evidence that the runtime works, has been secured in deployment, or meets measured recovery/performance goals.
