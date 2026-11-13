# Phase 2E - Simulated Execution, Finalization and Reputation (TV5)

> **Deep review v1.8 (2026-11-07; historical GitHub snapshot):** The preceding PR39-E appendix remains the historical v1.7 context. This review incorporated PR #39 HEAD `6788505cbb68e09ad08ea2b96728bc6c69e8a32e`, which incorporated test-only PR #42 at that time, and reconciled Phase 2A v0.9, 2B v1.3, 2C v0.9 and 2D v0.9. Current PR/main status is recorded in the 2026-11-08 addendum below. Newly proposed E-IF/DRT details require cross-owner ACK, not automatic owner approval. Existing conditional design approvals persist; no Phase 2 code authorization.

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Document version:** `v1.8-DEEP-REVIEW` (supersedes local v1.7; inherits `P2E-GATE-01 = APPROVED_DESIGN_CONDITIONAL`, updated 2026-11-07)  
> **Status:** `APPROVED_DESIGN_CONDITIONAL / GPU005B_DESIGN_CONDITIONAL_APPROVED / DOCUMENTATION_ONLY / NOT_APPROVED_FOR_IMPLEMENTATION`  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate:** Phase 1 integration must be accepted on `main`, affected interfaces reviewed, and coding separately authorized.

> **Proposed documentation owner:** TV5 - Jobs owner (`NguyenDucThang-tb`)

## 1. Goal and boundary

Design the Job lifecycle **after** Phase 1 `QUEUED` submit/read/cancel: authenticated mock execution dispatch to the isolated Simulator, durable callbacks, Manager-only finalization, release and exactly-once reputation contribution. TV5 owns this documentation work package based on the GPU-005 Job handoff; writing code or modifying Phase 1 Job commands is **not** authorized.

Important separation: Simulator generates a **signed claim**, Manager makes the authoritative `RUNNING -> COMPLETED/FAILED` decision, and API handles only ingress/role-safe read. The independent protected deterministic reference must never be dispatched to Simulator. Dispute adjudication remains Phase 3.

## 2. Proposed design deliverables (TV5)

| ID | Document deliverable | Dependency |
|---|---|---|
| `P2E-01` | Freeze Phase 1 Job/Listing `QUEUED`, immutable `enqueue_seq`, idempotency, cancel semantics | Phase 1E plus merged #32/#33/#34/#40 and integration #39 |
| `P2E-02` | Simulator deterministic workload, signed callback and duplicate-dispatch wire specification | ADR-004 V1 and ADR-005; resolve GPU-005-B proposal |
| `P2E-03` | Outbox/Inbox delivery sequence and restart/timeout timeline | TV1 dispatcher, TV2 tables, TV3 ingress/auth |
| `P2E-04` | Manager `TX-FINALIZE` / `TX-DEADLINE-FALLBACK` atomic-effects specification | TV2 transaction design and TV3 verifier output |
| `P2E-05` | Reputation contribution and role-safe results/Jobs UI handoff | Existing Worker aggregates; API Contract sections 9, 11, 12 |


## 2.1. TV5 boundary and integration contracts — review notes, not yet approved

The work package is design ownership, not blanket code ownership. TV5 specifies the behavior of simulated execution and Job finalization, but the final `RUNNING -> COMPLETED/FAILED` write belongs to the **Manager** and must use TV2's DB Unit of Work. TV3 defines the strict V1 parser and Ed25519 verification result; TV1 integrates the independent Manager loops; TV4 controls the FIFO/PAUSED contract. No TV5 module may bypass API Inbox, read the protected oracle from Simulator, or independently commit partial Job/reputation effects.

| Boundary | Direction | Contract/invariant | Design confirmation |
|---|---|---|---|
| Manager dispatcher -> Simulator | Internal HTTP | One immutable attempt/event/request identity, purpose-scoped dispatch Bearer, permitted `simulation_input` only | TV1 + TV3 + TV5 |
| Simulator -> API | Internal HTTP callback | Original V1 envelope bytes, stable callback `result_id` on retries of one produced receipt, callback Bearer; API saves Inbox before 202 | TV3 + TV5 + TV2 |
| Inbox -> Manager verifier | PostgreSQL / verifier interface | Strict V1 schema, registered `(worker_id,key_id)` context; never treat signature as ground truth | TV2 + TV3 + TV1 |
| Verifier -> finalization | Typed verification outcome + DB context | Recheck Job/Attempt, locked trusted time, once-only Job/Allocation/Contribution/Aggregate writes | TV1 + TV2 + TV3 + TV5 |
| Finalization -> API read projection | DB-backed role-safe view | No secrets/oracle/raw private evidence leaked to Client/Worker | TV3 + TV5 |

**Dependencies already approved in other Phase 2 design reviews:** 2A three Manager loops (Scheduling, Dispatch, Finalization) with fail-fast supervisor and UoW-backed bounded executor; 2B one six-table migration and guarded, scoped DB writes; 2C independent verifier and PostgreSQL raw-receipt dedup; 2D PAUSED does not stop repair of an already RUNNING attempt, and no new allocation occurs under PAUSED. All are approved at **design** scope only, with cross-owner ACK and implementation verification pending.

## 2.2. Primary proof obligations for TV5 — review notes

1. **Idempotent execution request**: a duplicate immutable dispatch with identical `attempt_id` must not change logical Job identity, create new GPU Allocation or bypass the stable deadline; an altered request for the same logical attempt is a conflict.
2. **Deterministic simulation**: the Simulator accepts only the approved `demo-v1` input; the protected reference is independently created and inaccessible to Simulator. The public SHA-256/JCS deterministic derivation mechanism is **APPROVED_DESIGN** via `P2E-GPU005B-DEC-02`, and the synthetic 80/10/10 outcome mapping is **APPROVED_DESIGN** via `P2E-GPU005B-DEC-03`; the nine-field expected-output schema and `work_units=0..999999` are **APPROVED_DESIGN** via `P2E-GPU005B-DEC-04`. The V1-V4 normative test fixtures are **APPROVED_DESIGN** under `P2E-GPU005B-DEC-05`, and immutable `demo-v1 -> demo-v1-public1` compatibility is **APPROVED_DESIGN** under `P2E-GPU005B-DEC-06`. Reference DB **least-privilege policy** is **APPROVED_DESIGN** under `P2E-GPU005B-DEC-07`; physical SQL grants, cross-owner ACKs and runtime tests remain **PENDING**; the overall GPU-005-B design gate is now **APPROVED_DESIGN_CONDITIONAL** via `P2E-GPU005B-GATE-01`.
3. **Wire-format compatibility**: exactly the approved ADR-004 V1 eleven signed fields, JCS RFC 8785, domain separator, unpadded Base64url Ed25519 signature; preserve historical key verification.
4. **Safe ingress**: service token validation occurs before Inbox write; an identical retained receipt replay is idempotent, a changed-envelope reuse is conflict.
5. **Atomic finalization**: one accepted result or system fallback, once-only terminal status, allocation release, Listing decrement and eligible reputation contribution/aggregate delta in a single transaction, with no remote HTTP while holding DB domain locks.
6. **Timed recovery**: a committed valid on-time Inbox candidate must be examined before SYSTEM_FAULT fallback even when Manager restarts late; Worker `finished_at` is never the trusted admission/retention clock.

## 2.3. P2E-OPEN-01 — Duplicate Simulator dispatch execution strategy (`APPROVED_DESIGN`)

**Fixed by ADR-003/005 and API Contract §13:** The Manager may redeliver a stable logical attempt after a lost ACK/restart, and deterministic simulation may execute more than once. A callback retry of **one produced signed receipt** must reuse exactly its original `result_id` and signed envelope bytes. No physical exactly-once execution claim is permitted.

| Option | Behavior | Consequence |
|---|---|---|
| **A — Per-attempt in-memory dedup/cache while Simulator is alive (APPROVED)** | On first accepted immutable dispatch, record attempt/request fingerprint and running/finished receipt state in the Simulator process; identical duplicate while retained returns `202` without competing reexecution, and callback retry reuses the same receipt bytes/ID. A different request under the same `attempt_id` is rejected. **After Simulator restart**, cache may be lost; Manager can redeliver, Simulator can deterministically rerun; final business effects remain once-only in PostgreSQL. | Improves work reuse within one process; requires a bounded cache, expiry/restart semantics and concurrency-safe duplicate handling. Does not introduce DB access or durable storage to Simulator. |
| B — Stateless per-dispatch reexecution | Each immutable repeat dispatch may recompute the deterministic mock; if the same process already has a produced receipt, a callback retry must still reuse the exact original bytes/ID of that receipt. A request-fingerprint guard is still required to refuse same-ID contradictory input. | Less cache state, potentially extra work and more separate signed receipts for one attempt; backend must still finalize at most one. |

**Decision `P2E-OPEN-01 = APPROVED_DESIGN` (2026-11-07):** Owner selected **Option A** for the simulation-only single-host MVP. Simulator maintains a bounded, concurrent-safe in-memory cache keyed by `attempt_id`, bound to the immutable dispatch request fingerprint, with running/finished receipt states. Within a retained cache entry, identical duplicate dispatch returns the same logical acceptance without a second competing execution; contradictory dispatch for the same attempt returns `409 EXECUTION_CONFLICT`. Retries of **one already produced signed callback** reuse exactly the original envelope bytes and `result_id`. Cache eviction/restart may lead to deterministic reexecution; PostgreSQL remains the authority for exactly-once committed finalization, allocation release and reputation effects. This `P2E-OPEN-01` approval did **not itself** approve GPU-005-B outcomes or output schema; the synthetic 80/10/10 outcome mapping has since been approved separately by `P2E-GPU005B-DEC-03`, while normative V1-V4 vectors have since been approved under `P2E-GPU005B-DEC-05`; reference **logical access policy** was subsequently approved by `P2E-GPU005B-DEC-07`, while exact PostgreSQL grants and implementation evidence remain pending; the full GPU-005-B design gate was subsequently approved conditionally under `P2E-GPU005B-GATE-01`. No durable DB/storage may be added to Simulator.

**Required unresolved cross-restart detail — `P2E-CACHE-GAP-01` (PENDING, not waived):** An in-memory-only cache cannot, by itself, recognize a previously seen contradictory `attempt_id` after eviction or process restart. API Contract §13.1 requires `409 EXECUTION_CONFLICT` when the same attempt identity is reused with a different immutable request. TV1/TV3/TV5 must propose and review how this requirement is enforced across restarts *without giving Simulator DB access or inventing a new unapproved service/table*. The immutable source-of-truth Outbox payload, authenticated dispatch and any proposed binding mechanism must be explicitly reconciled with the approved API Contract. Do not claim cross-restart conflict coverage before proof. The policy for bounded cache TTL, capacity, eviction, concurrency and resulting callback identities is also `PENDING`. Cross-owner human ACK is required before coding.

**Proposed test IDs (`NOT_RUN`)**:

| ID | Scenario | Required outcome |
|---|---|---|
| `P2E-SIM-01` | Two simultaneous identical dispatches, Simulator alive | Both acknowledged appropriately; one active in-memory execution per retained attempt; stable dispatch identity; no second GPU allocation |
| `P2E-SIM-02` | Same attempt ID with altered immutable request | `409 EXECUTION_CONFLICT`, no replacement/second business effect |
| `P2E-SIM-03` | Lost callback ACK, same signed receipt resent | Exact original raw signed envelope and `result_id`, one Inbox receipt and one finalization |
| `P2E-SIM-04` | Simulator restart loses cache; resend same committed attempt | May rerun mock deterministically; same attempt/dispatch identity/deadline; Manager finalization remains once-only |
| `P2E-SIM-05` | Listing PAUSED after allocation; missing-result repair | Allowed retry only for the already RUNNING attempt, no new Allocation or deadline extension |

All tests require owner sign-off on the deterministic output contract before interpreting claimed values as semantically correct. Status of all tests: `NOT_RUN`.

## 2.4. `P2E-OPEN-02` — Typed Verifier-to-Finalizer handoff (`APPROVED_DESIGN`)

**Decision `P2E-OPEN-02 = APPROVED_DESIGN` (2026-11-07):** The owner selected **Option A — Typed Verification Result**, not a raw/loosely typed callback handoff. TV3 owns the independent strict ADR-004 V1 parser/JCS/Ed25519 verifier. TV1 wires the verifier to the Manager; TV5 owns the finalization/reputation *design*. The sole authorized runtime finalizer is Manager through TV2's transaction-scoped Unit of Work. This approval is for the design boundary only; **code, GitHub changes and migration execution are not authorized**.

**Proposed typed, immutable verifier result** (shape and field naming **still `PENDING` cross-owner ACK**):

| Contract element | Proposed minimum semantic meaning | Trust restriction |
|---|---|---|
| `inbox_id`, `result_id` | Exact retained Inbox evidence and claimed signed result IDs | Only the Inbox row ID is DB-assigned; claimed IDs must be bound to persisted state |
| `job_id`, `attempt_id`, `worker_id`, `listing_id`, `key_id` | Identity binding context from verified payload | Compare all values against trusted DB records under domain locks |
| `verification_status` | Explicit `VERIFIED` or `REJECTED` produced by TV3 verifier | Never a field accepted from Simulator or a mere HTTP `202` |
| `verified_classification` | `SUCCESS`, `WORKER_FAULT`, or `JOB_FAULT` **only** after V1 schema/signature checks | Signed *claim*, **not** deterministic oracle truth |
| `rejection_code` | Stable redacted reason for an invalid candidate | No sensitive raw bytes, private key, Bearer or oracle in logs/DTOs |
| `envelope_sha256` / evidence binding | Fingerprint tying the verdict to the immutable original Inbox envelope | Re-check against the specific persisted Inbox row before use; digest alone is not authorization |

**Finalization sequence (one PostgreSQL transaction for all business effects):**

1. TV3 independently validates the **specific persisted** raw V1 envelope (exact 11-field schema, strict JSON/JCS, Ed25519 signature against registered `(worker_id,key_id)`) and returns a typed verdict. Verification may occur before domain locks, but the verdict is **not** approval to commit.
2. TV1/TV5 finalization UoW acquires required domain locks in approved order: **Listing -> Job -> Attempt/Allocation -> Inbox candidate -> Contribution -> Worker Aggregate**. Use a fresh DB snapshot after locks, not the earlier verifier-side snapshot.
3. Under those locks, recheck Job remains `RUNNING`, current stable Attempt and Worker/Listing/key binding match, Inbox belongs to this exact on-time callback (`received_at < hard_deadline_at`), original evidence identity/hash matches the verdict, and no result/terminal effect was already committed. A stale or rejected verdict **must not** finalize.
4. For a single eligible `VERIFIED` receipt, commit **together**: accepted immutable `signed_results` row; terminal `jobs` transition; `allocations` release; `gpu_listings.allocated_gpu_count` decrement; `result_inbox` processed status; and eligible `job_reputation_contributions`/`worker_reputation_aggregates` effect. **No intermediate repository commit and no HTTP under transaction locks.**
5. A rejected candidate can be marked `REJECTED` without terminalizing the Job or changing GPU/reputation. For deadline fallback, recheck **all previously committed, unprocessed, on-time Inbox candidates** in deterministic order before `FAILED/SYSTEM_FAULT`, including after Manager restart. `SYSTEM_FAULT` produces **no Worker reputation contribution**.
6. Replay, competing Manager consumers, rollback, restart or lost ACK must yield **at most one committed** Job terminal effect, accepted receipt, GPU release and eligible reputation effect. Correctness relies on guarded transactions and DB uniqueness, not solely on the typed verdict.

**Pending implementation-contract details (`P2E-VERDICT-CONTRACT-01`):** Exact Python type/API, where strict parse errors are surfaced, immutable envelope identity, public-key retirement policy for in-flight attempts, whether costly Ed25519 verification runs outside locks, the bounded candidate-processing strategy, and adversarial test fixtures require **TV1 + TV2 + TV3 + TV5 independent ACK**. No new signature schema or separate Reputation transaction is authorized by this decision.

**Acceptance designs (all `NOT_RUN`):**

| Test | Scenario | Expected durable result |
|---|---|---|
| `P2E-VER-01` | Authenticated Inbox with invalid Ed25519 signature | Typed `REJECTED`; no accepted receipt, terminal state, GPU release or reputation effect from this input |
| `P2E-VER-02` | Valid signature, but mismatched DB Job/Attempt/Worker/Listing/key | Reject stale/mismatched context; no business mutation |
| `P2E-VER-03` | Valid verdict computed, then Job state or Inbox evidence changes before finalization lock | Under-lock recheck rejects stale verdict; no double terminal effect |
| `P2E-VER-04` | Inject DB failure after some finalization writes but before commit | Entire transaction rolls back; no partial release/aggregate increment |
| `P2E-VER-05` | Same valid receipt consumed twice or finalization retried after committed response was lost | Exactly one signed result, release and eligible reputation effect |
| `P2E-VER-06` | On-time Inbox stored before deadline, Manager resumes after deadline | Verify on-time Inbox before fallback; no false `SYSTEM_FAULT` |

## 2.5. `P2E-OPEN-03` — Reputation once-only persistence decision (`APPROVED_DESIGN`)

**Decision `P2E-OPEN-03 = APPROVED_DESIGN` (2026-11-07):** Owner selected **Option A — Contribution-ledger-first + atomic Transaction-scoped Unit of Work**, not aggregate-only deduplication. This is a design approval, not authorization to implement/migrate/merge or a claim that PostgreSQL tests passed.

**Binding outcome mapping from ADR-004 and Database Design:**

| Valid Manager-accepted outcome | Job terminal status | `job_reputation_contributions` row | Lifetime aggregate delta |
|---|---|---|---|
| Signed `SUCCESS`, `failure_reason = null` | `COMPLETED` | One `SUCCESS` row | `successful_jobs += 1` |
| Signed `FAILED / WORKER_FAULT` | `FAILED` | One `WORKER_FAULT` row | `worker_fault_jobs += 1` |
| Signed `FAILED / JOB_FAULT` | `FAILED` | One explicit `NONE` row | Neither counter changes |
| Manager fallback `FAILED / SYSTEM_FAULT` | `FAILED` | **No contribution row** | Neither counter changes |
| Cancelled / rejected or late receipt / unfinished Job | No eligible signed finalization | **No contribution row** | Neither counter changes |

**Finalization transaction contract (TV5 behavior; TV2 DB adapter):**

1. Use one PostgreSQL Unit of Work with the approved domain lock order: **Listing -> Job -> Attempt/Allocation -> Inbox -> Contribution -> Worker aggregate**. Under locks, check `RUNNING`, retained verified Inbox/Attempt binding and absence of an already committed terminal outcome.
2. For an eligible verified receipt, insert **one** immutable `signed_results`, set terminal `jobs` state and trusted `terminal_at`, release the `ACTIVE` allocation, decrement the Listing allocation counter, mark Inbox processed, insert a contribution keyed by `job_id` and apply its aggregate delta **in the same commit**. For `NONE`, insert a contribution with zero aggregate delta. For `SYSTEM_FAULT`, release and terminalize atomically **without** inserting a contribution or changing Worker counters.
3. `job_reputation_contributions.job_id` is the primary key/once-only invariant; a duplicate callback, second Manager consumer, restart or replay is **no-op for business effects** when original finalization already committed. Uniqueness errors or a conflicting partial state must be rolled back and inspected, **never** treated as authorization to increment again.
4. `initial_category = effective_category` at first Phase 2 insert; `correction_version = 0`, `corrected_by_dispute_id = NULL`. Phase 2 must not make Dispute corrections. Phase 3 owns permitted corrections and must preserve signed evidence.
5. All lifetime aggregate counters remain nonnegative and persist independently of the 23-day Job-history purge. Tests must compare actual aggregate deltas with unique, effective contribution rows **for retained history**, while respecting that already-purged contributions no longer remain as lifetime evidence.
6. Never issue remote HTTP under domain row locks, and never split contribution and aggregate updates into separate commits.

**Required coordination / PENDING detail:** TV2 + TV5 define the exact SQL/UoW entry point and constraint/error names; TV1 verifies supervisor restart, concurrency and failure barriers; TV3 confirms that only the verified, correctly bound V1 signed claim can be mapped to an eligible contribution. Phase 3 correction and retention compatibility needs owner acknowledgment under interphase change control. No 19th table, new status, correction API or alteration to ADR-004 is approved here.

**Acceptance test designs (`NOT_RUN`):**

| Test ID | Setup | Must hold after commit / rollback |
|---|---|---|
| `P2E-REP-01` | Finalize valid signed `SUCCESS`, replay exact callback twice | One `SUCCESS` contribution, `successful_jobs` +1 total, one release and terminal transition |
| `P2E-REP-02` | Signed `FAILED / WORKER_FAULT`, replay | One `WORKER_FAULT` contribution, `worker_fault_jobs` +1 total |
| `P2E-REP-03` | Signed `FAILED / JOB_FAULT` | One explicit `NONE` contribution; lifetime counters unchanged |
| `P2E-REP-04` | Deadline with no valid committed on-time receipt; Manager `SYSTEM_FAULT` fallback | One terminal failure and release, zero contribution rows, zero Worker reputation penalty |
| `P2E-REP-05` | Two Manager consumers attempt finalization of same Job concurrently | At most one accepted result/contribution; exactly one allocation release and valid aggregate delta |
| `P2E-REP-06` | Inject exception after contribution insert or aggregate update but before commit | Full rollback: no partial terminalization, contribution, release or aggregate delta |
| `P2E-REP-07` | Manager crash immediately after durable finalization commit, then restart | Replay causes zero further changes; retained signed original bytes unchanged |
| `P2E-REP-08` | Authorized 23-day Job-history purge with no OPEN Dispute (when cleanup is enabled in its own approved phase) | Job-linked contribution may be removed; lifetime aggregate remains unchanged, no orphan or double adjustment |

The test cases are design-only and are not marked PASS by this approval.

## 3. Dispatch and Simulator constraints

- `simulation_input` must be exactly `{"workload_profile":"demo-v1"}`. No oracle seed, expected digest, private backend truth, Client-supplied arbitrary commands or real GPU workload.
- One stable logical `attempt_id` for the Job. Duplicate dispatch after lost `202` or missing-result probe must be idempotent and cannot create a second business effect.
- ADR-005 clocks: `started_at` at allocation, `finish_due_at = started_at + duration_seconds`, hard deadline `finish_due_at + 120 seconds`; missing receipt probe at due + 10 seconds.
- Dispatcher retries use persisted due times and fixed backoff 2/4/8/16/30 seconds with fenced 30-second claim and 2-second due poll. No DB locks during HTTP or mock execution.
- Simulator has no DB driver, credentials, private oracle or authority to update a Job. It signs only the approved V1 claim with privately provisioned Worker signing key and returns through the authenticated callback path.

## 4. Finalization and reputation map

| Manager-accepted evidence | Job state | One effective contribution |
|---|---|---|
| Valid V1 `SUCCESS` + `null` | `COMPLETED` | `SUCCESS`, `successful_jobs += 1` |
| Valid V1 `FAILED` + `WORKER_FAULT` | `FAILED` | `WORKER_FAULT`, `worker_fault_jobs += 1` |
| Valid V1 `FAILED` + `JOB_FAULT` | `FAILED` | `NONE`, counters unchanged |
| Deadline without any valid committed on-time candidate | `FAILED / SYSTEM_FAULT` | No Worker contribution or penalty |

Manager must process committed, on-time Inbox candidates before fallback, even if it restarts after deadline. `received_at == hard_deadline_at` is late. A verified signature alone is not a truth comparison and cannot automatically support a Dispute judgment. One accepted immutable result, terminal transition, release and effective reputation effect must commit **atomically**; replay changes none of them. Retain signed evidence for the future Phase 3 Dispute/retention model without implementing Phase 3 tables or business commands now.

## 5. Open deterministic-reference gate

The [GPU-005-B technical specification](../phase1e_gpu005_reference_technical_specification.md) is a Phase 1 reference-creation specification. The Phase 2E conditional design decisions `P2E-GPU005B-DEC-02..07` are recorded in this Phase 2E document and merged into main by PR #44; their Phase 2 consumer ACKs, physical DB grants and runtime interoperability evidence remain separate. The SHA-256/JCS/rejection derivation, synthetic 80/10/10 mapping, nine-field mock schema, V1–V4 fixtures, immutable version mapping and logical reference access policy remain at their documented approval scope. Do not treat a Phase 1 reference approval or a Phase 2 conditional design gate as runtime implementation or security proof. TV5 requests review by the team lead, TV2 (schema), TV4 (Listing Pause), TV3 (signed wire compatibility), and the assigned Phase 2 consumer owner; record actual decisions/ACKs against the reviewed SHA.

**Trust-model limitation `P2E-ORACLE-INDEPENDENCE-01` — ACCEPTED_FOR_SIMULATION_MVP (2026-11-07), NOT ANTI-CHEAT:** The current GPU-005-B *proposal* uses a public `demo-v1-public1` hash derivation over Job/Listing/Worker/duration/count/profile and has no separate server-held secret in the hash input. Those identifiers/parameters are available in the approved dispatch contract. Consequently, an implementation possessing the public algorithm may **recompute the proposed expected outcome and digest without querying the protected `simulation_references` table**. Merely isolating the Simulator from PostgreSQL does not make the proposed reference cryptographically secret or independently unpredictable. This is **not** a finding that the signed-result V1 contract is broken; it is a trust-model question for mock adjudication. The owner **accepts this limitation for the simulation-only MVP** via `P2E-GPU005B-DEC-01`; the reference is a separately persisted comparison baseline and **not proof of real GPU execution, non-predictability or resistance to a dishonest Simulator**. Requiring genuine anti-cheat would demand an independently reviewed workload/proof protocol; inserting a server-only HMAC secret without redesigning verification is not sufficient. Do not silently add a secret or change deterministic vectors without owner approval and cross-phase ACK.



## 5.1. `P2E-OPEN-04` — GPU-005-B must be reviewed before the Phase 2E design gate (`APPROVED_REVIEW_ORDER`, 2026-11-07)

**Owner decision (scope only):** Review the proposed `phase1e_gpu005_reference_technical_specification.md` algorithm, expected-output schema, and fixed vectors **before** considering conditional approval of the entire Phase 2E design. This authorizes a **documentation/design review only**, not adoption of the proposed generator, code changes, or the Phase 2E gate.

**Source review findings — `P2E-GPU005B-DEC-01 = APPROVED_DESIGN` (2026-11-07):**

| Area | Current GPU-005-B proposal | Design-review consequence |
|---|---|---|
| Determinism | Public SHA-256 domain-separated derivation `demo-v1-public1`; fixed Job/Listing/Worker/count/duration/profile input | Reproducible; no server-held key or unguessable private input is used |
| Trust boundary | Public derivation inputs are in the approved Manager-to-Simulator dispatch; `algorithm_version` is public/frozen in the proposed design | Simulator can recompute the proposed expected outcome/digest *without* SQL access. Protected DB storage does not imply unpredictability |
| Claim versus proof | ADR-004 signs the claim and binds Worker/Job/Attempt; reference comparison is a separate Dispute decision | Correct Ed25519 signature proves the signed claim's provenance/integrity, **not actual GPU execution**; public oracle does not prevent a malicious Simulator from emitting the expected answer |
| Mock reputation | Proposed 80% SUCCESS, 10% WORKER_FAULT, 10% JOB_FAULT buckets | Synthetic WORKER_FAULT frequency is not evidence of real Worker misconduct; explicitly label reputation as mock metrics |
| Versioning | `demo-v1` dispatch profile without `algorithm_version`; `demo-v1-public1` stored in protected reference | Pin exact version per compatible Simulator implementation, or propose and review a versioned protocol change. No silent alteration to `demo-v1` semantics |
| Test evidence | Four documented vectors including rejection-sampling case; author calculation marked verified | Runtime interop, PostgreSQL atomicity, authorization, crash/replay and dispute tests are still `NOT_RUN` |

**Owner-selected trust-model option (A selected, B outside current MVP scope):**

- **A — APPROVED_DESIGN: Public, reproducible mock reference:** Keep deterministic public reference for simulation-only demonstrator; explicitly state that it is a *separately persisted comparison baseline*, **not** a secret anti-cheating oracle or proof of real work. Keep protected DB writes/reads, fixed vectors and once-only dispute corrections. Review exact bytes, distribution and version lock as separate follow-ups. This preserves existing 5-service/18-table architecture.
- **B — Require non-predictable independent assessment:** Do not approve GPU-005-B public algorithm as the truth model; require TV5/TV3/TV2 to redesign how an honest Simulator can produce verifiable results **without receiving private answers**. Merely adding an HMAC secret on server-side expected digest is **insufficient**: it will make the honest Simulator unable to reproduce its expected output unless the protocol/workload is also redesigned. The redesign needs cross-owner ACK and contract impact assessment.

**Safety gate:** This section approves **only the public deterministic trust model**. The exact SHA-256/JCS/seed/rejection derivation was approved separately under `P2E-GPU005B-DEC-02`, and the synthetic outcome distribution subsequently under `P2E-GPU005B-DEC-03`. The `work_units` mapping/range and expected-output schema were separately **APPROVED_DESIGN** afterward via `P2E-GPU005B-DEC-04`. V1-V4 normative mock test vectors were later **APPROVED_DESIGN** under `P2E-GPU005B-DEC-05`, and the frozen version mapping/compatible rollout was subsequently **APPROVED_DESIGN** under `P2E-GPU005B-DEC-06`; the logical reference access policy was later approved via `P2E-GPU005B-DEC-07`, and the complete GPU-005-B design was subsequently approved **conditionally** via `P2E-GPU005B-GATE-01`; physical DB grants and runtime acceptance tests remain unapproved/not run. Phase 2E is `APPROVED_DESIGN_CONDITIONAL`; the checked-in GPU-005-B remains `PROPOSED / NOT OWNER APPROVED`; runtime and integration tests remain `NOT_RUN`.

## 5.2. `P2E-GPU005B-DEC-01` — Owner-approved public reference trust model (`APPROVED_DESIGN`, 2026-11-07)

The owner selected option **A**: retain a **public, deterministic, reproducible** `demo-v1-public1` reference derivation as the **MVP simulation baseline**, while explicitly refusing to claim that it is an unguessable oracle, fraud detection, attested GPU execution, or evidence that a Worker actually used physical compute. The Backend must still create and protect the reference in `TX-SUBMIT`, keep it out of public DTOs and Simulator payloads, and use it in the separately approved Phase 3 dispute process; public reconstructability is **not permission to expose the stored reference row or grant Simulator DB access**.

**Remaining boundaries:** Public trust-model acceptance (`DEC-01`) did not approve exact derivation bytes, but these are now independently approved by `DEC-02`; synthetic outcome mapping is now approved by `DEC-03`. Output schema and work-unit range have since been approved through `P2E-GPU005B-DEC-04`; fixture acceptance was subsequently approved through `P2E-GPU005B-DEC-05`; runtime deployment version compatibility has subsequently been approved by `P2E-GPU005B-DEC-06`; reference **logical access policy** has since been approved under `P2E-GPU005B-DEC-07`; physical SQL grants and implementation-specific claim-to-reputation fairness checks remain pending. The approved 80/10/10 synthetic outcome mapping must be described as **mock bucket distribution, not measured real Worker performance or wrongdoing**. ADR-004 Signed Result remains only a provenance/integrity claim. No implementation permission is granted.

### Independent calculation review of existing four draft vectors (documentation verification only)

The four declared fixtures were recomputed locally from the documented SHA-256 prefix/domain/counter and deterministic JSON inputs. For these basic ASCII/integer/null fixtures, sorted/minified JSON agrees with the supplied canonical representation. This **is not** an application implementation, a cross-runtime RFC 8785 test, a working SQL verifier, or a runtime test. The computed values match the GPU-005-B examples, subsequently adopted as normative mock test fixtures under `P2E-GPU005B-DEC-05`:

| Reference vector | `duration_seconds` | Mapped outcome | `seed_value` | `work_units` | `expected_digest` (SHA-256 hex) | Recalculation |
|---|---:|---|---:|---:|---|---|
| V1 | 60 | `SUCCESS` | `3035342533442321017` | 522303 | `a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c` | `MATCH` |
| V2 | 2 | `FAILED / WORKER_FAULT` | `8887054454783268118` | 634290 | `9baaaaa338423c75753ecbd00da615a1f88a006eeb0a512d432635664754b7bf` | `MATCH` |
| V3 | 1 | `FAILED / JOB_FAULT` | `2063102514678027846` | 490818 | `f1c9d8e371bd4e6876a73b2414c285c6362fe01bca4d8d432169f4d484b3d749` | `MATCH` |
| V4 | 60 | `SUCCESS` with `work_units` rejection at counter 0 and acceptance at counter 1 | `2240287873181493078` | 562456 | `ad2212d44fef948b303afb1e5d5d8e9435eeab64f6701c54cafc3c6f3fd77aa7` | `MATCH` |

Vector V4 additionally matches `work_units_raw(0)=4294735637` (rejected because it is >= 4294000000) and `work_units_raw(1)=316562456` (accepted), as well as all four declared `outcome_raw` values. **The exact derivation formula is approved by `DEC-02` and mock outcome buckets by `DEC-03`.** Fixture outcomes/digests were **APPROVED_DESIGN** as normative versioned mock test vectors by `P2E-GPU005B-DEC-05`; independent runtime interoperability tests remain `NOT_RUN`. All application, real PostgreSQL and cross-runtime tests remain `NOT_RUN`.

### `P2E-GPU005B-DEC-02` — Public SHA-256 / JCS derivation (`APPROVED_DESIGN`, 2026-11-07)

**Owner decision:** Select **Option A** and freeze **the deterministic derivation mechanism only** for the simulation-only MVP, matching the existing GPU-005-B proposal; do **not** authorize code, database migration, or alteration of the GitHub source.

**Exact approved byte-level rules:**

- `algorithm_version = "demo-v1-public1"` is the immutable identifier for this derivation mechanism; breaking changes require a separately reviewed version/protocol decision.
- `PREFIX_UTF8` is the UTF-8 byte string `GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1` followed by exactly one LF (`0x0A`); `LF` separators in the formula are exactly one `0x0A`, not CRLF.
- Canonical input `I = UTF8(JCS_RFC8785(input_object))`, with no appended final newline. The proposed input keys are `algorithm_version`, `duration_seconds`, `job_id`, `listing_id`, `requested_gpu_count`, `worker_id`, `workload_profile`; changing the input contract requires review, not a silent implementation choice.
- Hash derivation: `H(D,C) = SHA256(PREFIX_UTF8 || UTF8(D) || LF || I || LF || UINT32_BE(C))`, where `D` is one of the exact lowercase ASCII domain tags `seed`, `outcome`, `work_units`; `C` starts at 0 and is an unsigned, four-byte, **big-endian** counter.
- `seed_digest = H("seed",0)`; `seed_value = UINT64_BE(seed_digest[0:8]) & 0x7FFFFFFFFFFFFFFF`, an integer in the range `0` to `2^63-1`, compatible with PostgreSQL signed BIGINT.
- For each proposed discrete mapping with range size `n`, derive candidate `r = UINT32_BE(H(D,C)[0:4])`, set `limit = floor(2^32/n)*n`; if `r >= limit`, increment `C` and retry; otherwise use `r mod n`. This is rejection sampling with no modulo-bias shortcut. Those values were deliberately **not approved by DEC-02 alone**; the bucket distribution was subsequently approved by `DEC-03`, and `work_units` `n=1000000`/range was subsequently approved by `DEC-04`.
- Preserve the distinction between public derivability and private database access: a deterministic published reference **is not** proof of GPU execution, but the Simulator still may not read protected `simulation_references`, receive an oracle reference, or access DB credentials.

**Non-approval scope:** DEC-02 on its own did not approve the outcome distribution, `work_units` range, expected-output JSON schema, V1-V4 fixtures as normative test vectors, deploy-version compatibility policy, runtime tests, or full GPU-005-B/Phase 2E gate. The deploy-version policy was subsequently approved by `P2E-GPU005B-DEC-06`. Distribution, schema/range and normative fixtures were subsequently approved independently under DEC-03, DEC-04 and DEC-05, respectively. No additional table, service, secret, or Signed Result V1 change is authorized.

**TV5 and TV2/TV3 follow-up:** Implementer-independent cross-runtime JCS/SHA-256 test vectors, valid/error paths for rejection sampling, DB reference creation in `TX-SUBMIT`, and a hard no-reference-in-dispatch boundary are design acceptance criteria to be verified **after** coding authorization; tests remain `NOT_RUN`.

### `P2E-GPU005B-DEC-03` — Synthetic 80/10/10 outcome mapping (`APPROVED_DESIGN`, 2026-11-07)

**Owner decision:** Approve **Option A**: retain the existing `n=100` outcome-bucket mapping under the previously approved public hash/JCS/rejection derivation. This is a **synthetic distribution of deterministic input buckets**, not a guaranteed 80/10/10 percentage in any finite set of Jobs or an empirical measure of real Worker fault.

| Unbiased bucket `b` | Simulated output `outcome` / `failure_reason` | Share of 100 buckets |
|---|---|---:|
| `0..79` | `SUCCESS` / `null` | 80% |
| `80..89` | `FAILED` / `WORKER_FAULT` | 10% |
| `90..99` | `FAILED` / `JOB_FAULT` | 10% |

**Exact mapping:** Set `n=100`, `limit=floor(2^32/100)*100=4294967200`, and derive `b = unbiased_mod_100(H("outcome",C))`, where a rejected 32-bit candidate causes increment of the four-byte unsigned big-endian counter. No alternate random source, local RNG seed, Worker-controlled probability override, or post-hoc skew is approved. The accepted `outcome` and `failure_reason` combinations must remain compatible with ADR-004 V1.

**Safety boundary:** A synthetic `WORKER_FAULT` category may affect demo reputation under already-approved once-only transaction rules, but is not proof of real Worker negligence. Historical tests and future Dispute simulations must label this as mock adjudication. DEC-03 on its own did not approve the output schema, `work_units` mapping/range, normative V1-V4 fixtures, rollout/version compatibility policy, grants, implementation, or the Phase 2E gate. The rollout/version policy was later approved by `P2E-GPU005B-DEC-06`. Output schema, work-unit mapping/range and the V1-V4 fixed fixtures were subsequently approved under DEC-04 and DEC-05; physical reference grants and implementation remain pending; version compatibility is approved under DEC-06 and the logical reference-access policy under DEC-07.

**Design tests to add (`NOT_RUN`):** `P2E-DIST-01`: buckets `0,79,80,89,90,99` map exactly; `P2E-DIST-02`: `4294967200..4294967295` are rejected, counter increments and retries; `P2E-DIST-03`: same canonical input/version yields the same bucket; `P2E-DIST-04`: mock reputation labels cannot be presented as measured real-world Worker reliability. Integration tests are not yet executed.

### `P2E-GPU005B-DEC-04` - Freeze nine-field output schema and work-unit range (`APPROVED_DESIGN`, 2026-11-07)

**Owner decision:** Select **Option A**. Freeze the canonical simulated-output JSON object with **exactly nine fields** matching the existing GPU-005-B proposal; no additional protected reference, secret, private key, `attempt_id`, `worker_id`, or field may be silently added to this digest object:

| Field | Approved constraint |
|---|---|
| `schema_version` | String exactly `"demo-v1"` (distinct from Signed Result V1 `schema_version="1"`) |
| `job_id` | Canonical lowercase UUIDv4 string matching the trusted Job input |
| `listing_id` | Canonical lowercase UUIDv4 string matching the trusted Listing input |
| `requested_gpu_count` | Positive integer matching the trusted input |
| `duration_seconds` | Positive integer matching the trusted input |
| `workload_profile` | String exactly `"demo-v1"` |
| `work_units` | Integer in `0..999999`, derived using `n=1000000` and previously approved SHA-256/JCS/rejection sampling |
| `outcome` | `"SUCCESS"` or `"FAILED"` per DEC-03 |
| `failure_reason` | `null` if SUCCESS; `"WORKER_FAULT"` or `"JOB_FAULT"` if FAILED per DEC-03 |

**Exact `work_units` rule:** `n=1000000`, `limit=floor(2^32/1000000)*1000000=4294000000`; derive `r=UINT32_BE(H("work_units",C)[0:4])` from `C=0`, reject and increment for `r>=limit`, otherwise `work_units=r%1000000`. The `expected_digest` is the string `sha256:` plus the lowercase hexadecimal SHA-256 of `UTF8(JCS_RFC8785(the_exact_nine_field_output_object))`, with no final newline. The signed receipt `result_digest` uses the corresponding digest rule without changing the eleven-field ADR-004 Signed Result V1.

**Trust and ownership boundary:** `TX-SUBMIT` persists the immutable, protected reference; no reference row or secret is dispatched to Simulator. Because the approved derivation is public, Simulator can independently compute the same expected mock value; this is a comparison baseline, **not** proof of real execution or a security secret. A schema alteration is a separately reviewed version change, not a silent V1 extension.

**Historical DEC-04 scope (now superseded in part):** DEC-04 did not itself approve normative V1-V4 fixtures; they were **subsequently approved** under DEC-05. Reference **physical DB grants**, cross-owner ACK, runtime/integration tests and the overall GPU-005-B/Phase 2E implementation gate remain pending; DEC-07 later approved the least-privilege **logical access design**. Key/version rollout compatibility was subsequently approved under `P2E-GPU005B-DEC-06`. The checked-in GitHub GPU-005-B source remains `DRAFT / PROPOSED / NOT OWNER APPROVED` until separately updated under an authorized repository workflow. Documentation work only; no GitHub modification or code authorization.

**Acceptance test designs (`NOT_RUN`):** `P2E-SCHEMA-01` checks exact nine fields and canonical types; `P2E-SCHEMA-02` checks `work_units` boundaries, modulo and rejection path; `P2E-SCHEMA-03` rejects extra/missing fields and wrong `schema_version`; `P2E-SCHEMA-04` checks matching JCS output digest in two independent runtimes; `P2E-SCHEMA-05` checks that protected reference fields never reach dispatch, API DTOs or Simulator DB access. TV2/TV3/TV5 integration ACKs are `PENDING`.

### `P2E-GPU005B-DEC-05` - Freeze V1-V4 as normative public reference fixtures (`APPROVED_DESIGN`, 2026-11-07)

The four existing GPU-005-B documentation vectors were independently recomputed against the **now-approved DEC-02/03/04** derivation, distribution and schema. The independent check reproduced the original integer values and SHA-256 digests. **This is a documentation calculation check only**, not proof that production application code, PostgreSQL transactions, or two runtime implementations work.

Shared input (unless overridden): `worker_id=11111111-1111-4111-8111-111111111111`, `listing_id=22222222-2222-4222-8222-222222222222`, `job_id=33333333-3333-4333-8333-333333333333`, `requested_gpu_count=2`, `workload_profile=demo-v1`, `algorithm_version=demo-v1-public1`.

| Fixture | `duration_seconds` | `seed_value` | `outcome_raw` | Result | `work_units` | SHA-256 digest (after `sha256:`) |
|---|---:|---:|---:|---|---:|---|
| V1 | 60 | `3035342533442321017` | `300757047` | `SUCCESS` / null | 522303 | `a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c` |
| V2 | 2 | `8887054454783268118` | `3227470086` | `FAILED / WORKER_FAULT` | 634290 | `9baaaaa338423c75753ecbd00da615a1f88a006eeb0a512d432635664754b7bf` |
| V3 | 1 | `2063102514678027846` | `3078813497` | `FAILED / JOB_FAULT` | 490818 | `f1c9d8e371bd4e6876a73b2414c285c6362fe01bca4d8d432169f4d484b3d749` |
| V4 | 60 | `2240287873181493078` | `632019716` | `SUCCESS` / null | 562456 | `ad2212d44fef948b303afb1e5d5d8e9435eeab64f6701c54cafc3c6f3fd77aa7` |

**V4 override and rejection path:** `job_id=33333333-3333-4333-8333-000000000c02`; initial `work_units_raw(0)=4294735637` is **rejected** because `>=4294000000`, next `work_units_raw(1)=316562456` is accepted and maps to `562456`. Preserve the exact fixed input/output JSON, prefix/LF bytes, zero-based big-endian counters and these expected digests as the **approved** normative mock interoperability fixtures. The word oracle here means an expected test result, not a secret anti-cheat authority.

**Owner decision:** Approve **Option A**: V1, V2, V3 and V4 from the existing GPU-005-B technical proposal are now the **fixed, versioned, normative mock test fixtures** for `demo-v1-public1`. Their inputs, canonical nine-field output objects, rejection paths, expected integers and expected SHA-256 digests must not be silently edited. The alternative, recomputing a different set of vectors, was not selected.

**Implementation acceptance tests (`NOT_RUN`):**

| Test ID | Acceptance evidence required after implementation authorization |
|---|---|
| `P2E-VEC-01` | For V1, implementation emits exactly the approved canonical output bytes, `seed_value`, `outcome_raw`, `work_units` and digest |
| `P2E-VEC-02` | For V2, a `WORKER_FAULT` fixture matches canonical bytes, computed values and digest |
| `P2E-VEC-03` | For V3, a `JOB_FAULT` fixture matches canonical bytes, computed values and digest |
| `P2E-VEC-04` | For V4, the first rejected `work_units` candidate advances the counter, then canonical bytes and digest match |
| `P2E-VEC-05` | Independent JCS implementations and SQL reference-creation boundary agree on all four fixtures; no protected fields are dispatched |

**Boundaries:** This decision approves normative documentation test fixtures, **not**, by itself, deployment/version compatibility, physical reference DB grants, cross-owner ACKs, the complete GPU-005-B gate, the Phase 2E gate or coding. The GPU-005-B design gate was subsequently approved conditionally via `P2E-GPU005B-GATE-01`; the Phase 2E gate was subsequently approved conditionally as `P2E-GATE-01`. The deployment/version rule was subsequently approved under `P2E-GPU005B-DEC-06`. All runtime and integration tests remain `NOT_RUN`.

### `P2E-GPU005B-DEC-06` - Freeze `demo-v1` mapping and compatible rollout (`APPROVED_DESIGN`, 2026-11-07)

**Owner decision:** Select **Option A**. Freeze `simulation_input={"workload_profile":"demo-v1"}` to the single deterministic `algorithm_version="demo-v1-public1"` for the entire current MVP; `TX-SUBMIT` persists that exact algorithm version. Neither Simulator dispatch nor ADR-004 V1 signed envelope gains a new `algorithm_version` field. No additional table/service is permitted by this decision.

**Compatibility contract:**

1. A redeployed/restarted Simulator must preserve the **same** nine-field canonical mock output and SHA-256 digest for any existing `demo-v1` Job, including V1-V4 fixture results, while Jobs can remain QUEUED/RUNNING or be retried.
2. A candidate release must pass compatibility preflight before being enabled to receive work. A mismatch is a deployment/blocking fault, not an excuse to rewrite an immutable `simulation_references` row or silently produce a different result. A rollback must also remain compatible.
3. An algorithm with different semantics needs a **new explicitly approved workload profile**, plus separately reviewed API Contract/dispatch changes, version migration and inter-owner change control. No silent in-place reinterpretation of `demo-v1` is allowed.
4. Historical signed-result evidence and archived Worker public keys stay verifiable per ADR-004; the reference algorithm version per accepted Job and all original signed evidence are immutable.
5. This decision is **architecture/design approval only**. TV1/TV2/TV3/TV5 must validate inter-service rollout behavior and record human ACKs. No commit, migration, deployment or runtime PASS is asserted.

**Required compatibility tests (`NOT_RUN`):**

| Test | Evidence required after future implementation authorization |
|---|---|
| `P2E-VERSION-01` | `TX-SUBMIT` pins `demo-v1-public1` while dispatch contains only `workload_profile=demo-v1` |
| `P2E-VERSION-02` | A compatible Simulator replacement reproduces the full V1-V4 corpus |
| `P2E-VERSION-03` | An incompatible same-profile implementation fails release preflight and does not silently alter Job truth |
| `P2E-VERSION-04` | QUEUED/RUNNING retries across process restart preserve expected digest, identity and immutable reference |
| `P2E-VERSION-05` | Historical ADR-004 V1 signed evidence remains verifiable after supported rollout |
| `P2E-VERSION-06` | Rollback selects a compatible previously validated build and preserves output bytes |

### `P2E-GPU005B-DEC-07` - Protected reference DB least-privilege policy (`APPROVED_DESIGN`, 2026-11-07)

**Design question:** `simulation_references` is a **Phase 1** table inserted atomically with a Job in API `TX-SUBMIT`, and read by trusted Manager/dispute logic later. It contains the pinned `seed_value`, outcome/reason and `expected_digest`. Even though the mock formula is public, the **stored reference row remains protected**: it must not be exposed as a public DTO, log, audit payload, Simulator input, Worker/Client query, or an unrestricted SQL table. The current approved DB design already requires strict read access and immutability, but exact Phase 2 service-role grants/allowed write path are not implemented or tested here.

| Option | Proposed authorization contract | Impact |
|---|---|---|
| **A - recommended** | **Least privilege:** use the existing scoped `gpm_api_app` role only through a tightly controlled `TX-SUBMIT` insert path (direct narrow INSERT with no broad SELECT, or an audited narrowly scoped DB function if necessary); trusted `gpm_manager_app` receives the **minimum necessary SELECT** to verify/read reference for permitted internal workflows. Neither normal runtime role gets unrestricted UPDATE/DELETE on reference. Client/Worker/Admin HTTP routes receive no reference, and Simulator has **zero PostgreSQL credentials or grants**. Only controlled Phase 3 adjudication/retention code may later be granted additional reviewed access. | Protects stored truth without new service or table; requires TV2 to verify Phase 1 role ownership, column grants, SQL/ORM statement shape, protected deletions and any required SECURITY DEFINER function against actual PostgreSQL. |
| B | Let both API and Manager share a broad SELECT/INSERT/UPDATE/DELETE permission set over `simulation_references` for development simplicity. | Easier initially but permits accidental oracle exposure/tampering; conflicts with the existing protected-reference and immutable-evidence boundaries. Not recommended. |

**Non-negotiable for either option:** A single successful `TX-SUBMIT` commit creates one `jobs` row and **exactly one immutable** reference; on any failure both roll back. `simulation_references.job_id` PK alone guarantees *at most* one, not mandatory existence. API replay of an existing Job must not create/replace a second reference. Manager never changes the reference. Public recomputability of a mock digest does **not** authorize DB read. Phase 2B's approved six-table migration scope is unchanged; no new column/table/role is implied. The physical grant/trigger migration and any narrower privileged function remain **PENDING review**, not pre-approved by a logical matrix.

**Required acceptance tests (`NOT_RUN`):** `P2E-ACL-01`: API create Job/reference atomic and replay preserve exact row; `P2E-ACL-02`: API cannot update/delete reference or broadly read its private columns; `P2E-ACL-03`: Manager's permitted SELECT succeeds but UPDATE/DELETE fails; `P2E-ACL-04`: Simulator cannot connect/query PostgreSQL or receive reference through dispatch; `P2E-ACL-05`: Client/Worker/Admin and public DTO/log/audit cannot access reference values; `P2E-ACL-06`: unauthorized direct delete/history mutation denied, future authorized cleanup still preserves dispute-held evidence. All tests are planned, not executed.

**Coordination:** TV2 defines and tests PostgreSQL privileges and transaction interface; TV5 verifies exact `TX-SUBMIT`/idempotency integration, TV1 confirms Manager access boundaries, TV3 checks absence of reference leakage into signing/callback/HTTP representations; actual ACKs are `PENDING`. Phase 3 exception/retention design must be reconciled through interphase change control.

**Owner decision `P2E-GPU005B-DEC-07 = APPROVED_DESIGN` (2026-11-07):** Approve **Option A (least privilege)**. Keep the existing two scoped runtime roles without adding a new table/service: `gpm_api_app` may insert the Job-linked immutable reference only as part of the tightly controlled atomic `TX-SUBMIT` path; `gpm_manager_app` may read only the columns required for trusted internal reference checks. Neither ordinary role receives general-purpose UPDATE/DELETE over the protected truth row; all Client/Worker/Admin HTTP views, Simulator dispatch/callback payloads, logs and audit output must exclude private reference columns. Simulator receives **no PostgreSQL credentials, grants or direct DB route**. Authorised Phase 3 dispute adjudication and evidence cleanup are separately reviewed, not silently expanded by this approval.

**Not authorised by DEC-07:** Physical `GRANT`/`REVOKE`, row/column protection, SQL/ORM statement shape, narrowly scoped privileged functions or trigger implementation are **not automatically approved**. TV2 must demonstrate the necessary least-privilege SQL path with real PostgreSQL, distinguish runtime roles from migration/maintenance privileges, and obtain TV1/TV3/TV5 interface ACKs before code rollout. `P2E-ACL-01..06` all remain `NOT_RUN`. The source GPU-005-B document on GitHub still shows `NOT OWNER APPROVED` until a separately authorised repository documentation update.

### `P2E-GPU005B-GATE-01` — Conditional approval of GPU-005-B technical design (`APPROVED_DESIGN_CONDITIONAL`, 2026-11-07)

**Owner decision:** **Option A approved**. The GPU-005-B deterministic simulation reference **design only** is accepted conditionally for the simulation-only MVP. The approval binds the previously reviewed and accepted decisions `P2E-GPU005B-DEC-01..07` without modifying their byte-level constants, frozen output schema, 80/10/10 mock buckets, version mapping, or normative V1-V4 fixtures. It also preserves the explicit limitation that a public mock reference is **not** proof of real GPU work, an unpredictable oracle or resistance to a dishonest Simulator.

| Decision | Approved technical-design scope | Status |
|---|---|---|
| `DEC-01` | Public deterministic mock reference; clearly not real-GPU execution proof | `APPROVED_DESIGN` |
| `DEC-02` | Byte-exact SHA-256/JCS derivation, domain separation and rejection sampling | `APPROVED_DESIGN` |
| `DEC-03` | Synthetic `SUCCESS/WORKER_FAULT/JOB_FAULT` 80/10/10 mapping | `APPROVED_DESIGN` |
| `DEC-04` | Exact nine-field output schema; `work_units=0..999999` | `APPROVED_DESIGN` |
| `DEC-05` | Normative fixed V1-V4 simulation fixtures and their digest values | `APPROVED_DESIGN` |
| `DEC-06` | Frozen `demo-v1 -> demo-v1-public1` compatibility | `APPROVED_DESIGN` |
| `DEC-07` | Least-privilege reference access and immutable atomic `TX-SUBMIT` design | `APPROVED_DESIGN` |
| `P2E-GPU005B-GATE-01` | Entire GPU-005-B design, subject to the outstanding conditions below | **`APPROVED_DESIGN_CONDITIONAL`** |

**Mandatory unresolved conditions — not waived by this design approval:**

1. **TV2 + TV5 / real PostgreSQL:** demonstrate Job/reference atomicity, correct unique/immutable record, exact least-privilege grants or trusted function, API narrow insert, Manager permitted read, denied updates/deletes, and guarded maintenance. `P2E-ACL-01..06` remain `NOT_RUN`.
2. **TV3 + TV5 / wire and trust:** independently check JCS/SHA-256/Ed25519 V1 compatibility, V1-V4 fixtures, no reference leakage into Simulator dispatch, callback, public DTO or logs, and claim-vs-reference separation. Mock predictability is explicitly accepted, not hidden.
3. **TV1 + TV3 + TV5 / restart and replay:** finish `P2E-CACHE-GAP-01` before code: an in-memory Simulator cache does **not** prove conflict recognition after restart/eviction; preserve exactly-once *business effects*, not exactly-once *execution*. Define bounded cache behavior and test the rejected-conflict path without inventing a new DB role/service/table.
4. **TV2 + TV4 + TV5 / PAUSED boundary:** preserve the **already owner-approved** TX-SUBMIT replay after Listing PAUSED (PR #39 decision #6690901724: same retained Client/key/normalized body -> original Job, HTTP 200; changed body -> 409; new key still requires ACTIVE). The **remaining work is cross-owner ACK and deterministic concurrency/HTTP evidence**, not a new business-rule decision. Separately, `P2D-OPEN-02` permits redelivery of an already `RUNNING` Attempt while PAUSED, never a new allocation.
5. **TV1 + TV2 + TV3 + TV5 / finalization:** confirm the typed verifier contract `P2E-VERDICT-CONTRACT-01`, authorization, stable receipt identity, on-time durable Inbox before fallback, terminal/release/contribution transaction, race/rollback and restart tests. Obtain real human ACKs and record links.
6. **Implementation/start gate:** Phase 1 accepted integrated baseline on `main`, interface ACKs, physical schema/permissions review, and a **separate explicit coding authorization** must precede implementation. The checked-in GPU-005-B source on GitHub still says `DRAFT — NOT OWNER APPROVED` because **this approval is documented locally only**; no GitHub write or status change has occurred.

**Evidence status:** The fixed V1-V4 *documentation calculations* were reviewed; they do not establish runtime compliance. `P2E-VEC-01..05`, `P2E-SCHEMA-01..05`, `P2E-DIST-01..04`, `P2E-VERSION-01..06`, `P2E-ACL-01..06` and all real HTTP/DB/Manager concurrency/security tests remain `NOT_RUN`, never `PASS` by implication.

**Explicit non-authorization:** This conditional approval does not permit implementing the generator, changing DB grants, migrating schemas, sending GitHub comments, changing GitHub files, merging PRs, or starting Phase 2 code. Do not mislabel actual TV2/TV3/TV4/TV5 ACKs as obtained.

### `P2E-GATE-01`: Conditional approval of the entire Phase 2E design (`APPROVED_DESIGN_CONDITIONAL`, 2026-11-07)

**What is already approved at the design level:** `P2E-OPEN-01` Simulator cache and replay boundaries, `P2E-OPEN-02` typed verifier-to-finalizer/UoW integration, `P2E-OPEN-03` once-only contribution ledger + aggregate transaction, `P2E-OPEN-04` ordered review, and the GPU-005-B technical reference **conditionally** under `P2E-GPU005B-GATE-01`.

**Still PENDING for implementation:** `P2E-CACHE-GAP-01` restart/eviction conflict handling, typed contract details `P2E-VERDICT-CONTRACT-01`, actual DB grants and SQL/UoW shapes, **evidence/ACK for the already-approved PAUSED Listing TX-SUBMIT replay**, inter-owner ACKs, test execution and accepted Phase 1 integration baseline. The four other Phase 2A-2D design packages were conditionally approved, not implemented by these local reviews.

**Owner decision (2026-11-07): Option A selected, `P2E-GATE-01 = APPROVED_DESIGN_CONDITIONAL`.** The team lead approves the complete Phase 2E design package for documentation review, subject to the unresolved conditions listed below. This approval **does not waive** `P2E-CACHE-GAP-01`, `P2E-VERDICT-CONTRACT-01`, PAUSED Listing replay **integration evidence/ACK** (business rule already approved on PR #39), real PostgreSQL ACL verification, cross-owner ACKs, Phase 1 accepted baseline or the explicit separate implementation authorization. **Code, GitHub writes, PR merges, schema migration, deployment and operational activation are NOT authorized** by this decision.

### `P2E-GATE-01` — Mandatory cross-owner closure checklist (still PENDING)

| Blocker / evidence ID | Required closure | Required owners | State |
|---|---|---|---|
| `P2E-CACHE-GAP-01` | Reconcile immutable dispatch/request-conflict contract with in-memory Simulator cache loss on restart/eviction without adding a DB connection or unapproved storage | TV1 + TV3 + TV5 | `PENDING` |
| `P2E-VERDICT-CONTRACT-01` | Freeze typed verifier output, original Inbox identity, Job/Attempt binding, same-transaction finalization and error handling | TV1 + TV2 + TV3 + TV5 | `PENDING` |
| `P2E-SUBMIT-PAUSED-01` | **Owner decision DONE** in PR #39 comment #6690901724: same retained key/body -> 200 even while PAUSED; changed request -> conflict, new key requires ACTIVE. Verify compatibility ACK + real barrier/HTTP tests; do not confuse with dispatch retry of RUNNING Attempt. | TV2 + TV4 + TV5 | `OWNER_APPROVED / PENDING_ACK_AND_TESTS` |
| `P2E-DB-ACL-01` | Verify real SQL/ORM privilege path for reference INSERT/read, raw Inbox replay and protected immutable evidence on disposable PostgreSQL | TV2 + TV3 + TV5 | `PENDING_TEST` |
| `P2E-RUNTIME-01` | Run V1-V4, Ed25519/JCS, restart, timeout, exactly-once release/reputation, concurrency and Compose E2E tests after code authorization | TV1 with TV2–TV5 | `NOT_RUN` |
| `P2-PHASE1-BASE-01` | Confirm accepted integrated Phase 1 on main, exact Git SHA, actual Alembic heads and CI/E2E evidence; do not infer PR merge state | TV1 + TV2 and affected owners | `PENDING_VERIFICATION` |
| `P2-ACK-01` | Record explicit signed-off interface ACKs from every affected owner; no inferred ACKs | TV1–TV5 | `PENDING` |
| `P2-START-01` | Separate recorded decision authorizing implementation after the pre-code blockers close | Team lead | `NOT_AUTHORIZED` |

**Gate distinction:** The `NOT_RUN` runtime tests are **not pre-code requirements**; they become mandatory acceptance evidence before merge/deployment, *after* explicit authorization to implement. Pre-code gating requires accepted Phase 1 baseline, decisions/contracts/ACKs and a new owner authorization. This conditional design approval is not that authorization.

## 6. Test design and gates

- Plan `DBTX-07-OUTBOX-FENCE`, `DBTX-08-INBOX-REPLAY`, `DBTX-09-ON-TIME-DELAY`, `DBTX-10-EXACT-DEADLINE`, `DBTX-11-INVALID-PENDING`, `DBTX-12-REPUTATION-REPLAY`, `ENUM-01..06`, `WIRE-01..07`, `E2E-01` and `E2E-02` with real PostgreSQL/trusted clock and negative signature fixtures.
- Document role-safe result/Job read acceptance, UI updates and privacy constraints; no raw signed evidence, oracle or private keys in public DTOs.
- **Docs exit:** approved-compatible execution/result diagrams, truth-vs-claim note, exact-once/cancel race plan, cross-owner handoff, unresolved decision statuses. **Runtime status:** `NOT_RUN`.

## Approved design references

- [SRS](../../../requirements.md), [FR](../../../functional-requirements.md), [NFR](../../../non-functional-requirements.md).
- [System Architecture](../../system-architecture.md), [Module Design](../../../design/module-design.md), [Database Design](../../../design/database-design.md), [API Contract](../../../design/api-contract.md), [Test Design](../../../design/test-design.md).
- [ADR-001 to ADR-008](../../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), ADR-004 (signed result) and ADR-005 (retries and deadlines).
- [Phase 1E](../phase1e_job_submission_queue.md), [GPU-005-B reference specification](../phase1e_gpu005_reference_technical_specification.md), and the current [TV5 Phase 2E baseline](../../../development/handoffs/phase2/tv5-p2e-precode/TV5_BASELINE.md), [decision register](../../../development/handoffs/phase2/tv5-p2e-precode/TV5_OPEN_DECISIONS.md) and [test/release plan](../../../development/handoffs/phase2/tv5-p2e-precode/TV5_TEST_AND_RELEASE_PLAN.md).

Only the existing approved baselines are normative. Phase 2A-2D have **conditional design** approvals; Phase 2E is `APPROVED_DESIGN_CONDITIONAL`. **`P2E-OPEN-01` and `P2E-OPEN-02` are approved at design scope**, with unresolved implementation conditions `P2E-CACHE-GAP-01`, `P2E-VERDICT-CONTRACT-01` and bounded cache policy. `P2E-OPEN-03` has been approved at design scope (once-only contribution ledger + aggregate UoW). `P2E-OPEN-04` approved the **review-first order only**. The limitation `P2E-ORACLE-INDEPENDENCE-01` is accepted for the simulation-only MVP via `P2E-GPU005B-DEC-01`; the deterministic derivation formula is `APPROVED_DESIGN` via `P2E-GPU005B-DEC-02`; the synthetic 80/10/10 outcome mapping is `APPROVED_DESIGN` via `P2E-GPU005B-DEC-03`; the exact nine-field output schema and `work_units=0..999999` are `APPROVED_DESIGN` via `P2E-GPU005B-DEC-04`; V1-V4 normative mock fixtures are `APPROVED_DESIGN` via `P2E-GPU005B-DEC-05`, and frozen `demo-v1 -> demo-v1-public1` compatibility is `APPROVED_DESIGN` via `P2E-GPU005B-DEC-06`. The frozen rollout/version policy (`DEC-06`) and least-privilege reference access **design** (`DEC-07`) are `APPROVED_DESIGN`; exact SQL grants, cross-owner ACK and runtime tests remain pending, while GPU-005-B design gate (`P2E-GPU005B-GATE-01`) is now conditionally approved. This docs package does not execute any Phase 2 tests (`NOT_RUN`).

## Appendix PR39-E (2026-11-07): Simulator replays and exactly-once business effect

**Status:** `DESIGN-SUPPLEMENT / EXTERNAL WIRE ACK PENDING / NO CODE AUTHORIZED`.

### E1. Reuse the approved Phase 1 generator without conflating approval scopes

PR #39 includes the implemented `jobs/reference.py` generator and Phase 1 reference vectors V1-V4. Owner approval on PR #39 covers **TX-SUBMIT reference creation** only. The Phase 2 conditional design model (`demo-v1` → `demo-v1-public1`, nine-field output, 80/10/10 outcomes, `work_units=0..999999`, and V1-V4 test oracles) is recorded in this Phase2E spec and was included in the PR #44 documentation intake merged to main. This design record does not demonstrate a running Phase 2 Simulator or signed receipt and does not authorize implementation.

### E2. Make RAM cache and crash behavior truthful (resolves the design wording conflict)

- **During a live Simulator process with a retained cache entry:** same `attempt_id` + identical immutable dispatch bytes uses the same cached execution state/result; same `attempt_id` + conflicting dispatch bytes returns `409 EXECUTION_CONFLICT`. The key is the logical Attempt and verified request bytes/fingerprint; cache entries have explicit memory/TTL bounds.
- **After cache eviction or Simulator restart:** RAM alone cannot prove whether a conflicting old request existed. Do **not** claim that cross-restart conflict detection is guaranteed. The trusted Manager/DB/Outbox must store one immutable dispatch payload and retry **exactly those bytes** under the stable `outbox_event_id` and `attempt_id`; a caller without the correct dispatch Bearer is rejected.
- A cold replay may recompute the deterministic nine-field simulation output but produce a **new signed envelope and new `result_id`** if no original signed envelope survived. That is **not** a byte-identical replay of the original `result_id`; do not falsely return `202 DUPLICATE` for a new ID. PostgreSQL Inbox and Finalization enforce at most one accepted result per Job and no double release/reputation.
- If Simulator still has the original signed envelope for a callback retry, it must retransmit **the same original `result_id` and exact raw envelope bytes**; never regenerate `finished_at` or a signature during that retry.
- With no persisted Simulator cache, the MVP promises **at-least-once execution delivery and exactly-once business effect**, not exactly-once computation or perfect detection of a malicious conflicting same-Attempt request across cold restart. A stronger global conflict guarantee would require a separate owner-approved persistent Simulator state or cryptographically bound request protocol change.

### E3. Multiple distinct signed candidates for the same Attempt

Suppose after Simulator restart two authenticated callbacks for one Job arrive with **different** `result_id` values. The API can durably store eligible on-time candidates independently (subject to approved ingress constraints); they are not identical replay. Manager processes bounded candidates deterministically by trusted `(received_at, inbox_row_id)`: reject invalid candidates and continue, accept the first verified/context-eligible one, and mark later candidates superseded/rejected without changing the accepted immutable result. The `signed_results` Job uniqueness, terminal state and contribution uniqueness enforce one business outcome. **The exact Inbox state labels and locked candidate-selection SQL require TV2/TV3/TV5 ACK**; no new table is added.

At deadline, a previously admitted on-time Inbox candidate must be exhausted/considered before `SYSTEM_FAULT`; a receipt that first acquires the Job lock at or after `hard_deadline_at` cannot be admitted as new. Local or worker `finished_at` must not move this boundary.

### E4. Atomic reputation/finalization and signer prerequisite

Under Listing -> Job locks, recheck live Job/Attempt, persisted Inbox timestamp/evidence, signer, accepted-result uniqueness and available allocation. In **one PostgreSQL commit**, accept immutable Signed Result, finalize Job, release GPU once, mark Inbox processed, insert at most one `job_reputation_contributions` record and update aggregate counters only for `SUCCESS`/`WORKER_FAULT`; `JOB_FAULT` => contribution `NONE`/zero delta; Manager `SYSTEM_FAULT` timeout => no contribution. Do not create a second contribution for a replayed receipt.

Before dispatch, ensure the Worker has one active registered public key and the Simulator has corresponding privately provisioned signing material available across restart. If not, fail closed rather than simulate a signed receipt without valid key provenance. No private keys, protected reference bytes or secrets are in dispatch, Inbox public DTO or logs.

### E5. Focused owner/test handoff

TV5 -> TV3: exact V1 payload/envelope bytes, signature encoding, version and invalid-field oracles. TV5 -> TV2: contribution state transitions, raw signed-result evidence and crash/duplicate cases. TV5 -> TV4: PAUSED RUNNING retry and no second allocation. TV5 -> TV1: signed callback client, cache and restart behavior, progress/fallback metrics.

Tests needed: duplicate and conflicting dispatch while cache live; cold restart with *new* result ID; original callback lost ACK; two different valid callback IDs; invalid first candidate then valid candidate; on-time persisted candidate verified after deadline; no post-deadline new admission; crash before/after finalization commit; no double reputation or GPU release. All are `NOT_RUN` as Phase 2 runtime tests.


---

## Appendix DR-E — Deep review v1.8: simulator ↔ verifier ↔ finalizer ↔ reputation

> **Scope and status:** `DOCUMENTATION_REVIEW / DESIGN_SUPPLEMENT / PENDING_CROSS_OWNER_ACK`. Preserve existing `P2E-GATE-01 = APPROVED_DESIGN_CONDITIONAL`; this appendix is **not** a separate approval of exact Python interfaces, SQL, secrets provisioning, physical grants, incident-policy tradeoffs, or implementation. The earlier historical decisions are superseded only where this addendum explicitly documents an already-approved decision. All Phase 2 execution/verification/finalization tests below remain `NOT_RUN`.

### DR-E1. Verified source baseline and approval precedence

| Subject | Evidence-supported statement | Boundary |
|---|---|---|
| Phase 1 integration | [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39): `CLOSED / MERGED`; reviewed head `3482bce3cc9726543b9345a5224d8db1b9fc6454`; merge commit `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`; current base `main@bee832eaf5463df20f6c6815174322871eb6685a` | Live GitHub state checked 2026-11-08. No Phase 2 Manager/Signed Result/Simulator runtime is established by this merge |
| Phase 1 CI | [Actions run #42385995533](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533): SUCCESS on exact PR #39 head `3482bce3cc9726543b9345a5224d8db1b9fc6454` | Phase 1 baseline evidence only; not Phase 2 runtime PASS |
| Existing Manager | `backend/src/gpu_marketplace/manager/service.py` remains the foundation idle runner | Three Phase 2 loops, signer/verifier and terminalization are **not yet runtime features** on this branch |
| Phase 1 protected reference | `backend/src/gpu_marketplace/jobs/reference.py` contains `demo-v1-public1` deterministic reference generator; vectors V1–V4 tested in Phase 1 | Phase 1 owner approval #6690901724 covers TX-SUBMIT reference persistence; separate **local** Phase 2E design approved conditionally; GitHub Phase 2 output status not synchronized |
| `P2E-SUBMIT-PAUSED-01` | **OWNER_DECISION_DONE** at [#6690901724](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6690901724) | Same Client/key/request fingerprint -> 200 original Job while PAUSED; different body -> 409; new key still requires ACTIVE. Outstanding items are tests and TV2/TV4/TV5 ACK, **not a decision** |
| Signed Result V1 and retry | ADR-003/004/005, API Contract §13 and Database Design §11 are authoritative | V1's 11 signed fields, Ed25519/JCS bytes, immutable raw evidence, exactly-once business effect and fixed 120-second grace cannot be loosened by this review |

**Review evidence qualification:** some earlier P2 findings on PR #39 remain in human reviews (Jobs/Listing mutation audit, deterministic Submit ↔ Pause/Resize barriers, and cross-test-cluster role credential isolation). PR #42 adds an Auth E2E credential snapshot/restore helper; the prior Phase 1 journey test was **not** among the six changed paths in the new PR39 delta. Do not automatically mark its isolation finding solved. C1 Scrypt and readiness L2 remain separate Phase 1 gates. Cross-owner reviews on old SHAs cannot be presented as approval of the entire newer diff without a documented change-impact review.

### DR-E2. Honest Simulator execution contract; cross-restart gap remains open

**Immutable inputs:** `POST /internal/v1/executions` uses the accepted dispatch DTO, stable `outbox_event_id` and `attempt_id`, and `simulation_input` exactly `{"workload_profile":"demo-v1"}`. The Job's `gpu_count` in dispatch corresponds to `requested_gpu_count` in the seven-key canonical reference input; only the *approved immutable Job/Listing/Worker/duration/gpu-count fields* enter deterministic output, not `attempt_id`, event ID, worker-signing key or worker-supplied timestamps. `finish_due_at` and `hard_deadline_at` in dispatch are retry hints; the database is the time authority. No reference row, expected digest, `seed_value`, SQL credential, bearer secret or private key is permitted in the HTTP JSON body.

**Live cache (`P2E-OPEN-01` already owner-approved):** a bounded concurrent-safe cache keyed `attempt_id`, bound to one strictly normalized immutable request, has distinct `IN_FLIGHT`/`FINISHED` *in-memory* states; these are not DB statuses. Identical duplicate dispatch while entry is retained acknowledges the same work; contradictory reuse returns `409 EXECUTION_CONFLICT`; retries of an existing signed result use its original full envelope, `result_id`, `finished_at` and signature byte-for-byte. Cache capacity, TTL, eviction while in-flight, admission limits and handling shutdown are **PENDING_PARAMS**; eviction must never create an additional DB Attempt or move a hard deadline.

**Cold restart:** without its previous RAM entry, the Simulator may perform one **new physical mock execution** of the *same durable logical attempt*. That execution can produce a **different `result_id` and freshly signed envelope**, but must generate the same frozen nine-field *mock output and digest* under the same Job/reference version. New result ID => a separate Inbox candidate, never `202 DUPLICATE` on account of only matching `attempt_id`. Retained old receipt retry => identical bytes and `result_id`.

**`P2E-CACHE-GAP-01` remains a real pre-code design blocker:** the local cache alone cannot enforce the API Contract's **global** `409 EXECUTION_CONFLICT` after eviction/restart if a correctly authenticated party sends a same-`attempt_id` but altered immutable dispatch. Preserving the Manager's single immutable Outbox payload and denying invalid tokens prevents *honest Manager drift* and unauthenticated traffic, but does **not** cryptographically prove the same request was seen previously by a restarted Simulator. Do **not** claim it is solved by PostgreSQL's unique Job/Outbox constraints or by once-only finalization. Affected owners need to review/decide either (A) an approved verification/authorization path against existing trusted persisted dispatch state, with explicit transport contract change and no Simulator DB access; or (B) an explicit change-control qualification of the cross-restart conflict guarantee, retaining strict fail-closed behavior when state is present. Both are **PENDING_OWNER_DECISION / ACK**; neither option is silently selected here.

### DR-E3. Frozen deterministic-output and signed-result byte boundaries

- **Public mock output:** freeze `demo-v1`/`demo-v1-public1`, exactly **nine** JSON properties `schema_version`, `job_id`, `listing_id`, `requested_gpu_count`, `duration_seconds`, `workload_profile`, `work_units`, `outcome`, `failure_reason`. The digest is `"sha256:" + sha256(UTF8(JCS_RFC8785(output_object))).hexdigest()`; `work_units` is `0..999999` and the 80/10/10 bucket maps only the three approved outcome classifications. Fixed vectors V1–V4, including V4 rejection sampling, are normative for the mock. The Phase 1 `json.dumps(sort_keys=True)` generator relies on its restricted ASCII/32-bit-number domain; **do not** generalize that to arbitrary Unicode/floating-point RFC8785 input without a conforming JCS implementation.
- **Signed Result V1:** distinct `schema_version="1"`, exactly **11 signed payload fields**, signing bytes `b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n" + UTF8(JCS_RFC8785(payload))`, canonical UUIDv4 lowercase and microsecond UTC `finished_at`, 64-byte Ed25519 signature encoded as exactly 86 unpadded base64url characters. Verify against trusted `(worker_id,key_id)` registered public key, not a key supplied in callback. No `algorithm_version` may be inserted into signed V1 or dispatch without approved versioned change.
- **Signer provenance:** Worker private material is provisioned to the Simulator's secret boundary, never DB/API/Manager, and its registered public key is bound to the Worker. Key readiness and storage/recovery on restart require TV1/TV2/TV3/TV5 ACK. Planned retirement preserves historical public verification and must not race a RUNNING Attempt. The emergency compromised-key response **remains `NEEDS_OWNER_DECISION`**, not an implicit reason to accept forged evidence or mutate historical signed bytes.
- **Honesty:** a signed claim does not prove real GPU work, and a public deterministic mock is not anti-cheat. `WORKER_FAULT` buckets are synthetic and should not be presented as measurements of real Worker reliability.

### DR-E4. Raw callback ingress versus accepted result

The API checks the dedicated `SIMULATOR_CALLBACK_TOKEN` **before** any private Inbox lookup or INSERT; end-user JWT and opposite-direction Manager token are rejected. Strict envelope keys/types, raw body limits, duplicate-key/invalid-Unicode detection and RFC8785/I-JSON checks use TV3's reviewed parser budget (`PENDING_PARAMS`). The API captures the *actual received raw bytes*, not a reserialized object, in the persisted Inbox and returns `202 STORED` only after **known successful COMMIT**; `202` never means signature-verification or Job success.

For an existing retained `result_id`: same original **raw envelope bytes** and same trusted bound context -> `202 DUPLICATE`, including after Job terminalization, with unchanged trusted `received_at`; differing raw bytes -> `409 RESULT_ID_COLLISION`. If two concurrent INSERTs race, PostgreSQL unique constraint is authoritative: losing transaction rolls back and reads the committed winner in a fresh read transaction, then compares exact bytes and trusted context. SHA-256 is only an indexable prefilter, never a substitute for exact equality. New `result_id` after Job terminal or after equality deadline is **not** admitted. Invalid cryptographic signature of a *strictly well-formed* bound envelope is a later Manager rejection, not API HTTP ingress confirmation of validity.

To admit a new, bounded candidate: under **Listing → Job** locks, recheck RUNNING and the actual Attempt, then sample DB-trusted `received_at = clock_timestamp()` **after acquiring Job lock**, strictly require `< hard_deadline_at`, INSERT original envelope and trusted binding, COMMIT, then `202`. A client/Worker `finished_at` cannot backdate ingress. No background task may report a durable `202` before COMMIT succeeds; unknown COMMIT must be reconciled on the original `result_id` without inventing a second timestamp or new receipt.

### DR-E5. Provisional verifier → transaction-scoped Finalizer

**Proposed type, not a frozen Python signature:** `VerifiedV1Receipt(inbox_row_id, envelope_sha256, result_id, job_id, attempt_id, worker_id, listing_id, key_id, outcome, failure_reason, result_digest, schema_version="1") | RejectedV1Receipt(inbox_row_id, rejection_code)`; only TV3's verifier can create a trusted typed verdict after strict V1 canonicalization, public-key lookup, contextual claims and Ed25519 validation. An HTTP `202` or a user-supplied `verified=True` cannot create this trusted type. The type must bind one **specific retained Inbox row**, not just a logical Job; exact Python class/field naming remains `P2E-VERDICT-CONTRACT-01 = PENDING_ACK`.

TV5's finalization rule is executed only inside TV1 Manager with TV2's single transaction UoW. After any out-of-lock CPU verification, finalizer reads immutable Job/Listing/Attempt locator, locks **Listing → Job → Allocation → Inbox candidate → Contribution → Aggregate** in one Session, uses fresh READ COMMITTED reads after locks, checks `RUNNING`, original committed Inbox identity/raw-byte digest and context, exact trusted deadline and key registration. A stale verdict **does not grant an out-of-band DB write**. On accepted valid candidate, the **one commit** includes immutable `signed_results`, Job terminalization, Allocation `ACTIVE → RELEASED`, decrement of Listing's allocated GPU count, Inbox `ACCEPTED`, exactly one contribution (if eligible), and aggregate delta (if eligible). A DB exception before COMMIT rolls back all; uncertain COMMIT causes read/reconcile, never a new attempt/allocation/counter increment.

**Multiple different signed `result_id` for one Attempt:** they are distinct committed candidates. Order strictly by DB-trusted `(received_at, inbox_id)`, reject invalid first and continue to the next; first **eligible verified** claim wins under one locked finalization transaction. Other already-stored candidates must be handled as `REJECTED` with a stable redacted reason or safely cleaned in later bounded processing (the existing Inbox states are only `PENDING`, `ACCEPTED`, `REJECTED`; **do not add `SUPERSEDED`**). A distinct new callback arriving after the Job terminalizes is not eligible even if the sender claims old `finished_at`. Exact rejection code and post-finalization cleanup strategy need TV2/TV3/TV5 ACK.

### DR-E6. No premature `SYSTEM_FAULT` and no false deadline success

`finish_due_at = started_at + duration_seconds`; `hard_deadline_at = finish_due_at + 120 seconds`, both persisted with the stable Attempt at allocation. Missing-result probe is at `finish_due_at + 10 seconds`; dispatch retry spacing `2,4,8,16,30,...` and 30-second claim lease use ADR-005. HTTP `202` is merely dispatch/Inbox acknowledgement, not the execution outcome. PAUSED prevents **new allocation** but permits already RUNNING Attempt repair with the exact same immutable Outbox payload and deadline.

At `db_now >= hard_deadline_at`, the Manager must **exhaust the committed on-time Inbox candidates**, in deterministic bounded batches, before concluding no valid result and running `TX-DEADLINE-FALLBACK`. An invalid first candidate is not grounds to ignore a later valid one; if a batch limit is reached and pending candidate rows remain, **do not commit fallback**. `received_at == hard_deadline_at` is late. Callback ingress and finalizer/fallback both serialize by Listing → Job lock, requerying under READ COMMITTED after locks; a valid candidate committed before deadline still wins even if the Manager verifies it after deadline. Deadline scanning must not use Worker `finished_at`, process wall clock or an out-of-lock pending-inbox snapshot as final authority.

### DR-E7. Exactly-once outcomes and future retention

| Verified or terminal path | `jobs` state | `signed_results` | `job_reputation_contributions` | Lifetime counters |
|---|---|---|---|---|
| Bound Signed V1 `SUCCESS/null` | `COMPLETED` | Exactly one immutable accepted row | One `SUCCESS` | `successful_jobs +1` |
| Bound Signed V1 `FAILED/WORKER_FAULT` | `FAILED` | Exactly one immutable accepted row | One `WORKER_FAULT` | `worker_fault_jobs +1` |
| Bound Signed V1 `FAILED/JOB_FAULT` | `FAILED` | Exactly one immutable accepted row | One `NONE` | No counter change |
| Manager fallback `FAILED/SYSTEM_FAULT` | `FAILED` | **None** | **None** | No counter change |
| Client cancels still-QUEUED Job | `CANCELLED` | **None** | **None** | No counter change; no allocation existed |
| Invalid / late / duplicate / new-after-terminal candidate | No additional terminal effect | No additional row | No additional row | No delta |

Contribution is keyed by `job_id` and written in the **same UoW/COMMIT** as result acceptance, release and aggregate update; no independent reputation callback or second commit. On Phase 3 authorized Dispute correction, the *effective* category/aggregate delta may change in one later approved transaction, while original V1 raw evidence and `initial_category` remain immutable. At the authorized 23-day history purge, Job-linked contribution may disappear without decrementing lifetime counters; an OPEN Dispute holds evidence and archived public keys as required. No Phase 3 code is approved by this review.

### DR-E8. Source/consumer handoffs still requiring actual ACK

| ID | Contract that must be confirmed | Owner/consumer | State |
|---|---|---|---|
| `E-IF-01` | Immutable dispatch DTO, source-of-truth Outbox request, no oracle fields | TV1, TV2, TV5 | `PENDING_ACK` |
| `E-IF-02` | Cross-restart same-Attempt conflict guarantee; design/change-control decision | TV1, TV3, TV5 + group lead | `NEEDS_OWNER_DECISION` |
| `E-IF-03` | Cache cap, eviction, in-flight handling and shutdown/redelivery limits | TV1, TV5 | `PENDING_PARAMS` |
| `E-IF-04` | Worker key issuance, private secret provisioning, restart and planned rotation | TV1, TV2, TV3, TV5 | `PENDING_ACK` |
| `E-IF-05` | Strict JCS/Ed25519 signed-wire, fixed vectors, two independent runtimes | TV3, TV5 | `PENDING_ACK` |
| `E-IF-06` | Ingress bearer scope, bounded raw JSON parse, redacted errors and `202` semantics | TV1, TV3, TV5 | `PENDING_PARAMS/ACK` |
| `E-IF-07` | Native-role Inbox grants, raw byte UNIQUE conflict, commit-unknown reconciliation | TV2, TV3, TV5 | `PENDING_ACK` |
| `E-IF-08` | Typed `VerifiedV1Receipt`, evidence/key binding and finalizer TOCTOU recheck | TV1, TV2, TV3, TV5 | `PENDING_ACK` |
| `E-IF-09` | Candidate ordering, multiple result IDs and rejected/superseded cleanup | TV1, TV2, TV3, TV5 | `PENDING_ACK` |
| `E-IF-10` | Single Finalization UoW, contribution and aggregate deltas/recovery | TV1, TV2, TV5 | `PENDING_ACK` |
| `E-IF-11` | PAUSED same-key Submit replay (already approved), RUNNING dispatch repair (separate) | TV2, TV4, TV5 | `PENDING_ACK/TEST` |
| `E-IF-12` | Phase 1 accepted-main SHA, actual role/CI evidence, revisions + 2E compatibility | TV1–TV5 | `PENDING_PHASE1_GATE` |

**Change-control rule:** an owner ACK must cite exact document SHA/version, data shape, failure semantics and test oracle. If a proposed contract differs from accepted ADR-004/005, API §13, approved schema/DB lock order or Phase 2A–D design, use the project's interphase change-control process and affected owner + consumer review; do not silently amend the accepted contract here.

### DR-E9. Deterministic acceptance designs (ALL Phase 2 tests `NOT_RUN`)

| Test ID | Injection / action | Strict oracle |
|---|---|---|
| `P2E-DRT-01` | Same immutable dispatch twice while cache entry active (concurrently) | No competing in-memory execution for same retained Attempt; 202 idempotent; no extra Allocation |
| `P2E-DRT-02` | Same Attempt altered dispatch while cache entry exists | 409 EXECUTION_CONFLICT; original work unchanged |
| `P2E-DRT-03` | Cache eviction/cold restart, same persisted original dispatch | Logical Attempt/Outbox IDs stable; deterministic nine-field output/digest unchanged; new receipt ID permitted; exactly-once business effect |
| `P2E-DRT-04` | Cold restart, authenticated altered same-Attempt dispatch | **BLOCKED by `P2E-CACHE-GAP-01`** until owner approves enforceable cross-restart policy/contract; never label PASS from live-cache test |
| `P2E-DRT-05` | Worker key unavailable or incompatible at dispatch; restart signer recovery | Fail closed, no forged valid result, no hidden private-key/DB access |
| `P2E-DRT-06` | K1 planned rotation to K2 after quiescence; historical K1 evidence | No active in-flight K1 lost; old retained receipts still verify via archived K1 |
| `P2E-DRT-07` | V1–V4 and approved nine-field output against independent JCS implementations | Equal canonical bytes, hash-domain/rejection traces, digest and signed-claim outcome |
| `P2E-DRT-08` | Fixed ADR-004 V1 vector; tamper extra field, key_id, UUID/time or signature | Valid fixture verifies; every malformed/mismatched fixture rejected without state mutation |
| `P2E-DRT-09` | Wrong/missing/opposite-direction internal service token, valid end-user JWT | 401 and zero accepted dispatch/Inbox; no secrets in logs |
| `P2E-DRT-10` | Callback stored; lose its 202; resend original bytes; replay after Job terminal | One immutable Inbox row, unchanged received_at, 202 DUPLICATE; no second business effect |
| `P2E-DRT-11` | Simultaneous same `result_id` with same/different original bytes | UNIQUE winner + rollback/read/reconcile; exact-match duplicate 202, changed bytes 409, no silent overwrite |
| `P2E-DRT-12` | Two on-time distinct valid `result_id` for same Attempt | Deterministic first eligible verified candidate accepted once; later gives zero extra effect |
| `P2E-DRT-13` | First on-time Inbox candidate invalid then a later valid candidate | Invalid rejected, later valid wins; no early SYSTEM_FAULT |
| `P2E-DRT-14` | Candidate persisted at deadline-1us; Manager restart after deadline | Valid candidate finalized even after deadline; one release/contribution |
| `P2E-DRT-15` | New callback obtains Job lock exactly at deadline or later | 409/late, zero eligible Inbox; fallback only after draining older candidates |
| `P2E-DRT-16` | Pending eligible candidate count exceeds bounded batch | Multiple bounded passes; no fallback until all on-time pending were assessed |
| `P2E-DRT-17` | Crash before and after finalization COMMIT; unknown COMMIT ACK | Atomic rollback or deterministic reconciliation; never second release/reputation delta |
| `P2E-DRT-18` | Signed FAILURE/WORKER_FAULT, JOB_FAULT, SUCCESS, and system timeout | Expected one `SUCCESS`/`WORKER_FAULT`/`NONE` or no contribution; counter deltas +1/+1/0/0 respectively |
| `P2E-DRT-19` | Native API/Manager/Simulator credentials + protected reference/raw receipt ACL | API restricted TX-SUBMIT INSERT, Manager minimal SELECT, no Simulator PostgreSQL, no DTO/log oracle leaks |
| `P2E-DRT-20` | 23-day authorized cleanup and OPEN Dispute hold with key-retention fixture (Phase 3 boundary) | Eligible detail purged without aggregate decrement; OPEN holds retain signed evidence/public key; phase-specific tests BLOCKED until code authorized |

**Test reporting policy:** These are *test designs*, not test results. V1–V4 **Phase 1** generator tests exist and were exercised in #39 CI; that does not make `P2E-DRT-07` cross-runtime Simulator/Signer interoperability pass. Phase 2 test status is **`NOT_RUN`**. Each eventual executable test needs an exact code SHA, DB migration head, clock/concurrency barrier, native roles, redacted logs and persisted before/after assertions. Tests needing Phase 3 work remain `BLOCKED_BY_PHASE_3` until their phase is authorized; they do not block writing allowed Phase 2 code after the separate gate.

### DR-E10. Review outcome and implementation gate

**Review disposition for v1.8: `ACK_WITH_ACTIONS` / `APPROVED_DESIGN_CONDITIONAL` baseline preserved.** This appendix documents repairs, exact test design and explicit unresolved choices; it does **not** settle `P2E-CACHE-GAP-01`, emergency private-key compromise, precise `P2E-VERDICT-CONTRACT-01` Python shape, bounded cache/ingress parameters, physical DB grants or cross-owner ACKs. No implementation permission is generated by writing these documents.

**Before Phase 2 code authorization:** confirm Phase 1 #39 integrated/accepted on main (including tests/human review, not merely green CI); take and record any necessary owner decision on cold-restart dispatch conflict and compromised-key response; freeze affected inter-owner interfaces with explicit ACK; validate task ownership/phase scope. **After code authorization and before merge/deployment:** run actual V1–V4 cross-runtime/Ed25519, native-role PostgreSQL, concurrency, deadline/restart, failover, contribution/release and Compose E2E tests on reviewed SHA. There is no permission here to push GitHub commits, comment, migrate, start coding or mark CI Phase 2 PASS.

### Repository status synchronization — 2026-11-08 (documentation addendum)

The PR #39 status and SHA in the v1.8 header above are a historical 2026-11-07 snapshot, not the current repository state. At review time, `main` is `bee832eaf5463df20f6c6815174322871eb6685a`; PR #39 is merged with head `3482bce3cc9726543b9345a5224d8db1b9fc6454` and merge commit `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`. Exact-head CI evidence is [run 42385995533](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533), SUCCESS. PR #44 merged the five Phase 2 source specs and five handoffs into main; this is document intake and does not upgrade conditional design to implementation authorization. PR #45 remains Draft/open, #46 open/Ready, #47 Draft/open; none is merged and their contents are not accepted main contracts.

The source-only command `alembic -c backend/alembic.ini heads` reports one head, `0005_listing_d7` (system Alembic 1.13.1). Live PostgreSQL verification is `NOT_RUN`; no disposable database was contacted. Phase 2 runtime tests remain `NOT_RUN`.

The Phase 2E design approvals and unresolved statuses above remain unchanged. Algorithm-version compatibility across a queued Job and Simulator deployment remains an open decision: current dispatch has no `algorithm_version`, and exact `simulation_input` remains `{"workload_profile":"demo-v1"}`. Do not add a dispatch or Signed Result V1 field without owner review/change control.

Documentation workflow synchronization proposed for review: one Phase 2E docs branch/PR; after a separate coding gate, one implementation task per branch/PR, with eligible tasks mergeable independently. This wording is `PROPOSED — PENDING_LEAD_ACK`; it does not amend active contribution rules or grant implementation permission.

The no-GitHub-write sentence in the historical v1.8 review outcome records the scope/authority of that earlier review. This dated documentation synchronization is being prepared under the current documentation task; it still does not authorize Phase 2 code, migration, merge, or deployment.

---

### DR-E10. Cross-phase proposal sync — 2026-11-13 (not an approved change)

This addendum updates only the pre-code review snapshot for [TV2 #46 @ ba63466](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) and [TV3 #49 @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) against main@bee832e. Neither design PR is merged; no existing approved contract is silently altered.

- **E-IF-01:** exact immutable ten-key Manager→Simulator dispatch with demo-v1 and no oracle. TV5 prefers TV2 P1 (all ten in Outbox, stable caller IDs, canonical raw bytes), pending lead D-05/D-13; P2 eight-key core remains fallback. The proposed internal SignerReadiness is **not** an eleventh key.
- **E-IF-04:** proposed D-18 shared allocation/exclusive provisioning Worker advisory first in global lock order, durable two-active-public-key quiesce, exact {K1,K2} activation, K1 historical retirement and rollback. E-C3/D4 conflict with proposed unique partial active-key index requires lead L2 approval. Simulator local sign+verify startup check is necessary but not proof that it owns the current active DB key.
- **Live gate:** TV5 prefers G1 fresh 32-byte nonce signed under a separate SIGNER-PROOF:V1 domain, Manager verification against active DB key **outside any UoW**; needs a new internal endpoint and lead L2 change-control. G2 has unresolved bootstrap contradiction. TV2 #46 @ ba63466 proposes internal SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at), checked under Worker+Listing locks against the sole active key + trusted DB time; stale K1 proof after K2 activation returns Blocked(SIGNER_NOT_READY). P2B-DRT-29 NOT_RUN; owner ACK pending.
- **E-IF-06/07:** 202 STORED for known new commit or unknown-COMMIT reconciled SAME; 202 DUPLICATE for known retained exact replay; 401; 404 RESULT_CONTEXT_NOT_FOUND; 409 RESULT_ID_COLLISION or RESULT_NOT_ACCEPTABLE; 422 INVALID_SIGNED_ENVELOPE; 503 unreconciled. TV3 16,384-byte/depth-4 bound pending TV1. TV2 target-less ON CONFLICT + fresh probe; D-01 literal bytes versus SHA-256+CHECK equivalence and E-C1/E-C2 change-control not decided.
- **E-IF-08:** TV3 full VerifiedV1Receipt and RejectedV1Receipt (inbox_id, non-null result_id, envelope_sha256, trusted IDs), only four definitive post-ingress rejection codes; parser/key dependency drift leaves Inbox PENDING. TV3 accepts TV5's V-OUT with TV2 locked evidence/hash/result_id check and strict extract_signed_parts_v1; lead E-C4 and exact owner ACK pending.
- **E-IF-09/10:** TV2 PrecedingPending enforces earliest verified candidate; no caller-supplied fallback proof; on-time Inbox may finalize after deadline. One atomic UoW signed result/Job/release/Listing/Inbox/contribution/aggregate, SYSTEM_FAULT without Worker penalty; TV5/TV2 first-contributing reputation UPSERT proposal still needs native-role tests.
- **Separate unresolved topics:** P2E-CACHE-GAP-01 authenticated changed dispatch after Simulator cold restart, algorithm-version pin across queued deployment, provisioning identity D-03/S-10, compromised-key incident, G1/G2, D-18/E-C3 and all runtime budgets. G1 proof-of-private-key possession does not prove original dispatch-content binding.

All P2E-DRT-01..20, TV2 P2B-DRT-18/20..29, TV3 P2C-SIGN-01..06, native-role PG, concurrency, signer cross-runtime and E2E tests remain **NOT_RUN**. Existing PR #50 Draft remains docs-only; independent L2 review, lead G1 docs gate and separate coding authorization are pending.
