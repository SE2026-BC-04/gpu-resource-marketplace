# Phase 2D — FIFO Scheduling and Listing Capacity (TV4) — v0.9 Deep Review

> **Current review snapshot (2026-11-19):** Phase 1 PR #39 is merged; accepted `main` is `bee832eaf5463df20f6c6815174322871eb6685a` (see §7.1). TV1 reviewed PR #48 @ `b3991189f0d9f543013e035b3a0637bd9a62be77` and returned `ACK_WITH_ACTIONS / HOLD DOCS GATE`. This revision addresses that request; it still requires exact-HEAD cross-owner ACKs and a separate leader merge decision. It is not coding authorization.

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Version:** `0.9-docs-review-20261119-r2` (stable filename retained; approved baseline remains conditional), updated 2026-11-19
> **Existing baseline status:** `P2D-GATE-01 = APPROVED_DESIGN_CONDITIONAL`; **new v0.9 changes:** `PROPOSED_FOR_OWNER_REVIEW / PENDING_ACK / NOT_APPROVED_FOR_IMPLEMENTATION`.  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate:** self-review and revise design → docs PR/cross-review → leader decision and merge docs → implementation by task. No independent policy, application/test code or runtime activation before the applicable docs/dependency gates are approved.

> **Proposed documentation owner:** TV4 - Listings owner (`VietNguyen865`)  
**Current review conclusion:** `LEAD_ACK_WITH_ACTIONS_ADDRESSED / TV3_ACK_WITH_ACTIONS_FOR_D-IF-07_ADDRESSED / EXACT_HEAD_CROSS_REVIEW_PENDING / HOLD_DOCS_GATE / PHASE2_RUNTIME_NOT_RUN`. TV3's exact-HEAD review was scoped to signer readiness; its actions are recorded below and in §7.9. This is not whole-PR L2 approval.

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

**TV4 designs Listing-aware pure policy; Manager owns runtime execution.** TV1 owns the Scheduler loop, bounded Listing scan, executor/configuration and integration. TV2 owns `TX-ALLOCATE`, its native DB Session, Worker/Listing/Job locks, SQL and atomic effects. Under those locks TV2 selects the authoritative FIFO-head Job by `enqueue_seq` and gives TV4's pure policy only an immutable scalar snapshot; TV4 opens no Session and performs no database mutation. TV5 confirms Job/Attempt/Outbox and release semantics; TV3 owns signer/key security. Current pushed design references: Phase 2A [#47 @ `001619d`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/47), Phase 2B [#46 @ `0ca059c`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46), Phase 2C [#49 @ `f3edb94`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49), and Phase 2E [#50 @ `edb247f8`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/50). Phase 2C blob at #49 HEAD `f3edb94d7f11a5759d8308e64c17927ce947af19`: `a869dd7d4006981ac0d2478a2fb3b684f1f1a157`. Their conditional directions and technical ACKs do not by themselves close independent L2 review or authorize code.

### One Listing versus multiple Listings

**Existing invariant, not open for redesign:** FIFO is strictly ordered by `jobs.enqueue_seq` *within each Listing*. There is no cross-Listing global Job FIFO requirement and no permission to skip an unfittable head Job merely to fill unused GPUs.

**Approved P2D-OPEN-01 (2026-11-07):** exactly **one Listing per short `TX-ALLOCATE` transaction**, while one scheduler tick may handle several Listings in separate transactions, subject to a bounded work/time budget. The current TV1/TV2 contract uses an unlocked Listing locator and bounded lock wait; `SKIP LOCKED` is not used for Listing or FIFO-head Job locks. Outbox claim is a separate independent-row use.

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

All operations that contend for the same Listing serialize on that row and recheck their preconditions. Under conditional D-18, allocation first takes a Worker advisory lock; applicable row locks still use Listing before Job. The source lock-order supersession and exact ACKs remain pending.

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

**Context:** Phase 2A approved a separate Scheduling loop alongside Dispatch/Retry and Finalization. ADR-005 fixes a **2-second dispatch/outbox/receipt/fallback poll**, distinct from Scheduler cadence `P2D-OPEN-03`. FIFO and Listing-before-Job row locking remain binding; conditional D-18 adds the Worker advisory lock before allocation's Listing lock. Numeric budgets remain pending TV1/TV2/TV4 review.

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

1. Manager locates an eligible Listing without locking; allocation acquires the Worker shared advisory lock, then its Listing row with a bounded wait. Current TV1/TV2 design uses no Listing `SKIP LOCKED`.
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

- [SRS](../../../requirements.md), [FR](../../../functional-requirements.md), [NFR](../../../non-functional-requirements.md).
- [System Architecture](../../system-architecture.md), [Module Design](../../../design/module-design.md), [Database Design](../../../design/database-design.md), [API Contract](../../../design/api-contract.md), [Test Design](../../../design/test-design.md).
- [ADR-001 to ADR-008](../../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), ADR-004 (signed result) and ADR-005 (retries and deadlines).
- [Phase 1E](../phase1e_job_submission_queue.md), [GPU-005-B reference proposal](../phase1e_gpu005_reference_technical_specification.md) and [TV4 handoff](../../../development/handoffs/phase2/HANDOFF_TV4_Phase2D_v1.1.md).

The formerly linked `phase2_readiness_and_handoffs.md`, `phase2_decision_register.md` and `phase2_test_and_acceptance_plan.md` do not exist on this `main`. Use the actual approved sources above, §7.5–7.8 and the handoff; absent files are not approval/evidence.

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

**Updated 2026-11-08:** the four barrier-controlled Submit ↔ Pause/Resize cases were supplied and passed in [Phase 1 head `3482bce` CI](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533), as recorded in [TV4's re-review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#pullrequestreview-5813339600). Reuse that harness for Phase 2; these are not allocation tests. The remaining [early role-rejection audit finding](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#discussion_r4502535120) is a separate Phase 1 follow-up requiring lead disposition, not a reason to report the old barrier gap as still missing.

### D2. Scheduler fairness without violating strict per-Listing FIFO

- Default scan cadence is **2 seconds configurable** (`P2D-OPEN-03` owner-approved), not a 2-second job-start SLA. Keep one Listing in each allocation transaction (`P2D-OPEN-01`).
- Within a locked ACTIVE Listing, choose the smallest queued `enqueue_seq`; do not use `FOR UPDATE SKIP LOCKED` on the Job head and then run a later smaller Job. If head needs more GPUs than free capacity, do not allocate later Jobs from the same Listing.
- Avoid whole-system starvation: use a **bounded listing batch** and a rotating stable cursor/fair round-robin over Listings across scheduler ticks. Continue to other Listings when one head is capacity-blocked; do not loop hot on a single blocked head.
- `TX-ALLOCATE` takes Worker advisory shared -> Listing -> Job under the conditional D-18 direction; PAUSED/Cancel recheck state under their applicable Listing -> Job locks. Dispatch retry never creates a reservation.
- The concrete `listing_scan_budget`, DB pool/executor budget and cross-Listing cursor details are proposed, to be chosen and ACKed by TV1/TV2/TV4 after load testing; do not invent a performance guarantee.

### D3. Planned key rotation vs allocation race

**Current conditional D-18/E-C3 direction:** a per-Worker shared advisory transaction lock precedes Listing -> Job in allocation; registration/activation use the exclusive Worker lock. Two active key rows persistently block new allocations while RUNNING Attempts drain. Activation requires exactly {K1,K2}, trusted K2 readiness and no RUNNING Attempt; failed deployment restores a usable K1 signer before removing the fence. Preserve historical verification keys. This supersedes the earlier pause-all recipe as the proposed rotation protocol; normative source reconciliation, exact-SHA ACKs and native-role tests remain pending.

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

All are planned against **real disposable PostgreSQL**, not PASS evidence. The Phase 1 Submit/Resize barriers are baseline evidence only; every Phase 2 allocation race above still requires its own execution evidence.

## 7. Deep-review technical closure — v0.9 (`PROPOSED_FOR_CROSS_OWNER_ACK`)

> This section **documents and narrows the already-approved design** rather than changing FIFO, DB schema, API, ADR-005 or service topology. Where an exact port/signing-key readiness/pool-budget policy is still undecided, it is a **proposal requiring explicit ACK/owner disposition**, not a new approved requirement. Phase 2D remains `APPROVED_DESIGN_CONDITIONAL`; no Phase 2 runtime test was executed to author this document.

### 7.1. Authoritative baseline and separation of responsibilities

| Item | Verified evidence/baseline | Boundary of that evidence |
|---|---|---|
| Current `main` | `bee832eaf5463df20f6c6815174322871eb6685a`, merged docs intake [#44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44) | Contains five Phase designs and five handoffs; merge is not completion of their cross-review/coding gates |
| PR #39 | [`GPU-INT-01` PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) **merged** by TV1 as `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`; source head `3482bce3cc9726543b9345a5224d8db1b9fc6454`. #42 is included transitively | Phase 1 Auth → Listing → Submit → View → Cancel, not Phase 2 `TX-ALLOCATE` or Scheduler; audit follow-up remains separately recorded in D1 |
| Migration baseline | Read-only Alembic graph on this main: one head `0005_listing_d7` | No DB migration or native Manager-role verification was run for this docs review; TV2 must freeze the actual Phase 2 migration/grants |
| Listing implementation | `backend/src/gpu_marketplace/listings/service.py`: Listing-first lock for PATCH/Pause/Resume, hardware lock on nonterminal Jobs, downsize check against reserved count and max still-QUEUED demand | No Manager allocation API exists in this file; do not retrofit allocation into Listing routes |
| PostgreSQL Listing adapter | `backend/src/gpu_marketplace/repositories/listings.py`, via merged #31; SQLAlchemy `READ COMMITTED` UoW and D7 guard | Must not infer Manager grants or native `session_user` proof from this API adapter; separate role verification is pending |
| Phase 1 TX-SUBMIT | `backend/src/gpu_marketplace/repositories/job_submit.py` on #39: Listing `FOR UPDATE`; replay existing retained key/body even after PAUSED; creates Job+reference transactionally | New API Job submission does **not** allocate GPU, create Attempt/Outbox or guarantee execution |
| Phase 2D code/runtime | **NOT_IMPLEMENTED / NOT_RUN in #39** | PR #39's CI (4 jobs successful) cannot be claimed as Phase 2 allocation or concurrency PASS |
| Owner approvals | `P2D-OPEN-01/02/03`, `P2D-GATE-01`; D-18/E-C3, G1 and Worker-first lock are `APPROVED_DESIGN_DIRECTION_CONDITIONAL`; lead revision request on #48 @ `b399118` | Precise Python ports, D-19, TTL/replay/restart, provisioning/compromise, pool sizing and exact-HEAD reviewer ACKs remain PENDING |

**Ownership freeze (no duplicate implementation):** TV4 owns the *pure policy and FIFO correctness oracle* and presents a design/port to TV1; TV2 owns the PostgreSQL `TX-ALLOCATE` repository/UoW, locks, grants, constraints and rollback semantics; TV1 owns the Manager Scheduling loop, executor, bounded scan and integration; TV5 owns Job/Attempt/Outbox consumer invariants and final release; TV3 owns Worker key readiness/rotation security policy. A shared repo import does not move transaction ownership from Manager to the public API. Final code-file ownership/PR sequencing is `PENDING_ACK` among TV1/TV2/TV4/TV5; do not write competing scheduler or allocation services in parallel without agreement.

### 7.2. Candidate selection, fairness and scan progress (`PROPOSED_INTERFACE`)

**Separate two notions of FIFO:** (a) *within one Listing*, strict `enqueue_seq` ordering is binding; (b) *among Listings*, no global arrival-order guarantee exists. Fair progress among independent Listings is a scheduler liveness goal, not permission to violate (a).

Proposed bounded scanning, subject to TV1/TV2/TV4 ACK:

1. Discover candidate **Listing IDs** from an unlocked DB hint in a stable order (initial proposal: `gpu_listings.id ASC`). The hint may prefer Listings likely to contain queued work before a G1 call, but it is never authorization and cannot replace the locked head/status/capacity/key checks in `TX-ALLOCATE`.
2. A rotating cursor records the last **inspected Listing**, not the last allocated Job. Advance it after every inspected result, including `EMPTY`, `Blocked(HEAD_DOES_NOT_FIT)`, `Blocked(LISTING_NOT_ACTIVE)`, `Blocked(SIGNER_NOT_READY)` and `Noop(LOCK_BUSY)`. At the end, wrap to the beginning. A Listing inserted behind the current cursor is discovered after wrap; one inserted ahead may be discovered in the current pass. No Listing is permanently omitted.
3. The cursor is volatile in-memory scan progress only. After restart, rebuild eligibility from PostgreSQL and begin a conservative fresh pass; no cursor, race winner, lease or local clock authorizes reservation. Continuous inserts do not create a snapshot guarantee.
4. Bound `max_listings_per_cycle`, elapsed work, proof-call concurrency, executor use and DB-pool consumption. None receives a numeric value here; TV1+TV2+TV3+TV4+TV5 must measure and ACK the relevant budgets. The configurable 2-second cadence is not a Job-start SLA or a promise to finish the table each tick.
5. Do not issue unbounded G1 HTTP calls for every Listing every two seconds. Use per-Worker readiness cached only within its approved TTL; invalidate on expiry, Manager restart, active-key/key-lifecycle change and other approved signer lifecycle events. A cache entry that is expired or does not match the active Worker key is unusable. Proof HTTP has bounded timeout/concurrency, runs before a UoW, and signer failure advances the cursor and permits other Listings to proceed; the blocked Listing is reconsidered later.
6. Every candidate that reaches allocation gets its **own short `READ COMMITTED` `TX-ALLOCATE`**. TV2 re-reads Listing identity/status, selects the real FIFO head and checks capacity/key readiness under Worker → Listing → Job locks. A stale hint or proof cache is never allocation authorization.
7. A contended Worker/Listing/Job lock uses a bounded wait and returns `Noop(LOCK_BUSY)` after rollback; advance to other Listings and reconsider the blocked Listing after wrap/later passes. Never use Listing/Job `SKIP LOCKED`, `OFFSET`, timestamps or UUIDs to bypass the true Job head.
8. An unfit FIFO head returns `Blocked(HEAD_DOES_NOT_FIT)` without mutation and consumes only that Listing attempt, not the remaining cycle. After `Allocated`, commit and move on; a later transaction/cycle may consider the next head. Record only redacted IDs/result category/cycle counters—never proof, key, token or oracle bytes.

**Design caution:** stable iteration with continuous writes and contended Listings does not by itself prove a bounded-wait guarantee. Acceptance must include `listings > cycle_budget`, a continuously locked Listing, an oversized head, PAUSED/signer-blocked Listings, a Listing inserted on each side of the current cursor, wrap-around and Manager restart. Do not invent absolute fairness latency or a persistent scheduler cursor table, and do not let Scheduler/proof work exhaust Dispatcher or Finalizer executor/DB capacity.

### 7.3. Single UoW TX-ALLOCATE and proposed result port

The following is **pseudocode**, not executable SQL or a frozen Python signature. It freezes ownership and the two-level result vocabulary: TV4 policy returns an assessment; only TV2's committed UoW returns allocation outcomes.

```text
TV1 Scheduler (bounded loop):
  scan stable Listing-ID hints from rotating in-memory cursor
  advance cursor after every inspected Listing; wrap at end
  obtain/cache bounded G1 proof per Worker outside any DB UoW
  if unavailable/expired/key-mismatched: record SIGNER_NOT_READY; continue; revisit later
  call TV2.allocate_one_listing(listing_id, SignerReadiness)

TV2 allocate_one_listing(listing_id, signer):
  create one native gpm_manager_app Session / one READ COMMITTED UoW
  acquire shared Worker advisory lock; lock/recheck Listing; lock true FIFO-head Job
  select head by enqueue_seq ASC LIMIT 1 FOR UPDATE (NEVER SKIP LOCKED)
  build immutable scalar PolicySnapshot(listing_status,total,allocated,head_id,
      head_enqueue_seq,head_requested_gpu_count) -- no ORM row or Session escapes
  assessment = TV4.assess(snapshot)  // pure: ELIGIBLE | EMPTY |
                                     // HEAD_DOES_NOT_FIT | LISTING_NOT_ACTIVE
  EMPTY -> COMMIT no-op -> Noop(NO_QUEUED_HEAD)
  LISTING_NOT_ACTIVE -> COMMIT no-op -> Blocked(LISTING_NOT_ACTIVE)
  HEAD_DOES_NOT_FIT -> COMMIT no-op -> Blocked(HEAD_DOES_NOT_FIT)
  missing Listing or lock_timeout -> ROLLBACK -> Noop(LISTING_NOT_FOUND | LOCK_BUSY)
  recheck sole active key + signer worker/key/fingerprint + DB-time expiry under locks
  mismatch -> COMMIT no-op -> Blocked(SIGNER_NOT_READY)
  ELIGIBLE is not allocation success and does not authorize HTTP
  trusted t = clock_timestamp() AFTER required locks
  guarded increment gpu_listings.allocated_gpu_count
  guarded exact Job QUEUED -> RUNNING; insert one Allocation, Attempt and Outbox event
  persist fixed finish_due_at and hard_deadline_at; COMMIT atomically
  return Allocated(job_id, attempt_id, event_id) only after known COMMIT
  unknown COMMIT -> CommitOutcomeUnknown(listing_id,job_id,attempt_id,event_id)
  NO proof/HTTP call and no second Session while locks/UoW are open
```

**Erratum X-01:** `reserved_gpu_count` in the previous §7.3 pseudocode was a typo; the actual field is `gpu_listings.allocated_gpu_count`. TV1 confirms it in #47 @ `001619d`, and TV2 records it in #46 @ `0ca059c`. This changes no schema; exact-SHA cross-owner ACK and merging the corrected source remain pending.

**Frozen vocabulary proposed for exact-SHA ACK (TV2 #46 @ `0ca059c`, TV1 #47 @ `001619d`):** TV4's pure `PolicyAssessment` is only `ELIGIBLE | EMPTY | HEAD_DOES_NOT_FIT | LISTING_NOT_ACTIVE`. TV2 maps it and transaction conditions to `Allocated(job_id,attempt_id,event_id)`; `Blocked(LISTING_NOT_ACTIVE|HEAD_DOES_NOT_FIT|SIGNER_NOT_READY)`; `Noop(NO_QUEUED_HEAD|LISTING_NOT_FOUND|LOCK_BUSY)`; or `CommitOutcomeUnknown(listing_id,job_id,attempt_id,event_id)`. Do not expose `ALLOCATED`, `EMPTY_QUEUE`, `BLOCKED_CAPACITY` or `INACTIVE_LISTING` as a second UoW outcome set. No runtime port is implemented.

**Cleanup baseline:** `EMPTY`, `HEAD_DOES_NOT_FIT`, `LISTING_NOT_ACTIVE` and `SIGNER_NOT_READY` COMMIT no-op with zero business writes; missing Listing and `LOCK_BUSY` roll back/close the Session. A pure `ELIGIBLE` assessment is not `Allocated`, cannot authorize dispatch and carries no live ORM/Session. `DependencyUnavailable` remains a sanitized exception, not a policy/UoW business outcome.

**Mandatory correctness guards:** `jobs.id`, `jobs.listing_id`, `jobs.worker_id` remain immutable; one Job has **at most one** Allocation, Attempt and EXECUTE_JOB event (`UNIQUE`/FK as specified by Database Design); `allocated_gpu_count` reflects `SUM(active allocations.gpu_count)` after commit; no caller may open a second Session to finish an in-flight partial transaction. Do not hand a live ORM entity/locked Session across `asyncio.to_thread`/executor or across TV1/TV2 service boundaries. The short DB UoW is owned entirely within one synchronous worker call.

**Commit uncertainty:** after `CommitOutcomeUnknown(listing_id,job_id,attempt_id,event_id)`, TV1 calls TV2's fresh-session read `reconcile_allocation(expected=(listing_id,job_id,attempt_id,event_id))`. `AllocationCommitted` requires the complete durable Attempt/Allocation/Outbox graph and all four IDs equal, even if the Job is now terminal and the Allocation `RELEASED`. `AllocationNotCommitted` requires the whole graph absent and the Job still `QUEUED`. A partial/contradictory graph, advanced Job without the graph, or any Listing/Attempt/Event ID mismatch is `AllocationUnknown`: alert/fail closed, no blind retry, no new Attempt/Event and no second capacity delta. A definite rollback may enter only the separately bounded retry path approved by TV1/TV2.

### 7.4. Interaction with Listing edit, Cancel, Dispatch and Finalization

| Interaction | Required guard | Business effect |
|---|---|---|
| `PATCH` hardware versus new allocation | Hardware changes require **no** `QUEUED` or `RUNNING` Job; effective no-op hardware PATCH may proceed | Scheduler takes the same Listing lock; hardware change cannot silently invalidate an already accepted Job |
| Reduce Listing total capacity | New total cannot fall below `allocated_gpu_count` **or** maximum demand of still-QUEUED Jobs | Check after Listing lock. If both fail, existing API error priority gives `LISTING_CAPACITY_BELOW_ALLOCATED` precedence |
| `TX-CANCEL` vs `TX-ALLOCATE` | Both Listing → Job; recheck QUEUED after lock | Cancel-first yields CANCELLED/no allocation; allocate-first yields RUNNING and cancellation conflicts |
| `TX-PAUSE-EDIT` vs `TX-ALLOCATE` | Both serialize on Listing; allocate first takes Worker advisory shared, then rechecks status | PAUSE-first gives zero new reservation; allocate-first preserves old RUNNING attempt; PAUSED cannot cancel it |
| PAUSED + existing retained Submit key/body | Phase 1 approved replay HTTP 200, even if currently PAUSED | No new Job, reference, allocation or Outbox from replay |
| PAUSED + old RUNNING Outbox | TV1/TV2 dispatcher may resend only the **same** Attempt/event/payload under ADR-005 | No second reservation, hard deadline extension or job reopening |
| Manager Finalization / timeout | TV5/TV2 take Listing → Job → Allocation … in the approved order | GPU release and counter decrement **exactly once**; no stale in-memory scheduler count |
| Planned key rotation | D-18 Worker-first shared/exclusive advisory locks and two-active-key allocation fence; TV3 owns key policy | No head bypass; key/proof rechecked under lock; rollback and source reconciliation `PENDING_ACK` |

**Outbox fencing nuance:** Outbox claim/ACK/retry is its own short **Outbox-only** DB transaction. Never keep an Outbox lock and then acquire a Listing/Job lock (or vice versa) across a network call. A stale dispatch call may still arrive; the Simulator checks Attempt/request identity and the API/Manager enforce no second business effect. `lease_version` fences DB state writes by a stale dispatcher; it does **not** cancel an already sent HTTP request.

**Signer readiness, conditional direction:** TV1 obtains authenticated G1 nonce proof outside any UoW and passes in-memory `SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at)`; fingerprint is lowercase SHA-256 hex of the 32 raw public-key bytes. Unlocked queued-work hints may suppress obviously unnecessary proof calls but never authorize allocation. Proof calls have bounded timeout and concurrency, are cached per Worker only within the approved TTL, and are invalidated on expiry, Manager restart, active-key/key-lifecycle change, and whenever TV2's under-lock check returns `Blocked(SIGNER_NOT_READY)` for that Worker. An expired or key-mismatched cache entry is unusable. No fresh proof means no port call; report `Blocked(SIGNER_NOT_READY)`, continue other Listings and revisit this one later. Under Worker+Listing locks TV2 rechecks Worker, sole active key, fingerprint and `clock_timestamp() < proof_expires_at`, failing closed without writes. A Simulator restart inside an otherwise-valid proof TTL is not visible to Manager: allocation may proceed and later reach deadline fallback `SYSTEM_FAULT` without Worker penalty; this residual risk is `P2C-SIGN-07` in Phase 2C #49 @ `f3edb94`. `P2D-DRT-12` tests the approved rotation fence/stale proof behavior and does not claim that a Simulator restart inside TTL prevents allocation. The endpoint, numeric budgets, TTL/replay/nonce freshness, this restart residual, unavailable-signer recovery, compromise and provisioning remain OPEN for owner/lead decisions. No HTTP runs under locks. All runtime tests remain `NOT_RUN`.

**TV4 boundary disposition for D-19: `ACK_COMPATIBLE`, not approval.** PAUSED blocks only new allocation. Normal Outbox claim/ACK/retry remains Outbox-only and reuses the committed Attempt/event/payload. TV2's separate `B-IF-06R` ACKED missing-receipt repair remains `PROPOSED_FOR_ACK`; its proposed lock order is Listing → Job → Outbox with HTTP only after COMMIT, a separate repair fence/lease, the same immutable identity/payload, no reservation and no deadline extension. TV4 owns neither repair SQL, columns/grants/guards, HTTP client nor Finalizer. TV1/TV2/TV5 and the lead must freeze D-19 before code; do not infer approval from this compatibility statement.

### 7.5. Required two-session and bounded-scheduler evidence (additional test designs; `NOT_RUN`)

Existing `P2D-TX-01..12`, `P2D-RACE-01..08`, `P2D-SCHED-01..05`, `DBTX-*` and `API-LIST-*` remain authoritative. The extra cases below target **uncovered evidence** without changing existing oracles. Run on a **safety-marked disposable PostgreSQL 16 cluster**, with separate committed state snapshots, two or more native runtime-role sessions, test barrier(s) and a controlled trusted DB clock where time edges matter.

| New test ID | Injection | PASS oracle; every row remains `NOT_RUN` |
|---|---|---|
| `P2D-DRT-01` | Freeze `submitted_at`, submit two Jobs via proper TX-SUBMIT lock at different accepted orders | `enqueue_seq` alone chooses first admitted queued Job; UUID order/timestamp ties cannot reverse FIFO |
| `P2D-DRT-02` | Hold the Listing lock via an authorized Pause/Cancel/EDIT transaction; race a scheduler scan, then release its barrier | Bounded lock wait yields `LOCK_BUSY` and rollback; scan advances to other Listings and later rechecks the true head, without Listing/Job `SKIP LOCKED` |
| `P2D-DRT-03` | Queue head needs 4 GPUs with 2 free and later needs 1; another Listing has fitting head | Both Jobs on blocked Listing remain QUEUED, other Listing progresses, no phantom capacity delta |
| `P2D-DRT-04` | Cancel current FIFO head before Scheduler lock; inspect next cycle | Cancelled head is excluded; next earliest still-QUEUED Job may allocate if capacity permits, with one set of child records |
| `P2D-DRT-05` | Inject constraint failure after Listing counter/Job status write | Zero partial Allocation/Attempt/Outbox/Job RUNNING/counter effects after rollback |
| `P2D-DRT-06` | Drop COMMIT ACK after durable TX-ALLOCATE success; reconcile with expected `(listing_id,job_id,attempt_id,event_id)` and repeat with a different expected Event ID | Exact complete graph returns `AllocationCommitted` even after terminal/release; Event-ID mismatch returns `AllocationUnknown`; no second reservation/Attempt/Event |
| `P2D-DRT-07` | PAUSE commits just after allocation, then dispatch 202 lost | Re-dispatch same event/Attempt without another counter delta or deadline extension; eventual final effect once |
| `P2D-DRT-08` | Competing UPDATE/PATCH capacity reduction vs allocation in both commit orders | Existing Listing capacity/queued max guards respected; no allocated count > total |
| `P2D-DRT-09` | Listings exceed cycle budget; one is continuously locked, one has oversized head; add Listings before/after current cursor; wrap and restart | Cursor advances after every outcome, wraps, discovers new rows without starvation, eligible Listings progress and restart causes no duplicate allocation |
| `P2D-DRT-10` | Saturate slow SQL and signer-proof calls while Dispatcher/Finalizer are due | Proof/scan timeout and concurrency budgets hold; Scheduler does not monopolize HTTP/executor/DB pool; other Listings and due loops progress |
| `P2D-DRT-11` | Two independent Manager scheduler sessions claim same Listing simultaneously | At most one successful allocation per unique queued head; no overcommit or duplicate Attempt/Outbox |
| `P2D-DRT-12` | Planned K1→K2 rotation while queued jobs and running attempts exist | Key quiescence policy and new-allocation handling match **separately approved** TV3/TV5 signer-readiness contract; `BLOCKED` until ACK |
| `P2D-DRT-13` | Manager crash before/after allocation COMMIT; reconcile complete, absent, partial and wrong-ID graphs | Before/absent+QUEUED is `AllocationNotCommitted`; exact graph is `AllocationCommitted`; partial or any wrong ID is `AllocationUnknown`; never blind retry |
| `P2D-DRT-14` | Native API role attempts Manager-only TX-ALLOCATE; native Manager role runs legal allocation | API allocation writes denied; authorized Manager transaction behaves per contract; no owner/SET ROLE bypass |
| `P2D-DRT-15` | Stale Outbox dispatcher lease after new fencing claim | Old worker cannot ACK/modify new lease, and no duplicate business allocation/finalization occurs |

**No execution claim:** all `P2D-DRT-01..15` are newly authored **test designs**, `NOT_RUN`; they are neither a claim that CI on #39 ran these cases nor proof of performance/latency. Recording `BLOCKED` for a missing signer policy is a correct test outcome, not permission to weaken the guard.

### 7.6. Cross-owner ACK matrix and implementation-entry gates

| Interface/gate ID | Producer → consumers; exact reference | Required reviewers | State |
|---|---|---|---|
| `D-IF-01` | TV4 pure snapshot/assessment → TV2 mapping and TV1 orchestration; #46 `0ca059c`, #47 `001619d` | TV1 + TV2 + TV4 + TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-02` | TV2 UoW/native role/lock/cleanup/reconciliation → TV1/TV4; #46 `0ca059c` | TV1 + TV2 + TV4 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-03` | TV4+TV1 stable rotating cursor and revisit semantics → TV2 integration | TV1 + TV2 + TV4 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-04` | TV1 resource configuration → TV2/TV4; 2s default fixed, numeric proof/scan/time/executor/DB budgets not fixed | TV1 + TV2 + TV4 | `PENDING_PARAMS / MEASUREMENT` |
| `D-IF-05` | TV1/TV2/TV5 same-Attempt retry and proposed `B-IF-06R` → TV4 PAUSED boundary; #46 `0ca059c` | TV1 + TV2 + TV4 + TV5 | `TV4_ACK_COMPATIBLE / D-19 OPEN / EXACT_HEAD_ACK_PENDING` |
| `D-IF-06` | TV2+TV4 Listing/Cancel/Allocate race and error mapping → TV5 lifecycle | TV2 + TV4 + TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-07` | TV3 G1/key policy + TV2 Worker/key recheck + TV1 bounded proof calls → TV4/TV5; #49 `f3edb94` (`Phase_2C_v0.9.md` blob `a869dd7d4006981ac0d2478a2fb3b684f1f1a157`), #46 `0ca059c` | TV1 + TV2 + TV3 + TV4 + TV5 | `APPROVED_DESIGN_DIRECTION_CONDITIONAL / TV3_SCOPED_ACK_WITH_ACTIONS_ADDRESSED / OTHER_EXACT_HEAD_ACK_PENDING` |
| `D-IF-08` | TV2/TV5 release/finalization/timeout reconciliation → TV1/TV4; #46 `0ca059c`, #50 `edb247f8` | TV1 + TV2 + TV4 + TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-09` | TV1/TV2 Phase 1 baseline/native-role/audit disposition → TV4/TV5 | TV1 + TV2 + TV4 + TV5 | `BASELINE_RECORDED / AUDIT_DISPOSITION_PENDING` |

**Docs gate before code:** finish self-review/corrections, obtain affected source/consumer ACKs and independent cross-review, resolve blocking choices, then obtain the leader's decision and merge the docs PR. This applies to the pure policy too; a prototype or green CI cannot open the gate. Before the relevant code task starts: (i) freeze merged main/migration/role baseline and audit disposition; (ii) ACK the concrete TV2 port and lock/commit boundary for dependent tasks; (iii) resolve signer readiness before allocation integration; (iv) agree scan/work/pool parameters before runtime scanning. Follow §7.8 rather than using one implementation branch for the whole Phase.

**Code merge evidence is per task:** run the acceptance tests applicable to that task at its exact SHA; do not demand unrelated whole-Phase runtime evidence for a policy-only task or label policy tests as PG PASS. Full allocation/Scheduler integration still needs the intended `P2D-TX/RACE/SCHED/DRT` PostgreSQL/CI evidence, no unresolved critical skipped/blocked case, human review and no Phase 1 regression.

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

- **Preserved (owner-approved):** strict per-Listing FIFO, Listing-before-Job row locking, one Listing per `TX-ALLOCATE`, PAUSED RUNNING dispatch repair, configurable 2s scan, 18 total database tables, 5 runtime services, immutable Job and Attempt identities. Conditional D-18 adds a Worker advisory lock before allocation's Listing lock.
- **Clarified in v0.9:** split TV1/TV2/TV4/TV5 ownership, proposed scan/cursor semantics, bounded executor limits, typed allocation outcomes, commit-unknown reconciliation, stale Outbox fencing, signer readiness interface and deterministic evidence.
- **Still OPEN:** numerical G1/scan/time/executor/DB pool/lock/statement budgets; G1 TTL/nonce/replay and restart-inside-TTL; provisioning identity and unavailable-signer recovery; compromised-key response; D-19 repair columns/grants/guards; exact `LOCK_BUSY`/`DependencyUnavailable` orchestration; D-09 index; audit disposition. Preserve them as `PENDING` until source/consumer ACK and required L2 change control.
- **Runtime status:** official Phase 2D PG/Scheduler acceptance IDs remain `NOT_RUN`; PR #39's Phase 1 CI and prototype #45's policy unit results do not close those IDs. The prototype remains on hold pending docs approval.

### 7.8. Self-review and docs-first delivery — updated 2026-11-19

**Workflow:** self-review → `docs/phase2d-design-review` → cross-review/corrections → leader approves and merges docs → one code task/branch/PR at a time. Each subsequent task starts from latest `main`, with its own scoped tests and review; independent tasks may run in parallel only after their design/dependency approval. No self-merge. [Prototype #45 is Draft/HOLD](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/45#issuecomment-6721101443); it is not the docs PR or an approved implementation baseline.

| Self-review finding | Proposed document correction | Cross-review still required |
|---|---|---|
| Stale unmerged #39 snapshot and already-supplied Phase 1 barriers | Current SHA/evidence in §7.1 and D1; retain audit follow-up separately | TV1+TV2 acknowledge baseline/disposition |
| Broken source links after move to `phase2/`; three referenced files absent | Repair actual relative links; point to existing handoff/test design | TV2/TV1 verify source precedence |
| Wrong `reserved_gpu_count` field | X-01 corrected to actual `allocated_gpu_count` | TV2 + lead confirm erratum |
| No-op commit described as undecided despite approved DB pseudocode | Preserve EMPTY/BLOCKED COMMIT no-op in §7.3 | TV2 confirm port cleanup/mapping |
| Earlier handoff says one branch/PR for whole Phase | Docs first, then one branch/PR per code task | TV1 confirms sequence |
| PENDING labels without a concrete closure question | Questions below; no invented values, ACK or approval | Named producer/consumer owners |

**Questions to close during cross-review (still PENDING):**

1. **TV2 ↔ TV4, with TV1/TV5 (`D-IF-01/02`):** freeze `allocate_one_listing(listing_id, SignerReadiness)` and outcome fields by exact SHA. Listing ID is a locator; SQL selects the authoritative head under locks. Missing Listing, lock/statement failures and unknown COMMIT remain distinct. Reconcile the durable graph with stable IDs even if the Job became terminal and Allocation RELEASED; missing/contradictory evidence stays UNKNOWN, never blind retry.
2. **TV1+TV2+TV4 (`D-IF-03/04`):** agree cursor/lock-timeout/revisit semantics and concrete max Listings/work time/executor/pool/SQL timeout budgets, with a disposable-DB measurement plan. The already-approved configurable 2s cadence does not select those values. No new benchmark/SLA is proposed.
3. **TV1+TV2+TV3+TV4+TV5 (`D-IF-07`):** reconcile the conditional D-18 Worker-first lock and G1 proof with normative API/DB sources and exact producer/consumer SHAs. Merely pausing a discovered set is insufficient if another Listing is created/resumed. TTL/replay/restart, provisioning and compromised-key incident handling remain open; no private-key reads or HTTP under locks.
4. **TV1+TV2+TV5 with TV4 (`D-IF-05/06/08/09`):** ACK same-Attempt PAUSED repair, both-order Cancel/Pause/Resize races and exactly-once release. Record the existing audit follow-up disposition separately from the now-merged baseline and completed Phase 1 barriers.

**Review evidence:** link/file consistency and schema/design comparison only. All Phase 2 runtime, PG races and performance tests remain `NOT_RUN` (signer-dependent scenarios `BLOCKED` until contract approval). Self-review, CI and Codex advice do not count as independent human approval. The docs PR must record exact reviewed SHA, cross-owner ACKs and the leader's closure/merge decision before code resumes.

### 7.9. TV1 revision-request mapping and handover — 2026-11-19

| Request | Change in this revision | Status after edit |
|---|---|---|
| `P1-01` pure policy ↔ UoW | §2.1 and §7.3 freeze TV1/TV2/TV4 ownership, immutable `PolicySnapshot`, four policy assessments and one `B-IF-06` UoW outcome vocabulary | `PROPOSED_FOR_EXACT_HEAD_ACK` |
| `P1-02` bounded signer proof | §7.2/§7.4 add unlocked hints, per-Worker TTL cache/invalidation, bounded timeout/concurrency, cross-Listing progress and no HTTP under UoW | conditional direction only; exact-SHA ACK and endpoint L2 change control pending; numeric budgets `PENDING_PARAMS` |
| `P2-03` scan/fairness | §7.2 advances cursor after every outcome, wraps, defines restart/new-Listing behavior and protects Dispatcher/Finalizer resources | `PROPOSED_FOR_EXACT_HEAD_ACK` |
| `P2-04` unknown COMMIT | §7.3 defines the expected four IDs and all three reconciliation outcomes; `P2D-DRT-06/13` include wrong Event ID/partial graph | `PROPOSED_FOR_EXACT_HEAD_ACK` |
| `P2-05` D-19 boundary | §7.4 records TV4 `ACK_COMPATIBLE` only; normal Outbox and separate proposed repair port/lease remain distinct | D-19 remains `OPEN / NOT_APPROVED` |
| `P2-06` document reconciliation | top snapshot, §2.1, §7.1, §7.6–7.8 use pushed SHAs and conditional-decision labels; X-01 remains `allocated_gpu_count` | done in TV4 docs; producer ACKs pending |
| `P2-07` tests/handoff | Existing test families retained; §7.5 adds proof bounds, wrong Event ID, continuously locked/new Listing and wrap-around cases; handoff mirrors this matrix | all runtime/PG/performance tests `NOT_RUN` |

**TV3 exact-HEAD actions on #48 @ `813aa3e` (scoped to D-IF-07):** (1) P1-02 status now matches conditional direction / exact-SHA ACK pending; (2) the Simulator restart-inside-TTL residual and `P2C-SIGN-07` are explicit, with no claim that allocation is prevented in `P2D-DRT-12`; (3) cache invalidation on under-lock `Blocked(SIGNER_NOT_READY)` is named; (4) Phase 2C source SHA and blob hash are updated to #49 @ `f3edb94` / `a869dd7d4006981ac0d2478a2fb3b684f1f1a157`. TV3 requested a focused re-check of these changed lines. Its scoped ACK is not independent whole-PR L2 approval.

**Next gate:** publish the new exact HEAD and request scoped ACKs from TV1 (`D-IF-01..09`, budgets/integration), TV2 (`D-IF-01..06/08/09`, #46 compatibility), TV3 (`D-IF-07`), TV5 (`D-IF-01/05..08`) and the lead for independent L2/docs-gate closure. A technical ACK on a boundary is not a substitute for the required independent human reviews. No source code, migration, config or PR #45 change belongs to this revision.
