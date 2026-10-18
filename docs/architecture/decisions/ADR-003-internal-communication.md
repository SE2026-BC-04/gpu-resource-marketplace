# ADR-003 — Internal job dispatch and signed-result delivery

**Status:** ACCEPTED — decision approved; implementation unverified  
**Decision date:** 2026-10-18  
**Decision owner:** GPU Marketplace engineering team  
**Already-approved constraints:** one-codebase modular monolith; separate Backend API, Manager and Worker Simulator runtime processes; API/Manager directly access PostgreSQL; Worker Simulator has **no** application DB access; simulation only.

## 1. Problem to solve

A Job can be allocated and moved `QUEUED -> RUNNING` even if the Manager crashes before sending the execution request. The Worker Simulator can accept a request and later crash; acknowledgments and callbacks may be lost or duplicated. Signed results must be verified by Manager, then Job finalization, GPU release and reputation effect must commit only once. We need crash recovery without introducing an external broker or letting the Worker Simulator mutate business DB state.

## 2. Alternatives evaluated

| Option | Operation | Strength | Cost / risk | Assessment |
|---|---|---|---|---|
| **A: Direct HTTP + persisted Job/attempt polling** | Manager sends HTTP after committing allocation; re-scans RUNNING Job/attempt deadlines when recovering. Simulator sends a receipt callback; API persists it. | Fewer tables, simpler initially. | Need custom reconciliation for unknown delivery, multiple races, deduplication and lost callbacks; easy to omit a failure transition. | Viable minimal fallback only if exact recovery invariants are proven. |
| **B: PostgreSQL Outbox/Inbox + asynchronous internal HTTP** | Allocate + write outbox atomically; durable dispatcher retries; callback is stored in inbox before Manager verifies and finalizes. | Durable handoffs within current PostgreSQL boundary; explicit replay/ack semantics; inspectable recovery evidence. | Additional tables, status/lease handling, cleanup and DB load. | **SELECTED — ACCEPTED**, performance remains to be measured. |
| **C: External message broker** | Broker queues jobs and results. | Mature queue tooling and fan-out. | Another deployment, access-control and failure surface for the five-person MVP; not required for existing load target. | Defer unless measurements show current approach inadequate. |

## 3. Approved communication sequence (Option B)

1. **Submit**: authenticated Client chooses one ACTIVE Listing; Backend API validates request and idempotency key, persists one QUEUED Job. Fast response does not await simulation.
2. **Allocate**: Manager picks strict FIFO head on the Listing and, in a single PostgreSQL transaction with appropriate row locks, verifies `ACTIVE` and capacity, records one GPU allocation, marks the Job RUNNING, persists stable logical `attempt_id`, and inserts an `EXECUTE_JOB` outbox event. DB commit is the authoritative allocation boundary.
3. **Dispatch**: a Manager dispatcher claims pending outbox events using short DB leases (e.g., `FOR UPDATE SKIP LOCKED`); releases DB transaction before making an authenticated internal HTTP request. A successful HTTP `202` means **accepted for execution**, not completed. Failure/restart returns the event to durable retry. Do not hold listing locks during HTTP.
4. **Simulate/sign**: the Worker Simulator receives `job_id`, `listing_id`, `worker_id`, stable `attempt_id`, simulation input and configuration; it does not read/write PostgreSQL or access Manager's protected deterministic ground truth. It simulates the requested work and signs canonical result bytes with only that Worker's private Ed25519 key. Duplicate execute requests may re-run the *deterministic simulation* using the same attempt context; physical exactly-once execution is **not** promised.
5. **Callback and inbox**: Worker Simulator calls authenticated internal Backend API receipt endpoint. API durably inserts raw signed payload, signature, context and unique `result_id`/dedup hash into a Result Inbox and returns `202` only **after durable storage**. An identical delivery may be acknowledged idempotently; reusing the same `result_id` with different bytes is a **conflict**. API does **not** make the final cryptographic/truth decision.
6. **Verify/finalize**: Manager consumes Inbox entries, checks signer registry key ID, canonical Ed25519 bytes, Worker/Listing/Job/attempt binding and the RUNNING state. In **one database transaction** it stores the one accepted signed receipt, transitions to COMPLETED or FAILED, releases the allocation exactly once, applies an eligible reputation contribution exactly once, and marks Inbox processed. A valid signature attests to signed bytes/identity, **not to ground-truth correctness**; adjudication of a retained, eligible receipt occurs later upon Client dispute.
7. **Recovery/failure**: invalid signed messages remain rejected, are audit-linked and cannot penalize a Worker automatically. If a valid terminal result cannot be obtained after a bounded policy (ADR-005 still OPEN), Manager closes the Job as `FAILED/SYSTEM_FAULT` exactly once and releases resources, with no Worker reputation penalty.

## 4. Delivery and idempotency guarantees

| Boundary | Unique identity / guard | Guarantee under durable DB availability |
|---|---|---|
| Client -> API | Client-scoped `Idempotency-Key` + request fingerprint | A retry of same logical submit returns the same created Job; same key with different request payload is conflict. |
| Manager -> Simulator | `outbox_event_id` and stable `attempt_id`; retry leases | At-least-once *delivery attempts*, no loss after allocation commit; simulator work itself may repeat. |
| Simulator -> API | `result_id` + exact signed payload hash; unique Inbox identity | Same receipt no-op; same ID with changed bytes conflict. |
| Manager finalize | Job terminal conditional update, unique accepted result/job, allocation active guard, per-Job reputation effect uniqueness | **Exactly-once persistent business effect** across repeated deliveries; not exactly-once network delivery. |

**Concurrency lock order (proposed implementation detail):** when processing Listing+Job transitions, lock Listing before Job to resolve Pause/Cancel/Allocate races consistently; finalization locks the relevant Job/Allocation plus guarded Listing adjustment in documented order. Confirm a complete lock order in Database Design; do not assume this text proves deadlock freedom.

## 5. Security and trust boundaries

- Authenticate the Manager-to-Simulator and Simulator-to-API internal HTTP calls; deny public access to the receipt endpoint. Internal transport authentication is **additional** to Ed25519 receipt verification.
- Worker private keys exist only within Worker Simulator secret storage; API/Manager hold public verification material, never signing secrets.
- Do not give Worker Simulator a SQL connection string or permission to read hidden reference outcomes. No direct communication from untrusted Browser to Worker Simulator.
- Redact service credentials, Ed25519 private keys and oracle data from logs. Tie retry/rejection logs to stable Job/Attempt/Event/Result IDs.

## 6. Failure injection tests required to verify the accepted decision

| ID | Failure injection | Exact oracle |
|---|---|---|
| `COM-01-CRASH-BEFORE-DISPATCH` | Kill Manager after allocation+outbox commit but before internal HTTP. | RUNNING allocation and outbox survive; on restart dispatch resumes same attempt; no over-allocation. |
| `COM-02-LOST-ACK` | Simulator accepts command; drop Manager acknowledgment; force retry. | Same `attempt_id`, one accepted final result, one allocation release, one reputation contribution. |
| `COM-03-DUPLICATE-CALLBACK` | Send byte-identical signed receipt twice. | Inbox deduplicates; one terminalization and one accepted result. |
| `COM-04-ID-COLLISION` | Reuse `result_id` with different signed bytes. | Reject as conflict; immutable original record unchanged; no second finalization. |
| `COM-05-CRASH-BEFORE-FINALIZE-COMMIT` | Kill Manager after Inbox persisted but before finalization commit. | Inbox remains processable; restart finalizes once and releases GPU once. |
| `COM-06-CRASH-AFTER-FINALIZE-COMMIT` | Kill Manager after commit but before Inbox work acknowledgment and retry. | Job terminal and aggregate unchanged; duplicate effect count remains zero. |
| `COM-07-INTERNAL-AUTH` | Send callback without/with invalid service credentials. | API rejects without accepted inbox item; no DB business effect. |
| `COM-08-SIMULATOR-NO-DB` | Inject Simulator without application DB credential and attempt direct DB operation. | No database access; normal execution/callback path still succeeds without DB access. |

**Evidence for each test:** code commit, DB migration, fixed fixture, artificial clock, exact crash barrier, before/after persisted rows, signed payload hash, request/callback correlation IDs, observed output and PASS/FAIL assertions. Until implementation exists, every case is **NOT_RUN**. Retry count, backoff and final deadline are intentionally **not invented** and must be decided in ADR-005.

## 7. Impact and open details

- Adds logical `execution_outbox` and `result_inbox` to the persistence model (physical schema, indexes, TTL to follow in DB design). Dispatcher and Inbox consumer remain Manager components, not new independent microservices or brokers.
- Periodic polling and short SQL transactions are used to keep the client Job submit path asynchronous. Benchmark 736 active users under the approved traffic mix; do not claim performance before measuring.
- Exact internal HTTP schema, service authentication mechanism, result canonical bytes, retry budget and recovery threshold measurement will be frozen under ADR-004, ADR-005 and API Contract.
- **Decision ACCEPTED on 2026-10-18:** Option B was explicitly approved during architecture review. The communication pattern is binding for the MVP design; detailed leases, retry budget, authentication mechanism, SQL schema, and performance verification remain separate OPEN tasks in ADR-004/ADR-005 and the design/test specifications. All `COM-01..08` implementation tests remain `NOT_RUN`.
