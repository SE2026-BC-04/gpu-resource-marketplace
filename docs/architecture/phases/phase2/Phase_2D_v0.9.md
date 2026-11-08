# Phase 2D — FIFO Scheduling and Listing Capacity (TV4) — v0.9 Deep Review

> **PR #39 alignment addendum (2026-11-07):** See final Appendix PR39-D. Existing conditional owner approvals stay in force. HEAD `44579ed84605` is a draft Phase 1 PR, not merged; no Phase 2 code authorization. Historical earlier OPEN labels are superseded only where explicitly recorded below.

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Version:** `0.9-deep-review` (extends 0.8 PR #39 alignment; approved baseline remains conditional), updated 2026-11-07  
> **Existing baseline status:** `P2D-GATE-01 = APPROVED_DESIGN_CONDITIONAL`; **new v0.9 changes:** `PROPOSED_FOR_OWNER_REVIEW / PENDING_ACK / NOT_APPROVED_FOR_IMPLEMENTATION`.  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate:** Phase 1 integration must be accepted on `main`, affected interfaces reviewed, and coding separately authorized.

> **Proposed documentation owner:** TV4 - Listings owner (`VietNguyen865`)  
**Review conclusion:** `DOCUMENTATION_REMEDIATED / 14 P2 + 3 P3 FINDINGS / INTERFACE_ACK_PENDING / TESTS_NOT_RUN` — no implementation authorization.

## 1. Goal and boundary

Design the Manager's FIFO head-of-line allocation policy on top of Phase 1 `gpu_listings` and `jobs`, preserving **Worker Listing ownership**, ACTIVE/PAUSED semantics and database transaction authority. TV4 owns this **design work package** as the original Listing domain owner; a future scheduler implementation remains Manager-owned, not an API Listing mutation path.

No advanced fair-share, backfilling, multi-Worker Job allocation, overcommit, Worker manual allocation or new endpoint is within scope.

## 2. Proposed design deliverables (TV4)

| ID | Document deliverable | Required check |
|---|---|---|
| `P2D-01` | Frozen Phase 1 Listing DTO, status, ownership and capacity handoff | Check merged PR #17 and actual `main` contracts |
| `P2D-02` | FIFO selection algorithm specification | Immutable `jobs.enqueue_seq` per Listing; no head bypass |
| `P2D-03` | `TX-ALLOCATE` / `TX-CANCEL` / `TX-PAUSE-EDIT` concurrency sequence diagrams | Listing-before-Job row lock order |
| `P2D-04` | Capacity and state invariants / error and retry behavior | No oversubscription, PAUSED blocks new admission |
| `P2D-05` | Cross-owner interface ACK for retry of an already `RUNNING` attempt after PAUSED | Owner approved `P2D-OPEN-02`; TV1/TV2/TV4/TV5 implementation-interface ACK still pending |

## 2.1. Phase 2D architecture and delivery responsibility (review, not yet approved)

**TV4 designs Listing-aware scheduling policy; Manager owns runtime execution.** Phase 2A has conditional design approval for three concurrent logical loops in one Manager process, with Scheduling as one loop. TV4 does not create a new service or a second independent Job lifecycle implementation. TV1 integrates the Scheduler; TV2 supplies DB transaction and grants; TV5 confirms Job/Attempt/Outbox handoff; TV3 confirms role/identity boundaries where affected. Phase 2A v0.9, Phase 2B v1.3 and Phase 2C v0.9 are conditionally owner-approved local review documents; their tests and cross-owner interfaces are not thereby verified. Their locally approved design revisions have not been pushed to GitHub.

### One Listing versus multiple Listings

**Existing invariant, not open for redesign:** FIFO is strictly ordered by `jobs.enqueue_seq` *within each Listing*. There is no cross-Listing global Job FIFO requirement and no permission to skip an unfittable head Job merely to fill unused GPUs.

**Approved P2D-OPEN-01 (2026-11-07):** exactly **one Listing per short `TX-ALLOCATE` transaction**, while one scheduler tick may handle several Listings in separate transactions, subject to a bounded work/time budget. This isolates contention and rollbacks across unrelated Listings. If multiple Scheduler executors ever contend, `SKIP LOCKED` may be used **only to distribute Listing claims**, never to bypass locked queued Jobs.

### Proposed algorithm and transaction boundaries

1. Obtain a candidate Listing (optional unlocked discovery is only a hint) and acquire its lock; use only an `ACTIVE` Listing after recheck under lock.
2. Select the **actual lowest `enqueue_seq` currently `QUEUED` Job** for that Listing. Acquire its Job lock after Listing; do not use Job-level `SKIP LOCKED`.
3. If no queued Job, end without mutation. If the head cannot fit `free_gpu_count = total_gpu_count - allocated_gpu_count`, end without mutating; **do not** choose the second Job.
4. In the same database transaction, update Listing reserved GPU count, mark that head Job `RUNNING`, create exactly one `allocations`, one stable `execution_attempts` and one durable `execution_outbox` event. Any failure rolls back **all** changes; no remote HTTP call under locks.
5. Release locks on commit. The independent Phase 2A dispatch loop later sends the committed Outbox event; the finalization loop later releases allocation/reputation according to TV5 contracts.
6. Other Listings can be considered in separate short transactions, even if one Listing has an unfit head. No global FIFO/fair-share SLA or hard-coded pool size/batch limit is approved. **P2D-OPEN-03 approves a configurable 2-second initial Scheduler scan interval**; the precise bounded work budget remains pending TV1/TV2/TV4 verification.

### Concurrency and PAUSED

- `TX-CANCEL`, `TX-PAUSE-EDIT`, `TX-ALLOCATE` serialize on Listing before Job; re-evaluate all predicates after locks under PostgreSQL `READ COMMITTED` as approved in Database Design §11.
- A `PAUSED` Listing rejects **new submits and allocations**; it does **not** cancel/release a `RUNNING` Job.
- **Approved P2D-OPEN-02 (2026-11-07):** PAUSE does not block bounded Outbox repair/re-dispatch for an already `RUNNING` Job. Such repair is **not** new allocation, uses the same Attempt/Outbox identity and immutable dispatch payload, and cannot extend the persisted hard deadline. Cross-owner interface ACKs are still required before implementation.
- Maintain `allocated_gpu_count == SUM(allocations.gpu_count WHERE state='ACTIVE')` across the committed DB graph. `CHECK` bounds alone do not prove aggregate reconciliation.

## 2.2. `P2D-OPEN-01` — APPROVED: one Listing per TX-ALLOCATE (2026-11-07)

| Option | Design | Trade-off |
|---|---|---|
| **A — One Listing per short transaction (recommended)** | A scheduling loop can examine multiple Listings, but each `TX-ALLOCATE` locks and mutates **one Listing** and at most its FIFO-head Job. Each transaction commits/rolls back separately. | Short lock scope; easier race/recovery tests and collaboration with TV2/TV1; no global FIFO guarantee implied. |
| B — Batch multiple Listings into one transaction | One transaction may lock and update multiple Listings/Jobs before commit. | Longer lock hold, more rollback coupling and complex cross-Listing ordering; no approved product requirement justifies it. |

**Decision P2D-OPEN-01 — APPROVED (owner, 2026-11-07): Option A.** Each allocation transaction locks and mutates exactly one Listing, and at most one FIFO-head Job; one Scheduler tick may process multiple Listings via separate transactions. At the historical instant of `P2D-OPEN-01`, the approval did **not yet** fix polling cadence, batch/work budget, DB pool size, or PAUSED replay. **Current review supersession:** `P2D-OPEN-02` later approved PAUSED replay and `P2D-OPEN-03` approved configurable initial 2s scheduling cadence. Numeric batch/work budget and DB pool sizing remain PENDING. TV2 transaction API/lock-order ACK and TV1 runtime integration remain pending; no implementation authorization.

## 2.3. Concurrency truth table — PAUSE / CANCEL / ALLOCATE (approved baseline, no new decision)

All operations that contend for the same Listing serialize by **Listing-first** locking and recheck their preconditions under the lock. PostgreSQL `READ COMMITTED` and the existing `TX-PAUSE-EDIT`, `TX-CANCEL`, `TX-ALLOCATE` contracts are authoritative; this table only makes their accepted consequences explicit.

| Race / case | Winner commits first | Required committed outcome |
|---|---|---|
| PAUSE vs ALLOCATE | `TX-PAUSE-EDIT` | Listing becomes `PAUSED`; subsequent `TX-ALLOCATE` sees `PAUSED` and creates no new allocation/Attempt/Outbox. |
| PAUSE vs ALLOCATE | `TX-ALLOCATE` | The already allocated Job remains `RUNNING`; subsequent PAUSE blocks **new** allocations but does not cancel or release existing work. |
| CANCEL vs ALLOCATE | `TX-CANCEL` | Job becomes `CANCELLED` without allocation; Scheduler must not allocate it. |
| CANCEL vs ALLOCATE | `TX-ALLOCATE` | Job becomes `RUNNING` with one Allocation/Attempt/Outbox; QUEUED-only cancellation is rejected. |
| PAUSE vs CANCEL | Either | Client can still cancel its own `QUEUED` Job when Listing is `PAUSED`; PAUSE does not automatically cancel queued Jobs. |
| RESUME vs ALLOCATE | RESUME first, then Scheduler locks/rechecks | `ACTIVE` permits allocation only for the true FIFO head and only if GPU capacity is sufficient. |
| Listing capacity edit vs ALLOCATE | Either | Recheck current reserved capacity and every QUEUED Job capacity constraint after Listing lock; no overcommit and no forbidden reduction. |

**Required PostgreSQL evidence:** independent connections with deterministic barriers; show both commit orders, before/after Listing counter, Job states, Allocation/Attempt/Outbox cardinality, and absence of partial commits. A transaction that loses a race returns a defined legal rejection or no-work outcome; it must not silently retry past a user-facing CANCEL/PAUSE decision.

### `P2D-OPEN-02` — APPROVED: PAUSED Listing and replay of RUNNING work (2026-11-07)

**Decision: Option A (owner-approved design).** PAUSE prevents `TX-SUBMIT` and new `TX-ALLOCATE`, **not** retry/repair of an already committed, still-`RUNNING` Attempt. The Outbox dispatcher may resend the existing execution command only while the persisted retry/deadline policy in ADR-005 permits. This decision clarifies an existing PAUSE invariant; it does not add an additional Job state, Allocation, Attempt, or execution service.

| Guard / action | Required design behavior |
|---|---|
| Eligibility | The Job was already `RUNNING` and has one committed Allocation, Attempt, and Outbox; `gpu_listings.status='PAUSED'` alone does not prevent repair. |
| Stable identity | Re-dispatch uses the **same** `job_id`, `attempt_id`, `outbox_event_id` and immutable dispatch payload. No new allocation, counter increment or attempt. |
| Retry timing | Preserve ADR-005 persisted `next_retry_at`, fenced lease, same logical attempt, bounded retry, `finish_due_at+10s` missing-result probe and fixed `hard_deadline_at`; PAUSE never resets/backdates/extends either deadline. |
| Termination | No new dispatch once Job is terminal or the applicable retry cutoff has passed; an already-sent stale transport attempt cannot create a second business effect. |
| Locking | Outbox claim/ACK/retry remains in **Outbox-only** short fenced transactions. Do not hold an Outbox row lock while waiting for Listing/Job; do not hold Listing/Job locks across HTTP. |
| Callback | A retry of an **existing signed callback** retains the exact original `result_id` and raw signed bytes (TV5/TV3), independently of the Manager's execution-command re-dispatch. API/Manager apply the existing Inbox/context/deadline guards. |
| Other listings | A PAUSED Listing does not block Scheduler work on independent ACTIVE Listings. |

**Cross-owner handoff is PENDING, not deemed ACKed by this decision:** TV4 confirms PAUSE semantics; TV5 the Job/Simulator same-attempt contract; TV2 the Outbox fencing and DB role permissions; TV1 the Manager runtime scheduling/dispatch boundary. If any source/consumer contract must change, create the required interphase impact record and obtain each owner ACK before code/merge.

**Negative test expectations (`NOT_RUN`):** PAUSED + RUNNING + lost ACK repairs within ADR deadline; no extra GPU reservation; deadline unchanged; PAUSED + QUEUED does not allocate; terminal/expired RUNNING does not reopen or allocate; stale lease cannot overwrite a newer lease. These expand `P2D-TX-10..12` below.

## 2.4. Required design-time test matrix (all `NOT_RUN`)

| ID | Scenario | PASS oracle |
|---|---|---|
| `P2D-TX-01` | One Listing, head Job fits | One `RUNNING` transition, one Allocation, one Attempt and one Outbox in the same commit |
| `P2D-TX-02` | Head needs 4 GPUs but only 2 free, later Job needs 1 | Neither Job allocated; no FIFO head bypass |
| `P2D-TX-03` | Two independent Listings, first blocked by unfit head | Second Listing may allocate independently; first remains unchanged |
| `P2D-TX-04` | Two concurrent scheduler sessions on same Listing | No duplicated Attempt/Allocation; reserved GPU total never exceeds capacity |
| `P2D-TX-05` | `TX-CANCEL` vs `TX-ALLOCATE` synchronization barrier | Exactly one legal outcome; cancel-first has no allocation, allocate-first rejects cancel |
| `P2D-TX-06` | `TX-PAUSE-EDIT` vs `TX-ALLOCATE` | No allocation after PAUSE wins; already RUNNING work stays valid |
| `P2D-TX-07` | Force Outbox/Attempt insert failure after counter update | Entire transaction rolled back; counters/Job/Allocation unchanged |
| `P2D-TX-08` | Restart after successful `TX-ALLOCATE` commit | One stable Attempt and Outbox, no repeat reservation; dispatch is recovered separately |
| `P2D-TX-09` | Two committed orders of PAUSE vs CANCEL, with QUEUED Job | PAUSE does not remove right to cancel QUEUED Job; no allocation or illegal transition |
| `P2D-TX-10` | PAUSED after RUNNING allocation, then missing-ACK repair dispatch | Same stable Attempt/Outbox, no new GPU reservation, deadline unchanged, once-only finalization |
| `P2D-TX-11` | PAUSED Listing with a still-QUEUED Job; dispatcher sees no committed Attempt | No new allocation, Attempt or Outbox; no RUNNING transition until RESUME |
| `P2D-TX-12` | PAUSED after prior RUNNING attempt, then terminalize Job or pass dispatch retry deadline | No new dispatch effect, second allocation, extended deadline or reopened terminal Job; stale Outbox lease cannot mutate current state |

**Verification prerequisites:** PostgreSQL 16 real concurrent sessions on a disposable test cluster; recorded Git SHA, Alembic revision, barriers, before/after rows, and `PASS/FAIL/BLOCKED/NOT_RUN`. These cases extend approved `DBTX-*` tests; they do not replace them or assert test execution.


## 2.5. `P2D-OPEN-03` — APPROVED: configurable 2-second Scheduler scan (2026-11-07)

**Context:** Phase 2A approved a separate Scheduling loop alongside Dispatch/Retry and Finalization. ADR-005 fixes a **2-second dispatch/outbox/receipt/fallback poll**, which is distinct from the Scheduler cadence now approved in `P2D-OPEN-03`. FIFO order and Listing-first transaction locking remain binding regardless of timer choice. The numeric work budget and DB resource sizing still require review by TV1 (runtime), TV2 (DB concurrency/pool), and TV4 (scheduling).

| Option | Proposed cadence | Pros / trade-offs |
|---|---|---|
| **A — Periodic Scheduler, configurable 2-second initial default (recommended)** | Every ~2 seconds when healthy, with a **bounded number of Listing attempts per cycle** and stop-aware wakeup. Interval/budget are explicit configuration, validated against measured load; never change ADR-005's distinct dispatcher timing. | Simple, reproducible, aligns an initial polling model with existing operational rhythm. More frequent DB queries than a 5-second default. |
| B — Adaptive Scheduler/backoff | Increase/decrease scan cadence based on observed queue activity, with separate idle and busy configurations. | Can reduce empty scans but raises complexity, testing burden, and starvation/timing risk for this 5-person MVP. |

**Decision P2D-OPEN-03 — APPROVED (owner, 2026-11-07): Option A.** Phase 2D adopts a **configurable 2-second initial default** for the Scheduling loop, independent of the already-approved ADR-005 2-second dispatch/receipt/deadline polling. Each scan runs with a **bounded number of Listing attempts and a bounded work/time budget**; **numeric batch size, connection-pool capacity, and exact startup scheduling semantics remain `PENDING` TV1/TV2/TV4 ACK and real-DB performance evidence**, not implicitly approved as specific values. The Scheduler must be stop-aware, prevent accidentally overlapping scans of the same loop, and avoid starving eligible Listings merely because a fixed subset is repeatedly scanned. The exact Listing iteration/progress mechanism is a subsequent interface design and must not add tables or expand scope without separate approval. Interval is a **polling default, not an execution or response-time SLA**. Do not let Scheduler saturation block Dispatch/Finalization.

**Binding safeguards:** (1) select the true head `enqueue_seq` under Listing lock; (2) avoid unbounded database work or connection exhaustion; (3) an unfit head may block only its own Listing, not all others; (4) restarting does not rely on in-memory tick state; (5) metrics/performance claims remain `NOT_RUN` until real PostgreSQL measurements; (6) no scheduler deadline/SLA is implied merely by choosing an interval. The work budget/connection pool and precise startup timing require TV1/TV2 ACK before implementation.

## 2.6. Scheduler cadence acceptance design (`NOT_RUN`)

| ID | Proposed test | Required PASS evidence |
|---|---|---|
| `P2D-SCHED-01` | Start healthy Manager with initial Scheduler cadence configured to 2 seconds | Stop-aware scans use the configured initial interval; no claim of exact hard real-time tick or Job SLA |
| `P2D-SCHED-02` | Change the validated Scheduler interval via configuration in a test environment | Scheduler follows the supported configuration without changing ADR-005 dispatch/receipt/deadline 2-second cadence |
| `P2D-SCHED-03` | Seed more eligible Listings than per-cycle budget, including a Listing blocked by FIFO head | Each cycle remains bounded; independent eligible Listings are eventually considered, and the blocked Listing does not prevent progress elsewhere |
| `P2D-SCHED-04` | Slow/lock a Scheduler DB transaction while Dispatch and Finalization have due work | No overlapping scheduler scans or exhaustion of shared DB connection budget; Dispatch/Finalization continue within their established design constraints |
| `P2D-SCHED-05` | Kill/restart Manager between scan cycles and repeat with a PAUSED Listing | Scheduling derives eligibility from persisted DB state, performs no duplicate allocation, and does not allocate new Job on PAUSED |

All are design-only (`NOT_RUN`). TV1/TV2/TV4 must agree the work/time budget and database connection limit before implementation. Tests must record Git SHA, Alembic head, fixture size, interval/budget settings, measured scan behavior, and PostgreSQL before/after state; a 2-second polling setting does **not** itself demonstrate any latency/performance SLA.

## 3. Proposed scheduling algorithm (restatement of approved design)

1. Manager finds an eligible Listing and locks its row first; multiple scheduling instances may distribute **Listing** claims using `SKIP LOCKED` if needed.
2. Under that Listing lock, select the *earliest still-QUEUED Job* by ascending `enqueue_seq`. Never apply `SKIP LOCKED` to skip a locked Job head. If the head is too large for free capacity, do **not** schedule a smaller later Job.
3. Reject allocation when Listing is `PAUSED`, or when `requested_gpu_count > free capacity`. Re-evaluate all predicates after acquiring locks; trust persisted DB state.
4. Atomically increment `allocated_gpu_count`, transition head Job to `RUNNING`, insert one `allocations`, `execution_attempts` and stable `execution_outbox` row, then commit. A partial commit is invalid.
5. API `TX-CANCEL` and Manager `TX-ALLOCATE` compete under **Listing then Job**: cancel-first -> `CANCELLED` and no allocation; allocate-first -> `RUNNING` and queued-only cancel rejected.
6. On subsequent finalization, Manager releases the single allocation and decrements the Listing count once. PAUSED does not interrupt an already `RUNNING` Job; bounded retry of the **same already-committed Attempt** is permitted under approved `P2D-OPEN-02`, subject to ADR-005 and cross-owner interface ACK before implementation.

## 4. Invariants and scenarios

- `0 <= allocated_gpu_count <= total_gpu_count`, with `allocated_gpu_count == SUM(ACTIVE allocations.gpu_count)` for the Listing after each committed transaction.
- No reducing `total_gpu_count` below the current reserved count **or** any still-QUEUED Job requirement as specified in Database Design.
- PAUSED stops new submission and allocation while already RUNNING work remains valid; Resume permits later admission and scheduling under the same rules.
- `submitted_at`/UUID ordering cannot replace `enqueue_seq`; rolled-back sequence gaps are harmless.
- Scheduling does not use browser-side state, sleeps or network calls while holding DB domain locks.

## 5. Cross-phase handoff and test design

TV2 validates PostgreSQL lock/migration/transaction semantics; TV5 validates Job cancellation, immutable FIFO and Simulator retry; TV1 validates Manager orchestration; TV3 reviews role/owner isolation where affected. Treat a changed Listing or Job contract as interphase impact requiring source and consumer ACKs.

- Plan `DBTX-02-PAUSE-SERIALIZE`, `DBTX-03-FIFO-HOL`, `DBTX-04-CAPACITY-RACE`, `DBTX-05-CANCEL-ALLOCATE`, `DBTX-06-ATOMIC-COMMIT`, and Phase 2 subset of `E2E-05` with real PostgreSQL concurrent sessions.
- **Docs exit:** acceptance matrix, sequence diagrams, race plan, PAUSED replay decision status with named reviewers. **Runtime status:** `NOT_RUN`.

## Approved design references

- [SRS](../../requirements.md), [FR](../../functional-requirements.md), [NFR](../../non-functional-requirements.md).
- [System Architecture](../system-architecture.md), [Module Design](../../design/module-design.md), [Database Design](../../design/database-design.md), [API Contract](../../design/api-contract.md), [Test Design](../../design/test-design.md).
- [ADR-001 to ADR-008](../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), ADR-004 (signed result) and ADR-005 (retries and deadlines).
- [Phase 1E](phase1e_job_submission_queue.md), [GPU-005-B reference proposal](phase1e_gpu005_reference_technical_specification.md), [Phase 2 readiness](../../development/phase2_readiness_and_handoffs.md), [Phase 2 decisions](../../development/phase2_decision_register.md) and [Phase 2 test plan](../../design/phase2_test_and_acceptance_plan.md).

Only the existing approved baselines are normative. Phase 2D holds `APPROVED_DESIGN_CONDITIONAL`; `P2D-OPEN-01` (one Listing per transaction), `P2D-OPEN-02` (PAUSED transport replay), and `P2D-OPEN-03` (configurable 2-second Scheduler scan) are **APPROVED design decisions**; numeric work/batch budget and pool size remain `PENDING`. Phase 2A/2B/2C have only conditional design approvals. This document does not authorize coding or execute any Phase 2 tests (`NOT_RUN`).


### Review ledger, 2026-11-07 (documentation only)

- `P2D-OPEN-01`: **APPROVED** — one Listing per `TX-ALLOCATE`.
- `P2D-OPEN-02`: **APPROVED** — PAUSED permits bounded re-dispatch of the already `RUNNING` Attempt, no new allocation/deadline extension.
- `P2D-OPEN-03`: **APPROVED (Option A)** — configurable initial 2-second Scheduler scan with bounded per-cycle Listing work; numeric budget and resource sizing remain `PENDING`.
- `P2D-GATE-01`: **APPROVED_DESIGN_CONDITIONAL (owner, 2026-11-07)** — approve architecture/TV4 design scope with remaining interface, test, resource sizing and Phase 1 gates explicitly `PENDING`; no implementation authorization.
- Status: `APPROVED_DESIGN_CONDITIONAL`; owner and cross-owner ACKs, tests and Phase 1 baseline readiness remain outstanding; this record does not authorize code, repository changes or migration.


## 6. Conditional-approval readiness review — `P2D-GATE-01` (`APPROVED_DESIGN_CONDITIONAL`)

**Completed design decisions:** `P2D-OPEN-01` (one Listing per TX), `P2D-OPEN-02` (PAUSED permits retry of an already RUNNING Attempt), and `P2D-OPEN-03` (configurable 2-second Scheduler scan). These approvals do not grant implementation permission.

| Remaining gate | Required owner/verification |
|---|---|
| Scheduling loop interface and bounded Listing scan strategy, including progress across Listings | TV4 + TV1; no Job-head bypass or accidental starvation |
| `TX-ALLOCATE` transaction/locking and reconciliation with `TX-CANCEL`/`TX-PAUSE-EDIT` | TV2 + TV4 + TV5; PostgreSQL multi-connection barriers and `DBTX-*` / `P2D-TX-*` tests |
| Dispatcher retry while Listing PAUSED and Outbox fencing | TV1 + TV2 + TV4 + TV5; stable Attempt/event/lease/immutable payload |
| Scheduler pool/executor budget and concurrency with other Manager loops | TV1 + TV2; `P2D-SCHED-*` evidence |
| Phase 1 baseline and interphase impact acknowledgments | Accepted `main` Git SHA/Alembic head; source owner and each affected consumer owner ACK |
| Implementation tests | `NOT_RUN` for all Phase 2 scheduling/concurrency tests; no PASS claimed by docs |

**Owner decision, 2026-11-07:** `P2D-GATE-01 = APPROVED_DESIGN_CONDITIONAL` (Option A). The Phase 2D design direction and the three approved decisions are accepted, while all cross-owner interface, resource-sizing, PostgreSQL verification, interphase ACK and baseline gates in the table above remain `PENDING`. This approval does **not** authorize code, GitHub changes, migration, or runtime activation.

## Appendix PR39-D (2026-11-07): FIFO, Listing races and planned key rotation

**Status:** `DESIGN-SUPPLEMENT / CONCURRENCY EVIDENCE NOT_RUN / NO CODE AUTHORIZED`.

### D1. Inherit proven Phase 1 semantics

Owner decision on PR #39 explicitly resolves the earlier Submit/PAUSED ambiguity: for a **retained** `(client_id, idempotency_key)` and identical normalized body, TX-SUBMIT returns the original Job with HTTP 200 even if the Listing is now PAUSED. Changed body -> existing 409 conflict; new key -> ACTIVE and guarded admission required. Phase 2 should not reopen this as an unapproved contract change. This is distinct from `P2D-OPEN-02`: a PAUSED Listing permits repair dispatch of an *already RUNNING* Attempt but not a new allocation.

TV4's independent PR #39 review still finds missing **barrier-controlled Submit vs Pause/Resize tests in both commit orders**. Treat this as Phase 1 acceptance evidence gap (not a demonstrated implementation failure), and reuse the test harness for the more demanding Phase 2 Pause/Cancel/Allocate races.

### D2. Scheduler fairness without violating strict per-Listing FIFO

- Default scan cadence is **2 seconds configurable** (`P2D-OPEN-03` owner-approved), not a 2-second job-start SLA. Keep one Listing in each allocation transaction (`P2D-OPEN-01`).
- Within a locked ACTIVE Listing, choose the smallest queued `enqueue_seq`; do not use `FOR UPDATE SKIP LOCKED` on the Job head and then run a later smaller Job. If head needs more GPUs than free capacity, do not allocate later Jobs from the same Listing.
- Avoid whole-system starvation: use a **bounded listing batch** and a rotating stable cursor/fair round-robin over Listings across scheduler ticks. Continue to other Listings when one head is capacity-blocked; do not loop hot on a single blocked head.
- Lock order remains Listing -> Job; PAUSED and Cancel/Allocate transactions recheck current state after their locks. Outbox dispatch retry does not allocate again, and must not acquire a new Listing reservation.
- The concrete `listing_scan_budget`, DB pool/executor budget and cross-Listing cursor details are proposed, to be chosen and ACKed by TV1/TV2/TV4 after load testing; do not invent a performance guarantee.

### D3. Planned key rotation vs allocation race

The approved planned K1->K2 policy waits for related RUNNING work to quiesce. A **race-safe operational recipe to review** is: pause all of that Worker's relevant Listings using existing Listing state transitions; drain RUNNING attempts to terminal/timeout; acquire Listing locks in a stable order and verify there is no RUNNING attempt before controlled key retirement/activation; confirm K2 signing material is provisioned before resuming Listings. If checks fail, do not rotate and do not resume automatically. TV2/TV3/TV4/TV5 must review lock order and role permissions; this is not yet a validated SQL protocol.

### D4. Required two-session tests

| ID | Race | PASS condition |
|---|---|---|
| `P2D-RACE-01` | Pause commits before Allocate | zero allocation and no RUNNING transition |
| `P2D-RACE-02` | Allocate commits before Pause | one allocation, existing RUNNING Attempt remains retryable |
| `P2D-RACE-03` | Cancel commits before Allocate | CANCELLED, no capacity delta/outbox/attempt |
| `P2D-RACE-04` | Allocate commits before Cancel | RUNNING, Cancel conflict, exactly one reservation |
| `P2D-RACE-05` | two Managers allocate same head | one RUNNING/Attempt/Outbox; allocated count equals active allocations |
| `P2D-RACE-06` | head oversized, later Job fits | no bypass of FIFO head on same Listing; other Listing still progresses |
| `P2D-RACE-07` | rotation races allocation | no in-flight job bound to unavailable key; no deadlock |
| `P2D-RACE-08` | same-key TX-SUBMIT after PAUSED | original Job HTTP 200; new key remains rejected |

All are planned against **real disposable PostgreSQL**, not PASS evidence. Keep Phase 1 Submit/Resize race on PR #39 as a separately tracked acceptance action.

## 7. Deep-review technical closure — v0.9 (`PROPOSED_FOR_CROSS_OWNER_ACK`)

> This section **documents and narrows the already-approved design** rather than changing FIFO, DB schema, API, ADR-005 or service topology. Where an exact port/signing-key readiness/pool-budget policy is still undecided, it is a **proposal requiring explicit ACK/owner disposition**, not a new approved requirement. Phase 2D remains `APPROVED_DESIGN_CONDITIONAL`; no Phase 2 runtime test was executed to author this document.

### 7.1. Authoritative baseline and separation of responsibilities

| Item | Verified evidence/baseline | Boundary of that evidence |
|---|---|---|
| PR #39 | [`GPU-INT-01` PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39), reviewed HEAD `44579ed846051dee9000078e1afd7e8ea62e7358`; **Draft, unmerged** at review | Phase 1 Auth → Listing → Submit → View → Cancel, not Phase 2 `TX-ALLOCATE` or Scheduler |
| Listing implementation | `backend/src/gpu_marketplace/listings/service.py`: Listing-first lock for PATCH/Pause/Resume, hardware lock on nonterminal Jobs, downsize check against reserved count and max still-QUEUED demand | No Manager allocation API exists in this file; do not retrofit allocation into Listing routes |
| PostgreSQL Listing adapter | `backend/src/gpu_marketplace/repositories/listings.py`, via merged #31; SQLAlchemy `READ COMMITTED` UoW and D7 guard | Must not infer Manager grants or native `session_user` proof from this API adapter; separate role verification is pending |
| Phase 1 TX-SUBMIT | `backend/src/gpu_marketplace/repositories/job_submit.py` on #39: Listing `FOR UPDATE`; replay existing retained key/body even after PAUSED; creates Job+reference transactionally | New API Job submission does **not** allocate GPU, create Attempt/Outbox or guarantee execution |
| Phase 2D code/runtime | **NOT_IMPLEMENTED / NOT_RUN in #39** | PR #39's CI (4 jobs successful) cannot be claimed as Phase 2 allocation or concurrency PASS |
| Owner approvals | `P2D-OPEN-01/02/03`, `P2D-GATE-01`, Phase 2A/2B/2C conditional review | Precise Python ports, SQL, pool sizing, key-rotation locking, reviewer ACKs remain PENDING |

**Ownership freeze (no duplicate implementation):** TV4 owns the *pure policy and FIFO correctness oracle* and presents a design/port to TV1; TV2 owns the PostgreSQL `TX-ALLOCATE` repository/UoW, locks, grants, constraints and rollback semantics; TV1 owns the Manager Scheduling loop, executor, bounded scan and integration; TV5 owns Job/Attempt/Outbox consumer invariants and final release; TV3 owns Worker key readiness/rotation security policy. A shared repo import does not move transaction ownership from Manager to the public API. Final code-file ownership/PR sequencing is `PENDING_ACK` among TV1/TV2/TV4/TV5; do not write competing scheduler or allocation services in parallel without agreement.

### 7.2. Candidate selection, fairness and scan progress (`PROPOSED_INTERFACE`)

**Separate two notions of FIFO:** (a) *within one Listing*, strict `enqueue_seq` ordering is binding; (b) *among Listings*, no global arrival-order guarantee exists. Fair progress among independent Listings is a scheduler liveness goal, not permission to violate (a).

Proposed bounded scanning, subject to TV1/TV2/TV4 ACK:

1. Discover candidate **Listing IDs** in a stable order (e.g. `(gpu_listings.id)` ascending). A cursor records the last **inspected Listing**, not the last allocated Job. Continue after it and wrap at the end. It is a volatile optimization; never the authoritative business state.
2. Bound both `max_listings_per_cycle` and total time/DB executor use per cycle. These are **not assigned numerical values here**; obtain a measured capacity/pool budget from TV1+TV2 before runtime implementation. A 2-second default is polling configuration only, not a start-time SLA or a promise to finish scanning the entire Listing table every tick.
3. Every candidate gets its **own short `READ COMMITTED` `TX-ALLOCATE`**. The transaction re-reads `ACTIVE`, Job head and available capacity under Listing lock; an unlocked query or stale cursor is **never** an allocation authorization.
4. If a Listing lock is already owned, a `SKIP LOCKED` Listing-only claim may move the current scan onward **without trying to skip that Listing's FIFO Job**. A skipped Listing must remain eligible on later passes. Never use Job-level `SKIP LOCKED`, `OFFSET` on locked queue candidates, `ORDER BY submitted_at/UUID` or choose a later fit Job.
5. An unfit FIFO head produces **`BLOCKED_CAPACITY`** for that Listing and no mutation; the scan continues to other Listings. After a successful one-head allocation, commit and move on; another Job from the same Listing can be considered in a later separate transaction/cycle.
6. On restart, rebuild eligibility from database rows and recover the cursor conservatively (a fresh scan is permitted). No in-memory cursor, race winner, lease or local clock authorizes duplicate reservation. Record `listing_id`, `head_job_id`, `enqueue_seq`, reason, cycle ID and counts in redacted observability logs (no oracle/secret data).

**Design caution:** stable iteration with continuous writes and contended Listings does not by itself prove a bounded-wait guarantee. Acceptance must show observed progress with seeded `listings > cycle_budget`, blocked/PAUSED Listings and repeated cycles. Do not invent absolute fairness latency or new persistent scheduler cursor table.

### 7.3. Single UoW TX-ALLOCATE and proposed result port

The following is **pseudocode**, not executable SQL or a new frozen Python signature:

```text
allocate_one_listing(listing_id) -> AllocationDecision
  one TV2 native gpm_manager_app Session / one READ COMMITTED UoW
  begin; lock Listing[listing_id] before querying or locking any Job
  re-read Listing status and allocated/total capacity; require ACTIVE
  select first still-QUEUED Job by enqueue_seq ASC LIMIT 1 FOR UPDATE
      (NEVER SKIP LOCKED on Job rows)
  if none: commit no-op -> EMPTY_QUEUE
  if head GPUs > total - allocated: commit no-op -> BLOCKED_CAPACITY(head_id)
  trusted t = clock_timestamp() AFTER required locks
  conditional update Listing reserved_gpu_count += head.requested_gpu_count
  conditional update exact Job QUEUED -> RUNNING, started_at=t
  insert exactly one active Allocation for Job; one stable Execution Attempt
  insert one EXECUTE_JOB Outbox event, immutable dispatch payload and due time
  persist finish_due_at=t+duration_seconds and hard_deadline_at=finish_due_at+120s
  commit all changes ATOMICALLY; return ALLOCATED(job_id,attempt_id,event_id)
  any failed insert/guard -> rollback entire UoW; NO remote HTTP inside DB TX
```

**Proposed result categories** to prevent competing implementations: `ALLOCATED`, `EMPTY_QUEUE`, `BLOCKED_CAPACITY`, `INACTIVE_LISTING`, `LOCK_BUSY`, `DEPENDENCY_UNAVAILABLE` and `COMMIT_OUTCOME_UNKNOWN`. Typed data may include `listing_id`, `job_id`/`attempt_id`/`outbox_event_id` only when safely known. TV1+TV2+TV4+TV5 must approve names/types, exception-to-outcome mapping and whether each *no-op* completes an explicit commit or rollback; until then the interface is `PENDING_ACK`.

**Mandatory correctness guards:** `jobs.id`, `jobs.listing_id`, `jobs.worker_id` remain immutable; one Job has **at most one** Allocation, Attempt and EXECUTE_JOB event (`UNIQUE`/FK as specified by Database Design); `allocated_gpu_count` reflects `SUM(active allocations.gpu_count)` after commit; no caller may open a second Session to finish an in-flight partial transaction. Do not hand a live ORM entity/locked Session across `asyncio.to_thread`/executor or across TV1/TV2 service boundaries. The short DB UoW is owned entirely within one synchronous worker call.

**Commit uncertainty:** a confirmed rollback can be retried only by a fresh DB read and contract-approved bounded policy. An **unknown COMMIT outcome** (lost acknowledgement/connection, PostgreSQL `40003`, unknown SQLSTATE) is **not** permission for a blind re-allocation. Reconcile committed rows from a new trusted Session using Job/Allocation/Attempt/Outbox uniqueness. If the outcome remains uncertain, fail closed and surface safe operational evidence; do not return `ALLOCATED` without a reliable committed state and do not advance capacity twice. Mapping and safe retry budget are `PENDING_ACK` with TV1/TV2/TV5, while the no-blind-retry invariant is inherited from #39.

### 7.4. Interaction with Listing edit, Cancel, Dispatch and Finalization

| Interaction | Required guard | Business effect |
|---|---|---|
| `PATCH` hardware versus new allocation | Hardware changes require **no** `QUEUED` or `RUNNING` Job; effective no-op hardware PATCH may proceed | Scheduler takes the same Listing lock; hardware change cannot silently invalidate an already accepted Job |
| Reduce Listing total capacity | New total cannot fall below `allocated_gpu_count` **or** maximum demand of still-QUEUED Jobs | Check after Listing lock. If both fail, existing API error priority gives `LISTING_CAPACITY_BELOW_ALLOCATED` precedence |
| `TX-CANCEL` vs `TX-ALLOCATE` | Both Listing → Job; recheck QUEUED after lock | Cancel-first yields CANCELLED/no allocation; allocate-first yields RUNNING and cancellation conflicts |
| `TX-PAUSE-EDIT` vs `TX-ALLOCATE` | Both Listing-first, current status rechecked | PAUSE-first gives zero new reservation; allocate-first preserves old RUNNING attempt; PAUSED cannot cancel it |
| PAUSED + existing retained Submit key/body | Phase 1 approved replay HTTP 200, even if currently PAUSED | No new Job, reference, allocation or Outbox from replay |
| PAUSED + old RUNNING Outbox | TV1/TV2 dispatcher may resend only the **same** Attempt/event/payload under ADR-005 | No second reservation, hard deadline extension or job reopening |
| Manager Finalization / timeout | TV5/TV2 take Listing → Job → Allocation … in the approved order | GPU release and counter decrement **exactly once**; no stale in-memory scheduler count |
| Planned key rotation | TV3 owns key policy. Existing PAUSE + drain RUNNING can be used as proposed quiescence mechanism | Must avoid new allocation with unavailable signing key; precise multi-Listing lock/key-readiness protocol `PENDING_ACK` |

**Outbox fencing nuance:** Outbox claim/ACK/retry is its own short **Outbox-only** DB transaction. Never keep an Outbox lock and then acquire a Listing/Job lock (or vice versa) across a network call. A stale dispatch call may still arrive; the Simulator checks Attempt/request identity and the API/Manager enforce no second business effect. `lease_version` fences DB state writes by a stale dispatcher; it does **not** cancel an already sent HTTP request.

**Signer readiness is an unresolved cross-owner input:** No new status/table/endpoint is approved solely to solve Worker key rotation. TV3+TV5 must define how the Simulator can sign for the selected Worker and how TV2/TV4 safely determine readiness or fail closed **without exposing private keys or reading the protected reference**. Absent a reviewed policy, mark the provisioning/rotation-dependent allocation acceptance tests `BLOCKED`, rather than silently adding a runtime RPC inside the `TX-ALLOCATE` lock.

### 7.5. Required two-session and bounded-scheduler evidence (additional test designs; `NOT_RUN`)

Existing `P2D-TX-01..12`, `P2D-RACE-01..08`, `P2D-SCHED-01..05`, `DBTX-*` and `API-LIST-*` remain authoritative. The extra cases below target **uncovered evidence** without changing existing oracles. Run on a **safety-marked disposable PostgreSQL 16 cluster**, with separate committed state snapshots, two or more native runtime-role sessions, test barrier(s) and a controlled trusted DB clock where time edges matter.

| New test ID | Injection | PASS oracle; every row remains `NOT_RUN` |
|---|---|---|
| `P2D-DRT-01` | Freeze `submitted_at`, submit two Jobs via proper TX-SUBMIT lock at different accepted orders | `enqueue_seq` alone chooses first admitted queued Job; UUID order/timestamp ties cannot reverse FIFO |
| `P2D-DRT-02` | Hold the Listing lock via an authorized Pause/Cancel/EDIT transaction; race a scheduler scan, then release its barrier | Scheduler waits/skips **only the Listing claim** and never selects a later QUEUED Job via Job `SKIP LOCKED`; after lock release it rechecks the true head |
| `P2D-DRT-03` | Queue head needs 4 GPUs with 2 free and later needs 1; another Listing has fitting head | Both Jobs on blocked Listing remain QUEUED, other Listing progresses, no phantom capacity delta |
| `P2D-DRT-04` | Cancel current FIFO head before Scheduler lock; inspect next cycle | Cancelled head is excluded; next earliest still-QUEUED Job may allocate if capacity permits, with one set of child records |
| `P2D-DRT-05` | Inject constraint failure after Listing counter/Job status write | Zero partial Allocation/Attempt/Outbox/Job RUNNING/counter effects after rollback |
| `P2D-DRT-06` | Drop COMMIT ACK after durable TX-ALLOCATE success, then retry orchestration | Reconciliation finds same Job/Attempt/Outbox/Allocation; no second reservation or new event |
| `P2D-DRT-07` | PAUSE commits just after allocation, then dispatch 202 lost | Re-dispatch same event/Attempt without another counter delta or deadline extension; eventual final effect once |
| `P2D-DRT-08` | Competing UPDATE/PATCH capacity reduction vs allocation in both commit orders | Existing Listing capacity/queued max guards respected; no allocated count > total |
| `P2D-DRT-09` | Hundreds of Listings with a bounded scan and blocked head at beginning; restart scanner | Per-cycle budget respected, eligible later Listing observed within tested fair passes, no duplicate allocation after restart |
| `P2D-DRT-10` | Saturate slow SQL worker calls while dispatcher/finalizer due | Scheduling does not monopolize shared connection pool/executor; no deadlock/starvation under agreed budget |
| `P2D-DRT-11` | Two independent Manager scheduler sessions claim same Listing simultaneously | At most one successful allocation per unique queued head; no overcommit or duplicate Attempt/Outbox |
| `P2D-DRT-12` | Planned K1→K2 rotation while queued jobs and running attempts exist | Key quiescence policy and new-allocation handling match **separately approved** TV3/TV5 signer-readiness contract; `BLOCKED` until ACK |
| `P2D-DRT-13` | Manager crash before and after allocation COMMIT; restart | Before: no side effects; after: exactly one persisted allocation/Attempt/Outbox and one eventual dispatch |
| `P2D-DRT-14` | Native API role attempts Manager-only TX-ALLOCATE; native Manager role runs legal allocation | API allocation writes denied; authorized Manager transaction behaves per contract; no owner/SET ROLE bypass |
| `P2D-DRT-15` | Stale Outbox dispatcher lease after new fencing claim | Old worker cannot ACK/modify new lease, and no duplicate business allocation/finalization occurs |

**No execution claim:** all `P2D-DRT-01..15` are newly authored **test designs**, `NOT_RUN`; they are neither a claim that CI on #39 ran these cases nor proof of performance/latency. Recording `BLOCKED` for a missing signer policy is a correct test outcome, not permission to weaken the guard.

### 7.6. Cross-owner ACK matrix and implementation-entry gates

| Interface/gate ID | Source/consumer decision to record | Required reviewers | State |
|---|---|---|---|
| `D-IF-01` | Pure FIFO policy and allocation result categories/fields, no duplicated scheduler | TV1 + TV2 + TV4 + TV5 | `PENDING_ACK` |
| `D-IF-02` | One synchronous, bounded UoW + native Manager role/ACL + lock/commit uncertainty | TV1 + TV2 + TV4 | `PENDING_ACK` |
| `D-IF-03` | Listing ID scan/cursor + Listing-only SKIP LOCKED and cross-Listing progress | TV1 + TV2 + TV4 | `PENDING_ACK` |
| `D-IF-04` | Scheduler 2s config, work/time budget, executor/DB pool and health metrics | TV1 + TV2 + TV4 | `PENDING_PARAMS` |
| `D-IF-05` | PAUSED existing RUNNING dispatch repair (same Attempt/event/lease) | TV1 + TV2 + TV4 + TV5 | `PENDING_ACK` |
| `D-IF-06` | Cancel/Pause/Capacity edit vs TX-ALLOCATE barriers and error mapping | TV2 + TV4 + TV5 | `PENDING_ACK` |
| `D-IF-07` | Worker key readiness, planned rotation quiescence and emergency incident policy | TV2 + TV3 + TV4 + TV5 | `PENDING_ACK / OWNER_DECISION_REQUIRED` |
| `D-IF-08` | Allocation release/finalization/timeout counter reconciliation and retry | TV1 + TV2 + TV4 + TV5 | `PENDING_ACK` |
| `D-IF-09` | Phase 1 PR #39 audit, R3 Submit-Pause/Resize barrier and baseline acceptance | TV1 + TV2 + TV4 + TV5 | `PENDING_PHASE1_GATE` |

**No Phase 2 code gate is opened by this document.** Before implementation: (i) Phase 1 accepted `main` SHA + single Alembic head + role setup, including disposition of PR #39's actual open findings; (ii) TV1/TV2/TV4/TV5 ACK on the concrete `allocate_one_listing` port and tested lock/commit boundary; (iii) resolved/explicitly gated key signer readiness with TV3/TV5; (iv) bounded scheduler work/pool parameters and tests agreed; (v) separate leader authorization to code Phase 2. Before merge: real PostgreSQL barriers and CI/E2E evidence at exact implementation SHA, all intended `P2D-TX/RACE/SCHED/DRT` tests run with no critical `SKIPPED/BLOCKED`, independent human review, owner approvals and no regressed Phase 1 semantics.

**Evidence log template:**

```text
Phase 2D test ID:
Repo/PR SHA and Alembic version:
Native session_user / current_user:
Fixture Listing, FIFO head enqueue_seq, active Allocation SUM:
Barrier steps; first/second COMMIT order:
Before and after Listing/Job/Allocation/Attempt/Outbox rows:
Observed vs expected response/status and timed scans:
CI/run URL and disposition PASS/FAIL/BLOCKED/NOT_RUN:
Owner/consumer ACKs and remaining gaps:
```

### 7.7. Change-control and version ledger

- **Preserved (owner-approved):** strict per-Listing FIFO, Listing-first Job locking, one Listing per `TX-ALLOCATE`, PAUSED RUNNING dispatch repair, configurable 2s scan, 18 total database tables, 5 runtime services, immutable Job and Attempt identities.
- **Clarified in v0.9:** split TV1/TV2/TV4/TV5 ownership, proposed scan/cursor semantics, bounded executor limits, typed allocation outcomes, commit-unknown reconciliation, stale Outbox fencing, signer readiness interface and deterministic evidence.
- **Still undecided:** concrete adapter signature/port, numerical budget/pool limit, complete key-rotation SQL and separate compromised-key response, exact `LOCK_BUSY`/`DEPENDENCY_UNAVAILABLE` retry policy. Preserve as `PENDING` until source/consumer ACK and any required owner change control.
- **Runtime status:** `NOT_RUN` for all Phase 2D tests; PR #39's Phase 1 CI evidence does not transfer to Phase 2.
