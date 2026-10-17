# GPU Resource Marketplace - Quality Attribute Scenarios

**Version:** 0.3 (QA-MOD-01 review decision A; verification protocol clarified)  
**Date:** 2026-10-17  
**Status:** QA-MOD-01 review decision A ACCEPTED: hypothesis thresholds are exploratory, with explicit binary test oracles. Other scenarios remain under review. No tests, implementation or benchmark results are claimed.

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

| Element | Scenario |
|---|---|
| **Source** | Security maintainer / development team. |
| **Stimulus** | Add an optional signed metadata field and introduce a new receipt schema version. |
| **Environment** | Existing retained receipts need verification for as long as their evidence is actually retained: normally 23 days after job termination, possibly longer during an explicit unresolved-dispute retention exception. Worker Simulator and Manager run as distinct processes. |
| **Artifact** | Receipt encoding/verifier interface and Worker Simulator serializer. |
| **Response** | Support explicit schema versioning; verify old retained receipts while signing new receipts with the new version; reject ambiguous/unknown encodings. |
| **Response measure** | **APPROVED:** no old retained signed evidence becomes silently invalid and no tampered payload is accepted. **PROPOSED:** schema change localized to signing/verifier contracts plus related fixtures; no public Job API breaking change; all old/new signature fixtures pass. |

**Verification:** golden canonicalization fixtures, tampered-payload suite, compatibility tests for every retained schema version. Key rotation UI remains out of scope.

### QA-REL-01 - Recover Manager after process restart (Reliability)

| Element | Scenario |
|---|---|
| **Source** | Operator/process failure. |
| **Stimulus** | Manager is killed while queued/running jobs and pending dispatch/results exist. |
| **Environment** | PostgreSQL data remains available and durable; normal network/connectivity resumes on restart. |
| **Artifact** | Manager scheduler, persisted jobs/deadlines/allocations and proposed outbox/inbox. |
| **Response** | Reload committed work, recover in-flight simulation deadlines and resume delivery/finalization without duplicate allocation or reputation. |
| **Response measure** | **APPROVED:** 0 lost committed jobs, 0 duplicate accepted results/reputation effects, 0 capacity violations. **TARGET:** eligible work resumes <=120 seconds after Manager restart (NFR-R02). |

**Verification:** crash injection before dispatch, before and after finalization commit, then DB invariants and restart timestamp audit.

### QA-INT-01 - Concurrent capacity and state transitions (Data Integrity)

| Element | Scenario |
|---|---|
| **Source** | Multiple Clients/Worker and Manager concurrently. |
| **Stimulus** | Two 3-GPU requests target a 4-GPU listing while a cancel and Worker Pause may race allocation. |
| **Environment** | Concurrent API requests, Manager polling/dispatch; a listing has finite capacity. |
| **Artifact** | Job/listing state, GPU allocations and transaction boundaries. |
| **Response** | Serialize conflicting commits; produce a legal state and capacity level; reject invalid cancel or post-Pause allocation. |
| **Response measure** | **APPROVED:** `0 <= allocated <= capacity` after every commit; no `CANCELLED` job holds allocation; no allocation begins after committed PAUSED state; one legal state transition wins each race. |

**Verification:** concurrent DB-backed stress tests; repeat with randomized interleavings, plus contention/load profile.

### QA-SEC-01 - Reject altered or replayed signed results (Security)

| Element | Scenario |
|---|---|
| **Source** | Faulty/malicious result sender. |
| **Stimulus** | Submit receipt signed with wrong key, modified after signing, wrong attempt/listing, or redelivered verbatim. |
| **Environment** | Job execution is in progress; Manager and Worker Simulator are separate processes. |
| **Artifact** | API ingress (if callback chosen), result verifier, Worker Registry keys and finalization logic. |
| **Response** | Authenticate sender, validate canonical bytes/Ed25519 and matching business context, reject invalid receipts, deduplicate genuine retries; do not penalize Worker for infrastructure verification failures. |
| **Response measure** | **APPROVED:** every mutated/misbound fixture is rejected, no acceptance for unknown key/attempt, a replay changes business state **0** additional times; no secret appears in client/API/log artifacts. |

**Verification:** deterministic cryptographic positive/negative fixtures, duplicate callback storm, API ownership and secret scans.

### QA-PER-01 - Mixed 736-user workload (Performance)

| Element | Scenario |
|---|---|
| **Source** | 736 concurrently active simulated users. |
| **Stimulus** | Repeated catalog reads, job submits, status/dashboard polling and Worker listing updates. |
| **Environment** | Fixed documented traffic mix, seeded test data, machine size and a proposed 10-minute steady state. |
| **Artifact** | Backend API, PostgreSQL, Manager and role-scoped read endpoints. |
| **Response** | Respond quickly without relaxing authorization, allocation or idempotency invariants. |
| **Response measure** | **APPROVED BASELINE:** exercise **736** VUs (not 736 `RUNNING` GPU jobs). **TARGETS:** successful reads p95 <=2s; valid job submissions p95 <=3s; unexpected server errors <1%; **MUST:** zero invariant/authorization failures (NFR-P01..05). |

**Verification:** k6/Locust profile with recorded mix/dataset/hardware, request p95, 5xx and DB/queue metrics. Baseline targets are not measured results.

### QA-SCA-01 - Growth in simulated Workers and Listings (Scalability)

| Element | Scenario |
|---|---|
| **Source** | Project Owner / increased test dataset. |
| **Stimulus** | Seed significantly more Worker identities, listings and queued jobs. |
| **Environment** | Same logical architecture, controlled database and infrastructure resources. |
| **Artifact** | Registry queries, queue scheduler, DB indexes and Manager dispatch loops. |
| **Response** | Maintain independent per-listing scheduling and avoid global mutable singleton state; identify load-related bottlenecks via metrics. |
| **Response measure** | **OPEN:** exact data-growth multiple and acceptable throughput degradation must be chosen after a baseline measurement. **MUST:** no capacity violation or cross-listing data leakage at any tested volume. |

**Verification:** scale fixture sizes progressively and record job dispatch delay, lock wait and per-listing fairness. Do not invent a production scale SLA.

### QA-DAT-01 - Expire historical evidence safely (Data Lifecycle)

| Element | Scenario |
|---|---|
| **Source** | Scheduled retention cleanup process. |
| **Stimulus** | A terminal Job and linked evidence become older than 23 x 24 hours from `terminal_at`; unresolved dispute may coexist. |
| **Environment** | Normal running marketplace; workers/listings still active; fake clock available in tests. |
| **Artifact** | Terminal Job details, signed receipts, simulation references, disputes, per-job reputation evidence and lifetime aggregates. |
| **Response** | Delete only eligible resolved history, preserve active business state and lifetime Worker totals; record exception instead of deleting unresolved dispute evidence. |
| **Response measure** | **APPROVED:** eligibility at 23 days; no active job/managed listing removed; no orphan evidence; reputation counters unchanged during expiry; repeated cleanup safe. **TARGET:** periodic hourly cleanup, expiry lag <=1 hour (NFR-D02). **OPEN:** maximum exceptional retention hold. |

**Verification:** fake-clock at 22d23h59m and 23d+, retry cleanup, unresolved dispute exceptions and counter reconciliation.

### QA-OBS-01 - Explain a disputed result end-to-end (Observability/Auditability)

| Element | Scenario |
|---|---|
| **Source** | Admin/maintainer investigating a suspicious result. |
| **Stimulus** | A Client disputes a signed but inconsistent result or the Manager logs an invalid receipt. |
| **Environment** | Evidence is still within its 23-day retention window and the Admin has read-only dashboard access. |
| **Artifact** | Structured logs, verification outcome, job/attempt/result/dispute IDs and persisted audit events. |
| **Response** | Correlate job allocation, signing/verification, dispute decision and reputation effect without exposing private keys or sensitive tokens. |
| **Response measure** | **APPROVED:** relevant activity events contain actor/service ID, correlation and outcome; no signing secrets in logs (NFR-S07). **PROPOSED:** one job's retained chain can be reconstructed from IDs with no missing state-transition events. |

**Verification:** scripted end-to-end dispute followed by a log/audit reconciliation query.

### QA-TST-01 - Repeatable testing and safe refactoring (Testability/Maintainability)

| Element | Scenario |
|---|---|
| **Source** | Developer changes scheduler, signature or dispute domain logic. |
| **Stimulus** | Code refactor or defect fix. |
| **Environment** | Pull request CI with PostgreSQL fixture and seeded deterministic jobs. |
| **Artifact** | Module boundaries, automated tests and test fixtures. |
| **Response** | Run focused unit, integration, race, signature, dispute, recovery and retention tests, rejecting invalid changes. |
| **Response measure** | **APPROVED:** CI must cover listed critical invariants (NFR-M02). **PROPOSED:** every PR touching core domains runs relevant integration tests and passes the complete defined acceptance suite before merge. |

**Verification:** CI artifacts, injected defect tests and fake-clock/seed reproducibility.

### QA-OPS-01 - Reproducible local operation (Deployability)

| Element | Scenario |
|---|---|
| **Source** | New developer or CI agent. |
| **Stimulus** | Fresh checkout and setup of the MVP environment. |
| **Environment** | Supported workstation/CI image with documented prerequisites and synthetic fixtures. |
| **Artifact** | Frontend, API, DB, Manager, Simulator, Compose/configuration files and `.env.example`. |
| **Response** | Start services without GPU hardware or production secret material; demonstrate a signed simulated job end-to-end. |
| **Response measure** | **APPROVED:** reproducible documented startup of all required services (NFR-M03/M04); private keys/secrets absent from tracked code. **PROPOSED:** all seeded acceptance fixtures can be replayed from a clean checkout by an independent developer. |

**Verification:** clean-environment setup and acceptance demo run. Choice of Docker Compose remains a proposal until implementation stack is accepted.

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

**Review rule:** A scenario's new numeric engineering measure is not binding solely because it appears here. QA-MOD-01 Option A is approved **as a calibration method**, not an acceptance-threshold waiver. All 11 scenarios must eventually get test-ID-level fixtures/oracles and evidence under Section 1.1 before architecture quality can be called VERIFIED. Other new targets remain PROPOSED/OPEN until reviewed; report tests as PASS/FAIL/BLOCKED/NOT_RUN/ERROR rather than narrative impressions. Assignment reports may highlight three primary drivers while this catalog remains comprehensive for the actual system.
