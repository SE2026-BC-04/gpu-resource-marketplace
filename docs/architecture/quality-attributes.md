# GPU Resource Marketplace - Quality Attribute Scenarios

**Version:** 0.12 (11 scenario test designs approved; approved unresolved-dispute hold and escalation policy; new exception tests awaiting review)  
**Date:** 2026-10-18  
**Status:** **11/11 Quality Attribute Scenario test designs APPROVED** (through 2026-10-18), including QA-DAT-01 with 17 deterministic checks and the 7-day dispute filing rule. **All implementation tests remain `NOT_RUN`**; no performance, recovery or system-correctness result has been verified. 30-minute deployment effort, 1.50x latency and 0.85x throughput remain calibration hypotheses, not product SLAs. **APPROVED policy (2026-10-18):** keep evidence while a timely dispute is OPEN, without an arbitrary maximum; warn within 1 hour of exception detection, elevate to CRITICAL at 24 hours unresolved, retry every 15 minutes while Manager is healthy, and purge within 1 hour of resolution if evidence is already expired. New exact exception-monitoring test specifications below remain proposed for review; they have NOT RUN.  

See [System Architecture](system-architecture.md), [SRS](../requirements.md) and [NFR](../non-functional-requirements.md).

## 1. Scenario format and acceptance vocabulary

Every scenario uses the standard six-part template:

1. **Source:** who/what causes the event.
2. **Stimulus:** event or requested change.
3. **Environment:** system state and operating conditions.
4. **Artifact:** the component affected.
5. **Response:** expected system/team behavior.
6. **Response measure:** observable, measurable pass/fail criteria.

**APPROVED:** business invariants and numerical constraints accepted in the SRS. **TARGET:** quantitative objectives already proposed by NFR v1.0 but not yet measured. **PROPOSED:** new engineering goal requiring team confirmation. **OPEN:** cannot yet have a hard pass/fail threshold without an additional design/test decision.

> **Important distinction:** <=18 elapsed hours is the maximum time for *initial substantive change-request response*, not the time to deliver the code change. A Modifiability scenario additionally needs change effort, change propagation, compatibility and regression metrics.

### 1.1. Non-ambiguous scenario test protocol (mandatory for every QA scenario)

Each Quality Attribute Scenario must have at least one explicitly identified verification case with: **test ID**, **baseline/preconditions**, **fixed input/fixture**, **stimulus/action**, **expected observable outcome**, **assertion/oracle**, **run evidence**, and **decision rule**. No statement such as "acceptable performance", "minor impact", "works well", or "easy to extend" is a passing criterion without an operational definition.

| Execution status | Exact meaning |
|---|---|
| `PASS` | The test was executed on the declared code version and environment, and **every** mandatory assertion matched its oracle; evidence is attached. |
| `FAIL` | The test was executed and **at least one** mandatory assertion did not match; record the first failing assertion and its counterexample. |
| `BLOCKED` | A named prerequisite is missing (e.g., contract snapshot, module ownership map or performance profile). Record the prerequisite and owner; never count as PASS. |
| `NOT_RUN` | Test specification exists but has not been executed on an implementation. Never count as PASS. |
| `ERROR` | Test infrastructure could not execute a meaningful assertion; record error and rerun. Never count as PASS or business-behavior FAIL. |

**Acceptance gate:** A scenario is **verified only if all of its approved MUST checks are `PASS`**. `FAIL`, `BLOCKED`, `NOT_RUN`, `ERROR`, skipped or `xfail` checks never establish acceptance. For new metrics under calibration, record a separately labeled **hypothesis outcome** (`SUPPORTED`, `REFUTED`, or `UNMEASURED`) rather than quietly converting them to product requirements. An exercise can pass all mandatory product invariants while refuting a modifiability effort hypothesis; report both outcomes separately.

**Reproducibility:** Preserve Git commit IDs, database migration version, fixture IDs/seed, fake-clock timestamps, API contract snapshot, test-run command when implemented, runner/environment version, exit code, assertions and log/artifact locations. CI should give test-ID-specific failures, not only a generic green/red summary. Actual executable commands must be added only when the test runner exists; this document does not pretend its examples have run.

**Cross-scenario rule:** Any numeric target stated in an owning NFR (e.g., 736 VUs, read p95 <=2s, recovery <=120s) remains a measurable target rather than a verified system capability until its environment and workload are fixed and the test has passed. Every unresolved test prerequisite is an explicit `BLOCKED`, never an ambiguous "to be tested" pass.

## 2. Quality scenario catalog

### QA-MOD-01 - Modify scheduling algorithm (Modifiability)

**Review decision (2026-10-17):** Option A ACCEPTED. `<=2` impacted production modules and `<=2` engineer-days are **calibration hypotheses**, not approved product/release thresholds. Nevertheless their evaluation is **binary** under the pre-registered measurement procedure below: the measured hypothesis is supported or refuted, never described vaguely as "roughly achieved". Approved business invariants remain hard PASS/FAIL gates.

| Element | Scenario |
|---|---|
| **Source** | Project Owner / stakeholder submitting a traceable change request (CR). |
| **Stimulus** | In a controlled **future change exercise**, add an opt-in `PriorityScheduling` policy while retaining strict FIFO as the default. Priority is descending integer rank; for equal priorities, order by `(submitted_at, job_id)` ascending. The exercise is NOT authorized to enable a non-FIFO policy in the current MVP. |
| **Environment** | Isolated development/CI branch with a pinned baseline commit, fixed PostgreSQL seed, fake clock, preserved API contract and working Manager/Simulator. The SRS still mandates FIFO for MVP; any real product switch to priority would first require approved scope/FR change. |
| **Artifact** | Manager scheduling-policy boundary and its dependencies; Job Lifecycle, shared atomic allocation engine, public API and persisted schemas are protected/observed artifacts. |
| **Response** | Assess the CR; implement an isolated alternate scheduling strategy; preserve FIFO as default, non-overallocation, legal states, retry safety, API compatibility and retention. Execute contract and integration regression tests, inspect code diff and log engineering effort. |
| **Response measure** | **MANDATORY GATES:** substantive CR assessment <=18 elapsed hours (NFR-O01); FIFO default behavior unchanged; 0 allocation/state/reputation invariant violations; 0 breaking changes to the frozen public API; all enumerated critical regression tests PASS. **CALIBRATION HYPOTHESES:** <=2 impacted production modules and <=16 person-hours (2 engineer-days, defined as 8 hours/day). **PERFORMANCE TARGETS:** compare against the fixed 736-VU NFR profile when it exists; lack of such a profile is an explicit blocker for performance verification, not a silent PASS. |

#### QA-MOD-01 deterministic exercise fixture and oracle

Create an isolated test fixture (not a production API contract): one `ACTIVE` listing `L` with `total_gpu=4`, `allocated_gpu=0`; three `QUEUED` jobs ordered by `submitted_at`, then immutable `job_id`:

| Job | Required GPUs | Creation order | Exercise-only priority |
|---|---:|---:|---:|
| `A` | 3 | 1 | 1 |
| `B` | 2 | 2 | 10 |
| `C` | 1 | 3 | 10 |

Run a **single scheduler allocation pass until no further job is schedulable**, with no worker completion during the pass. The priority field may be supplied by an isolated policy-test fixture; it is **not** an existing Client-facing MVP field. A future real feature may need additional domain/API/schema work and a separate requirements change.

- **FIFO default oracle:** `A=RUNNING`, `B=QUEUED`, `C=QUEUED`, `allocated_gpu=3`, `free_gpu=1`. Even though `C` fits the free GPU, `C` cannot bypass blocked head-of-line `B`.
- **Opt-in priority experiment oracle:** `B=RUNNING`, `C=RUNNING`, `A=QUEUED`, `allocated_gpu=3`, `free_gpu=1`. `B` precedes `C` because they have equal priority and B was submitted first. **This behavior must never be activated for baseline MVP traffic.**
- **Safety oracle for both policies:** every committed state satisfies `0 <= allocated_gpu <= 4`; every `RUNNING` job has exactly one active allocation; no `QUEUED`/`CANCELLED` job has an active allocation.

#### QA-MOD-01 verification cases and decision rules

| Test ID | Fixed action / evidence | Exact expected outcome | Gate |
|---|---|---|---|
| `MOD-CR-01` | Compare UTC `received_at` and `first_substantive_response_at` in CR ticket. A substantive response must identify owner, priority, change impact and next step; auto-acknowledgment does **not** qualify. | `0 <= delta_seconds <= 64,800`; missing timestamp or missing required substantive content = `FAIL` after a received CR has been processed. | **MANDATORY** |
| `MOD-FIFO-01` | Seed `L,A,B,C` above; select default policy; run one scheduler pass; query committed Jobs/allocations. | `RUNNING={A}`, `QUEUED={B,C}`, allocated 3, free 1; any other result = `FAIL`. | **MANDATORY** |
| `MOD-PRIO-01` | Same seed reset; explicitly opt into experimental priority policy in isolated test config; run a pass; capture scheduler selection trace. | `RUNNING={B,C}`, `QUEUED={A}`, selection order exactly `[B,C]`, allocated 3, free 1; any other result = `FAIL`. | **EXERCISE GATE** |
| `MOD-RACE-01A` | Seed `L:4 GPU`, job `A:3 GPU, QUEUED`; use transaction barriers so Client cancel **commits before** Manager allocation attempt. | `A=CANCELLED`; zero active allocations for A; listing allocated=0. | **MANDATORY** |
| `MOD-RACE-01B` | Reset same seed; barriers make Manager allocation **commit before** Client cancel attempt. | `A=RUNNING`, one active allocation of 3; cancellation returns `409 Conflict`; listing allocated=3. | **MANDATORY** |
| `MOD-PAUSE-01A` | Seed `L:ACTIVE,4 GPU`, `A:3 GPU,QUEUED`; force listing Pause to **commit before** Manager attempts allocation. | `L=PAUSED`, `A=QUEUED`, listing allocated=0; no newly submitted job accepted while PAUSED. | **MANDATORY** |
| `MOD-PAUSE-01B` | Reset; Manager allocation **commits before** Pause; then deliver a valid finishing result for A while L is PAUSED. | `A` may finish terminal normally; allocation returns to 0 exactly once; `L=PAUSED` remains; queued jobs are not newly allocated. | **MANDATORY** |
| `MOD-FINAL-01` | Seed one `RUNNING` A with one allocation and valid fixture Ed25519 `SUCCESS` receipt; submit the **same** finalization event twice. | One accepted result; Job `COMPLETED`; allocation released once; `successful_jobs` increases by exactly 1, `worker_fault_jobs` by 0; second event has no persistent business effect. | **MANDATORY** |
| `MOD-API-01` | Diff public API contract against pinned pre-change snapshot; run existing API consumer contract tests. | 0 backward-incompatible route, field or response changes; any breaking change or failed contract test = `FAIL`. | **EXERCISE GATE** |
| `MOD-REG-01` | Execute a **frozen test manifest** for FIFO, state transitions, capacity, signature tamper/replay, dispute/reputation and 23-day retention on the exercise commit. | Every mandatory test ID in manifest executed with `PASS`; 0 skipped/xfail/failed cases. Missing test/manifest = `BLOCKED`, failed assertion = `FAIL`. | **MANDATORY** |
| `MOD-SPREAD-01` | `git diff --name-only BASE..CHANGE`; map every changed production file using a module/path ownership map **frozen before** the exercise. Count distinct production modules, including shared/core; exclude tests/docs but do not omit unmapped production files. | `<=2` modules => hypothesis `SUPPORTED`; `>2` => `REFUTED`; missing baseline/map => `UNMEASURED` (`BLOCKED` prerequisite). | **CALIBRATION ONLY** |
| `MOD-EFFORT-01` | Sum per-developer hands-on analysis, implementation, review, debugging and testing time; excludes waiting/elapsed queue time. | `<=16.0` person-hours => hypothesis `SUPPORTED`; `>16.0` => `REFUTED`; missing log => `UNMEASURED` (`BLOCKED` prerequisite). | **CALIBRATION ONLY** |

**Mandatory exercise decision:** `PASS` **only if** `MOD-CR-01`, `MOD-FIFO-01`, `MOD-PRIO-01`, `MOD-RACE-01A/B`, `MOD-PAUSE-01A/B`, `MOD-FINAL-01`, `MOD-API-01`, and `MOD-REG-01` all execute and PASS. One failed assertion -> `FAIL`; a missing frozen contract, fixture, test manifest or module integration -> `BLOCKED`; before any run -> `NOT_RUN`. The `MOD-SPREAD-01` and `MOD-EFFORT-01` calibration findings are separate binary hypothesis results and cannot override a failing system test.

**Implementation note:** Tests use explicit transaction barriers, fresh database snapshots and an injectable clock so each ordering is forced instead of relying on nondeterministic timing or manual clicks. The test runner must report the first incorrect state/ID and committed transaction order. A generic assertion such as "no race condition" without a forced interleaving and state oracle is not sufficient.

**Evidence required to close:** CR issue/timestamps; baseline and exercise commit SHAs; fixture snapshot; DB state before/after each scheduling pass; API contract diff; test-ID-specific CI output; module ownership map and classified `git diff`; timestamped effort entries. Before those artifacts exist, scenario implementation verification is **`NOT_RUN`**, not `PASS`.

**Open test prerequisites, explicit rather than vague:** (1) implement/freeze module ownership map after source layout exists; (2) baseline public API contract snapshot after the API exists; (3) create automated fixture/test runner and CI manifest; (4) define 736-VU environment/traffic profile separately in QA-PER-01. Each absent item blocks the matching measurement only, and never justifies claiming it was verified.

**Modifiability vs Performance trade-off:** a replaceable policy interface isolates changes but must not add unbounded per-job DB queries or lock contention. The shared allocation transaction remains authoritative. Evaluate performance under a **fixed** load-test profile; do not claim p95 or throughput improvement/degradation until both before/after measurements exist. The current MVP still runs strict FIFO only.

### QA-MOD-02 - Evolve signed receipt schema (Modifiability)

**Design-review status (2026-10-18):** nine deterministic verification checks below are **APPROVED FOR TEST DESIGN**, not yet executed (`NOT_RUN`). The exercise is an isolated future compatibility change, **not** a requirement to implement multiple signed-receipt schemas in the current MVP. Version 1 canonical encoding and test keys must be specified by the relevant crypto/API design before the tests can run; missing inputs cause `BLOCKED`, never presumed success.

| Element | Scenario |
|---|---|
| **Source** | Security maintainer / development team submitting a controlled receipt-compatibility change. |
| **Stimulus** | Introduce signed receipt `schema_version=2` with one new optional **signed** field, `simulator_build_tag`, while preserving verification of version-1 receipts. |
| **Environment** | Isolated migration/test branch with pinned baseline commit, deterministic Worker/Job/Attempt IDs, separately injected Ed25519 fixture keys, fixed clock, retained version-1 receipts and frozen public Job API contract. Some evidence may remain beyond 23 days under a previously filed, unresolved dispute hold. |
| **Artifact** | Worker Simulator receipt serializer/signing path, Manager canonical-payload verifier/version dispatch, signer-key lookup and retained immutable signed evidence. |
| **Response** | Produce valid version-2 receipts and continue verifying all retained version-1 receipts against the original signed bytes and signer key; refuse unknown versions or tampered data; preserve exactly-once finalization and the existing public API. |
| **Response measure** | **Required for this change exercise:** `MOD2-01..09` pass with the exact fixed oracles below; **zero** existing retained valid V1 receipts become unverifiable, **zero** tampered/unsupported receipts are accepted, **zero** duplicate business effects and **zero** breaking changes to the pinned public Job API. These are binary regression/compatibility gates, not claims that the feature already exists. |

#### QA-MOD-02 deterministic fixture and measurement boundaries (APPROVED test design)

- Freeze two fixture schema contracts, `V1` and `V2`, including exact canonical byte serialization, signature input, `schema_version`, `key_id`, and Ed25519 public-key fingerprint. Do **not** invent a production canonicalization rule before its ADR; store known-good fixture byte digests and signatures after the contract is frozen.
- Seed Worker `W1`, Listing `L1`, Job `J1`, Attempt `A1`, Result `R1`, signer key `K1` and a valid, accepted `V1` receipt. Keep a snapshot of `canonical_payload_bytes`, `signature`, `key_id`, and their digests before the change. Use a separate eligible Job/Attempt/Result (`J2/A2/R2`) for V2 signing tests so one-result-per-job rules remain meaningful.
- The only proposed new V2 field is `simulator_build_tag="sim-v2-test"`, included **inside the signed canonical payload**, not silently added outside the authenticated bytes. No Client-supplied field may override verification context. A frozen public Job API contract snapshot is required before claiming API compatibility.
- For the held-evidence fixture, a valid dispute was filed at `terminal_at+6d` and remains OPEN at `terminal_at+24d`; the original V1 signed receipt and necessary key metadata are deliberately retained. This is an explicit NFR-D06/D08 retention exception, not a general permission to keep expired history indefinitely.
- **Release gate semantics:** `MOD2-01..09` all PASS to verify *this version-change exercise*. If the product ships V1 only and no change exercise has run, scenario verification remains `NOT_RUN`; V2 support is not an MVP P0 feature by implication.

| Test ID | Controlled input / action | Exact PASS oracle / FAIL witness |
|---|---|---|
| `MOD2-01-V1-BACKWARD` | Run archival signature-and-historical-context verification on the preserved V1 receipt after deploying a V1+V2 verifier; Job `J1` may already be terminal. | Archived signature and stored historical Worker/Listing/Job/Attempt context verify exactly as at baseline; original bytes, signature and `key_id` unchanged; **do not rerun new-result admission or finalization**. Previously valid retained V1 evidence becomes unverifiable or is rewritten => `FAIL`. |
| `MOD2-02-V2-SIGN-VERIFY` | Worker Simulator signs V2 result `R2` for eligible `J2/A2`, including `simulator_build_tag`. | Manager verifies the V2 signature against registered `K1`, correct Worker/Listing/Job/Attempt; persisted V2 signed payload contains the field; exactly one accepted result and one finalization. Otherwise `FAIL`. |
| `MOD2-03-TAMPER-BOTH` | Modify exactly one signed field byte in a copy of archived V1 evidence; repeat on a not-yet-accepted V2 receipt by modifying `simulator_build_tag`. | Historical V1 cryptographic re-verification and fresh V2 result admission both reject the altered bytes; no receipt, allocation or reputation side effect. Any tampered signature accepted => `FAIL`. |
| `MOD2-04-NO-VERSION-SWAP` | Change signed `schema_version` of valid V2 payload to V1 without resigning, and separately attempt to parse V2 bytes as V1. | Neither altered/cross-version interpretation is accepted. Successful downgrade or changed accepted meaning => `FAIL`. |
| `MOD2-05-UNKNOWN-VERSION` | Submit receipt claiming unsupported `schema_version=99`, including a well-formed signature under a fixture key. | Verifier rejects as unsupported; no fallback parsing as V1/V2, no finalization or reputation effect. Acceptance => `FAIL`. |
| `MOD2-06-OLD-KEY-RETAINED` | In fixture only, register a new `K2` for later receipts while preserving historical V1 `key_id=K1` and key material. | Old V1 verifies specifically with `K1`; V2 signed under `K2` verifies with `K2` when registered for its Worker/attempt; mismatched `key_id` or Worker fails. Rotating keys must not rewrite old signatures. No key-rotation UI required. |
| `MOD2-07-EXCEPTIONAL-HOLD` | At `terminal_at+24d`, perform **archival verification, not new-result admission**, on valid V1 evidence attached to a dispute correctly filed at day 6 and still OPEN. | Original bytes, signature, historical public key and recorded acceptance context remain available and cryptographically verifiable by adjudication; missing/unverifiable held evidence => `FAIL`. |
| `MOD2-08-ONE-RESULT-ONLY` | Re-deliver the accepted V1 receipt for `J1`, then submit a different validly signed V2 receipt targeting the already-finalized same `J1/A1`. | No second accepted final result, GPU release or reputation contribution; immutable first accepted receipt remains authoritative. Any second business effect or receipt replacement => `FAIL`. |
| `MOD2-09-API-COMPAT` | Diff the version-change public Job API specification against the pinned baseline; replay frozen Client contract tests. | Zero breaking public API changes and 100% mandatory Client contract tests PASS; missing baseline snapshot or unimplemented contract runner => `BLOCKED`, never PASS. |

**Decision rule (APPROVED test design, 2026-10-18):** all nine tests must PASS on the specified change-exercise branch for QA-MOD-02 to be VERIFIED. Any failing check is a specific compatibility/security defect, not an averaged score. The exact V1/V2 byte format, key registry model, API snapshot and test runner are prerequisites to executing the cases; they remain Architecture/Database/API decisions and do not become silently approved through this proposal.

### QA-REL-01 - Recover Manager after process restart (Reliability)

**Design-review status:** **APPROVED (2026-10-17)** deterministic verification plan, **NOT_RUN**. Mandatory invariants below come from NFR-R01/R03/R04/R08; the 120-second target comes from NFR-R02 and is not yet measured. These tests specify business effects and do **not** approve a particular Outbox/Inbox transport.

| Element | Scenario |
|---|---|
| **Source** | Test operator triggering a controlled Manager process failure (`SIGKILL` equivalent). |
| **Stimulus** | Crash Manager at a known transaction/dispatch/result-processing barrier, then restart the process. |
| **Environment** | Isolated integration-test database with durable committed PostgreSQL state; one Manager owner, deterministic Worker Simulator, fixed seed/fake domain clock, available DB/network after restart. No database-volume loss is simulated. |
| **Artifact** | Durable Job/Allocation/Execution Attempt records; Manager scheduler, delivery/recovery and finalization paths; any durable pending-result representation chosen by the eventual communication design. |
| **Response** | Recover only committed work; resume queued/running attempts without generating a new logical attempt on a transport retry; finish exactly once and release allocation exactly once. |
| **Measurable response** | **MUST:** zero lost committed Jobs, zero duplicate accepted results, zero duplicate reputation effects, zero leaked/overallocated GPUs, unchanged stable `attempt_id` on resend. **NFR TARGET:** eligible pending work has a persisted recovery action within 120.0 elapsed seconds from Manager process start invocation, on a documented test machine with DB ready. |

#### REL fixture and shared oracle

Each test starts from an **independent restored database snapshot**. Seed Worker `W1`, ACTIVE Listing `L1` with `total_gpu=4`, and a configurable `RUNNING` Job `JR` requesting 2 GPUs with one persisted allocation (`allocated_gpu=2`) and logical execution `attempt_id=ATT-JR-1`; also seed a `QUEUED` Job `JQ` requesting 1 GPU when a case requires it. The deterministic worker returns a known signed `SUCCESS` fixture for a valid attempt. Choose a simulated deadline due in the test by a controllable clock; a real-time wait for simulation completion is not the oracle.

After every relevant **committed** transaction, assert `0 <= allocated_gpu <= total_gpu`, `allocated_gpu = SUM(active_allocation.gpu_count)` for the listing, and legal Job states. For a fully completed successful `JR`, assert exactly one accepted receipt, zero active allocations for `JR`, and exactly one net `(success +1, worker_fault +0)` reputation contribution. A rejected/timeout result is a separate failure-path fixture and does not contribute to reputation.

**Crash harness rule:** inject the kill at a named barrier and persist evidence of the barrier and committed transaction order. `sleep()` plus a random kill is not a deterministic crash test. The transport can use an inbox/outbox if later accepted, but the oracle concerns durable intent/result and exactly-once **business effects**, not physical exactly-once simulator execution.

| Test ID | Precisely forced action | Exact mandatory oracle |
|---|---|---|
| `REL-01` | Kill **before** allocation transaction commits; restart. | Pre-crash uncommitted state absent. Job remains `QUEUED` with no committed allocation; after recovery it may be allocated through a **new** valid transaction, never twice. |
| `REL-02` | Commit `RUNNING` + allocation + stable `ATT-JR-1`, kill **before sending** the execution request; restart. | Committed allocation survives unchanged; persisted attempt is resumed with **the same `attempt_id`**; one final Job result and one release after successful callback. |
| `REL-03` | Worker accepted the execution request, but kill Manager **before acknowledging/recording delivery**; restart and force a retry. | Every retry refers to `ATT-JR-1`; duplicate execution requests cannot create a second accepted final result, allocation or reputation contribution. |
| `REL-04` | Ingest a valid signed receipt into the chosen **durable pending-result** mechanism; kill before finalization; restart. | Pending receipt is recovered and verified; exactly one `RUNNING -> COMPLETED` transition, one release and one reputation effect. If no durable/replayable result mechanism exists, test fails its recovery invariant. |
| `REL-05` | Commit finalization, then kill **before external acknowledgment**; redeliver receipt after restart. | Job stays terminal, original accepted receipt unchanged, zero additional releases or reputation effects; unique final result count remains 1. |
| `REL-06` | Persist a due execution deadline; kill and restart Manager with fake clock after deadline. | Manager discovers due work using database data without any pre-crash in-memory timer; no stranded allocation or forgotten Job. |
| `REL-07` | With a pending eligible item and healthy PostgreSQL, start the Manager process and record monotonic `t0`; record `t1` on first **persisted recovery/claim action** for that item. | NFR target supported if `t1 - t0 <= 120.0 s`, otherwise target failed; missing environment/time evidence = `BLOCKED`, never PASS. **TARGET**, separately reported from correctness gates. |

**Decision rules:** mandatory recovery case PASS requires all assertions true at its specified observation points, and all relevant test cases (`REL-01..06`) must PASS for QA-REL-01 mandatory acceptance. A single reproducible violation is FAIL with before/after DB snapshots. `REL-07` reports NFR-R02 target status distinctly; an unmet latency target cannot be described as achieved, even if correctness passed. No arbitrary fixed simulator response timeout is assumed: retry/backoff/deadline parameters are explicitly **OPEN** pending their architecture decision.

**Required run evidence:** fixture ID/seed and fake time; commit SHA and migration version; crash barrier and last committed transaction ID; process restart timestamps; stable attempt IDs; Job/Allocation/Result/Reputation DB snapshots; per-test command and assertion diffs. Until harness and implementation exist: `NOT_RUN`.

### QA-INT-01 - Concurrent capacity and state transitions (Data Integrity)

**Design-review status:** **APPROVED (2026-10-17)** deterministic verification plan, **NOT_RUN**. No randomized test is allowed to substitute for the forced-order cases below.

| Element | Scenario |
|---|---|
| **Source** | Concurrent Client requests, Worker Pause/Resume request and Manager allocator/finalizer. |
| **Stimulus** | Two scheduler workers race to allocate, or Client Cancel / Worker Pause race with allocation and capacity edits. |
| **Environment** | A fresh PostgreSQL fixture per test; deterministic transaction barriers enforce specified commit order. All Jobs belong to a single Listing unless stated otherwise. |
| **Artifact** | Listing capacity/status, ordered Jobs, allocation records, state-transition and locking/transaction boundaries. |
| **Response** | Serialize conflicts into a valid committed order, preserve strict per-listing FIFO, reject stale/invalid operations, and keep capacity and job state in agreement. |
| **Measurable response** | **MUST:** after every committed transaction `0 <= allocated_gpu <= total_gpu`; `allocated_gpu = SUM(active allocations)`; every `CANCELLED` Job has zero active allocation; no new allocation may commit after `PAUSED` has committed; no later Job bypasses an unschedulable head Job; all forced-order results below match exactly. |

#### INT fixtures and independent cases

Use Listing `L1: ACTIVE, total_gpu=4, allocated_gpu=0`, Worker `W1`, Client `C1`, and a controllable Manager allocation step. Unless a test says otherwise, all cases reset to this empty fixture. No Worker completion occurs during a scheduler allocation pass. For races, the test runner controls **transaction boundaries/commit order** rather than relying on thread timing. Preserve stable ordering by `(submitted_at, job_id)`.

| Test ID | Fixed setup + forced operation | Exact oracle |
|---|---|---|
| `INT-01-FIFO` | Submit `A=3 GPUs`, `B=2 GPUs`, `C=1 GPU` in that order. Run one allocation pass until blocked. | `A=RUNNING`, `B=QUEUED`, `C=QUEUED`; `allocated_gpu=3`, `free_gpu=1`. `C` must **not** leapfrog `B`. |
| `INT-02-DOUBLE-ALLOC` | Submit `A=3` then `B=3`; allow two Manager allocation workers to race. | `A=RUNNING`, `B=QUEUED`; exactly one 3-GPU active allocation; `allocated_gpu=3`; no duplicate allocation for `A`. |
| `INT-03-CANCEL-FIRST` | Job `A=3` is `QUEUED`. Force Client cancellation to commit before allocator examines committed state. | `A=CANCELLED`; cancel succeeds; Manager does not allocate `A`; `allocated_gpu=0`. |
| `INT-04-ALLOC-FIRST` | Job `A=3` is `QUEUED`. Force allocation transaction to commit before cancellation. | `A=RUNNING`, allocated=3; cancel rejected as `409 Conflict`; no `CANCELLED` state. |
| `INT-05-PAUSE-FIRST` | Job `A=3` is `QUEUED`. Force Listing `ACTIVE -> PAUSED` commit before scheduling transaction's eligibility check. | Listing `PAUSED`, `A=QUEUED`, `allocated_gpu=0`; new submission rejected while PAUSED. |
| `INT-06-ALLOC-THEN-PAUSE` | Job `A=3` is `QUEUED`. Force allocation commit first, then `ACTIVE -> PAUSED`. | Listing `PAUSED`, `A=RUNNING`, `allocated_gpu=3`; existing Job may finish and release GPUs; queued Jobs may not start until Resume. |
| `INT-07-CAPACITY-SHRINK` | Begin with committed RUNNING `A=3` and allocated=3. Worker requests reducing `total_gpu` from 4 to 2. | Update rejected without partial modification; `total_gpu=4`, `allocated_gpu=3`, `A=RUNNING`. Also reject reduction below largest still-queued request per FR-WR-03. |
| `INT-08-FINALIZE-ONCE` | From RUNNING `A=3`, deliver the same valid finish twice concurrently. | Exactly one accepted terminal transition and one GPU release; `allocated_gpu=0`; duplicate release cannot drive allocation negative. |

**Important ordering nuance:** a scheduler transaction may begin before Pause, but it must not **commit allocation using an out-of-date ACTIVE view after Pause committed**. The implementation must lock/revalidate Listing status and capacity at the database boundary. The UI response alone is not proof; capture the committed DB state and the losing transaction's response.

**Decision rules:** QA-INT-01 mandatory acceptance requires `INT-01..08` all PASS. `INT-02` requires a fixture that deterministically schedules two contenders to the same conflict boundary. Optional randomized/stress interleavings add coverage but cannot replace these eight exact tests. If lock/barrier instrumentation is unavailable, the corresponding test is `BLOCKED` or `NOT_RUN`, not presumptively PASS.

**Evidence:** ordered transaction/barrier log; per-case before/after Listing/Job/Allocation snapshots and API status codes; constraints checked after **each commit**, not just test completion; seed/commit/migration and exact failed invariant/IDs.

### QA-SEC-01 - Reject altered or replayed signed results (Security)

**Design-review status:** **APPROVED (2026-10-17)** deterministic verification plan, **NOT_RUN**. The exact signed-byte canonicalization and callback transport are **OPEN** decisions; cryptographic fixture bytes and real test commands can only be frozen after the contract is chosen.

| Element | Scenario |
|---|---|
| **Source** | Authorized Worker Simulator for valid receipts; hostile/buggy sender or duplicated transport for invalid/replayed receipts. |
| **Stimulus** | Submit a correctly signed receipt, a tampered signed payload, a receipt signed by another Worker, an attempt/listing mismatch, an unknown schema/key, or a verbatim replay. |
| **Environment** | Isolated test integration: `W1` with Ed25519 public key `K1`, `W2` with different key `K2`; Job `J1` belongs to `W1`/Listing `L1`, is `RUNNING` with current attempt `T1`. Test private keys are injected as test secrets only. The Manager has registered public keys but no Worker private keys. |
| **Artifact** | Receipt transport ingress, signed canonical payload, result verifier, Worker Registry lookup, finalization and Reputation state; protected simulation oracle for the dispute cross-check. |
| **Response** | Authenticate service ingress where applicable; verify signature and bound execution context; accept one valid result; reject invalid or context-mismatched signed claims; deduplicate exact repeats without new business effects; keep signed-but-false content eligible for separate dispute checking. |
| **Measurable response** | **MUST:** every defined tamper, wrong-key, wrong-context and unknown-version case results in **zero trusted acceptance**; one valid receipt results in exactly one finalization; replay causes **zero additional** finalization/reputation/allocation deltas; leaked Worker private key bytes in tracked source, public API, Registry or logs = FAIL. |

#### SEC fixture, trust oracles and exact test cases

A valid signed payload must include `schema_version`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at`, `key_id`; verification binds **all** fields via agreed canonical bytes and the currently registered `key_id`. The signed receipt for the successful `J1` fixture has `outcome=SUCCESS`, and a ground-truth reference chosen independently before the receipt exists.

**Observation boundary:** An HTTP callback may return `202 Accepted` simply because raw evidence was **durably enqueued**. This does **not** mean the Manager accepted the result as trustworthy. The test oracle is the **trusted accepted-result table**, Job finalization, allocation and reputation effects. Raw inbound records/audit entries may increase for rejected messages without violating Security.

| Test ID | Attack / event | Exact trusted-state oracle |
|---|---|---|
| `SEC-01-VALID` | Valid `J1/T1/W1/L1/K1` receipt with correct Ed25519 signature. | Exactly 1 accepted result; `J1=COMPLETED`; `J1` active allocation released once; Worker `W1` success count increased by exactly 1. |
| `SEC-02-TAMPER` | Copy signed receipt and change one signed field (`result_digest`, then separately `outcome`) **without re-signing**. | Signature fails; accepted-result count=0 for fresh test; `J1` remains RUNNING immediately after verification failure; allocation held; reputation delta=0. Subsequent retry/timeout path is tested separately. |
| `SEC-03-WRONG-KEY` | Claim `worker_id=W1` but sign using `W2` private key (`K2`), or use an unregistered `key_id`. | Verification/context fails; accepted-result count=0; no Job/reputation business effect. |
| `SEC-04-WRONG-CONTEXT` | Sign a cryptographically valid receipt with `K1` but bind to stale `attempt_id=T0` or other Listing/Job. | Valid math signature is not sufficient; expected `J1/T1/W1/L1` binding fails; accepted-result count=0; no finalization. |
| `SEC-05-REPLAY` | First accept valid receipt, then deliver **identical signed bytes** again. | Total accepted results for `J1` stays 1; additional GPU release=0, additional reputation effect=0, terminal state unchanged. |
| `SEC-06-RESULT-ID-COLLISION` | After a valid accepted result, submit another correctly signed but **different** payload with the same `result_id`. | Conflict rejected; originally accepted payload/signature immutable; results count still 1 and no further business effects. |
| `SEC-07-UNKNOWN-SCHEMA` | Use unsupported `schema_version` or ambiguous canonical encoding. | Receipt rejected before trusted acceptance, with structured rejection reason; Job/reputation unchanged. Requires a frozen version/encoding contract to execute. |
| `SEC-08-SECRET-BOUNDARY` | Inspect tracked sources, service responses, Registry data and structured logs with a known test key marker and its encodings. | Zero Worker private-key material in any prohibited location; `API` and `Manager` cannot read Worker signing private keys via their configured service identities. Do not store real credentials or test signing secrets in Git. |
| `SEC-09-SIGNED-BUT-FALSE` | Produce a correctly signed but **factually false** `outcome`/digest using an isolated Worker test double; then submit one Client dispute. | Signature check **passes** and original signed receipt is immutable; protected oracle comparison returns `UPHELD`; effective reputation correction applied exactly once. Rejecting all false-but-signed receipts at signature stage is **not** the desired dispute behavior. |

**Decision rules:** cryptographic/context cases (`SEC-01..07`), key boundary (`SEC-08`) and trust/dispute separation (`SEC-09`) all must PASS to establish this scenario's full security behavior. Invalid messages can be logged/queued for rejection diagnostics, but they must never become an **accepted signed result**. During immediate negative-case assertions, do not wait for a later configured `SYSTEM_FAULT` expiry; that is a separate Reliability fallback and must not count against Worker reputation.

**Evidence:** fixed payload bytes and signature test vectors for each schema; public key fingerprint/key ID; rejection reason; Manager verification trace with job/attempt IDs; snapshots of accepted results, Job/Allocation/Reputation; secret scan report, role-access checks and dispute decision proof. A `202` or other transport response alone is not sufficient evidence of signature verification.

**Open prerequisites to freeze before executing:** canonical Ed25519 byte specification and version policy; result-ingress and authenticated service-call contract; durable delivery/retry behavior; executable DB schema and isolated key-fixture injection. These are named prerequisites, **not waived safety checks**. Their absence makes executable test status `BLOCKED` or `NOT_RUN`, not PASS.

### QA-PER-01 - Mixed 736-user workload (Performance)

**Design-review status:** **APPROVED as a repeatable benchmark design (2026-10-17)**; **NOT_RUN**. The 736-VU target and NFR latency/error thresholds were already present in requirements. The 552/147/37 roles, 2-minute ramp, 600-second plateau, three runs, request mix and fixture are now approved **as test-design parameters**, not demonstrated system capacity. Test-machine configuration and executable generator must be pinned and reported before measurements can be valid.

| Element | Scenario |
|---|---|
| **Source** | Load generator representing 736 concurrently active authenticated virtual users (VUs), with Client/Worker/Admin roles. |
| **Stimulus** | Repeated role-correct catalog, listing, job-status, signed-result, dashboard, job-submission and price-update requests under a fixed seeded sequence. |
| **Environment** | Separate load-generator host; pinned single-node API+Manager+Simulator+PostgreSQL test deployment; fixed dataset, API version, network, request mix and pacing; 2-minute ramp followed by 10-minute steady-state plateau. |
| **Artifact** | Backend API, Manager queue, PostgreSQL, authorized read endpoints, job-submission transactions and dashboard queries. |
| **Response** | Return timely responses and accept valid jobs as `QUEUED` without waiting for simulated completion; continue authorization, FIFO and capacity enforcement; emit latency/error/queue metrics. |
| **Measurable response** | **NFR TARGETS:** 736 active VUs for 600 s; successful read server-side p95 <=2.000 s; valid job-submission server-side p95 <=3.000 s; unexpected 5xx fraction <0.0100. **MUST:** zero observed cross-user authorization breaches, overallocations, invalid state transitions or double finalization. No target is considered achieved without reproducible evidence. |

#### QA-PER-01 approved workload contract (not yet executed)

**Profile ID:** `PERF-736-V1` (approved test-design ID). In the future test repository, the executable profile and fixture must be versioned together; none has yet been implemented. Propose PRNG seed `20261017`, VUs **552 Client + 147 Worker + 37 Admin = 736**, each continuously active with **5.0 s think time between completed requests**, one outstanding HTTP action per VU. Steady state begins **after** the 2-minute ramp and lasts exactly **600 s**; ramp intervals never enter latency pass/fail calculations. This models 736 user sessions, **not** 736 running GPU jobs nor 736 simultaneously in-flight HTTP requests. Actual achieved request rate must be reported; do not infer it from the VU count.

Pre-register role-correct per-request choices (percentage **within that role**, selected from a deterministic seeded PRNG):

| Role | Fixed VUs | Permitted actions and weights (sum = 100%) |
|---|---:|---|
| Client | 552 | Browse catalog/listing **40%**; read own Job status **30%**; read own retained Signed Result **15%**; submit a **valid** Job to an `ACTIVE` Listing **15%**. |
| Worker | 147 | Read own listings **40%**; read assigned jobs **30%**; read reputation **20%**; edit allowable **simulated price only** on a separate owned Listing **10%**. |
| Admin | 37 | Read system dashboard **50%**; review queue/jobs **30%**; review disputes/reputation **20%**; read-only throughout. |

**Approved seed dataset design (`PERF-SEED-V1`):** at least **552 distinct Client**, **147 distinct Worker** and **37 distinct Admin** test accounts; **200 Workers**, **600 Listings** (3/Worker, initially ACTIVE, `total_gpu=4` each), **12,000 terminal Jobs within the 23-day retention window** with signed evidence needed for reads, and **600 QUEUED Jobs**. A fixed subset of Worker-owned Listings is reserved for price edits; Client valid submissions select from a fixed set of ACTIVE Listings excluded from conflicting listing changes. Creation times, immutable IDs and outcome/reference seeds are deterministic. Valid job-submission requests have unique per-Client idempotency keys and supported `gpu_count/duration_seconds`; 4xx caused by invalid test fixtures is a **profile error**, not an expected Client workflow. The fixture generator must make retained receipts accessible only to their owning Client.

**Reference test environment (must be pinned at execution):** dedicated load-generator `4 vCPU / 8 GiB RAM`; SUT `8 vCPU / 16 GiB RAM + SSD` with API, Manager, Simulator and PostgreSQL, pinned container CPU/memory limits and PostgreSQL settings; stable LAN with documented RTT. These are comparison specifications, **not** a claim the project has these machines. If the actual available machine differs, agree and version a new profile **before** running or label the result exploratory, not comparable. Workload generator bottlenecks, missing server-side telemetry or invalid fixtures mean `BLOCKED/ERROR`, never PASS.

**Measurement conventions:** collect server-side request-duration histograms for each relevant endpoint; the score is the **nearest-rank p95** of all qualifying samples in the 600 s steady-state window (`sort durations ascending; index=ceil(0.95*n)-1`). Bucket **read** covers successful catalog/listing/Job-status/result/role-dashboard reads, and **submit** covers valid accepted `POST job` requests (response must contain one persisted `QUEUED` Job, even if Manager advances it shortly after). For each run require `n_read >= 1000`, `n_submit >= 500` (PROPOSED sampling minima), plus no omitted endpoint categories. Unexpected 5xx numerator includes application/gateway HTTP 500-599; denominator is **all observed HTTP responses**; report 4xx and network failures separately. Any unexpected client-connection failure is an independent test-profile failure, not hidden in a success-only latency percentile. Latency measurement must exclude load-generator/Internet transit, which is reported separately. Run **three independent repetitions**, each starting from the same restored seed and environment, and record all runs rather than averaging away one failure.

#### QA-PER-01 approved verification IDs and binary rules

| Test ID | Measurement/action | Exact oracle / decision rule |
|---|---|---|
| `PER-01-PROFILE` | Start 2-min ramp, maintain **736 VUs** with fixed 552/147/37 role split during every sample of the 600-s plateau. | Exactly 736 active virtual sessions during plateau; no unreported dropped or skipped actions; generator has sufficient headroom; profile and fixture versions match. Any mismatch = invalid run / `BLOCKED` (not a successful benchmark). |
| `PER-02-READ-P95` | Collect `n_read >= 1000` qualifying **server-side** read durations per run. | `p95_read <= 2.000 s` in **each** of the 3 runs. One exceeding run = target `FAIL`. |
| `PER-03-SUBMIT-P95` | Collect `n_submit >= 500` successful valid POST submissions per run. | `p95_submit <= 3.000 s` in **each** run; every successful POST persists exactly one Job and does not wait for execution. |
| `PER-04-5XX` | Count all HTTP responses and unexpected 5xx during plateau. | `(count_5xx / count_all_http_responses) < 0.0100` **in each** run; report 4xx and transport errors separately. |
| `PER-05-SAFETY` | Run independent SQL reconciliation after batches and at plateau end; inspect ownership/authorization assertions. | Zero capacity exceedances, allocation/Job mismatches, duplicate finalizations or reputation contributions, and zero private cross-role data disclosures. Any single violation = mandatory `FAIL`. |
| `PER-06-EVIDENCE` | Archive code commit, schema, load profile, fixture seed, hardware/limits, timing, endpoint samples, DB/Manager metrics and independent raw run reports. | All expected evidence exists and read/submit sample minimums hold. Otherwise test `BLOCKED/ERROR`, never infer a PASS from incomplete output. |

**Acceptance rule:** The mandatory safety check `PER-05` is hard-gated regardless of throughput. `PER-02..04` independently report numeric NFR target PASS/FAIL once `PER-01` and `PER-06` validate the experimental profile. Passing numeric targets alone does not establish correctness; a profile bottleneck is `BLOCKED/ERROR`, not a product `FAIL`. The three-run workload/profile design is review-approved; actual hardware, executable fixture versions and instrumentation must be frozen before running. No recorded run has passed.

### QA-SCA-01 - Growth in simulated Workers and Listings (Scalability)

**Design-review status:** **APPROVED as a data-volume scalability experiment (2026-10-17)**; **NOT_RUN**. Distinguish dataset growth on unchanged resources from horizontal service replication (not evaluated here). The 5x dataset and binary 1.50x latency / 0.85x throughput **hypothesis tests** were approved for measurement; these relative thresholds are **not** silently promoted into product NFR SLAs.

| Element | Scenario |
|---|---|
| **Source** | Project Owner or benchmark operator increasing simulated Workers, Listings and Job histories. |
| **Stimulus** | Restore dataset `SCA-1X` and `SCA-5X`, with exactly 5 times as many Worker/Listing/history/queued-job records in the second dataset; replay identical `PERF-736-V1` mixed-user workload on both. |
| **Environment** | Same commit, DB schema, service resources, pinned SUT/generator configuration, 736 active VUs and 600-s plateau; restore database and restart processes before each independent run. |
| **Artifact** | Worker Registry, Listing/catalog indexing, Jobs/retained histories, per-listing queue scan, PostgreSQL query paths and Manager scheduler. |
| **Response** | Preserve ownership/isolation, strictly per-Listing FIFO and data integrity; measure effects on read/submit latency, completed request throughput, DB wait and queue-processing delay. |
| **Measurable response** | **MUST:** zero authorization leaks, overallocations, state violations and duplicated finalizations under **both** sizes. **NFR Performance targets:** report read p95 <=2 s, valid submit p95 <=3 s, 5xx <1% **for each dataset**, without silently treating those as a newly accepted 5x scale SLA. **APPROVED-TO-TEST CALIBRATION HYPOTHESES (not product NFRs):** growth factor exactly 5; 5x read/submit p95 <=1.50 times their 1x values; completed HTTP throughput at 5x >=0.85 times 1x under fixed users/resources. The outcome of each hypothesis must be `SUPPORTED` or `REFUTED`, never 'looks scalable'. |

#### QA-SCA-01 approved data-size profiles

| Fixture | Workers | Listings | Retained terminal Jobs | Initially QUEUED Jobs | Test principals |
|---|---:|---:|---:|---:|---|
| `SCA-1X` | 200 | 600 | 12,000 | 600 | At least 552 Clients +147 Workers +37 Admins (same IDs) |
| `SCA-5X` | 1,000 | 3,000 | 60,000 | 3,000 | Same active test principals; added Workers have non-active fixture accounts |

Generation rule: `SCA-5X` includes the same deterministic `SCA-1X` records (their IDs and ownership unchanged), plus four disjoint identically generated extensions; timestamps fit current retention or explicitly mark non-retained data. Same job mix, simulated GPU capacity distribution and per-listing queue topology; never compare unrelated workload compositions. **Both profiles must exclude test-generated signed results older than 23 days unless intentionally exercising cleanup.** Use the same API traffic sequence (same logical action and selection seed); map random listing selection in a documented stratified way to avoid comparing one hotspot to a different hotspot.

#### QA-SCA-01 approved verification IDs and deterministic verdicts

| Test ID | Measurement/action | Exact oracle / decision rule |
|---|---|---|
| `SCA-01-FIXTURES` | Count entities and compare shared seed IDs after restore. | Counts match the table exactly; all baseline entities preserved; no job with invalid owner, missing evidence or expired unmarked detail; same active test user IDs and traffic mix. Otherwise `BLOCKED`. |
| `SCA-02-INVARIANTS` | Replay the same 736-VU profile for each dataset size, verify DB and role-scoped responses. | **MUST:** zero violated capacity, FIFO, Job status, authorization, receipt/dedup and reputation invariants at both 1x and 5x. One counterexample = `FAIL`. |
| `SCA-03-ABSOLUTE-PERF` | Measure server read/submit p95 and 5xx separately per size and each of three runs. | Evaluate NFR target pass/fail separately: read <=2s; valid submit <=3s; 5xx<1%. A target miss is reported explicitly, never masked by a good 1x result. |
| `SCA-04-RELATIVE-LATENCY` | For matched repetition `i`, compute `r_read_i = p95_read_5x_i / p95_read_1x_i` and `r_submit_i = p95_submit_5x_i / p95_submit_1x_i`. | **Hypothesis SUPPORTED** only if BOTH ratios <=1.50 for **every** matched pair; any pair >1.50 = **REFUTED**. A missing/nonpositive baseline or non-comparable run = `UNMEASURED`. |
| `SCA-05-RELATIVE-THROUGHPUT` | For matched run pairs, compare total completed HTTP responses over the 600-s plateau on the same machine. | **Hypothesis SUPPORTED** only if `throughput_5x_i / throughput_1x_i >=0.85` for **every** pair; any lower pair = **REFUTED**; invalid/missing measurements = `UNMEASURED`. |
| `SCA-06-BOTTLENECK-EVIDENCE` | Record DB query plans, lock wait, CPU, memory, job queue depth, scheduler eligible-to-allocation delay and request-rate measurements per fixture/run. | Required diagnostic evidence present; missing data = `BLOCKED`. Data must be retained even for failing runs to identify the concrete bottleneck. |

**Decision rule:** `SCA-02` is a non-negotiable product safety gate. `SCA-03` assesses original NFR targets; `SCA-04/05` test the **approved-to-test** scaling hypotheses without promoting them to approved NFRs. A run may meet the NFR performance targets but refute the 1.5x-degradation hypothesis: report **both** conclusions explicitly. Until hardware, load profile and fixture generator are pinned and executable, every benchmark remains `NOT_RUN`/`BLOCKED`.

### QA-DAT-01 - Expire historical evidence safely (Data Lifecycle)

**Design-review status (2026-10-18):** The **7-day dispute filing window is APPROVED**, and the 23-day terminal-Job retention, separate audit TTL, lifetime aggregate reputation and unresolved-dispute evidence hold remain APPROVED requirements. The **17 deterministic test designs (`DAT-01` to `DAT-17`) and their fixed fixtures/oracles are APPROVED FOR TEST DESIGN**, not yet executed; every executable check has status `NOT_RUN`. The exception policy is **APPROVED**: preserve linked evidence until the dispute reaches RESOLVED, with **no fixed maximum hold**; warning <=1 hour after exception detection, CRITICAL at 24 hours if still OPEN, retry every 15 minutes while the Manager is healthy, and cleanup <=1 hour after resolution when 23-day expiry has passed. A strict hard-delete bound is deliberately NOT promised for unresolved cases. The 17 existing test designs remain approved; the new addendum tests are proposed for review.

| Element | Scenario |
|---|---|
| **Source** | Client submits a dispute; the Manager cleanup scheduler runs; trusted Manager adjudicates a pending dispute. |
| **Stimulus** | A Client attempts to file before, exactly at or after the **7-day cutoff**; separately, a terminal Job reaches the **23-day history expiration**, possibly with a dispute still `OPEN`. |
| **Environment** | Durable PostgreSQL; controlled UTC fake clock and independent database snapshot per test; fixed Worker/Client/Job identities; all time predicates evaluated by a **trusted server/database time source**, not Client-supplied timestamps. |
| **Artifact** | Dispute eligibility/insertion, terminal Job and dependent signed receipt, simulation reference, reputation contribution, audit events, public-key evidence and lifetime reputation counters. |
| **Response** | Atomically admit only one eligible Client dispute strictly before its filing deadline; reject late/ineligible/duplicate submissions with no inserted second dispute; resolve any timely-filed dispute even after the filing deadline; clean up eligible 23-day history together without touching active data or lifetime counters; preserve and flag unresolved evidence at expiry. |
| **Measurable response** | **MUST:** accepted dispute creation time in `[terminal_at, terminal_at + 604800 seconds)`; at exactly `+604800 s` reject; unique `disputes.job_id`; 23-day cleanup eligibility at `terminal_at + 1987200 s`; zero premature deletion/orphans/double reputation effects; preserved and flagged unresolved cases; no unauthorized read/write. **NFR TARGET:** eligible, nonexception history removed within 3600 seconds after expiry under normal operating conditions. **APPROVED EXCEPTION POLICY:** no hard maximum while the dispute remains OPEN; warning within 3600s of detection, CRITICAL once still OPEN at detected_at+86400s, retry on each 900-second due tick under healthy service conditions; if already expired, cleanup within 3600s after successful RESOLVED commit. Newly added monitoring cases remain design-review candidates. |

#### Filing eligibility contract — authoritative policy (APPROVED)

```text
T_file_end = terminal_at + 7 * 24 * 60 * 60 seconds  # 604800 seconds
T_history_end = terminal_at + 23 * 24 * 60 * 60 seconds  # 1987200 seconds

Eligible only when ALL conditions are true:
  current authenticated actor == owning Client
  Job is terminal (COMPLETED or FAILED) and has an accepted, verified signed receipt
  retained evidence still exists
  no earlier dispute for that Job (unique disputes.job_id)
  terminal_at <= decision_at < T_file_end

After successful filing:
  filing cutoff does not cancel an existing OPEN dispute
  Manager may adjudicate it after T_file_end (UPHELD or REJECTED)
  original signed receipt is immutable; reputation correction executes once
```

`CANCELLED` Jobs and `FAILED/SYSTEM_FAULT` Jobs without an accepted signed receipt cannot be disputed under the current MVP rule. The eligibility check and unique dispute insertion must be protected against concurrent requests in **one database transaction** (e.g. row lock / conditional insert + unique constraint). Capture `decision_at` using the authoritative clock **after acquiring the necessary lock**, immediately before the eligibility check and insert; persist this value as the creation/decision timestamp. A request arriving before the cutoff but reaching the atomic eligibility check at or after it **fails**. This **testable admission-time boundary is APPROVED for the seven-day rule**; the exact database locking implementation and API status mapping remain design decisions; the API must not trust a Client-supplied `created_at` or request header as the filing clock. A transaction whose decision instant was valid may commit after the boundary: eligibility is judged by its persisted atomic `decision_at`, not by the later acknowledgement time.

**Time precision:** Persist and compare UTC instants with microsecond precision (`timestamptz` or equivalent); do not truncate to local calendar dates. Every test injects one trusted clock value and verifies both response and final DB state. HTTP status/error-code names will be frozen by `api-contract.md`; until then, the **required business oracle is admission/rejection and unchanged DB on rejection**, while an exact HTTP-status contract check is `BLOCKED` rather than invented.

#### QA-DAT-01 fixed fixture, timestamps and exact retention oracles

Use `T0 = 2026-10-01T00:00:00.000000Z` as `terminal_at` of two historical Jobs for Worker `W1` / Listing `L1` (one effective verified `SUCCESS`, one effective `WORKER_FAULT`), with full accepted signed evidence, immutable references and no unresolved disputes unless a test explicitly seeds one. Worker lifetime aggregates before cleanup: `(successful_jobs=7, worker_fault_jobs=3)` including both Jobs. A settled upheld dispute's delta must already be applied **before** the cleanup snapshot. Separately seed `QUEUED` and `RUNNING` Jobs, one active GPU allocation, `ACTIVE` and `PAUSED` Listings, user accounts, and signer key metadata. Reset to a **fresh database snapshot** before each independent test.

**Deterministic supplementary fixtures (APPROVED test design, 2026-10-18):**

- For `DAT-06` and `DAT-07`, select Job `J-FALSE-SUCCESS`: its immutable, correctly signed receipt reports `SUCCESS`, while the protected reference is `WORKER_FAULT`. Start with lifetime counters `(7,3)` including that receipt. The dispute was filed on day 6 and is still `OPEN` at day 23. Adjudication at day 24 **must** be `UPHELD`; the only correct post-adjudication aggregate is `(6,4)`, and cleanup must leave `(6,4)` unchanged.
- For `DAT-10` and `DAT-14`, hold the deterministic adjudicator at a test barrier until API insert outcomes and initial `OPEN` rows have been asserted. This prevents asynchronous auto-resolution from making the fixture nondeterministic.
- For `DAT-14`, issue two independent submissions with **distinct** request/idempotency keys. The required business-level oracle is exactly one successful creation and one `DUPLICATE_DISPUTE` conflict, with **one** persisted dispute; exact HTTP status and error schema remain a future `api-contract.md` decision. This fixture does not permit two creation successes disguised by response idempotency.

| Boundary | Absolute UTC instant | Required behavior |
|---|---|---|
| Filing last allowed instant | `2026-10-07T23:59:59.999999Z` (`T0+7d-1µs`) | One eligible new dispute may be inserted. |
| Filing cutoff | `2026-10-08T00:00:00.000000Z` (`T0+7d`) | New dispute must be rejected; no DB insert. |
| Filing after cutoff | `2026-10-08T00:00:00.000001Z` (`T0+7d+1µs`) | Same rejection as at cutoff. |
| History last retained instant | `2026-10-23T23:59:59.999999Z` (`T0+23d-1µs`) | Cleanup must NOT remove eligible-linked history early. |
| History expiration | `2026-10-24T00:00:00.000000Z` (`T0+23d`) | Explicit cleanup may atomically remove history with no unresolved hold. |
| Normal periodic cleanup deadline | `2026-10-24T01:00:00.000000Z` (`T0+23d+3600s`) | In normal available DB/scheduler, no expired nonexception history remains. |

Audit events have a **separate** `created_at + 23 days` expiration. Job-linked domain history needed to prove a retained Job is not interchangeable with raw operational audit logs. Signer public-key material required to verify still-retained/held receipts must remain usable.

#### QA-DAT-01 deterministic tests and exact PASS/FAIL decisions

| Test ID | Controlled action | Mandatory oracle / reason to FAIL |
|---|---|---|
| `DAT-01-PRE-EXPIRY` | At `T0+23d-1µs`, invoke cleanup. | Both historical Jobs, receipts, references, settled disputes and contribution evidence still exist; **any deletion = FAIL**. |
| `DAT-02-BOUNDARY` | Restore; at exactly `T0+23d`, invoke cleanup/commit. | Eligible histories and dependent evidence absent, zero orphans, active records preserved; **any undeleted eligible row after a successful explicit cleanup = FAIL**. |
| `DAT-03-PERIODIC-DEADLINE` | Restore; advance controlled scheduler across expiry to `T0+23d+3600s`. | No expired nonexception historical Job remains by this deadline when DB/scheduler healthy. Otherwise target `FAIL`; absent scheduler instrumentation => `BLOCKED`. |
| `DAT-04-NONTERMINAL-EXEMPT` | At `T0+24d`, run cleanup with aged `QUEUED`/`RUNNING` Job, active allocation, `ACTIVE/PAUSED` Listings. | Every nonterminal Job, allocation, identity, active listing and still-required signer key survives; `0 <= allocated <= total`; any loss = FAIL. |
| `DAT-05-LIFETIME-REPUTATION` | Snapshot W1 `7/3`; expire historical detail and rerun cleanup twice. | Lifetime aggregate remains **exactly `7/3`** on every read; no reputation effect replay. Any counter change = FAIL. |
| `DAT-06-OPEN-DISPUTE-HOLD` | Seed a dispute **filed at T0+6d**, still `OPEN` at `T0+23d`; invoke cleanup twice. | Job, original signed receipt, protected reference, dispute and verifier key preserved; durable retention-exception record identifies reason and Job. Any deletion/missing marker = FAIL. Hold remains active until dispute resolution; no fixed maximum. Warning/retry/escalation checks are specified in the addendum below. |
| `DAT-07-HOLD-RELEASE` | Using `J-FALSE-SUCCESS` from `DAT-06`, adjudicate the timely filed dispute at `T0+24d`, then run cleanup. | Exactly one `UPHELD` decision and one net correction: lifetime `(7,3) -> (6,4)`; the signed receipt stays byte-identical until cleanup; cleanup removes expired detail and leaves lifetime **exactly `(6,4)`**. Any other aggregate/decision = FAIL. |
| `DAT-08-CLEANUP-RESTART` | Crash before cleanup commit; separately crash after commit/before acknowledgement; retry both cases. | Before-commit rollback leaves full evidence; after-commit retry remains deleted; zero orphans, no counter changes. Any partial inconsistent deletion = FAIL. |
| `DAT-09-AUDIT-OWN-TTL` | Create operational audit at `T0-30d` and another at `T0`; clean at `T0+1d`. | Old audit event absent, new event and still-retained Job domain history present. Using missing old raw audit as required proof = FAIL. |
| `DAT-10-FILE-BEFORE` | Same Client with eligible signed receipt; atomic decision at **`T0+7d-1µs`**. | Exactly one new `OPEN` dispute, persisted `decision_at=T0+7d-1µs`, correct Job/Client reference; otherwise FAIL. |
| `DAT-11-FILE-AT-CUTOFF` | Restore eligible Job; atomic decision at **`T0+7d`**. | Reject, `COUNT(disputes where job_id=J)=0`, no reputation change; any insert = FAIL. |
| `DAT-12-FILE-AFTER-CUTOFF` | Restore; decision at **`T0+7d+1µs`**. | Reject with zero new disputes and zero effects; any accepted insert = FAIL. |
| `DAT-13-INELIGIBLE` | Independently test (a) nonowner Client, (b) `RUNNING` Job, (c) terminal Job without accepted signed receipt, (d) `CANCELLED` Job. | Every request rejected; **zero** inserted disputes; no private evidence leaked to nonowner. A single wrongly admitted request = FAIL. Exact 403/404/409/422 codes pending API contract. |
| `DAT-14-CONCURRENT-DUPLICATE` | At `T0+6d`, concurrently file two **distinct-key** submissions for one eligible Job, forcing the conflict boundary and keeping auto-adjudication behind the test barrier. | Precisely **one successful creation**, **one `DUPLICATE_DISPUTE` business conflict**, exactly **one** `disputes.job_id` row, zero duplicated adjudication/reputation effects. Two creation successes, zero rows, or two rows = FAIL. Exact HTTP status remains a pinned API-contract prerequisite. |
| `DAT-15-RESOLVE-AFTER-7D` | Client files `OPEN` at `T0+7d-1µs`; Manager adjudicates at `T0+8d`. | Dispute accepted when filed, resolved once after cutoff, receipt bytes identical, exactly one net effective reputation correction. Rejecting adjudication because 7d elapsed = FAIL. |
| `DAT-16-TRUSTED-CLOCK` | Client sends forged `created_at=T0+6d` in a request actually checked at DB `T0+7d+1µs`; also force request wait on row lock across cutoff. | Reject in both cases; persisted/used decision time always server-issued *after* lock and never derived from Client time. Any admission after cutoff decision = FAIL. |
| `DAT-17-AFTER-HISTORY-PURGE` | Finish a Job, purge eligible history at `T0+23d`, then retry dispute submission referring to old Job ID. | No newly created dispute; old job/evidence remains unavailable; lifetime reputation unchanged. Any resurrection or new row = FAIL. |

**Decision gate (APPROVED test design, 2026-10-18):** The **7-day filing boundary is a binding business rule** and **all 17 `DAT-01..17` cases, fixtures and database-state oracles are approved**. To verify QA-DAT-01, every named mandatory test must run and `PASS`; one concrete failure is a `FAIL`, and a missing prerequisite during attempted execution is `BLOCKED`. None has run yet (`NOT_RUN`). The proposed hourly periodic-cleanup deadline remains a measurable **NFR target**, separate from the mandatory zero-premature-deletion/no-orphan/no-double-count invariants. **OPEN policy:** the maximum unresolved-dispute evidence-hold period and terminal behavior are not defined, so the approved tests check correct preservation/release without claiming a hard cap or approving forced deletion of unresolved evidence.

#### QA-DAT-01 exception monitoring — approved policy, proposed deterministic tests (2026-10-18)

**Decision:** A dispute filed within the approved seven-day window that remains `OPEN` when its Job reaches `terminal_at + 23 days` creates an exceptional evidence hold **until it becomes `RESOLVED`**. There is **no arbitrary maximum or automatic adverse decision**. Evidence includes original signed bytes, historical verifier public key, immutable simulation reference, dispute and required per-Job reputation attribution. This exception does not extend the TTL of unrelated operational audit logs. Only authorized internal services can access the oracle. Admin can observe the hold/alert but **does not manually adjudicate** the dispute in MVP.

**Clock definitions and operating conditions:** Let `E=terminal_at+23 days`; an eligible cleanup attempt detecting a still-OPEN dispute atomically persists an exception marker with DB-issued `detected_at=D` and a stable `job_id`. If the scheduled cleanup runs while database and Manager are healthy, discovery is targeted within one hour of E (existing NFR target). Warning must be visible by `D+3600s`; while still OPEN, CRITICAL must be visible at or after `D+86400s` on the first due evaluation. A retry becomes due at `D+900s` and on every subsequent 900-second interval *while Manager/DB are running*; a delayed/restarted Manager picks up overdue work durably rather than pretending attempts happened while offline. Exact implementation of scheduling may differ; persist due timestamps so fake-clock tests can force due evaluation. No new Worker fault can be inferred from merely being unresolved.

**Clearance rule:** Resolution updates decision and effective reputation **in one transaction**, exactly once. If the 23-day deadline has already passed, the successful cleanup must remove eligible expired evidence within 3600 seconds after the RESOLVED commit under normal operating conditions. If the dispute resolves before E, preserve its history until E as normal. Retry or cleanup cannot alter lifetime aggregates a second time. The exception marker must be cleared/closed without losing metrics needed to diagnose resolution; after normal audit TTL it may also expire. The absence of a hard maximum means exceptional evidence may be retained indefinitely during a fault and a strict universal 23-day deletion claim is prohibited.

| Proposed test ID | Deterministic fixture/clock/action | Exact oracle (FAIL otherwise) |
|---|---|---|
| `DAT-EX-01-WARNING` | Restore approved `DAT-06` fixture; detect exception at `D=T0+23d`; run warning evaluator at `D+3600s` while `OPEN`. | Exactly one persisted exception marker for Job and a non-secret Admin-visible WARNING by `D+3600s`; missing marker or missing/late warning = FAIL. |
| `DAT-EX-02-CRITICAL` | Keep OPEN at `D+86400s`; evaluate; separately resolve at `D+86399s` in fresh fixture and evaluate at `D+86400s`. | Still OPEN: severity `CRITICAL` with timestamp >= `D+86400s`; already RESOLVED: no new CRITICAL. Duplicate alerts cannot create new adjudication or reputation effects. |
| `DAT-EX-03-RETRY-CADENCE` | Prevent deterministic adjudication completion with a fault fixture; keep Manager healthy; force due ticks at `D+900s`, `D+1800s`, `D+2700s`. | Three due retry attempts recorded with correct `job_id` and monotonic retry count; no accepted resolution or reputation adjustment while resolution is blocked; `next_retry_at` strictly advanced. Missed due tick under healthy test setup = FAIL. |
| `DAT-EX-04-RESTART-RECOVERY` | Stop Manager just before a retry due tick; advance fake clock beyond due time; restart and invoke due-work recovery. | Persisted OPEN dispute and evidence survive; overdue retry is attempted after recovery without double reputation/decision; unavailable service interval is reported, not claimed to have performed retries. |
| `DAT-EX-05-RESOLVE-CLEANUP` | At `T0+24d`, complete the approved `J-FALSE-SUCCESS` dispute `UPHELD` while exception OPEN; run cleanup by `resolved_at+3600s`. | Lifetime `(7,3)->(6,4)` exactly once; original receipt remains unchanged up to cleanup; expired linked evidence and exception hold are removed/closed by deadline; lifetime remains `(6,4)`. |
| `DAT-EX-06-NO-HARD-PURGE` | Keep valid dispute OPEN with repeated adjudication faults through `T0+60d`; run cleanup repeatedly. | Required signed evidence, verifier key and protected reference still available to authorized evaluator; CRITICAL marker remains visible; no silent deletion, auto-REJECTED/UPHELD, or reputation delta. |

**Review/execution status:** Six **additional test designs are PROPOSED for review**, not part of the original approved `DAT-01..17` test manifest yet. The *policy and its precise timers are approved*. All checks are currently `NOT_RUN`. Missing a working DB/clock/retry test harness makes execution `BLOCKED`, never PASS; an executed case failing its stated oracle is `FAIL`.

### QA-OBS-01 - Reconstruct retained job and dispute evidence (Observability/Auditability)

**Design-review status:** **APPROVED (2026-10-18) for the minimal Job-linked evidence contract and 9 deterministic checks; NOT_RUN.** This scenario separates **Job-linked durable domain evidence**, retained until `terminal_at+23d` (or an explicit unresolved-dispute hold), from operational audit events retained until `audit_event.created_at+23d`. It does NOT extend raw log retention or grant Client/Worker access to the protected simulation oracle.

| Element | Scenario |
|---|---|
| **Source** | Read-only Admin or authorized maintainer investigating a signed result, upheld dispute, failed verification or duplicate delivery. |
| **Stimulus** | Client files within the approved 7-day window, Manager verifies/adjudicates, and an authorized actor later asks to reconstruct a Job's business outcome from still-retained evidence. |
| **Environment** | Durable PostgreSQL domain data, role-scoped API, deterministic simulation reference restricted to trusted verifier/adjudicator, controllable clock and a fixture whose original submission audit events may already have expired. |
| **Artifact** | Job identity and lifecycle timestamps, allocation/attempt metadata, immutable signed receipt/verification metadata, dispute decision and effective per-Job reputation contribution; distinct operational audit events/correlation IDs. |
| **Response** | Return a complete, attributable chain for a retained Job without relying on expired audit logs, double-counting retries or revealing signing secrets and protected oracle; enforce Client ownership and Admin read-only access. After evidence expiry, return no individual proof while maintaining Worker lifetime aggregates. |
| **Measurable response** | **MUST:** every required evidence-field relationship is present and consistent, **one** accepted receipt and at most **one** effective contribution per Job, `100%` of the fixed mandatory chain verifiable, zero unauthorized reads/writes and secret leakage; individual proof unavailable after deletion; lifetime aggregates unchanged. All 9 exact test cases below PASS to verify QA-OBS-01. |

#### Minimal domain-evidence contract (review-approved architecture obligation)

While a terminal Job remains retained, an authorized investigation must reconstruct **all** the following from durable **domain records**, not from raw audit logs. This defines fields/semantics, **not** a mandatory table design; `job_timeline_events` or normalized Job/Attempt/Receipt/Dispute tables are both possible.

| Required link | Minimal queryable facts / exact oracle |
|---|---|
| Job ownership | `job_id`, `client_id`, `listing_id`, `worker_id`; all consistent with Registry/Listing ownership. |
| Submission | `submitted_at`, requested `gpu_count`, immutable Job ID and Listing choice. |
| Execution/Allocation | `started_at`, stable `attempt_id`, committed GPU allocation count and an identifiable release/finalization fact (timestamps or domain event). |
| Verification | `result_id`, signed payload bytes/signature, `key_id`, verification outcome and `attempt_id` linkage; accepted receipt has valid Ed25519 context. |
| Finalization | `terminal_at`, terminal Job status, finalization/result reference; at most one accepted final receipt, no active GPU allocation after terminalization. |
| Dispute, if filed | `dispute_id`, owning Client, persisted `decision_at` in `[terminal_at, terminal_at+7d)`, `resolved_at`, decision `UPHELD/REJECTED`, adjudication reason; original signed bytes unchanged. |
| Reputation effect | A unique per-Job contribution/effect ID, effective classification, before/after **delta** for an upheld correction; exactly one net effective per-Job contribution even if callbacks are replayed. |
| Service correlation | Stable correlation mapping from Job to attempt, result, dispute and contribution (e.g. `correlation_id`); operational log events are useful **while retained** but not the sole source of these mappings. |

**Boundary condition:** Job-linked business evidence remains available until its approved expiry instant; it may disappear at `terminal_at+23d` after cleanup (except hold). A job can have `submitted_at` older than 23 days while still `QUEUED/RUNNING`; its core domain timeline must not disappear merely because a submission audit event has expired. After expiry, do not present lifetime aggregates as if per-Job historical proof still exists.

#### QA-OBS-01 deterministic fixtures

- `OBS-J1`: Client `C1`, Worker `W1`, Listing `L1`, Job `J1`, attempt `A1`, signed receipt `R1` (valid Ed25519 but intentionally inconsistent with protected deterministic reference), dispute `D1` **filed at `J1.terminal_at+6d`**, resolved `UPHELD` at `terminal_at+8d`, corrected reputation effect `E1`; `correlation_id=CORR-J1`. Signed receipt bytes before/after adjudication must hash identically.
- `OBS-JLONG`: a separate Job whose `submitted_at = terminal_at-30d`, completed at `terminal_at=T0`; its submission audit event was created at `submitted_at` and has expired by `terminal_at+1d`. Its core Job evidence is still retained at `terminal_at+1d`.
- `OBS-J2`: a Job with deliberately invalid signed receipt, known rejection reason code, and no accepted result; after configured bounded retry/deadline (once defined), the Job becomes `FAILED/SYSTEM_FAULT` without Worker reputation effect.
- All fixtures use their own independent database snapshot and fake UTC clock; all joins and counts are verified against database rows and role-scoped API outputs, not a screenshot or dashboard approximation.

#### QA-OBS-01 approved verification cases

| Test ID | Controlled action | Exact PASS oracle / failure witness |
|---|---|---|
| `OBS-01-CORRELATION` | Query retained `J1` with `A1/R1/D1/E1` by trusted investigator. | All mandatory domain links in the table above agree on Job/Worker/Listing and correct IDs; **no null required link or unrelated Job record**. Any missing/wrong link = FAIL. |
| `OBS-02-UPHELD-PROOF` | Independently verify `R1` with Worker public key; compare claimed result to protected reference; adjudicate `D1`. | Signature valid, claim mismatches reference, decision `UPHELD`, signed bytes unchanged, one effective corrected contribution. Any difference = FAIL. |
| `OBS-03-LONG-QUEUED` | At `JLONG.terminal_at+1d`, clean audit events older than 23d from event creation, then retrieve its still-retained domain milestones. | Old submission audit log **absent**; `submitted_at`, allocation/attempt, terminal time and evidence chain **present**. Any missing core domain fact = FAIL. |
| `OBS-04-AUTHORIZATION` | Query `J1` as owner `C1`, unrelated `C2`, Worker `W1`, read-only Admin `A0`; attempt Admin state-changing request. | C1 only permitted own proof; C2 gets no private proof; W1 only worker-scoped metadata; A0 reads authorized evidence but cannot mutate; no protected reference exposed to Client/Worker. One permission violation = FAIL. Exact HTTP mapping deferred to API contract. |
| `OBS-05-NO-SECRETS` | Inject synthetic private-key/token canaries into secure test secrets; inspect API, structured logs, tracked repo text and artifact outputs. | **Zero** canary matches and zero private-key bytes in public registry/API/logs. Any match = FAIL. Never use real production keys. |
| `OBS-06-RETRY-VISIBILITY` | Redeliver `R1` twice using same `result_id`, `attempt_id`, compare accepted/duplicate domain effects and correlation metadata. | Exactly one accepted receipt, one finalization, one net reputation effect; duplicate classified as no-op and identifiable while corresponding audit metadata remains retained. Any second business effect = FAIL. |
| `OBS-07-EVIDENCE-PURGED` | At exactly `J1.terminal_at+23d`, with resolved dispute and no hold, invoke cleanup then request Job proof and reputation. | Individual proof unavailable, lifetime reputation still displays same stored counters; no implied reconstructability from deleted events. If deleted Job proof leaks or counters change = FAIL. |
| `OBS-08-INVALID-RECEIPT` | Submit invalid signature for `J2`; query rejection evidence with Admin before its own TTL; then advance past configured retry deadline if one exists. | Rejection is attributable to J2 and attempt with stable nonsecret reason; **zero** accepted result/reputation effect; final `FAILED/SYSTEM_FAULT` and single release only after retry deadline. Retry deadline not decided => final-phase check `BLOCKED`, not silently passed. |
| `OBS-09-FILING-VS-RESOLUTION` | File D1 at `terminal_at+6d`; adjudicate at `terminal_at+8d`; query evidence at `terminal_at+9d`. | `decision_at<terminal_at+7d`, resolution later is allowed; `D1` is `RESOLVED/UPHELD`, receipt immutable and corrected effective contribution queryable. A resolution rejected merely because filing window closed = FAIL. |

**Review decision APPROVED (2026-10-18):** the **minimal durable Job-linked evidence contract** and `OBS-01..09` verification design are accepted, **not** any specific new database table/framework. The final physical schema, role-specific API projections, signed-byte canonical format and retry policy remain separate design decisions. No tests have been run, so QA-OBS-01 remains `NOT_RUN`; missing prerequisites when attempting execution produce `BLOCKED`, never a fabricated PASS.

### QA-TST-01 - Repeatable testing and safe refactoring (Testability/Maintainability)

**Design-review status:** **APPROVED (2026-10-18), NOT_RUN.** The nine deterministic test designs and the 4/4 defect-detection gate are accepted. The acceptance tests apply once the affected modules, fixtures and frozen CI manifest exist; a missing prerequisite is `BLOCKED` when execution is attempted, never PASS. Approval does not imply mutation tests already exist.

| Element | Scenario |
|---|---|
| **Source** | A developer opening a pull request that changes Scheduler, result verification, dispute handling, reputation or retention behavior. |
| **Stimulus** | A behavior-preserving refactor or bug fix accidentally introduces a domain regression, such as FIFO leapfrogging, accepting a tampered receipt, duplicate reputation updates or filing a dispute at the 7-day cutoff. |
| **Environment** | A clean isolated CI run against a **pinned commit and schema version**, separate fresh PostgreSQL database, deterministic fixture IDs/seeds, controlled UTC clock, defined transaction barriers, ephemeral injected test-signing secrets, and a frozen manifest of mandatory test IDs. |
| **Artifact** | Modular source dependencies, CI job, test runner, fixtures, Job/Allocation/Receipt/Dispute/Reputation domain behavior and test-report artifacts. |
| **Response** | Execute the required regression suite; fail the CI gate on any concrete invariant violation; produce machine-readable test-ID-level evidence; demonstrate that a deliberately injected known defect is actually detected by its corresponding test. |
| **Measurable response** | **Approved mandatory gate:** 100% of frozen mandatory test IDs execute and `PASS` on an intentionally correct baseline; zero skipped/xfail; **4/4 isolated seeded regressions** are detected as `FAIL` by their corresponding tests and produce nonzero pipeline exit status; two fresh runs of identical fixture/clock produce equal normalized domain-state snapshots; no unauthorized architectural dependency. No source coverage percentage is inferred as a correctness guarantee. |

#### QA-TST-01 fixed fixtures and evaluation procedure (APPROVED test design)

- `TST-SEED-V1`: deterministic identities `C1/W1/L1`; `L1` has `total_gpu=4`; FIFO jobs `A=3`, `B=2`, `C=1`; a separate RUNNING Job has attempt `T1` and a valid Ed25519 fixture receipt; terminal Job has `T0=2026-10-01T00:00:00.000000Z` for the 7-day dispute boundary. All mutation cases **reset from a known-good baseline** and do not run against shared staging or production data.
- A **frozen CI manifest** lists the exact critical requirements/tests needed for each affected domain; at minimum the manifest must contain the existing `INT-01-FIFO`, `INT-08-FINALIZE-ONCE`, `SEC-02-TAMPER`, `SEC-05-REPLAY`, `DAT-11-FILE-AT-CUTOFF` and `OBS-01-CORRELATION` checks once their code exists, plus the appropriate Manager-restart tests. A failing or omitted mandatory test is not concealed by a general green smoke test.
- To evaluate the test suite's **defect-detection power**, inject each defect in an **isolated disposable test build** with a stable diff: (a) allow Job `C` to bypass blocked Job `B`; (b) bypass Ed25519 verification of a tampered payload; (c) apply a second success reputation contribution after receipt replay; (d) treat `now == terminal_at+7d` as eligible. For each defect, execute a fresh copy of the relevant existing test. No defect-injected build may be merged or reused as the correct baseline.
- Domain-state comparisons normalize nondeterministic transport/log metadata (e.g. correlation trace IDs) but **never** discard Job ownership, state, allocation, signed payload content, dispute decision, effective reputation contribution or the business timestamp being tested.

| Test ID | Controlled execution / evidence | Exact PASS oracle / FAIL witness |
|---|---|---|
| `TST-01-MANIFEST-GATE` | Run the frozen mandatory test manifest on a clean baseline CI build touching core modules. | Every listed test ID ran and returned `PASS`; `0` failing, skipped, xfail or missing mandatory IDs; CI exit code `0`. A missing manifest/runner => `BLOCKED`; an actual failed assertion => `FAIL`. |
| `TST-02-REPRODUCIBLE` | Restore identical DB seed/fake clock twice in fresh isolated DBs; replay same actions and collect normalized state snapshots. | Snapshot equality for Job states, allocation totals, accepted signed result facts, dispute decisions and reputation counters (`hash(snapshot1)==hash(snapshot2)`); any differing domain field => `FAIL`, report the field. |
| `TST-03-INJECT-FIFO-DEFECT` | Isolated mutant permits C ahead of blocked B, then execute `INT-01-FIFO`. | The `INT-01-FIFO` test **fails**, with expected `C=QUEUED`, observed `C=RUNNING`, and CI nonzero. If mutant is not detected => **QA-TST FAIL**. |
| `TST-04-INJECT-SIGNATURE-DEFECT` | Mutant skips Ed25519 verification for tampered result, execute `SEC-02-TAMPER`. | `SEC-02-TAMPER` detects an unexpected trusted accepted receipt and fails; CI nonzero. If it passes with the bad implementation => **QA-TST FAIL**. |
| `TST-05-INJECT-REPLAY-DEFECT` | Mutant increments reputation on replay of the same verified receipt, execute `SEC-05-REPLAY` and `INT-08-FINALIZE-ONCE`. | At least one named test detects additional `successful_jobs` or duplicate effect and fails; CI nonzero. Undetected replay bug => **QA-TST FAIL**. |
| `TST-06-INJECT-CUTOFF-DEFECT` | Mutant changes dispute eligibility predicate from `< deadline` to `<= deadline`, execute `DAT-11-FILE-AT-CUTOFF`. | `DAT-11-FILE-AT-CUTOFF` fails with unexpected Dispute row at exactly `T0+7d`; CI nonzero. Undetected boundary bug => **QA-TST FAIL**. |
| `TST-07-FORCED-INTERLEAVINGS` | Run `INT-03-CANCEL-FIRST` and `INT-04-ALLOC-FIRST` separately twice with explicit transaction barriers. | Both prescribed transaction orders reproduced (barrier trace present); actual terminal/nonterminal DB states equal their respective oracles on both runs. Random timing without barrier evidence => `BLOCKED`. |
| `TST-08-MODULE-BOUNDARIES` | Run a dependency/import/config scan against a **frozen component-ownership map**. | Zero imports granting API/Manager use of Simulator private-signing keys, zero Worker Simulator direct DB credentials/access, zero user API paths to protected simulation oracle; any prohibited dependency => `FAIL`. Absent mapping => `BLOCKED`. |
| `TST-09-FAILURE-REPORT` | Cause a known assertion failure in a disposable test and inspect emitted machine-readable report. | Report contains `test_id`, `fixture_id`, `commit_sha`, `expected`, `actual`, failed invariant/path, and executable run reference; CI exit nonzero. Missing any required field => `FAIL`. |

**Decision rule (APPROVED design):** QA-TST-01 **verified** only if `TST-01..09` all satisfy their oracles. The 4 injected-defect checks intentionally run **failing tests** against defective code: QA-TST passes only when those defects are detected, not when the mutant builds turn green. All run outputs must distinguish the deliberate negative-test result from the baseline CI run. Missing a test runner, frozen manifest, fixture generator or ownership map => `BLOCKED`, not PASS; before execution all are `NOT_RUN`. The number of changed production modules or elapsed coding time belongs separately to QA-MOD-01 calibration, not this scenario.

**Design-to-implementation mapping:** the concrete `pytest`/framework commands, CI job names and file paths will be added after the implementation stack/runner is selected. These abstract test IDs are stable acceptance contracts, not fabricated currently runnable commands.

### QA-OPS-01 - Reproducible local operation (Deployability)

**Design-review status:** **APPROVED (2026-10-18), NOT_RUN.** Seven mandatory test designs and the 30-minute calibration *method* are approved; the timing number is a calibration hypothesis, not a product SLA. Deployability here means a developer can rebuild and run the actual MVP from documented prerequisites, without a real GPU or external payment infrastructure. Docker Compose is a **recommended but not yet approved** deployment mechanism; the observable startup/smoke oracles below do not depend on pretending this ADR is closed.

| Element | Scenario |
|---|---|
| **Source** | A new team developer or an independent CI runner without existing project configuration. |
| **Stimulus** | Clone a pinned repository commit into a clean environment; configure local development secrets; initialize and start the complete simulation system. |
| **Environment** | A **versioned reference CPU-only environment profile** (OS/arch, CPU/RAM, Docker/runtime or equivalent, network access and dependency cache policy fixed before testing), fresh project checkout, empty PostgreSQL application database and no production credentials, cloud GPU or payment integrations. |
| **Artifact** | Frontend, Backend API, Manager, Worker Simulator, PostgreSQL migrations, environment templates, synthetic fixtures, startup scripts and runbook. |
| **Response** | Following documented commands only, initialize local test secrets and database, start all required processes, pass readiness/health checks, and complete one signed simulated Job through the API; rerunning initialization is safe. |
| **Measurable response** | **Approved mandatory gate:** all five required components become healthy from a clean checkout with **zero undocumented manual steps**; database migrations/fixtures are repeatable; one Job is accepted, signed, verified, completed and released exactly once; zero real-GPU/payment dependence and zero secret leakage. **Calibration hypothesis (not product NFR):** end-to-end cold setup + smoke <=30 minutes, measured only on the agreed reference profile. |

#### QA-OPS-01 fixture and measurement protocol (APPROVED test design)

- Version `OPS-ENV-V1` before executing: exact OS/image, processor architecture, CPU/RAM limits, package/container runtime versions, cache/network policy, Git commit SHA and expected services. A candidate lab profile is **4 vCPU/8 GiB, CPU-only Linux with Docker Compose v2**; this is an **unapproved test reference**, not a production infrastructure claim. A run on another machine must be marked separately rather than called comparable.
- `OPS-SMOKE-V1`: seeded Worker `W1`, Client `C1`, Listing `L1` (`ACTIVE`, `total_gpu=4`), one `gpu_count=1` deterministic `SUCCESS` Job. Generate/inject an ephemeral test-only Worker Ed25519 private key at startup, register its public counterpart, freeze simulation seed and test clock, and use the documented supported runtime entry points. `successful_jobs` before smoke `S0`; after smoke `S0+1` and `worker_fault_jobs` unchanged.
- Do not embed real or test secret private keys in Git; do not require a GPU driver or external settlement service. Dependency downloads at build time, if allowed by the frozen environment profile, are recorded; runtime never calls real GPU or payment endpoints. If startup requires manual fixes absent from the runbook, the reproducibility gate fails, even when a team member can eventually make it work.

| Test ID | Controlled execution / evidence | Exact PASS oracle / FAIL witness |
|---|---|---|
| `OPS-01-CLEAN-BOOT` | Clone pinned commit into fresh workspace; create local configuration following only runbook; initialize DB; start UI/API/Manager/Simulator/PostgreSQL. | All 5 health/readiness probes pass on the supported reference environment; **0 undocumented commands/manual edits**; reported schema version equals expected. Missing prereq/runbook => `BLOCKED`; documented steps that fail on supported hardware => `FAIL`. |
| `OPS-02-E2E-SIGNED-JOB` | On the fresh system create `OPS-SMOKE-V1` Job via authenticated Client endpoint and advance controlled simulation to completion. | Job transitions `QUEUED -> RUNNING -> COMPLETED`; one verified Ed25519 result; active allocation returns to `0`; `successful_jobs=S0+1` exactly; no real GPU used. Any violated state/count => `FAIL`. |
| `OPS-03-CPU-ONLY` | Run smoke in environment without GPU device access; intercept/block external GPU and payment/settlement network calls. | Signed simulated Job still completes; **0** GPU-device dependency errors and **0** outbound calls to real GPU/payment/settlement providers. Any dependency/call => `FAIL`. |
| `OPS-04-NO-SECRET-LEAK` | Inject ephemeral synthetic secret canaries; inspect tracked files, public responses, logs and generated artifacts. | **0** canary/private-key matches in prohibited surfaces; private key is not readable by API/Manager/frontend service identities. Any exposure => `FAIL`. |
| `OPS-05-MIGRATION-IDEMPOTENCE` | Apply migrations and fixture seeding to empty DB, record schema and seed counts; reapply twice. | Version remains pinned; zero duplicate accounts/listings/keys; key domain-record counts unchanged across reapplication; any changed count/schema after repeat => `FAIL`. |
| `OPS-06-PROCESS-RESTART` | Restart API/Manager/Simulator with durable DB intact during a RUNNING Job; continue the smoke without changing seed/Job ID. | No committed job loss, no extra allocation/receipt/reputation effect; all required services become ready again; correct single finalization. Any loss or duplicate => `FAIL`. |
| `OPS-07-REPEAT-INDEPENDENT` | Repeat clean setup and `OPS-SMOKE-V1` on two independent fresh workspaces with identical `OPS-ENV-V1`. | Both runs satisfy `OPS-01..06`; normalized core Job, receipt verification and reputation snapshots are identical, except allowable transport timestamps/log IDs; differing business outcomes => `FAIL`. |
| `OPS-08-COLD-SETUP-TIME` | Measure monotonic time from start of fresh checkout/dependency installation to all five ready probes **and** completed E2E smoke; record each sub-phase. | **Calibration SUPPORTED** if each of two independent runs <=1,800 s; any run >1,800 s => **REFUTED**; missing environment/cache policy or timings => `UNMEASURED`. Not a mandatory product PASS gate until reviewed as a target. |

**Decision rule (APPROVED design):** Mandatory Deployability acceptance requires `OPS-01..07` all `PASS`. `OPS-08` has a **binary calibration outcome** (`SUPPORTED`/`REFUTED`) separate from product correctness, and no timing claim is valid until `OPS-ENV-V1` is frozen. Tests must archive exact documented setup commands, tool versions, environment profile, redacted build/start logs, schema revision, verified receipt fingerprint, Job/Allocation/Reputation DB snapshots and run IDs. The precise startup tool, health endpoint shapes, secret provisioning and migration tool remain **OPEN implementation decisions**.

### Review status register — approved design vs executable verification (2026-10-18)

| Scenario | Design review | Executable verification | Important distinction |
|---|---|---|---|
| QA-MOD-01 | APPROVED (calibration option A) | NOT_RUN | 2 modules/16 hours are hypotheses, not automatic release gates. |
| QA-REL-01 | APPROVED (7 tests) | NOT_RUN | Recovery correctness required; <=120 seconds remains measured NFR target. |
| QA-INT-01 | APPROVED (8 tests) | NOT_RUN | All eight forced-order cases must pass to verify the scenario. |
| QA-SEC-01 | APPROVED (9 tests) | NOT_RUN | Signing bytes/transport contracts must be frozen before executing. |
| QA-PER-01 | APPROVED (6 performance checks; fixed 736-VU workload) | NOT_RUN | 552 Client / 147 Worker / 37 Admin, 2-minute ramp, 600-second plateau, 3 independent runs; actual test machines must be pinned. |
| QA-SCA-01 | APPROVED (6 scalability checks; 1x to 5x fixtures) | NOT_RUN | 1.50x latency / 0.85x throughput are approved-to-test calibration hypotheses, not new release SLAs. |
| QA-DAT-01 | APPROVED (2026-10-18; original 17 deterministic cases); approved exception-hold policy; new monitoring checks proposed | NOT_RUN | Filing cutoff `[terminal_at, terminal_at+7d)`; hold until RESOLVED (no fixed maximum); warning <=1h, CRITICAL at 24h, retry each 15m, post-resolution expired cleanup <=1h. |
| QA-OBS-01 | APPROVED (2026-10-18; 9 deterministic cases + minimal Job-linked evidence contract) | NOT_RUN | Domain evidence outlives operational audit events for long-queued Jobs; no raw audit TTL extension. |
| QA-TST-01 | APPROVED (2026-10-18; 9 tests including 4 defect injections) | NOT_RUN | Frozen CI manifest and mutant-killing evidence required; no code tested yet. |
| QA-OPS-01 | APPROVED (2026-10-18; 7 mandatory tests + timing calibration) | NOT_RUN | CPU-only reproducible signed-job demo; 30 minutes is an unverified calibration hypothesis, not a product SLA. |
| QA-MOD-02 | APPROVED (2026-10-18; 9 deterministic compatibility/security tests) | NOT_RUN | V1/V2 version-change exercise only; requires frozen canonical signed-byte contract; V2 is not MVP scope. |

## 3. Cross-scenario trade-off summary

| Conflict | Risk | Design response | Test evidence |
|---|---|---|---|
| Modifiability vs Performance | Policy layers or broader hooks increase expensive queue checks | Stable scheduling interface + small atomic allocator + profile before optimizing | QA-MOD-01 + QA-PER-01 |
| Modifiability vs Security | Extensible simulation code can expose signing secrets | Separate signing boundary, versioned payload contract, no arbitrary code plugins | QA-MOD-02 + QA-SEC-01 |
| Reliability vs Response Time | Durable commits and retries increase work and visible queue delay | Non-blocking submit, durable DB state, bounded dispatcher | QA-REL-01 + QA-PER-01 |
| FIFO fairness vs GPU utilization | A large head job blocks smaller jobs | Preserve strict FIFO for MVP; log queue age/unused capacity | QA-INT-01 + QA-PER-01 |
| 23-day retention vs Lifetime Auditability | Evidence is deleted while aggregates persist | Preserve aggregates, ensure disputes settle first, disclose loss of per-job auditability | QA-DAT-01 + QA-OBS-01 |

## 4. Traceability and governance

| Scenario | Main Architecture Drivers | Requirement evidence |
|---|---|---|
| QA-MOD-01 / QA-MOD-02 | AD-03, AD-14, AD-06 | NFR-M01, NFR-O01, NFR-S04, SRS BL-01..03 |
| QA-REL-01 | AD-05, AD-04 | NFR-R01/R02/R04/R08 |
| QA-INT-01 | AD-01, AD-04 | FR-JL-02..04, NFR-R03/R06 |
| QA-SEC-01 | AD-02, AD-06 | FR-SR-01..04, NFR-S03..06 |
| QA-PER-01 | AD-07, AD-08 | NFR-P01..05 |
| QA-SCA-01 | AD-08, AD-12 | NFR-P01, NFR-M01/M03 |
| QA-DAT-01 | AD-09, AD-04 | NFR-D01..08, FR-RP-01/02 |
| QA-OBS-01 | AD-10, AD-02 | NFR-S07, FR-DP-01..03 |
| QA-TST-01 | AD-11, AD-03 | NFR-M01..04 |
| QA-OPS-01 | AD-12, AD-13 | NFR-M03/M04, SRS out-of-scope constraints |

**Review rule (11/11 scenario designs APPROVED, 2026-10-18):** Approval is **for test specifications and decision rules only**, never proof of implementation quality. All execution statuses are `NOT_RUN` until tests produce fixture/commit/environment-specific evidence; runtime prerequisites may cause `BLOCKED`, and a failed required assertion is `FAIL`. Calibrations (QA-MOD-01's <=2 modules/16 engineer-hours, QA-SCA-01's 1.50x/0.85x, QA-OPS-01's 30 minutes) remain clearly separated from binding business correctness. The Data Lifecycle exception policy was **APPROVED 2026-10-18**: hold until RESOLVED without a fixed maximum, alert/retry/escalate at specified intervals and cleanup expired resolved evidence promptly. The six new exception-monitoring tests are not yet separately approved/executed. No strict hard-delete bound is asserted for unresolved cases. Detailed architecture, canonical signature encoding, actual load-test hardware and API schema may still be OPEN implementation prerequisites. Assignment reports may highlight three primary drivers, while this comprehensive catalog is retained for the real system.
