# Phase 2B - PostgreSQL Execution and Result Persistence (TV2)

> **PR #39 alignment + deep-review addendum (2026-11-07):** PR39-B and the final Appendix P2B-DR apply. All owner-approved architectural decisions remain conditionally approved, while the new detailed SQL/interface remedies in P2B-DR remain `PROPOSED_FOR_ACK`. PR #39 HEAD `44579ed84605` is Draft, not merged, and its green Phase 1 CI does not authorize or verify Phase 2 code.

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Version:** `1.3-deep-review-pr39`, updated 2026-11-07 (source v1.2 PR39-aligned; review corrections proposed)  
> **Status:** `APPROVED_DESIGN_CONDITIONAL / DOCUMENTATION_ONLY / NOT_APPROVED_FOR_IMPLEMENTATION`  
> **Decision log:**
> - `P2B-GATE-01 = APPROVED_DESIGN_CONDITIONAL (2026-11-07)`: team lead approves Phase 2B documentation scope, six-table migration strategy, principle of least privilege, minimum necessary triggers, staged fail-closed rollout, transaction-scoped UoW and accepted Phase 1 baseline **with outstanding evidence/owner-ACK gates**. This is not approval of executable SQL, a migration run, a repository update, coding, deployment or production activation. The table in section 2.9 remains the mandatory closure checklist.
> - `P2B-DEC-01 = APPROVED (design-only)`: exactly six Phase 2 tables; defer the FK to Phase 3 `disputes` while enforcing a Phase 2 no-correction transitional guard.
> - `P2B-DEC-02 = APPROVED (design-only, 2026-11-07)`: use one dependency-ordered, transactional Alembic **schema revision** to create all six approved Phase 2 tables. The exact revision ID and parent are determined from the accepted Phase 1 `main` baseline when implementation is separately authorized. Privileges and protective triggers require their own design review and may be delivered in an additional migration, but Phase 2 runtime must remain disabled until every mandatory migration, grant and gate has passed.
> - `P2B-OPEN-03 = APPROVED (policy only, 2026-11-07)`: keep Phase 1 D1-separated non-superuser API/Manager DB roles; enforce least-privilege PostgreSQL grants together with DB constraints and protective triggers.  
> - `P2B-OPEN-03A = APPROVED_CONDITIONAL (design-only, 2026-11-07)`: the *proposed intent* of the Phase 2 table/column GRANT matrix in §2.4 is accepted, **subject to** TV2 proving PostgreSQL column privileges and emitted ORM SQL with actual `gpm_api_app`/`gpm_manager_app` identities; TV2+TV3+TV5 must agree on race-safe byte-identical callback deduplication; affected owners must ACK. This is **not** blanket approval of unverified SQL GRANT syntax or arbitrary raw evidence reads.
> - `P2B-OPEN-03B = APPROVED (design-only, 2026-11-07)`: choose layered protection with approved PK/FK/UNIQUE/CHECK and narrow GRANTs, plus only **necessary** protective triggers. Preserve Phase 1 guards and retain transaction-level cross-row and fencing guarantees. Approval covers the protection strategy and invariant inventory in §2.5, **not** final SQL/DDL/privileges; affected owners must review and ACK.
> - `P2B-OPEN-03C = APPROVED (design-only, 2026-11-07)`: staged rollout with mandatory verification and **fail-closed activation**. Verify the accepted Phase 1 baseline/roles, apply the six-table schema revision on a disposable PostgreSQL cluster, apply reviewed grants/necessary triggers, run real-role negative and concurrent-transaction tests, obtain affected-owner ACKs and independent review, then consider runtime activation **only under a separately approved implementation/release decision**. On any mandatory failure, keep Phase 2 disabled; never widen DB grants, silently relax triggers, run destructive tests on a persistent database, or assert PASS without evidence.
> - `P2B-OPEN-04 = APPROVED (design-only, 2026-11-07)`: use **transaction-scoped Unit of Work (UoW)**, with one SQLAlchemy `Session` per complete logical DB transaction, all blocking synchronous DB calls executed within a **bounded executor** under the Phase 2A async supervisor. Never share a Session across threads/tasks or commit within individual repositories. Full rollback + whole-unit retry only for classified transient conflicts (not arbitrary errors), with stable logical identifiers and finite retry policy. Pool/executor sizing, deadline budgets and implementation-level cancellation handling are **PENDING TV1+TV2 verification**. Approval does not authorize DB/code execution.  
> - `P2B-OPEN-05 = APPROVED (design-only, 2026-11-07)`: choose **A — accepted Phase 1 baseline**, not frozen `0005_listing_d7`. Before separately authorized Phase 2 implementation, TV1+TV2 must record the accepted Phase 1 Git SHA, actual `main` Alembic head, target database revision and migration graph; verify D1/D2/D3 roles/guards and all affected contracts; block on drift, unresolved heads, missing privileges or incomplete Phase 1 acceptance. Use disposable PostgreSQL for migration tests. This is not implementation authorization.  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate:** Phase 1 integration must be accepted on `main`, affected interfaces reviewed, and coding separately authorized.

> **Proposed documentation owner:** TV2 - Database owner (`TranVu2005`)

## 1. Goal and scope

Design the **Phase 2 rollout of exactly six approved tables**, migrations, service-level privileges and atomic transaction ports. Design-only now; no Alembic migration, SQL trigger, implementation or DB test execution is authorized. The 18-table catalog is frozen: 10 Phase 1, 6 Phase 2, 2 Phase 3.

## 2. Approved Phase 2 tables (not new entity proposals)

| Table | Trusted writer / use | Primary invariant |
|---|---|---|
| `execution_attempts` | Manager | One stable logical attempt for Job and persisted trusted start/due/deadline |
| `allocations` | Manager | At most one allocation per Job, release at most once |
| `execution_outbox` | Manager | One stable dispatch event, fenced 30-second lease and durable retries |
| `result_inbox` | API INSERT; Manager processing status | Immutable original ingress envelope/received time and ID-level duplicate handling |
| `signed_results` | Manager | At most one accepted immutable signed result per Job; historical verifying public key |
| `job_reputation_contributions` | Manager | At most one effective contribution per Job; replay-safe aggregate update |

`worker_reputation_aggregates` belongs to Phase 1B already and is updated by Manager; `disputes` and `retention_exceptions` remain Phase 3 tables. Use Database Design section 9's exact types, indexes, keys, FKs and constraints, **never** a guessed new physical schema.

### 2.1. `P2B-DEC-01` — Approved phased FK rollout (design-only)

**Decision:** Keep the agreed `10 + 6 + 2` table rollout. In Phase 2, create `job_reputation_contributions.corrected_by_dispute_id` as a **nullable `uuid` column without a FK to `disputes`**: that Phase 3 table does not yet exist. Do not create a placeholder Dispute table, a seventh Phase 2 table, or a fake reference target. This is a *temporary implementation ordering*, not approval to change the final 18-table logical model.

**Phase 2 temporary data guard (proposed DDL, requires TV2's precise constraint/permissions review):**

```sql
CHECK (
    correction_version = 0
    AND corrected_by_dispute_id IS NULL
    AND effective_category = initial_category
)
```

Additional required safeguards:

1. `initial_category`/`effective_category` remain constrained to the **approved** `SUCCESS`, `WORKER_FAULT`, `NONE` values; `job_id` is unique and correctly bound to `jobs`/`workers` per approved Database Design §9.
2. Manager's Phase 2 write path **inserts** a first contribution only as part of successful finalization. It cannot update corrections, invent a Dispute, or directly amend signed evidence. A `FAILED/SYSTEM_FAULT` or `CANCELLED` Job has **no** contribution. A valid signed `FAILED/JOB_FAULT` has `NONE` category.
3. Effective permission/immutable-write enforcement must be shown in the DB role/grants and trigger review, **not** assumed from this CHECK or Python callers alone.
4. The Phase 2 temporary guard is explicitly marked **`P2B-DEC-01 / TRANSITIONAL`**, with a documented obligation to replace it at Phase 3. It must not be mistaken for the final physical constraint of Database Design §9.

**Phase 3 schema completion (planned, not authorized yet):**

1. Create `disputes` with all approved parent keys and unique targets in dependency order.
2. Preflight existing `job_reputation_contributions` records for Phase 2 guard compliance; fail safely if contradictory rows are present. Never silently repair historical reputation.
3. Replace the transitional CHECK with the **final approved** correction-version/evidence CHECK; add the approved composite FK `(job_id, corrected_by_dispute_id) -> disputes(job_id, id)` with the correct NULL behavior. No existing Phase 2 row should need a backfill merely to create the FK.
4. Introduce Phase 3 correction logic only after DB constraints, role permissions, migration verification and independent review. Test migration upgrade/rollback on **disposable PostgreSQL only**, never on the shared persistent environment.

**Required future test evidence (all `NOT_RUN`):**

| ID (proposed) | Requirement | PASS condition |
|---|---|---|
| `P2B-FK-01` | Fresh Phase 2 schema deploy | Exactly six Phase 2 tables; nullable `corrected_by_dispute_id`; no FK to absent `disputes`; migration succeeds |
| `P2B-FK-02` | Attempt to insert or update a corrected contribution before Phase 3 | Transitional CHECK/DB permission stops nonzero `correction_version`, non-null dispute ID, or a changed effective category |
| `P2B-FK-03` | Finalization replay and `NONE` contribution | One contribution and corresponding aggregate effect only as authorized; no correction at Phase 2 |
| `P2B-FK-04` | Forward migration in disposable Phase 3 fixture | Approved FK installs, existing Phase 2 contributions remain valid, invalid references are rejected |
| `P2B-FK-05` | Rollback/failure injection | No orphaned rows, silent historical changes or partial uncontrolled production deletes |

**Governance:** TV2 must trace the exact transitional DDL to Database Design §9 and route any difference from approved *physical constraints* through Change Control. Phase 3 schema owner and TV5 (reputation consumer) must ACK the eventual completion path; design approval here is **not** a migration/code authorization or an implicit ACK for other contributors.

### 2.2. `P2B-DEC-02` — Approved single schema revision (design-only)

**Decision:** After Phase 1 integration is accepted on `main` and code work is explicitly authorized, TV2 plans **one PostgreSQL transactional Alembic schema revision** to create the six Phase 2 tables and their in-scope PK/FK/UNIQUE/CHECK/index objects. No intermediate half-created Phase 2 schema is accepted as an application-ready runtime state. This is a documentation decision, not an instruction to generate or run an Alembic migration now.

**Required migration design and review evidence:**

1. **Parent revision and dependency lock:** obtain the actual Alembic head and Git SHA from the approved Phase 1 baseline immediately before implementation; check for concurrent migration changes. The current observed `0005_listing_d7` is context, **not** a frozen or preassigned parent. Do not invent a `0006` ID or fork from a stale head.
2. **Object creation order:** specify the dependency ordering among `execution_attempts`, `allocations`, `execution_outbox`, `result_inbox`, `signed_results`, and `job_reputation_contributions`, taking into account existing Phase 1 parents and referenced unique targets. All six use their approved Database Design section 9 types and constraints.
3. **Phase 3 dependency exception:** carry forward `P2B-DEC-01`'s transitional guard; there is **no** FK to the nonexistent `disputes` table until Phase 3. Document the later constraint swap and upgrade/rollback compatibility.
4. **Atomicity boundary:** target PostgreSQL transactional DDL for the six-table schema revision, so a failed revision leaves none of its new objects committed. A *separate* grants/trigger revision is permitted **only after its design is reviewed**, and is not part of the claim that the complete Phase 2 rollout is a single transaction.
5. **Activation gate:** API/Manager Phase 2 code must not be enabled against a merely partially applied database. All schema, required DB role/grant/trigger revisions, DBTX and privilege checks must be verified on a disposable PostgreSQL cluster. Never use shared persistent DB for destructive rollback tests.
6. **Rollback contract:** document downgrade order, exact objects removed, existing Phase 1 data untouched, and safety when Phase 2 Job executions or retained evidence already exist. A potentially data-destructive downgrade is **not** automatically authorized by approval of this design.

**Planned evidence (all `NOT_RUN`):**

| Test ID (proposed) | PASS oracle |
|---|---|
| `P2B-MIG-01` | Fresh disposable PostgreSQL from the accepted Phase 1 head upgrades to exactly six additional tables with required in-scope constraints. |
| `P2B-MIG-02` | Injected DDL error rolls the revision back completely with the original Phase 1 schema and rows intact. |
| `P2B-MIG-03` | A compatible Phase 1 database with existing Jobs/Listings upgrades without modifying or losing existing rows. |
| `P2B-MIG-04` | Safe downgrade/upgrade round-trip succeeds on a disposable fixture; data-loss boundary and reverse-dependency order are explicit. |
| `P2B-MIG-05` | Application activation is blocked when schema or mandatory privilege/trigger rollout is incomplete. |

**Review owners:** TV2 (schema/migration), TV1 (shared runtime and activation), TV3/TV4/TV5 for the Phase 2 columns and constraints their contracts consume. Interphase impact classification and real ACKs are required for affected interfaces; design approval here is not a substitute for those acknowledgments.

### 2.3. `P2B-OPEN-03` — Approved least-privilege policy (design-only)

**Policy approved by the team lead:** retain the separated PostgreSQL runtime identities from GPU-002/D1 (`gpm_api_app` member of `gpm_api_rw`; `gpm_manager_app` member of `gpm_manager_rw`), with no application service using the migration owner/superuser credential. Enforce command ownership with **narrow table/column GRANTs, physical constraints and protective triggers**. The Simulator has **no PostgreSQL identity, DSN, ORM path or network access**. Neither service receives `TRUNCATE`, arbitrary `DELETE`, `REFERENCES`, `TRIGGER` or DDL privileges from this Phase 2 approval.

**Approval boundary:** this section records the policy only. Matrix §2.4 is **APPROVED_CONDITIONAL as a GRANT intent**, while the minimum-trigger strategy in §2.5 and staged rollout in §2.6 are approved *as design*. Executable SQL, row-access details, trigger selection and emitted-ORM-SQL compatibility remain **PROPOSED_FOR_ACK**, subject to TV2 feasibility validation and affected-owner acknowledgements. Existing Phase 1 role D1, lifecycle trigger D2, guarded deletion D3 and runtime wiring are not silently replaced. Runtime role isolation must be verified on the accepted Phase 1 baseline, not inferred from documentation.

### 2.4. Conditionally approved Phase 2 table/column GRANT intent — `P2B-OPEN-03A`

Legend: `R(columns)` = SELECT on only listed columns where practical; `I(columns)` = INSERT on only allowed columns; `U(columns)` = UPDATE on only allowed columns; `NONE` = no direct privilege. The team lead accepted this **design intent with conditions**; the table is **not** tested executable GRANT SQL. Never grant `UPDATE` on immutable IDs, original callback bytes, claimed/bound IDs, signature bytes or originally trusted timestamps.

| Table | API role (`gpm_api_rw`) | Manager role (`gpm_manager_rw`) | Safety rationale |
|---|---|---|---|
| `execution_attempts` | `R(job_id, attempt_id, hard_deadline_at)` for authenticated callback binding only | `R(all required), I(approved columns)`; no routine UPDATE | API can validate a RUNNING bound attempt; only Manager creates stable attempt/deadline |
| `allocations` | `NONE` for direct business writes; rely on Listing/Job projections | `R`, `I`, `U(state, released_at)` | At-most-once reservation/release; keep identity, count and allocation time immutable |
| `execution_outbox` | `NONE` | `R`, `I`, narrowly scoped `U(state, delivery_attempts, next_retry_at, lease_owner, lease_until, lease_version, acked_at, updated_at)` | Outbox-only fenced CAS; immutable `event_id`, `attempt_id`, event type and dispatch payload |
| `result_inbox` | Authenticated, **bound PENDING-only INSERT**; minimally scoped `R` for `result_id` duplicate comparison; the exact raw-byte comparison path remains to be designed | `R` for original evidence and metadata; `U(state, rejection_code, processed_at)` only | API persists received bytes, DB-trusted receive time; Manager processes but never rewrites evidence |
| `signed_results` | `R` of explicitly approved safe projection **only** via authorized API queries (no unrestricted raw payload/envelope/signature export) | `R`, `I`; **no UPDATE/DELETE** | Immutable accepted Ed25519 evidence, one result per Job |
| `job_reputation_contributions` | `NONE` for direct writes; reputation projection read from existing aggregate | `R`, `I`; **no UPDATE/DELETE in Phase 2** | Unique once-only attribution; Phase 2 transitional no-dispute-correction guard |

**Existing Phase 1 tables affected by Phase 2:** keep Manager's authorized `R(gpu_listings, jobs, worker_public_keys,...)` and narrowly scoped `U(gpu_listings.allocated_gpu_count, jobs.status/started_at/terminal_at/failure_reason, worker_reputation_aggregates.successful_jobs/worker_fault_jobs)` per the approved ownership matrix; do **not** give Manager user provisioning or Client cancellation rights. API retains protected INSERT-only `simulation_references`, no oracle SELECT; Manager's protected read is subject to the approved trusted purpose. Do not broaden the Phase 1 guard transitions or override the approved role classifier.

**Two grant details requiring technical confirmation, not automatic approval:**

1. **Inbox duplicate comparison:** approved semantics are *same `result_id` + byte-identical envelope = idempotent; same ID + changed bytes = conflict*. A digest-only comparison is **not** proof of byte equality. TV2 + TV3 + TV5 must select a race-safe mechanism (restricted application SELECT, atomic statement or narrowly constrained DB function), document the exact privileges it needs, and prohibit arbitrary endpoint exposure of raw evidence.
2. **Column-grant/ORM feasibility:** SQLAlchemy ORM statements may implicitly use `RETURNING`, read server-default columns or update timestamps. Actual SQL emitted under `gpm_api_app`/`gpm_manager_app` must be tested. Do not expand grants just to make failing ORM tests pass; change the adapter or seek a reviewed grant change first.

**Unbound authenticated payloads:** Phase 2 baseline may reject an unbindable/invalid callback immediately with minimal redacted logging rather than insert it as `result_inbox.PENDING`. If storing a `REJECTED` unbound Inbox row is required, specify its `state`, `processed_at` and grant path explicitly: it must never become a bound on-time candidate. Unauthenticated requests never create Inbox rows.

### 2.5. Conditionally scoped DB protection inventory — `P2B-OPEN-03B` (approved design strategy)

**APPROVED DESIGN STRATEGY:** Use a **layered, minimum-necessary DB guard** rather than a trigger on every table. First use approved PK/FK/UNIQUE/CHECK and narrow PostgreSQL GRANTs. Add triggers only where an allowed `UPDATE` must be restricted to a legal state transition, trusted columns must remain immutable under that update, or the approved Phase 1 guard already exists. Cross-row conservation, replay fencing and once-only reputation are **not** enforceable by a simple same-row CHECK/trigger alone; authorized transactions and conditional writes remain mandatory.

| Phase 2 object | Prefer PK/FK/UNIQUE/CHECK/GRANT | Trigger/transaction boundary still needed |
|---|---|---|
| `execution_attempts` | `UNIQUE(job_id)`; trusted `finish_due_at > started_at`, `hard_deadline_at = finish_due_at+120s`; Manager INSERT, no normal UPDATE | No additional lifecycle trigger by default if UPDATE/DELETE forbidden to runtimes; test that timestamps and identity cannot be rewritten by application roles |
| `allocations` | `UNIQUE(job_id)`, `gpu_count>0`, `state=ACTIVE/RELEASED`, `released_at` present iff RELEASED; Manager UPDATE only `state,released_at` | **Propose a narrowly scoped BEFORE UPDATE guard**: `ACTIVE -> RELEASED` once, immutable other values; actual Listing counter decrement and Job finalization MUST be the same transaction |
| `execution_outbox` | One event per `(attempt_id,event_type)`; immutable identity/payload by UPDATE-column grants | Lease takeover, version fencing and ACK/RETRY must use conditional `UPDATE ... WHERE lease_version=<observed> ... RETURNING ...` (CAS) and only Outbox-row locks; a trigger checking increasing versions is not a substitute for CAS. No mandatory new trigger without a demonstrated gap |
| `result_inbox` | Partial UNIQUE non-NULL `result_id`; bound FK, PENDING/processed state CHECKs; Manager UPDATE limited to `state,rejection_code,processed_at` | **Propose a BEFORE UPDATE guard** preserving original envelope, hash, claimed/bound identities and DB-trusted `received_at`, allowing only legal `PENDING -> ACCEPTED/REJECTED` processing. Auth and lock-before-clock admission must be enforced at API/transaction boundary; duplicate-byte equality remains TV2/TV3/TV5 review |
| `signed_results` | At most one accepted result per Job; valid referenced key, 64-byte signature, immutable evidence; Manager INSERT-only and no routine UPDATE/DELETE | **Propose an UPDATE rejection guard as defense in depth**, but **do not** install an unconditional DELETE rejection trigger that would break future guarded 23-day Job-history purge. Authorized cleanup path is reviewed separately before enabling it |
| `job_reputation_contributions` | PK `job_id`; approved category CHECK; **temporary Phase 2** `correction_version=0`, `corrected_by_dispute_id IS NULL`, `effective_category=initial_category`; Manager INSERT-only | No Phase 2 correction UPDATE path; uniqueness plus the atomic finalization transaction ensures at most one effect. Do not pre-install Phase 3 dispute-correction trigger/behavior |
| `worker_reputation_aggregates` (Phase 1) | Counter nonnegative CHECK, Worker identity immutable, UPDATE only on count columns | Once-only aggregate change must be coupled atomically with contribution insertion; a trigger cannot infer valid Job attribution without the required business transaction |

**Approved decision nuance:** Required outcomes are mandatory; an additional trigger is not automatically mandatory where a narrower GRANT, existing trigger, CHECK or race-safe conditional SQL already establishes the outcome. TV2 must document the exact reason for each selected trigger (including Allocation and Inbox state transitions) and the safe purge/retention interaction for Signed Results. The Manager cannot hold Listing/Job locks during HTTP.

**Existing Phase 1 guards must remain authoritative:** Preserve `trg_jobs_guard_update` (D2) caller classification and allowed transitions, `trg_jobs_guard_delete` (D3) cleanup boundary, and approved protections on `simulation_references`. Do not duplicate or replace them in a Phase 2 revision without approved change control.

**Proposed negative verification (`NOT_RUN`):**

| ID | Attempt / injected failure | Required result |
|---|---|---|
| `P2B-GUARD-01` | API tries to change Manager-owned Allocation/Outbox/signed data | PostgreSQL denies it |
| `P2B-GUARD-02` | Manager edits immutable Attempt/Inbox/Signed Result bytes or timestamps | DB rejects the change |
| `P2B-GUARD-03` | Manager releases the same Allocation twice or changes a RELEASED row | State guard rejects second mutation; counters remain consistent |
| `P2B-GUARD-04` | Stale Outbox dispatcher submits ACK/lease update after fencing version changed | Conditional CAS updates zero rows, no lease overwrite |
| `P2B-GUARD-05` | Duplicate `result_id` with unchanged bytes, then different bytes | First is idempotent, altered body is rejected; exactly one on-time bound candidate |
| `P2B-GUARD-06` | Two concurrent finalizers race with the same signed result | One committed terminal state, one Allocation release and one reputation effect |
| `P2B-GUARD-07` | Try `correction_version=1`, non-NULL dispute ID, or changed effective category during Phase 2 | Transitional CHECK / restricted role blocks all attempts |
| `P2B-GUARD-08` | Authorized future purge on a disposable Phase 3 fixture | Guarded eligible purge is possible; direct premature delete remains prohibited |

**Decision boundary (`P2B-OPEN-03B = APPROVED`):** The team lead has approved **what must be protected** and the **minimal necessary trigger strategy**, not exact trigger definitions, SQL GRANT statements or migration execution. Suggested allocation/inbox/signed-results trigger details remain subject to TV2 SQL feasibility review, existing Phase 1 guard compatibility, required cross-owner ACKs, independent review, and isolated PostgreSQL test evidence. Do not interpret this decision as approval to implement.

### 2.5.1. Original cross-owner invariants (retained for traceability)


| Protected object | Mandatory design guard | Owner / review interface |
|---|---|---|
| `jobs` | Preserve approved `trg_jobs_guard_update` caller classification and legal `QUEUED -> RUNNING -> terminal` edges; API retains own `QUEUED -> CANCELLED`; never bypass terminal immutability | TV2 + TV4 + TV5; shared with Phase 1 |
| `simulation_references` | Preserve immutable oracle and restricted SELECT; no Simulator access | TV2 + TV5 |
| `execution_attempts` | Unique one attempt per Job, deadline CHECK; no runtime UPDATE of signed/trusted attempt identity/times | TV2 + TV5 |
| `allocations` | Only `ACTIVE -> RELEASED` once, `released_at` must match state, count/counter reconciliation must be transactional | TV2 + TV4 + TV5 |
| `execution_outbox` | Immutability of dispatch identity/payload; monotonic `lease_version`; stale claimant update must be rejected by CAS predicate; do not treat ACK as Job terminal | TV2 + TV1 + TV5 |
| `result_inbox` | Immutable original bytes/hash, binding and DB-trusted received time after Job lock; processing state transitions only; reject conflicting `result_id` reuse | TV2 + TV3 + TV5 |
| `signed_results` | Immutable accepted V1 signed bytes/key context, unique accepted result per Job; insert-only for Manager, guarded cleanup only after retention eligibility | TV2 + TV3 + TV5 |
| `job_reputation_contributions` | Phase 2 CHECK from `P2B-DEC-01` (`correction_version=0`, `corrected_by_dispute_id IS NULL`, unchanged effective category), no UPDATE grant | TV2 + TV5 |
| `worker_reputation_aggregates` | Counter nonnegative, Worker identity immutable, only Manager updates; one aggregate effect in TX-FINALIZE | TV2 + TV5 |

**Important distinction:** PostgreSQL `CHECK` protects **same-row** invariants, UNIQUE/FK protect keys/bindings, grants enforce command ownership, and SQL transactions with required locks enforce **cross-row** atomicity. Triggers provide defense in depth where necessary; they are not a substitute for guarded transactions or for isolating superuser credentials. A DB superuser can disable ordinary triggers, so runtime must never use one. The exact trigger bodies and whether they are needed in addition to constraints/grants require TV2 review; this inventory does **not** authorize additional triggers today.

### 2.6. Approved rollout and negative-test gate — `P2B-OPEN-03C`

**APPROVED DESIGN DECISION:** Use **fail-closed staged rollout** as a *future test/activation design*, not as approval to change a running database. The mandatory gate order is: accepted baseline and dedicated DB roles -> disposable-cluster schema revision -> reviewed grants/necessary triggers -> real-role negative SQL/ORM tests and multi-session transaction tests -> owner ACKs / independent reviews -> separately approved runtime activation. If a mandatory check fails, Phase 2 remains disabled and the failure is reported, not silently worked around with broad grants or a production migration rollback.

1. **Baseline verification:** enumerate real Phase 1 DB roles/grants, login DSNs and D2/D3 guard behavior at the accepted Git SHA/Alembic head; mark missing production wiring as a blocker rather than assuming D1 has already switched Compose credentials.
2. **Schema first, policy before activation:** apply the approved six-table schema revision on a disposable PostgreSQL cluster; then apply reviewed grants and necessary protection triggers (possibly in a separate revision). No Phase 2 runtime activation at a half-ready grants/trigger boundary.
3. **Privilege negatives:** API cannot change `allocations`, `execution_outbox`, accepted signed results or Manager-owned Job lifecycle; Manager cannot insert untrusted Inbox callbacks or change oracle/key evidence. Neither can execute arbitrary DELETE/DDL or write as owner. Simulator has no DB connection path.
4. **Integrity negatives:** reject mutable original Inbox bytes, a second accepted result, repeat contribution/aggregate increment, invalid lease fencing, transition out of terminal state and pre-Phase-3 reputation correction.
5. **Real-role test evidence:** run migrations and SQL/ORM statements as real `gpm_api_app` and `gpm_manager_app` on a disposable PostgreSQL 16 cluster; record Git SHA, Alembic revision, GRANT inventory, rejected SQLSTATE and transaction snapshots. All are currently `NOT_RUN`.

**Approved acceptance rule:** Every required verification record must include the exact Git SHA, Alembic revision/head, PostgreSQL version, DB roles in use, commands, measured outcomes and `PASS | FAIL | BLOCKED | NOT_RUN`. A failed or missing mandatory gate blocks Phase 2 activation (`BLOCKED`, never implicit PASS). **This decision does not permit migrations or production changes.** Require TV2, TV3 (callback/key), TV4 (allocation/Listing) and TV5 (finalization/reputation) ACKs where contracts are affected. Do not treat the owner's decision as a substitute for their human review.

**Gate status (already decided):** `P2B-GATE-01 = APPROVED_DESIGN_CONDITIONAL` on 2026-11-07. The future migration parent, exact DB-role/trigger SQL, measured pool/executor sizing and cross-owner ACKs remain pending; do not invent numeric defaults or claim test evidence. Appendix P2B-DR specifies proposed closure tests and no new owner approval.

### 2.7. Approved transaction-scoped UoW and bounded DB execution — `P2B-OPEN-04`

**APPROVED DESIGN CHOICE (`2026-11-07`):** Choose **A — transaction-scoped Unit of Work**, compatible with Phase 2A's already-approved **three independent loops, async supervisor, and bounded executor**. A repository method does **not** commit its own partial effects: the service-level logical transaction owns `Session`, commit, rollback and cleanup.

**Execution contract (design, not executable code):**

1. **Whole-unit context:** each DB transaction begins, obtains all needed locks, rechecks predicates, writes all related rows, and commits or rolls back **inside one synchronous execution context**. A fresh SQLAlchemy `Session` is created and finally closed **within the same executor worker call**. Never move a live `Session` between threads, `asyncio` tasks or `await` boundaries. Engine and pool may be shared by the approved service as intended, but **Session is not shared**.
2. **Repository boundary:** repositories expose transaction-safe primitives and neither open independent commits nor hide cross-row business decisions. The service/transaction adapter owns one complete logical operation such as `TX-ALLOCATE`, `TX-FINALIZE` or `TX-INBOX-INGRESS`.
3. **Bounded sync I/O:** the async supervisor dispatches blocking SQLAlchemy work into an executor with bounded **active calls and waiting work** (not an unbounded default queue). Manager Scheduling/Dispatch/Finalization remain independent loops while actual PostgreSQL connection demand is controlled. TV1+TV2 must specify max concurrent DB work, executor and SQLAlchemy pool limits, statement/lock timeouts and shutdown budgets **after measured testing**; there is no approved numeric preset.
4. **Short lock scopes:** domain transactions follow `gpu_listings -> jobs -> attempt/allocation -> inbox -> contribution -> aggregate`, acquiring only needed rows in the approved order. The Outbox claim/ACK/retry transactions lock **Outbox only**, with compare-and-swap fencing and no subsequent Listing/Job row lock. External HTTP/Simulator calls never occur within a database transaction or while holding Listing/Job locks.
5. **Failure semantics:** on SQL error, rollback the **whole** transaction, close the Session and preserve original failure classification. Retry a *new whole UoW* for qualified transient database failures (e.g., PostgreSQL `40P01` deadlock or `40001` serialization), with bounded attempt/backoff policy and stable Job/Attempt/event/result identifiers. Do **not** blindly retry privilege violations, constraint failures, conflicting callback bytes or arbitrary business rejection. On uncertain commit outcome, read authoritative DB state before deciding whether the logical effect needs retry.
6. **Cancellation/shutdown:** cancelling or timing out an awaiting `asyncio` task **does not prove** a synchronous executor thread or PostgreSQL transaction has stopped. During Phase 2A graceful shutdown, stop scheduling new DB units; supervise in-flight sync units until an observed commit/rollback or safe termination according to the approved shutdown budget. Do not dispose the Engine, reuse the Session, or emit a competing business effect based merely on a coroutine cancellation. Persistence/replay must remain safe after abrupt process termination.
7. **Scope and ownership:** TV2 owns Session/UoW and DB transaction-adapter contracts; TV1 owns supervisor/executor lifecycle and integration, TV4 owns FIFO/capacity domain rules, TV5 owns Job finalization/reputation rules, TV3 owns verification. Any cross-owner contract change needs source/consumer ACKs under Inter-Phase Change Control. This decision does not pre-approve code ownership outside those boundaries.

**Logical transaction requirements — consistent with Database Design §11:**

| Logical unit | Owner | Single-commit requirement |
|---|---|---|
| `TX-ALLOCATE` | Manager, TV4/TV2 integration | Lock Listing then actual FIFO head Job; `QUEUED -> RUNNING`, capacity counter, Allocation, Attempt and Outbox **all together** |
| `TX-OUTBOX-CLAIM/ACK/RETRY` | Manager dispatch, TV1/TV2 integration | Short Outbox-only fenced update; HTTP always **after** the claim transaction commits |
| `TX-INBOX-INGRESS` | API, TV3/TV5/TV2 integration | Auth before DB transaction; lock Listing then Job; DB-time received_at after lock; raw-byte storage and duplicate handling within admitted transaction |
| `TX-FINALIZE` / `TX-DEADLINE-FALLBACK` | Manager, TV5/TV2 integration | Lock Listing then Job and required children; once-only terminal state, GPU release, Inbox processing, accepted Signed Result and eligible contribution/aggregate effect in one commit |
| `TX-CANCEL` (Phase 1) | API, TV5 source | Preserve Listing-before-Job lock ordering; cannot win against already-committed `RUNNING` allocation |

**Required implementation-verification plan (all `NOT_RUN`):**

| Test ID (proposed) | Test situation | PASS evidence required |
|---|---|---|
| `P2B-UOW-01` | Inject failure mid-`TX-ALLOCATE` | No partial `RUNNING`, Allocation, Attempt, Outbox or GPU counter delta remains |
| `P2B-UOW-02` | Concurrent Scheduler and Cancel sessions | Exactly one legal outcome, FIFO/capacity preserved, no deadlock bypass |
| `P2B-UOW-03` | Competing finalizers or duplicate callback | One terminal effect, one GPU release, at most one contribution and aggregate update |
| `P2B-UOW-04` | Force deadlock/serialization retry and non-retryable constraint failure | Whole-UoW restart with stable logical identifiers for eligible transient error; non-retryable failure not looped |
| `P2B-UOW-05` | Cancel coroutine/stop Manager with a DB worker still running | No Session cross-thread reuse, no unsafe Engine disposal, no assumption that cancelled await means rolled back |
| `P2B-UOW-06` | Concurrency saturation and DB pool limits | Bounded active/queued work, measured pool utilization and lock waits, no indefinite silent starvation |
| `P2B-UOW-07` | Kill/restart after uncertain commit/ACK loss | Recover authoritative PostgreSQL state; no duplicate reservation, release or reputation effect |

**Outstanding verification, not a reopened architecture choice:** TV1+TV2 must document measured worker/pool capacities and budgets and confirm emitted SQL/GRANT compatibility under real Phase 2 runtime roles. This is a **conditional technical handoff**, not authority to execute migrations, alter roles, edit code or activate Phase 2. Phase 1 acceptance remains a prerequisite.

### 2.8. Approved baseline selection and migration safety — `P2B-OPEN-05`

**APPROVED DESIGN CHOICE (`2026-11-07`):** Select **A — the Phase 1 baseline accepted on `main`**, not a prematurely fixed migration parent. The currently observed `0005_listing_d7` is an inspection datum, **not** an approved future parent or a guarantee that Phase 1 is complete. The actual Phase 2 revision ID and its `down_revision` must be selected only after Phase 1 integration acceptance and separate authorization to implement Phase 2.

**Required baseline evidence before implementation:**

1. **Acceptance & source identity:** TV1 records the accepted Phase 1 integration PR/approval, exact `main` commit SHA, the required API/Jobs/Listings/Auth contracts and any related interphase change records. An open/draft integration PR is not itself acceptance evidence.
2. **Alembic graph & live revision:** TV2 records `alembic heads` on the accepted codebase and `alembic current` / `SELECT version_num FROM alembic_version` against the explicitly selected target DB; checks a single intended migration head, linear/upgradable dependency path, and code-vs-DB alignment. A DB already on an unexpected revision is **BLOCKED** for automatic upgrade.
3. **D1/D2/D3 effective state:** Inspect effective PostgreSQL runtime login identities, grants, D2 Job lifecycle trigger and D3 guarded deletion rule, plus schema/constraints that the six new tables reference. Do not infer Compose DSN separation from an approved design document; verify actual connectivity/privileges with the real roles.
4. **Drift & cross-owner review:** Compare the accepted Phase 1 as-built schema and public interfaces with Phase 2B's six-table design. Classify `NO_IMPACT / POTENTIAL_IMPACT / CONFIRMED_IMPACT`; require TV2 as DB source owner, TV1 as integration owner and **each affected consumer** (TV3/TV4/TV5 as applicable) to provide the mandated ACKs before integrating a changed contract. Unresolved drift or missing ACK means `BLOCKED_INTERPHASE`.
5. **Safety scope:** Trial migration, failure injection and downgrade only on an isolated/disposable PostgreSQL 16 cluster with the approved test safety guardrails; do not run destructive validation against a shared persistent database. Never run an unreviewed automatic downgrade, reset an existing migration history or silently change DB role credentials.
6. **Release gate:** Even if the schema revision succeeds, no Phase 2 runtime activation until the separately reviewed privileges/triggers, transaction tests and independent human approvals have passed. This decision approves a documentation prerequisite only.

**Planned baseline checks — all `NOT_RUN`:**

| ID (proposed) | Scenario | Required proof |
|---|---|---|
| `P2B-BASE-01` | Correct accepted `main` baseline | Record acceptance evidence, Git SHA, migration head and actual database revision; all consistent |
| `P2B-BASE-02` | DB role and guard inventory | Real API/Manager role behavior, constraints, D2/D3 triggers and no privileged runtime DSNs are verified |
| `P2B-BASE-03` | Unexpected or multiple heads / drift | Detection results in `BLOCKED`, not a guessed migration parent or forced upgrade |
| `P2B-BASE-04` | Phase 1 contract changed since design | Affected source and consumer ACKs are recorded; no silently reinterpreted design |
| `P2B-BASE-05` | Destructive migration test requested against persistent DB | Guard refuses the operation; test is redirected to isolated disposable cluster, with status `NOT_RUN/BLOCKED` until safely performed |

### 2.9. `P2B-GATE-01` — Conditional Phase 2B design approval (APPROVED_DESIGN_CONDITIONAL)

**Recorded decision (2026-11-07):** The team lead selected **A — `APPROVED_DESIGN_CONDITIONAL`** for the Phase 2B design documentation. TV2's scope and design principles are approved **subject to all outstanding conditions in the table**. This decision does not approve SQL/DDL/GRANT bodies, running migrations, code, repository modifications or activation of Phase 2.

| Gate item | Status at documentation review | Required closure evidence / owners |
|---|---|---|
| Exactly six Phase 2 tables; transitional Phase 3 Dispute FK | **Design choice approved** | TV2 produces precise DDL/constraint matrix and Phase 3 FK completion path, reviewed with TV5 and Phase 3 consumer |
| One transactional Alembic schema revision; post-Phase-1 parent | **Design choice approved** | TV2+TV1 record accepted Phase 1 SHA/head and disposable upgrade/downgrade verification |
| Least-privilege API/Manager grants and minimal triggers | **Policy approved; exact SQL pending** | TV2 proves column-level privileges, guards and negative tests; TV3/TV5 review sensitive Inbox/Result boundaries |
| Transaction-scoped UoW + bounded executor | **Design choice approved; sizing pending** | TV1+TV2 measure pool/executor limits, lock/statement timeout and cancellation semantics |
| Callback bytes, deduplication, finalization invariants | **Cross-owner agreement pending** | TV2+TV3+TV5 agree exact implementation interface; verify with real DB and raw-byte tests |
| FIFO/Allocation/Cancel lock order | **Approved baseline design; Phase 2 integration pending** | TV2+TV4+TV5 verify on actual PostgreSQL multi-session races |
| Interphase impact and independent review | **ACKs pending** | TV1+TV2 and each affected consumer provide explicit human acknowledgements; missing ACK remains blocked |
| Overall Phase 2 readiness | **Not ready for implementation** | Phase 1 integration accepted on `main`; no blocked gates; separate coding/release authorization needed |

**Gate outcome:** `APPROVED_DESIGN_CONDITIONAL` (design only). Outstanding conditions remain `PENDING` and can block implementation/release. Next design review: Phase 2C, without assuming Phase 2B evidence is complete.

## 3. Proposed design deliverables (TV2)

| ID | Document deliverable | Explicit checks |
|---|---|---|
| `P2B-01` | Single six-table transactional schema-revision design and dependency map | Record accepted `main` parent at implementation time, rollback, staged permission activation, and P2B-MIG-01..05 |
| `P2B-02` | Table-by-table DDL/constraint/index traceability matrix | Database Design section 9, approved catalog, no 19th table; mark transitional corrected-by-dispute FK/guard and future Phase 3 completion |
| `P2B-03` | API/Manager DB privileges matrix; Simulator receives none | Immutable references/results; principle of least privilege |
| `P2B-04` | Lock ordering/transaction ownership maps and rollback plan | Listing before Job; DB trusted clock after locks |
| `P2B-05` | PostgreSQL multi-session race/lock fixture plan | No mock-only proof of contention behavior |

## 4. Critical transaction design (already approved)

- `TX-ALLOCATE`: Listing -> *actual* FIFO-head Job; commit Job `RUNNING`, count increment, one Allocation, one Attempt and one Outbox **atomically**.
- `TX-OUTBOX-CLAIM/ACK/RETRY`: Outbox-only claim, version/fencing CAS, no outbound HTTP while any DB lock is held.
- `TX-INBOX-INGRESS`: API authenticates callback, locks Listing -> Job, commits original bytes and DB `received_at < hard_deadline_at`; duplicate same ID/same bytes is no-op; changed bytes conflict.
- `TX-FINALIZE` / `TX-DEADLINE-FALLBACK`: Listing -> Job -> Allocation -> Inbox -> Contribution -> Aggregate; committed on-time Inbox precedence, at-most-one terminal and GPU release; fallback produces no Worker penalty.
- `TX-CANCEL` from Phase 1 must serialize correctly with `TX-ALLOCATE`. `SKIP LOCKED` is allowed on Listing/Outbox claims but **never** to skip a FIFO-head Job.
- Keep Phase 3 evidence-retention FKs and future adjudication compatibility while withholding actual Dispute and retention-exception implementation.

## 5. Required cross-phase handoff

Obtain source version and DB-ACK from Phase 1B owner, Job schema/cancel ACK from TV5, Listing capacity ACK from TV4, callback/keys ACK from TV3, and Manager integration review from TV1. If an accepted physical schema or role-grant decision must change, create an explicit change-control record rather than quietly rewording approved docs.

## 6. Test mapping and review gate

- Mandatory planned `DBTX-03` to `DBTX-12` and applicable physical schema/privilege tests from `database-design.md`; include two real DB sessions, barriers, rollback/crash injection and exact invariant checks.
- Log baseline SHA/revision, target DDL diff, down/forward migration safety, actual reviewer names and negative permission tests.
- **Documentation exit:** reviewable plan with constraints, privileges, DB lock graph and fixtures.
- **Runtime status:** `NOT_RUN`; no migration or implementation authorized.

## 7. Decision register after `P2B-DEC-01` and `P2B-DEC-02`

| ID | Topic | Decision needed | Proposed owner(s) |
|---|---|---|---|
| `P2B-DEC-02` | Phase 2 Alembic rollout organization | **APPROVED**: one transactional six-table schema revision; grants/triggers subject to separate review; activation gate mandatory | TV2 + TV1 |
| `P2B-OPEN-03` | Least-privilege DB policy | **APPROVED (policy only):** separate API/Manager non-superuser roles, minimal grants, constraints and protective triggers | TV2 + TV1 |
| `P2B-OPEN-03A` | Exact table/column GRANT matrix | **APPROVED_CONDITIONAL** in §2.4; final SQL/ORM feasibility, byte-exact callback dedupe contract and affected-owner ACKs are pending | TV2 + TV3 + TV4 + TV5 |
| `P2B-OPEN-03B` | Protection triggers/constraints | **APPROVED (design strategy only)** in §2.5; final SQL and grant feasibility remain pending; preserve Phase 1 guards | TV2 + TV3 + TV5 |
| `P2B-OPEN-03C` | Safe grants rollout and negative tests | **APPROVED (design-only)**: staged, fail-closed gate; real-role disposable PostgreSQL verification and human reviews mandatory before separate activation authorization | TV2 + TV1 |
| `P2B-OPEN-04` | Transaction adapter, sessions and concurrency | **APPROVED (design-only):** transaction-scoped UoW, one Session per complete DB transaction, bounded synchronous DB execution under async supervisor; worker/pool sizing, SQL feasibility and shutdown validation still pending | TV2 + TV1 |
| `P2B-OPEN-05` | Baseline and migration safety | **APPROVED (design-only):** Phase 1 accepted `main` SHA and actual Alembic head/DB revision, not frozen `0005_listing_d7`; D1/D2/D3 and drift checked before migration design | TV2 + TV1 |
| `P2B-GATE-01` | Conditional Phase 2B design approval | **APPROVED_DESIGN_CONDITIONAL (2026-11-07):** design approved, all unresolved SQL, test, sizing, baseline and cross-owner ACK gates retained | Team lead; TV2 for closure |

Approved design decisions: `P2B-DEC-01`, `P2B-DEC-02`, `P2B-OPEN-03` (policy), `P2B-OPEN-03A` (**conditional grant intent only**), `P2B-OPEN-03B` (**minimal trigger strategy only**), `P2B-OPEN-03C` (**staged fail-closed rollout gate**) and `P2B-OPEN-04` (**transaction-scoped UoW / bounded DB execution design only**), plus `P2B-OPEN-05` (**accepted Phase 1 baseline selection; implementation evidence pending**). `P2B-GATE-01` is APPROVED_DESIGN_CONDITIONAL; executable GRANT/trigger SQL, measured sizing and cross-owner ACKs remain pending. None of these decisions authorizes a repository edit, migration execution, DB privilege change, production activation or application-code implementation.

## Approved design references

- [SRS](../../requirements.md), [FR](../../functional-requirements.md), [NFR](../../non-functional-requirements.md).
- [System Architecture](../system-architecture.md), [Module Design](../../design/module-design.md), [Database Design](../../design/database-design.md), [API Contract](../../design/api-contract.md), [Test Design](../../design/test-design.md).
- [ADR-001 to ADR-008](../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), ADR-004 (signed result) and ADR-005 (retries and deadlines).
- [Phase 1E](phase1e_job_submission_queue.md), [GPU-005-B reference specification, Phase 1 owner-approved; Phase 2 design conditionally approved outside PR #39](phase1e_gpu005_reference_technical_specification.md), [Phase 2 readiness](../../development/phase2_readiness_and_handoffs.md), [Phase 2 decisions](../../development/phase2_decision_register.md) and [Phase 2 test plan](../../design/phase2_test_and_acceptance_plan.md).

The existing approved ADR/Database Design/API contracts are normative. Phase 2A–2E architecture work packages have **conditional owner design approval**; this v1.3 deep-review addendum proposes additional implementation-level interface specifications that are **not** independently approved. All Phase 2 runtime tests remain `NOT_RUN`.

## Appendix PR39-B (2026-11-07): Data/migration and transaction preconditions

**Status:** `DESIGN-SUPPLEMENT / DB ROLE TESTS NOT_RUN / NO IMPLEMENTATION AUTHORIZATION`.

### B1. Safe, version-pinned schema rollout

- PR #39 HEAD `44579ed` has evidence of Alembic `0005_listing_d7` as the Phase 1 test baseline, but PR #39 is still Draft, not an accepted `main` merge. **Never hardcode `0005_listing_d7` as Phase 2 migration parent until TV2 reads the actual accepted main head and verifies DB `alembic_version`.**
- The approved Phase 2 change is **exactly six new tables** in one dependency-ordered schema revision: `execution_attempts`, `allocations`, `execution_outbox`, `result_inbox`, `signed_results`, `job_reputation_contributions`. The deferred `corrected_by_dispute_id` FK must not refer to an as-yet-uncreated Phase 3 `disputes` table; require NULL in Phase 2.
- Use a staged schema revision **then** reviewed GRANTs/necessary triggers **then** negative tests on an isolated disposable PostgreSQL cluster; verify Phase 1 operations and native restricted roles before enabling any Manager Phase 2 writes. No runtime superuser or owner-backed `SET ROLE` as evidence.

### B2. DB invariants and operation boundaries

| Operation | Atomic commitment / uniqueness | Required race test |
|---|---|---|
| `TX-ALLOCATE` | `jobs.RUNNING`, one stable `execution_attempt`, capacity allocation and stable Outbox event in one commit; Listing lock precedes Job lock | two Managers, one Listing, insufficient capacity, paused/cancel race |
| Inbox ingress | exact original raw envelope bytes + SHA-256 + DB-trusted `received_at`; one parseable `result_id` uniqueness; identical replay 202, altered bytes 409 | two concurrent inserts for same ID; loser rollback/re-read committed winner |
| Accepted result | immutable `signed_results` with `(worker_id,key_id)` FK and one accepted result per Job; preserve signed wire bytes | concurrent different result IDs for same Attempt/Job |
| Finalization | signed-result acceptance, Job terminal, GPU release, Inbox handled, contribution and reputation delta in one commit | crash before/after commit and concurrent timeouts |
| Key retention | retired `worker_public_keys` remain while referenced evidence survives, physical RESTRICT/FK | rotate K1->K2, then verify old receipt and reject key deletion |

READ COMMITTED with explicit locked rechecks and a fresh DB `clock_timestamp()` after Job lock is the approved approach. Session/UoW owns commit; repositories must not commit autonomously. Commit-time connection loss, cancellation or ambiguous `40003` is **unknown outcome**; do not retry the mutation as if it rolled back. Reconcile the durable transaction result first.

### B3. Risk inherited from PR #39 test infrastructure

TV5 reviewed a P2 test-isolation issue: the Phase 1 HTTP/Chromium/Postgres E2E test can rotate cluster-wide `gpm_api_app` and `gpm_manager_app` role passwords, while schema teardown does not restore them. This is not a proven production password leak. **For Phase 2 use a dedicated one-shot PostgreSQL cluster destroyed after the job**, or a tightly controlled restoration fixture with cleanup failure visible; schema reset alone is not sufficient. Never run safety-marked tests on a persistent developer or shared database.

The Phase 1 readiness L2 proposal checks additional relations/permissions; it remains `PENDING_OWNER_DECISION`. The Phase 2 **migration preflight** can validate its own DB dependencies without changing Phase 1 readiness route semantics.

**Owner dependencies:** TV2 must provide migration/grant matrix and exact UoW boundary; TV1 confirms Manager usage; TV3 verifies Inbox/signature raw-byte confidentiality; TV4 supplies allocation lock order; TV5 supplies finalization/reputation writes. `PENDING_ACK` is not a failed test or an authorization to infer a privilege grant.

---

## Appendix P2B-DR (2026-11-07): Deep review against PR #39, Database Design, Phase 2A v0.9

> **Review status:** `DEEP_REVIEW_PROPOSED / ORIGINAL_P2B_GATE_REMAINS_APPROVED_DESIGN_CONDITIONAL / NEW_SQL_AND_CROSS_OWNER_CONTRACTS_PENDING_ACK`. These checks are *documentation and future acceptance designs only*. They do not claim a working migration, a new privilege grant, an executed race test, accepted PR #39, or authorization to write code. See companion report `REVIEW_PHASE2B_v1.3.md` for each finding and severity.
>
> **Evidence anchor:** PR #39 `feat/gpu-int-01-runtime-integration`, HEAD `44579ed846051dee9000078e1afd7e8ea62e7358` against `main@1d8b1b2c52b759d99a072c3d0d889b375083a8c4`, still Draft/unmerged at review. Actions run `42350954394` completed successfully for Phase 1 integration; it is not Phase 2 DB acceptance. PR #42 is separately stacked on #39 and not automatically accepted into Phase 2's baseline.

### DR-B1. Baseline/ACL preflight that does not rewrite the Phase 1 readiness contract

Before any authorized migration, TV1 and TV2 freeze: merged/accepted Phase 1 `main` SHA, Git migration graph and `alembic heads`, actual `alembic_version` in the isolated target database, `current_user=session_user` login evidence for both `gpm_api_app` and `gpm_manager_app`, inherited `gpm_api_rw/gpm_manager_rw` grants, existing Phase 1 D1/D2/D3 guards, and exact tests using the emitted SQL from the adapters. If PR #39 or #42 changes before merge, re-evaluate the baseline and affected ACKs. Never infer a migration parent from the present observational `0005_listing_d7`.

`CR-GPU-INT-01-READY-01` on PR #39 remains an undecided **Phase 1 L2 HTTP readiness change**. A separate **Phase 2 Manager fail-closed schema/grant preflight** may be specified without silently changing `/health/ready` on the Phase 1 API. Missing checks -> `BLOCKED`, not permission to run with DB owner credentials.

### DR-B2. Complete callback ingress / duplicate algorithm (PROPOSED_FOR_ACK)

**This specifies the currently missing race and privilege contract for TV2+TV3+TV5; it does not amend the approved API responses.**

1. Authenticate `SIMULATOR_CALLBACK_TOKEN`, apply strict V1 structural bounds, validate claimed UUIDs, cap raw body size, and preserve the exact received **wire body bytes** before parsing/reformatting. No PENDING row exists for unauthorized or structurally unusable callbacks.
2. A safe **non-locking** lookup of the retained `result_id` may short-circuit an existing exact duplicate; it must compare the **complete raw original envelope bytes** and stored bound identity/context. A SHA-256 match is only a filter. Never lock an Inbox row and then request a Listing/Job row lock.
3. For a new candidate: look up the Job's immutable Listing locator without row lock; begin `READ COMMITTED`; lock `Listing -> Job`; fresh-check `RUNNING`, persisted Attempt identity, authorized claimed Worker/Listing and `hard_deadline_at`. Capture trusted `received_at` using database `clock_timestamp()` **after** Job lock, and admit only if `received_at < hard_deadline_at`. The DB role/column path must not permit a Worker-supplied or HTTP-supplied timestamp to become trusted.
4. Insert immutable raw body/hash and trusted bound context, then COMMIT before `202 STORED`. The PostgreSQL **unique non-NULL result_id** index arbitrates two concurrent first arrivals; a failed conflicting insert rolls back the complete UoW. In a fresh short `READ COMMITTED` transaction, read the committed winner using the constrained duplicate-comparison interface. Return `202 DUPLICATE` only for full-byte and binding-context identity; otherwise `409 RESULT_ID_COLLISION`. No unsafe retry of an uncertain COMMIT.
5. For a retained exact duplicate, `202 DUPLICATE` is allowed **even after Job terminalization** as a lost-ACK repair, but does not move `received_at` or change any state. After the authorized 23-day purge, indefinite duplicate recognition is not promised. No callback that first obtains the Job lock at or after the deadline becomes on-time.

**Least-privilege decision still pending:** a PostgreSQL column-level `SELECT(original_envelope_raw)` permission is *not row-scoped*; granting it to `gpm_api_app` allows reads of that column across all qualifying rows. TV2+TV3 must select one of: (a) a reviewed narrowly scoped trusted duplicate-comparison DB function returning only a status, with fixed search path, no PUBLIC execute grant and caller validation; or (b) an explicitly reviewed API-role read boundary whose data exposure is justified and tested. Do not claim a column GRANT provides row-level isolation. An optional function is not a seventh table or a new service, but exact function privileges are **not** approved yet.

**Clock-privilege issue pending:** decide and test exactly how the DB-generated `received_at` value is sampled after the Job lock and cannot be supplied from the HTTP payload: an approved restricted SQL path or reviewed server-default/trigger approach. If such a choice alters an accepted physical schema or grant, use the existing L2/L3 change-control process rather than silently changing it.

### DR-B3. Manager receipt processing and fallback (PROPOSED_FOR_ACK)

- A tentative claim/locator for pending Inbox work may be read without locks, but **never hold an Inbox lock while waiting on Listing/Job**. The definitive `TX-FINALIZE` or `TX-DEADLINE-FALLBACK` UoW locks `Listing -> Job -> required Allocation/Inbox rows`; fresh SQL statements under `READ COMMITTED` must see previously committed on-time Inbox rows.
- **Candidate order:** `received_at, id` among admitted candidates with `received_at < hard_deadline_at`. Multiple `result_id` values may represent one Attempt after a cold Simulator restart. Uniqueness by `result_id` is not uniqueness by Job: the first eligible verified result in this deterministic order wins one accepted `signed_results.job_id` slot; later candidates must not release GPU or increment Reputation.
- **Batch completeness:** if processing bounded Inbox batches, the deadline fallback decision must prove that **all eligible committed on-time candidates** have been examined, including later batches after a rejected earlier one. Reaching a batch limit is `CONTINUE/DEFER`, **never** evidence permitting `FAILED/SYSTEM_FAULT`. Put explicit bounded work and progress markers in the TV1/TV2/TV5 design; do not add a 19th table by default.
- **Terminal reconciliation gap:** after one result wins, additional already-committed candidates could remain `PENDING` and no longer be eligible for normal RUNNING processing. TV2+TV3+TV5 must explicitly agree on bounded post-terminal Inbox housekeeping, a redacted structured rejection reason and retry/recovery semantics. A candidate that was on time but non-winning must not be mistaken for a second accepted result. Do not invent a new API response/status or adjudication outcome without owner review.
- The Manager may perform CPU-bounded signature/JCS work in the same transaction after acquiring authoritative locks **only under measured lock duration and payload limits**, or use a verify-outside / reverify-context-inside pattern subject to an explicit TOCTOU recheck design. The TV3 verifier itself owns no SQL Session or commit; the TV5 transaction owns every final business effect.

### DR-B4. Atomic business effects and Outbox fencing

- `TX-ALLOCATE`: `Listing -> actual FIFO head Job`, then one transaction for Job RUNNING, counter, Allocation, Attempt, Outbox. Re-use Phase 1 Listing capacity and locked FIFO rules; no Job-row `SKIP LOCKED`, no network I/O while locked, and only one Listing per allocation transaction (`P2D-OPEN-01`).
- `TX-OUTBOX-CLAIM/ACK/RETRY`: **Outbox-only** DB UoW, stable `(attempt_id,event_id,dispatch_payload)` across HTTP retries. Every lease ownership/ACK/retry mutation is conditional on observed `lease_version`, owner/lease state and due boundary. Stale 30-second claims must affect zero rows; HTTP `202` only acknowledges dispatch, not Job completion. Retrying an already-RUNNING Attempt on a PAUSED Listing is permitted (`P2D-OPEN-02`) without new Allocation/deadline.
- `TX-FINALIZE`: use one commit for immutable Signed Result, Job terminal, allocation ACTIVE->RELEASED once, Listing counter release once, accepted Inbox state and `job_reputation_contributions` insert plus matching lifetime counter delta. Valid signed `FAILED/JOB_FAULT` inserts a contribution with category `NONE` but does **not** increase an aggregate counter. SYSTEM_FAULT/CANCELLED create no contribution.
- `TX-DEADLINE-FALLBACK`: only after the complete eligible Inbox search; one FAILED/SYSTEM_FAULT and release, no signed result, no contribution and no Worker penalty. A rejected cryptographic claim must not make a Job terminal before the deadline if another on-time candidate may exist.
- `COMMIT` loss is *not* a definite rollback. Adopt the Phase 1 #39 distinction: a **definite rollback** is not automatically retriable: only explicitly qualified transient errors (for example `40001` / `40P01`) may receive a bounded whole-UoW retry; `23xxx` constraint errors are generally non-retryable business/integrity failures. Connection loss, `40003` and unknown COMMIT outcomes require **read/reconcile durable state** first. Async task cancellation does not stop the synchronous SQL worker; never dispose an Engine while in-flight transactions are unresolved.

### DR-B5. Six-table physical schema and grants — no unchecked new objects

- Exactly the approved six Phase 2 tables, **one schema revision** after an actually accepted `main` migration head; Phase 1 tables `worker_public_keys`, `worker_reputation_aggregates`, `gpu_listings`, `jobs`, `simulation_references`, and `audit_events` already exist. Re-verify their real columns and D1/D2/D3 guards. No seventh Phase 2 table, no new runtime DB service role, and no extra Manager/Simulator service.
- `job_reputation_contributions.corrected_by_dispute_id` is nullable and **NULL throughout Phase 2**, with `correction_version=0`, `effective_category=initial_category` and no Phase 3 FK until `disputes` is created. The transitional CHECK is not the permanent Phase 3 constraint; design its safe replacement separately. Check exact defaults, `RETURNING` clauses, sequence/identity access and ORM-emitted SQL using native restricted runtime logins rather than granting broad privileges to make tests green.
- `signed_results` retains `(worker_id,key_id)` composite FK to historical `worker_public_keys` and immutable raw accepted bytes; the Manager may read registered public keys but must not gain Worker private keys or write protected oracle data. The API callback token does not imply signature validity. Confirm key-rotation quiescence and historical key retention with TV3/TV5 before code.
- GRANT and necessary trigger revision(s) may follow the six-table schema revision, but Phase 2 runtime is **disabled** until the entire staged policy and negative-test suite pass. Ordinary service roles cannot UPDATE evidence, DELETE a Job or edit immutable fields. Avoid unconditional Signed Result deletion blocks that would obstruct an approved future 23-day guarded cleanup. Actual Phase 3 cleanup execution is **not a Phase 2 runtime acceptance test**; only schema/foreign-key compatibility planning is required now.
- `result_inbox` row-level confidentiality, bytes, clock and uniqueness contracts from DR-B2 are mandatory to resolve before granting its reads; no broad general-purpose oracle or signature export to the API/frontend.

### DR-B6. Test safety, resource budgets and acceptance evidence

- **Disposable PostgreSQL only:** PR #39's E2E test has an open TV5 finding about rotating shared cluster-wide `gpm_api_app/gpm_manager_app` passwords without restoration by schema teardown. Phase 2 must use a dedicated one-shot disposable PostgreSQL cluster with guaranteed cluster destruction, or a reviewed password-restoration fixture with observable cleanup failures. Never run these experiments on a persistent or shared database. Treat prior PR #39 CI as *Phase 1 evidence*, not proof this risk is closed or Phase 2 tests pass.
- Real two-or-more-session test barriers must establish both commit orders for `Submit<->Pause/Resize`, `Allocate<->Cancel`, callback `<-> Deadline`, repeated callback ID, concurrent finalizers, and Outbox lease takeover. Record `current_user`, `session_user`, SQLSTATE, exact before/after persisted row snapshots, revision and Git SHA. No mock-only PASS for cross-transaction invariants.
- TV1+TV2 must measure connection pool size, bounded synchronous worker/queue capacity, lock/statement timeout budgets, backlog behavior and shutdown drain, preserving progress for the three independent Manager loops. Numeric defaults remain `PENDING_PARAMS` rather than invented performance evidence.

### DR-B7. Proposed focused regression matrix (ALL `NOT_RUN`)

| ID | Future test / fault | PASS oracle (future implementation only) |
|---|---|---|
| `P2B-DRT-01` | Migrate an accepted disposable Phase 1 DB | Exactly six Phase 2 tables; approved FK/guard set; one correct schema-revision dependency; no orphan/mismatched `alembic_version` |
| `P2B-DRT-02` | Native API and Manager role GRANT positives/negatives; ORM SQL incl. `RETURNING` | Required accepted operations pass; unauthorized raw oracle/DDL/signed-result mutation denied; current_user=session_user; no permission widening |
| `P2B-DRT-03` | Two concurrent identical callbacks with same `result_id` | One Inbox row; losing transaction reconciles committed winner; both receive safe `202`; original raw bytes and `received_at` unchanged |
| `P2B-DRT-04` | Same `result_id` but altered body / different context | `409 RESULT_ID_COLLISION`; no overwrite and no second eligible Inbox record |
| `P2B-DRT-05` | Duplicate of retained old receipt after Job terminal | `202 DUPLICATE`, no write/clock change/reputation delta |
| `P2B-DRT-06` | Multiple on-time Inbox candidates across batches, valid receipt in later batch; Manager processes after deadline | Every on-time candidate evaluated before timeout; valid later receipt wins; zero false SYSTEM_FAULT |
| `P2B-DRT-07` | Two different `result_id` values for same Attempt, concurrent finalizers | One accepted Signed Result/Job, one release, at most one contribution/delta; non-winning Inbox state eventually reaches documented terminal state |
| `P2B-DRT-08` | Outbox expired claim/stale owner and bounded retry, including PAUSED Listing | CAS old owner/version affects 0 rows, stable event/attempt, no extra Allocation/deadline, no premature terminalization |
| `P2B-DRT-09` | Cancel vs Allocate and two Managers competing for one Listing | Both commit orders yield legal state, strict FIFO and exact conservation `allocated_gpu_count == SUM(ACTIVE allocations.gpu_count)` |
| `P2B-DRT-10` | Fault after partial Finalization writes, then restart and replay | Rollback has zero partial effects; after commit exactly one terminal transition/release/contribution/aggregate change |
| `P2B-DRT-11` | COMMIT ACK loss + coroutine cancellation with a live sync DB worker | No blind mutation retry, no cross-thread Session, observed reconcile without duplicate business effect |
| `P2B-DRT-12` | Worker K1 signed receipt, retire K1, register K2; attempt premature key DELETE | Old retained evidence still verifies, key DELETE restricted; no private signing material in DB |
| `P2B-DRT-13` | Disposal/credential rotation failure injection on dedicated PG cluster | No persistent/shared cluster touched; credentials restored or entire ephemeral cluster destroyed; cleanup failures visible |
| `P2B-DRT-14` | Executor/DB-pool saturation under concurrent Scheduler/Dispatch/Finalization | Bounded queue, measured timeouts and recovery; no starvation of Finalization; phase-independent retries remain finite |
| `P2B-DRT-15` | Phase 2 corrected contribution fraud `correction_version=1`/non-NULL `corrected_by_dispute_id` | Transitional constraint and role privilege deny change; real Dispute correction remains Phase 3 only |

### DR-B8. Cross-owner ACK matrix, scope and release gates

| Interface contract | Required reviewer/owner ACK | Current status |
|---|---|---|
| Phase 1 accepted `main` SHA + migration head + native DB identity | TV1+TV2 (with affected Phase 1 owners) | `PENDING_BASELINE` |
| Allocation UoW FIFO/lock order, one Listing per TX | TV1+TV2+TV4 | `PENDING_ACK` |
| Callback exact-byte dedup + result_id UNIQUE winner reconciliation + Inbox privileges | TV2+TV3+TV5 | `PENDING_ACK` |
| Receipt ordering, multi-batch deadline proof and non-winning Inbox cleanup | TV1+TV2+TV3+TV5 | `PENDING_ACK` |
| Outbox CAS/fencing and transport retry | TV1+TV2+TV5 | `PENDING_ACK` |
| Finalization/reputation atomic delta and key evidence retention | TV2+TV3+TV5 | `PENDING_ACK` |
| Restrained migration/GRANT/trigger SQL, no Phase 3 premature logic | TV1+TV2; affected TV3/TV4/TV5 | `PENDING_SQL_TEST` |
| Real PostgreSQL native-role races, safe test cluster and measured pool limits | TV1+TV2; relevant TV3/TV4/TV5 | `PENDING_TEST` |

**Release boundary:** `P2B-GATE-01` remains `APPROVED_DESIGN_CONDITIONAL`. New DR-B2/DR-B3 interfaces are `PROPOSED_FOR_ACK` and may need owner change control if they alter a normative contract. Code, migration, GitHub writes, activation and deployment are **NOT AUTHORIZED** by this review. All tests in DR-B7 are `NOT_RUN`.

