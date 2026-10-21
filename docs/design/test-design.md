# GPU Resource Marketplace — Test Design & Traceability Plan

**Version:** v0.2 — approved documentation-only test plan and traceability baseline  
**Date:** 2026-10-18  
**Status:** **APPROVED_DESIGN** by user review on 2026-10-18 for the consolidated test plan and 100 API contract cases / eight module ownership checks. Previously approved QA, DB and ADR case requirements remain authoritative; unreviewed `DAT-EX` extras remain PROPOSED; ADR-008 `STACK-01..10` cases are APPROVED_DESIGN. **ALL runtime/SQL/API/benchmark tests remain `NOT_RUN`**.  
**Target path:** `docs/design/test-design.md`  
**No implementation:** no pytest/k6 scripts, migration, Postman collections, GitHub workflows or generated source code in this deliverable.

## 1. Objective and definition of a valid result

**Objective:** consolidate previously approved Requirements, ADR, database and quality scenarios into an implementable **test plan**, rather than create a second, conflicting set of business requirements or claim that design review proves software correctness.

An executable verification result must eventually include: Git commit SHA; approved requirement/test ID; fixed fixture identity and seed; schema migration revision; service/runtime versions; fake/trusted-clock setup; exact HTTP/DB stimuli and injected failure barrier; observed status/response/rows; expected **binary oracle**; stdout/log references with secrets redacted; execution date; verdict `PASS | FAIL | BLOCKED | ERROR | NOT_RUN`. For latency tests also record hardware profile, generator health, sample size, percentile method and three independent runs. Without these fields, do **not** label the test `PASS`.

**Current result:** 0 product tests were executed as part of this Markdown deliverable. This document's own link/count/traceability lint is a **documentation check only** and must not be cited as functional verification.

## 2. Sources, status vocabulary, and ordering

- [SRS](../requirements.md), [21 Functional Requirements](../functional-requirements.md), [33 Non-functional Requirements](../non-functional-requirements.md).
- [System Architecture](../architecture/system-architecture.md) and [Quality Attribute Scenarios](../architecture/quality-attributes.md) — **11 approved scenario test designs** (all runtime tests NOT_RUN).
- [Database Design](database-design.md) — **18 approved tables**, physical schema and transactions; reference `DBP-01..12`, `DBTX-01..18` and other listed DB invariants (`NOT_RUN`).
- [API Contract](api-contract.md) — **14 Auth + 18 Listing + 68 other public/internal/general tests = 100 API test IDs**, all runtime execution `NOT_RUN`. Owner-approved `API-OPEN-01/02/06` decisions are synchronized; extra JWT claim, NumericDate precision and Unicode normalization details are separately marked `NEEDS_OWNER_DECISION` and do not block GPU-001 foundation without Auth implementation.
- [Module Design](module-design.md) — `MODOWN-01..08` **APPROVED_DESIGN** boundary checks, all `NOT_RUN`.
- [ADR-001..007](../architecture/decisions/ADR-001-modular-monolith.md) (use their individual files for exact acceptance), especially ADR-003 Outbox/Inbox, ADR-004 Signed Result V1, ADR-005 retry and auth, ADR-006 evidence holds, ADR-007 load configuration. [ADR-008](../architecture/decisions/ADR-008-technology-stack.md) is **ACCEPTED** with `STACK-01..10` approved as test designs; all `NOT_RUN`.

| Status | Meaning; not interchangeable |
|---|---|
| `APPROVED_DESIGN` | User approved the specification and expected oracle; **not** a passing implementation |
| `PROPOSED_DESIGN` | Draft contract/test to review; may change without invalidating accepted business baseline |
| `NOT_RUN` | No executed implementation against the specified environment/commit |
| `BLOCKED` | Preconditions absent, e.g. no working API or PostgreSQL; NEVER treated as PASS |
| `ERROR` | Runner/environment failure; cannot infer product correctness |
| `FAIL` | Executed test with valid preconditions, at least one mandatory assertion failed |
| `PASS` | Executed approved case, **every** mandatory assertion and evidence condition satisfied |
| `SUPPORTED/REFUTED/UNMEASURED` | Separate status **only for calibration hypotheses** (2 modules/16h change effort, 1x→5x performance ratios, 30-minute setup); not product acceptance |

**Precedence:** a later API/UI proposal cannot override a business/DB/ADR invariant already accepted. If two designs conflict, mark the affected test `BLOCKED` for specification review rather than “choosing what the code currently does.”

## 3. Review and future execution phases

| Gate | Dependency | What must be checked later | Evidence; scope boundary |
|---|---|---|---|
| `G0` Documentation consistency **now** | Markdown files only | Relative links; 18-table cardinality; no AD-090 parameter leakage; public route inventory; status labels | Text-level review, **not** application PASS |
| `G1` Database integrity | User authorizes implementation; actual PostgreSQL + migrations | DBP/DBTX, FK/uniqueness, custody of oracle and historical keys, FIFO/locked time | Row snapshots and concurrency barriers |
| `G2` API and RBAC | G1 + implemented routes | `API-AUTH`, `API-LIST`, `API-JOB`, `API-RES`, `API-DSP`, `API-REP`, `API-DASH`, `API-COM` | HTTP status/body + DB effects |
| `G3` Internal HTTP and cryptography | G1 + Manager/Simulator | ADR-004 `WIRE/ENUM`, `API-INT`, COM, RT, SEC | Frozen signed bytes, captured Inbox/Outbox and keyed test fixtures |
| `G4` End-to-end correctness and fault injection | G2+G3 | INT, REL, DAT, OBS, TST, OPS, MODOWN critical checks | Crash barriers, retry traces, state/reputation deltas |
| `G5` Performance and scalability | G4 safety passes in stable environment | ADR-007 736 VU/1x–5x campaigns, three independent runs | Per-run raw metrics, hardware, generator validity, DB invariants |
| `G6` Release readiness | All mandatory P0 evidence PASS | No missing, skipped, xfail or BLOCKED critical checks | Reviewable test manifest and signed-off report |

The order is a future **testing workflow**, not approval to write code today. A defect in a critical invariant blocks load-test success claims even when p95 appears good.

## 4. Frozen deterministic fixture families (design only)

Each fixture family is isolated with a **fresh DB snapshot** and a frozen fake DB clock unless explicitly testing concurrent execution. Short labels below are aliases for **actual UUIDv4** in future fixtures; do not store literal `W1`/`J1` in columns requiring UUID.

| Fixture ID | Fixed data | Main use |
|---|---|---|
| `FX-IDENTITY` | Seeded C1/C2 (`CLIENT`), W1/W2 (`WORKER`), A1 (`ADMIN`), disabled D1; unique login/role rows; separate valid 900s user tokens | Login, role, object ownership |
| `FX-LISTING` | ACTIVE L1 owned W1, `total=8`, `allocated=3`, RUNNING J_RUN=3 and QUEUED J_Q=6; PAUSED L2 owned W2 | Worker edit/capacity, pause/resume; 18 existing `API-LIST` oracles |
| `FX-FIFO` | ACTIVE L3 owned W1, `total=4`; queued accepted-order Jobs J_A=3, J_B=2, J_C=1 (increasing `enqueue_seq`) | Strict FIFO, cancel/allocate race, no capacity violation |
| `FX-RESULT` | RUNNING J1 with one active allocation; stable `attempt_id=A1`, historical key K1, correct ADR-004 V1 signed bytes and an altered invalid variant | Signed verification, Inbox dedup, replay, key retention |
| `FX-DEADLINE` | `started_at=T0`, `duration_seconds=60`, `finish_due_at=T0+60s`, `hard_deadline_at=T0+180s` | Ingress at hard deadline minus 1µs vs equality; Manager restart |
| `FX-DISPUTE` | Verified terminal Job at `terminal_at=T0`; protected reference matches or differs from valid signed claim; separate W1 Reputation `(7,3)` | File at `T0+7d-1µs`, equality reject, UPHELD/REJECTED and one delta |
| `FX-RETENTION` | Terminal Jobs at `T0+23d-1µs`, exact 23d; one OPEN Dispute from day 6 continuing through day 24 | Cleanup under lock, evidence hold, independent audit TTL |
| `FX-PERF-1X` / `FX-PERF-5X` | ADR-007 seed `20261017` and exact `200/600/12000/600` vs `1000/3000/60000/3000` Worker/Listing/terminal/queued counts | Three-run 736-VU load and paired 1x/5x comparisons |

**Isolation rules:** the Coordinator must not expose protected `simulation_references` to Client/Worker or Simulator. Worker private signing keys exist only as **injected test secrets**, not committed fixtures. Freeze the exact ADR-004 V1 canonical bytes and public verification vector; do **not** invent a different test-vector signature. The signing simulator is a mock, not real GPU compute. All timestamps are trusted server/DB values except the deliberately untrusted Worker `finished_at` claim.

### 4.1. Concurrency-barrier requirements

For a race test, independently force **both commit orders** under separate DB snapshots. Examples: `pause-then-allocate` vs `allocate-then-pause`, `cancel-then-allocate` vs reverse, `callback commit-then-fallback` vs `fallback commit-then callback`, `cleanup candidate discovered-then Dispute row locked`. A test that “happens to race” under normal thread scheduling is not deterministic evidence of the invariant.

- Lock Listing before Job in every domain transition; do not lock a queued Job using `SKIP LOCKED` and schedule a later one.
- Do not keep a Listing/Job lock while making internal HTTP requests or waiting for callbacks.
- A test must assert **persisted** rows, not only HTTP response codes or frontend labels.
- For any allegedly idempotent command assert both that the intended state is correct and the relevant duplicate-row/counter delta is exactly zero.

## 5. Traceability: 21 FRs → design boundary → mandatory safety tests

| FR | Owning module / contract | Test evidence group; explicit oracle |
|---|---|---|
| `FR-WR-01` | Registry + key metadata; ADR-004/Module §3 | `SEC-03`, `API-RES-01`: key binds to owning Worker, 0 secret exposure |
| `FR-WR-02` | Registry `POST /gpu-listings` | `API-LIST-06..08`, DBP FK: only Worker-owned valid Listing inserted |
| `FR-WR-03` | Registry edit/pause/resume TX-PAUSE-EDIT | `API-LIST-09..17`, `INT-05..07`: no forbidden shrink/edit/allocate |
| `FR-WR-04` | Catalogue/details and reputation projection | `API-LIST-01..05,18`: ACTIVE admission, safe read |
| `FR-JL-01` | Jobs submit + reference TX-SUBMIT | `API-JOB-01..07`, `DBTX` submit cases: exactly one QUEUED Job/reference |
| `FR-JL-02` | Manager FIFO Scheduler | `API-JOB-13`, `INT-01`, `MOD-FIFO-01`: head cannot be skipped |
| `FR-JL-03` | Manager allocation, pause | `INT-02/05/06/07`, `DBP-04`, `MODOWN-04`: capacity guard |
| `FR-JL-04` | Jobs QUEUED cancel TX-CANCEL | `API-JOB-09..12`, `INT-03/04`: mutually exclusive winning state |
| `FR-JL-05` | Manager Outbox/Inbox/finalize | `COM-01..08`, `RT-01..14`, `REL-01..06`: one terminal result/release |
| `FR-JL-06` | Jobs DB trusted time and errors | `API-JOB-01/10`, `API-INT-09/10`: honest terminal time/fault reasons |
| `FR-SR-01` | Simulator Ed25519 key + Registry | `SEC-03/08`, `STACK-09` (approved design, `NOT_RUN`): no private key leak |
| `FR-SR-02` | Simulator V1 wire contract | `WIRE-01..07`, `ENUM-01..06`: correct canonical bytes/enums |
| `FR-SR-03` | Manager verifier/finalization | `SEC-01..07`, `API-INT-05/11`, `DBP-06/11`: signature + DB context |
| `FR-SR-04` | Inbox reject/replay, Manager fallback | `SEC-02/05/06`, `RT`, `API-INT-06..12`: invalid/replay produces zero duplicate effect |
| `FR-DP-01` | Client dispute filing | `DAT-10..16`, `API-DSP-01..06`: `<7d`, owner, accepted receipt |
| `FR-DP-02` | Manager oracle comparison | `SEC-09`, `API-DSP-09/10`: signed-but-false UPHELD, true REJECTED |
| `FR-DP-03` | Retained signed evidence, automatic resolution | `DAT-06/07/15`, `API-DSP-08/11/12`: original immutable, retry/hold |
| `FR-RP-01` | Manager contribution + aggregate | `INT-08`, `API-REP-01..04`: correct counts, lifetime after purge |
| `FR-RP-02` | Manager one-time net dispute correction | `API-DSP-09`, `DBTX` reputation case: exactly one effective delta |
| `FR-DB-01` | Role-specific Dashboard read | `API-DASH-01..05/09`: no cross-role/cross-owner leakage |
| `FR-DB-02` | Read server snapshots, polling | `API-DASH-06..08`: view reflects durable state/held Dispute |

Authentication/Logout `UC-G01` is cross-cutting rather than a separately numbered module FR. It is covered by `API-AUTH-01..14` and NFR-S01/S02; never ignore it because the 21-row FR catalog doesn't assign a dedicated FR-AUTH number.

## 6. API and module test manifest (all execution `NOT_RUN`)

### 6.1. Endpoint contract cases: exactly 100 described in `api-contract.md`

| Group | Count | Status of **test design** | Typical gate |
|---|---:|---|---|
| `API-AUTH-01..14` | 14 | APPROVED_DESIGN for owner-approved Auth policy; extra claim profile, NumericDate fractional precision, and Unicode normalization/repertoire are `NEEDS_OWNER_DECISION`; all `NOT_RUN` | Login/Me/Logout, role/token limits and normalization subcases |
| `API-LIST-01..18` | 18 | Reviewed design baseline; tests `NOT_RUN` | 6 Listing endpoints, ownership/capacity/races |
| `API-JOB-01..16` | 16 | APPROVED_DESIGN | QUEUED submit, persisted idempotency, cancel, FIFO |
| `API-RES-01..06` | 6 | APPROVED_DESIGN | Immutable verified Signed Result read only |
| `API-DSP-01..12` | 12 | APPROVED_DESIGN | One Dispute before strict 7d cutoff, auto-resolution |
| `API-REP-01..05` | 5 | APPROVED_DESIGN | Lifetime counters and N/A representation |
| `API-DASH-01..09` | 9 | APPROVED_DESIGN | Role-safe retained history snapshots |
| `API-INT-01..12` | 12 | APPROVED_DESIGN; exact `simulation_input` allowlist is owner-approved; all `NOT_RUN` | Authenticated 202 dispatch/callback + Inbox |
| `API-COM-01..08` | 8 | APPROVED_DESIGN | Shared HTTP, correlation, timestamps, error safety |
| **Total** | **100** | **0 executed in this documentation phase** | Do not convert designs into implementation PASS |

`MODOWN-01..08` are eight **separate approved-design module-boundary checks**, not part of the 100 API cases. The original DB/QA/ADR IDs may overlap a scenario by design; avoid counting duplicate semantic checks as different evidence when reporting test coverage.

### 6.2. Existing DB and architecture verification suites (no rewriting of their oracles)

| Source | Previously documented test family | Approved design vs proposed | MVP priority |
|---|---|---|---|
| [Database Design](database-design.md) | `DB-INV-01..14`, `DBD-01..10`, `DBP-01..12`, `DBTX-01..18` | Approved design, all `NOT_RUN` | P0 integrity |
| [ADR-003](../architecture/decisions/ADR-003-internal-communication.md) | `COM-01..08` | Approved design, `NOT_RUN` | P0 durability |
| [ADR-004](../architecture/decisions/ADR-004-signed-result.md) | `ENUM-01..06`, `WIRE-01..07` and signature security vectors | Approved design, `NOT_RUN` | P0 signed result |
| [ADR-005](../architecture/decisions/ADR-005-retry-timeout-internal-auth.md) | `RT-01..14`, `AUTH-01..04` | Approved design, `NOT_RUN` | P0 recoverability and service auth |
| [ADR-006](../architecture/decisions/ADR-006-dispute-retention.md) + QA | `DAT-01..17`, extra `DAT-EX-01..06` proposed review | Original DAT approved; DAT-EX remains proposed, all `NOT_RUN` | P0 data safety / proposed ops detail |
| [QA Security / Integrity / Reliability](../architecture/quality-attributes.md) | `SEC-01..09`, `INT-01..08`, `REL-01..07` | Approved design, all `NOT_RUN` | P0 |
| [QA Observability / Testability](../architecture/quality-attributes.md) | `OBS-01..09`, `TST-01..09` | Approved design, all `NOT_RUN` | P0 release-quality gates |
| [QA Operations](../architecture/quality-attributes.md) | `OPS-01..07` mandatory; `OPS-08` calibration | Approved design, all `NOT_RUN` | P0 ops / hypothesis separate |
| [QA Modifiability](../architecture/quality-attributes.md) | `MOD-*`, `MOD2-01..09` | Approved **experiment design**; V2 is not MVP P0 | Change-exercise/traceability |
| [ADR-007](../architecture/decisions/ADR-007-load-test-configuration.md) + QA | `LDCFG-01..09`, `PER-01..06`, `SCA-01..06` | Approved benchmark design, all `NOT_RUN` | P0 perf measurements and safety; ratios calibration only |
| [ADR-008](../architecture/decisions/ADR-008-technology-stack.md) | `STACK-01..10` | **ACCEPTED ADR / APPROVED_DESIGN**, all `NOT_RUN` | Required implementation verification when coding authorized |

If an original source uses a longer suffix or human-readable ID, the **exact identifier in that source wins**. This register is navigation only, not a replacement for original individual test fixtures/oracles.

## 7. Critical cross-boundary acceptance stories

All flows below require **complete persisted-state assertions** and future execution evidence. Their checklists are test design, not executable scripts.

### E2E-01 — Happy path with signed SUCCESS

1. Seed Client C1, Worker W1, ACTIVE L1 with total 4; retain public K1 in Registry and inject private K1 to Simulator only.
2. C1 POST valid Job with idempotency key; assert exactly 1 QUEUED Job + 1 protected reference, no allocation.
3. Manager schedules FIFO; assert one RUNNING, allocation/attempt/outbox same commit, Listing used count = requested GPU.
4. Simulator receives duplicated execute attempts (same ID) and sends valid ADR-004 V1 `SUCCESS`; API Inbox `202` after commit.
5. Manager verifies signature **and context**, accepts once, Job COMPLETED, allocation released once, success reputation +1 and original bytes immutable.
6. Client GET Job and Signed Result; no reference/oracle/secret leaked. Repeat callback and finalization; persistent state unchanged.

### E2E-02 — Invalid signature, timeout fallback

Inject forged/altered signed payload with valid service token but wrong Ed25519 signature. Inbox ingress may return `202` if envelope/context structurally eligible, but Manager REJECTS. No immediate reputation penalty or premature terminalization. At trusted hard deadline, Manager checks all on-time Inbox candidates under locks, then commits `FAILED/SYSTEM_FAULT` and releases exactly once if none valid; contribution row absent. Late callback cannot reopen.

### E2E-03 — Dispute UPHELD and REJECTED

Create two distinct verified signed terminal Jobs with immutable protected references. A correctly signed but **factually inaccurate** result yields `UPHELD`; category correction changes counters by exactly one effective net delta and preserves original receipt. A truthful signed claim yields `REJECTED`, no counter change. File at `terminal_at+7d-1µs` accepted; at exact cutoff rejected; Client-provided timestamps have no effect.

### E2E-04 — 23-day cleanup and unresolved hold

Job X is terminal, signed, and has a Dispute filed on day 6, still `OPEN` on day 24. Verify X and its required key/oracle/contribution retained, warning within one hour of exception detection, CRITICAL 24 hours later, adjudication retry every 15 minutes while healthy; unrelated operational audit logs still expire on their own 23d clock. Resolve Dispute on day 24; aggregate corrected once, original evidence then eligible for guarded purge within 1 hour, no orphan records or aggregate reset. Job Y without pending Dispute is purged normally at expiry.

### E2E-05 — Two independent concurrency orders

Execute two snapshot-isolated barriers: (A) Pause commits before submit/allocate; no new admitted/allocation; (B) allocation commits first; Running Job can finish while paused, and later Cancel loses. Separately test Cancel-first vs Allocate-first with one contested Job. In all cases Listing capacity bounds, FIFO and monotonic legal Job state machine remain invariant.

## 8. Benchmark methodology — record results, never invent them

**Accepted ADR-007 profile `PERF-736-V1`:** 736 active VUs = **552 Client + 147 Worker + 37 Admin**, 2-minute ramp followed by **10-minute plateau**. Run **3 independent repetitions per dataset** (six runs for 1x and 5x comparison), each with identical seeded snapshot and a separately identified environment; 5-second think time and one active HTTP request per VU. SCA-1X and SCA-5X datasets use the exact counts in Fixture §4, same fixed hot Listing set/roles/traffic sequence.

| Metric | Per-run target or evidence requirement | Interpretation |
|---|---|---|
| Successful read p95 | `<=2.000s`, >=1000 successful samples/run, server-side nearest-rank percentile | NFR target to be measured, not a proven SLA |
| Successful Job submission p95 | `<=3.000s`, >=500 valid accepted submissions/run | NFR target; queued execution time is separate |
| Unexpected VU-facing 5xx | `<1.00%` of VU-facing plateau responses | Separate from transport/internal retries |
| FIFO/capacity/authorization/reputation violations | **0**, checked after deterministic batches, periodically and at end | Mandatory hard correctness gate |
| Load-generator validity | 4 vCPU/8GiB reserved, CPU p95 <=80%, peak RSS <=85%, zero dropped/skipped actions | Invalid generator => `BLOCKED` campaign, not SUT PASS |
| Scale 5x relative latency and throughput | Ratios <=1.50 for each p95, throughput >=0.85 in each paired run | **Calibration hypotheses only**, not product SLAs |
| Manager restart recovery | First durable recovery action <=120s in healthy persisted environment | NFR target measured separately from 120s execution grace |
| 18-hour Change Request response | First substantive assessment received within 64800 seconds | Organization process target, **not** code-delivery deadline |

A valid load-test run that misses p95 or server-error targets is a real performance target `FAIL`, even if correctness succeeds; an invariant violation is a release-blocking `FAIL` even if p95 appears good. Never average three runs into one pass or report throughput/microservice scalability claims without actual evidence.

## 9. Test priorities and future release-blocking rules

| Class | Examples | Future gate |
|---|---|---|
| P0 — mandatory invariant | owner isolation, FIFO, no over-allocation, terminal monotonicity, Ed25519/context, one contribution, no OPEN-Dispute purge | **Every approved MUST test executed and PASS** before product claim |
| P0 — lifecycle and recovery | Outbox persisted after allocation, on-time Inbox before SYSTEM_FAULT, race/cancel, 7d exact boundary | All relevant approved COM/RT/REL/DAT/DBTX tests PASS |
| P0 — role-safe usable MVP | Listing, Job, Signed Result, Dispute, Reputation, Dashboard | API group contract review first, then implementation PASS |
| P0 — reproducibility and benchmark recording | Clean setup, seeded fixture repeatability, 736-VU measurement | OPS mandatory PASS and honest per-run NFR reporting |
| Calibration / future experiment | MOD 2-module/16-person-hour effort, V1->V2 compatibility exercise, 30m setup, SCA ratios | Record SUPPORTED/REFUTED/UNMEASURED; **do not** turn into MVP shipping features |

**Stop conditions:** any unauthorized data disclosure, key/oracle leak, FIFO head bypass, `allocated > total`, accepted altered signature, duplicate effective reputation correction, evidence purge with OPEN Dispute, or fabricated deadline timestamp blocks a valid release regardless of otherwise healthy HTTP responses. Any DB test requiring physical triggers/grants is `BLOCKED` until actual migrations exist; Markdown approval cannot bypass it.

## 10. Traceability and review checklist before coding

| Review item | Current outcome / next action |
|---|---|
| 18-table model, PK/FK/locking and retained evidence ownership | **APPROVED design** per [Database Design](database-design.md) |
| 11 QA scenarios and associated deterministic tests | **APPROVED designs**, actual execution all `NOT_RUN` |
| ADR-001..007 policies | **ACCEPTED**, implementation still `NOT_RUN` |
| API Listings group and approved 900s token lifetime | Previously reviewed; maintain that baseline |
| API endpoints/DTO/errors and owner-approved token/storage/workload policies | **APPROVED_DESIGN**; `API-OPEN-01/02/06` broad decisions are resolved; see [API Contract](api-contract.md) §14.2 |
| Additional Auth profile details | `NEEDS_OWNER_DECISION` before Authentication implementation; not a blocker for GPU-001 foundation when Auth is excluded; see [API Contract](api-contract.md) §14.3 |
| Logical module responsibilities/dependency/ports | **APPROVED_DESIGN**; implementation package names may be reviewed as needed |
| ADR-008 Python/FastAPI/React reference stack | **ACCEPTED (2026-10-18)**; implementation still requires separate coding authorization |
| Physical migrations, executable SQL/Python/TypeScript, generated OpenAPI, CI, benchmark | **NOT_STARTED/NOT_RUN**; user has expressly prohibited coding until separate authorization |

**Document approval is not a substitute for implementation evidence**. After documentation review, seek **explicit user authorization** to code. Then freeze the revision/commit and create executable tests; later use actual code commit hashes for the AD-090 school assignment, keeping its 99/28d/22h parameters separate from the real product baseline.
