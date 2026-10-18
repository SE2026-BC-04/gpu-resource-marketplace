# ADR-007 - Reproducible load-test configuration

**Status:** ACCEPTED (2026-10-18) - Option B, fixed reference environment, 128 in-flight Simulator attempts, deterministic job fixture and nine LDCFG test designs approved  
**Version:** 0.2 (design approval only; benchmark `NOT_RUN`)  
**Date:** 2026-10-18  
**Project:** GPU Resource Marketplace - simulation-only MVP  
**Intended repository path:** `docs/architecture/decisions/ADR-007-load-test-configuration.md`  
**Implementation / benchmark status:** `NOT_RUN`; no achieved latency, throughput, capacity, or load-test result is claimed.

## 1. Goal and scope

Freeze a reproducible, measurable load-test configuration for **QA-PER-01** and its data-volume comparison **QA-SCA-01**. This ADR specifies *how to evaluate* the existing 736-VU performance objectives and safety invariants. It neither expands the functional MVP nor silently turns calibration hypotheses into product SLAs. It does not select the Backend/Frontend framework (ADR-008), implement the test runner, prescribe physical tables/API endpoints (later Database/API design), or alter ADR-003/004/005/006.

**Previously APPROVED and not reopened here:** `PERF-736-V1`, 736 VUs = 552 Client + 147 Worker + 37 Admin, 120-second ramp, 600-second plateau, one outstanding HTTP action per VU, 5.0-second think time after each completed action, three independent runs from restored fixtures, the role-specific weighted action mix, `PERF-SEED-V1`, six `PER-*` verification gates, and six `SCA-*` checks (1x and 5x). These are approved *test designs*, not executed results.

**Review decision completed (2026-10-18):** the user approved option B, the specified test-runner/reference resources, 128 in-flight Simulator attempts, Section 4 job mix and all nine LDCFG preflight tests. Tool/image digests are not yet pinned, and execution remains `NOT_RUN`.

## 2. Alternatives and accepted decision

| Option | Test execution | Advantages | Limitations | Review |
|---|---|---|---|---|
| A | Ad hoc HTTP scripts, unspecified machines and data | Quick local smoke checks | Noncomparable user/session mix; cannot credibly verify 736 VUs or report reliable p95 | Not recommended for acceptance |
| **B** | Version-pinned `k6` runner on separate load host + seeded Postgres fixture + pinned SUT + database reconciliation | Reproducible role sessions, controlled pacing, independent metrics, re-runnable 1x/5x comparisons | Requires prepared machines/fixtures/observability and a controlled reset | **ACCEPTED (2026-10-18)** |
| C | Open-ended maximal RPS/stress ramp | Useful for exploratory capacity discovery | Does not answer the agreed 736-active-user profile; may conflate backlog and traffic | Outside baseline acceptance |

**Accepted choice: B (2026-10-18).** `k6` is the selected load-test tool, not the application framework. The runner's exact release number and image digest must be recorded and frozen at implementation time; never claim they are pinned already.

## 3. Approved workload protocol: `PERF-736-V1`

- Execute one test campaign with **3 fully independent runs**. For each run, restore identical seed state, restart processes, and clear all test-generated metric series and transient queues not contained in the authoritative fixture. Preserve the same code commit, migrations, configuration, hardware limits and runner version.
- Ramp from 0 to **736 active VUs** over `120 s`, respecting the final role split (552 Client, 147 Worker, 37 Admin). Evaluate plateau metrics only in `[ramp_end, ramp_end + 600 s)`; do not pool ramp-up/cooldown results into acceptance percentiles.
- Use a fixed PRNG seed `20261017`, deriving separate deterministic streams per VU (`profile_id`, `role`, `vu_index`, `action_index`); selected actions follow the immutable role weights below. Per VU: maximum **1** outstanding HTTP action, then `5.0 s` think time **after completion**. Consequently 736 active sessions do not imply 736 simultaneous in-flight requests or GPU jobs; actual throughput must be observed, not inferred.
- Authenticate each VU with the correct test identity. Every Client request refers to its own Job/evidence; every Worker operation stays in its owned Listings; Admin remains read-only. Generated Job submission identifiers and idempotency keys are unique per new action, except in independently defined replay tests (not part of the ordinary traffic mix).

| Role | VUs | Approved weighted actions (percentage of *that role's* completed action selections) |
|---|---:|---|
| Client | 552 | 40% browse catalog/listing; 30% read own Job status; 15% read own retained Signed Result; 15% valid Job submission to ACTIVE Listing |
| Worker | 147 | 40% read owned Listings; 30% read assigned Jobs; 20% read lifetime reputation; 10% edit valid simulated price on an owned, specially reserved Listing |
| Admin | 37 | 50% read system dashboard; 30% read queue/jobs; 20% review disputes/reputation; never mutate |

**Implementation note:** The specific REST URLs, method/schema snapshots and test user credentials must be pinned after the API contract exists. Map each logical action to exactly one documented endpoint operation for scoring. Any fixture-induced 4xx, wrong role, missing object, silent action skip, or misleading substitution of a different endpoint invalidates the profile; do not hide it within the 5xx percentage.

## 4. Dataset contract: `PERF-SEED-V1` / `SCA-1X` / `SCA-5X`

| Seeded entity | `PERF-SEED-V1` = `SCA-1X` | `SCA-5X` | Rule |
|---|---:|---:|---|
| Worker accounts | 200 | 1,000 | 147 active test Worker accounts remain identical in both |
| GPU Listings | 600 | 3,000 | Exactly 3 per Worker; initially ACTIVE and `total_gpu=4` each |
| Retained terminal Jobs | 12,000 | 60,000 | Retained, valid ownership and signed evidence for result-reading paths |
| Initially QUEUED Jobs | 600 | 3,000 | Legal job/listing ownership and capacity requests |
| Active Client / Worker / Admin test principals | 552 / 147 / 37 | The same 552 / 147 / 37 | Extra 5x Workers are non-active fixture principals |

**Seed and reset rules:**

1. A versioned fixture generator, seed `20261017`, produces stable fixture IDs/ownership, unique signing keys stored only in injected test secrets, valid Signed Result V1 evidence and deterministic simulation reference/oracle values. The protected oracle cannot be read or modified by Client/Worker VUs. No test key is committed to the repository.
2. Spread retained terminal Jobs among Client identities so **all 552 active Clients** can read at least one owned Job and accepted Signed Result. Fix terminal timestamps in `[T0 - 7 days, T0 - 1 day]`, where campaign epoch `T0` is recorded before seeding; reruns use the identical fixture snapshot. Nothing must expire during the benchmark. Seeded queued jobs must have valid GPU counts/durations and no active allocation.
3. Reserve an immutable subset of owned Listings for Worker price edits; the Client submission pool is a disjoint fixed subset of ACTIVE Listings in `SCA-1X`, and those exact Listing IDs are reused for 5x comparisons. Do not introduce pause, delete, arbitrary pricing races or extra user-facing workflows.
4. `SCA-5X` preserves every original `SCA-1X` entity and adds exactly four disjoint, similarly distributed extension sets. Compare the same VU identities, scenario sequence and original Listing selection in both sizes, rather than changing which endpoints or hot spots are exercised.
5. Approved benchmark-only bounded legal *new Job* fixture profile (not a new business rule): `gpu_count=1/2/4` with weights `80/15/5%`; `duration_seconds=2/5/10` with weights `50/30/20%`. All submitted Jobs are valid for `total_gpu=4`. Apply the same synthetic outcome mix (e.g., `80% SUCCESS`, `10% JOB_FAULT`, `10% WORKER_FAULT`) from deterministic Manager-protected reference fixtures in both sizes. These weights and duration choices are **ACCEPTED only for the load-test fixture**, not a new user-facing requirement; they do not change the Worker receipt enum rules or reputation accounting.
6. Hash a normalized seeded-DB snapshot (excluding timestamps/fields legitimately populated only by the running service) and record table row counts before every run. Do not combine results across runs with different seed contents or configuration.

## 5. Accepted reference execution environment and worker concurrency

| Setting | `ADR-007` accepted reference configuration | Why it must be fixed |
|---|---|---|
| Separate load generator | `4 vCPU / 8 GiB RAM`, stable LAN, exact `k6` version/image digest recorded | Avoid benchmarking the load client itself |
| SUT host | Dedicated **8 vCPU / 16 GiB RAM + SSD**; no unrelated competing workloads | Matches QA-PER-01 reference environment |
| API | **2 process/worker execution units**, pinned for every matched run | Record actual process model after ADR-008; no dynamic autoscaling |
| Manager | **1 process**; ADR-005 2-second polling and all accepted retry/deadline settings unchanged | Prevent a different scheduler concurrency from contaminating comparison |
| Worker Simulator | **1 process; maximum 128 in-flight simulated attempts** (independent of count of Worker accounts) | Fixed logical processing capacity; at-least-once transport and Job/Listing GPU capacity invariants still apply |
| PostgreSQL | Single local SUT instance; fixed version, settings, pool limits and container resource caps | Stable query/lock contention and reproducible results |
| Network and time | Dedicated isolated LAN; log RTT distribution and NTP/time source; server-side durations | Distinguish network time from API execution |

**Important:** The `128` Simulator concurrency cap is an *accepted load-test environment parameter*, not a product limit, number of concurrent Worker users, guarantee of 128 running GPU Jobs, or permission to bypass FIFO/Listing capacity. Asynchronous mock work may share the Simulator process. Simulator behavior when at cap must use existing ADR-003/005 retry/deadline rules; no new Job state is added.

Before a benchmark can be declared valid, freeze the exact machine identifiers, OS/kernel, CPU/RAM/SSD quotas, process and container limits, API and DB pool sizes, service and PostgreSQL versions, benchmark scripts/commit, internal/external networking, UTC test window and telemetry configuration. If the reference hardware is unavailable, use a **new explicitly versioned exploratory profile** and do not report its results as comparable `PERF-736-V1`/`SCA-1X`/`SCA-5X` evidence without an approved profile amendment.

**Generator validity guard (ACCEPTED for benchmark design):** During the 600-second plateau, normalized generator CPU utilization `p95_1s <= 80%` of its reserved 4 vCPUs, peak RSS `<= 85%` of its 8 GiB memory budget, zero skipped/dropped actions and zero unexpected client transport failures. Failing this is `BLOCKED` profile validity, **not** a measured SUT performance failure. The SUT itself may saturate and miss targets; never invalidate a genuine SUT bottleneck merely because its CPU usage is high.

## 6. Instrumentation, metric definitions and verdicts

**Source of truth for server-side latency:** a uniform API middleware timer from request entry into the application to response completion, excluding load-generator/network transit; export per-endpoint status and duration raw samples or precise histograms. Preserve VU-measured end-to-end latency separately. No performance PASS is allowed if server timings cannot be tied to actual plateau requests.

**Scoring per independent run (never average the three runs into one pass):**

| Metric | Exact measurement | Verdict |
|---|---|---|
| VUs | Plateau role VU counters (each 1-second sampling tick) | Exactly `552/147/37` and `736` total for every recorded tick; any dropped/undocumented action => `BLOCKED` |
| Read p95 | Successful read operations across the approved categories; at least `1,000` samples per run. Compute nearest-rank percentile: `sorted[ceil(0.95*n)-1]` | NFR performance target `PASS` iff `<= 2.000 s` **for each** run |
| Submit p95 | Valid successfully accepted Job submissions; at least `500` samples per run; require exactly one persisted Job per accepted submission | NFR performance target `PASS` iff `<= 3.000 s` **for each** run |
| 5xx | `count(external VU-facing HTTP 500..599) / count(all external VU-facing HTTP responses)` in plateau | NFR performance target `PASS` iff `< 0.0100` **for each** run; no dilution by internal dispatch/callback responses |
| Transport/4xx | Report unexpected 4xx, TCP/connect failures, client-side timeouts and skipped actions separately | Unexpected errors invalidate profile correctness and are not quietly counted as successful requests; report root cause |
| Throughput | Completed VU-facing HTTP responses / `600 s` | Diagnostic requests/second; no new absolute throughput SLA |
| Queue and Manager | Queue depth, age, time from eligibility to allocation, outcome-finalization delay, outbox/inbox retry counts, job fault reasons | Required evidence, not a new queue-delay SLA |
| DB and runtime | DB lock wait/p95, slow query timings and plans, CPU/RSS, connection-pool saturation, external RTT | Required diagnosis; data does not override correctness gates |
| Invariants | Independent DB queries and actor-scoped response assertions for FIFO, Listing allocation limits, Job state, ownership, accepted results and reputation | **0** violations at each sampled checkpoint and final reconciliation. Any single violation = mandatory `FAIL` regardless of latencies |

Use 1-second source timestamps to identify the exact steady-state window. Sample independent consistency checks after each controlled batch and at 60-second intervals throughout plateau, plus an end-of-run snapshot. For FIFO, keep allocation order evidence per Listing (not merely a post-test aggregate). At the end of a run stop **new requests**; do not pretend in-flight or queued Jobs instantly complete, and never mix their completion events into VU-facing HTTP response latency samples. Preserve the state and in-flight counts in the report.

**Conflict resolution:** `PER-01-PROFILE` and `PER-06-EVIDENCE` validate the experiment; `PER-05-SAFETY` is a hard correctness gate; `PER-02..04` report NFR target PASS/FAIL individually. A generator failure is a `BLOCKED/ERROR` measurement, not proof the application met the target. A SUT latency failure in a valid run is a genuine target `FAIL` even if safety remains PASS. All checks are `NOT_RUN` until executed.

## 7. Approved scalability comparison: `QA-SCA-01`

Run the **same three-run `PERF-736-V1` campaign** on each of `SCA-1X` and `SCA-5X`, using the identical SUT/generator resources, code, settings, active principals and logically equivalent traffic sequence. Restore fixtures between every run; pair repetition indices `i=1..3`.

- `SCA-1X` counts: `200 Workers / 600 Listings / 12,000 terminal Jobs / 600 queued Jobs`.
- `SCA-5X` counts: `1,000 Workers / 3,000 Listings / 60,000 terminal Jobs / 3,000 queued Jobs`.
- **Mandatory**: zero capacity/FIFO/state/authorization/reputation invariant breaches at both sizes.
- **Existing NFRs**: report read/submit p95 and 5xx individually for each run/size; do **not** treat a good scaling ratio as an absolute performance pass.
- **Calibration only**: for each paired run, both `p95_read_5x/p95_read_1x` and `p95_submit_5x/p95_submit_1x` must be `<= 1.50` for the relative latency hypothesis to be `SUPPORTED`; throughput_5x/throughput_1x must be `>= 0.85` for the throughput hypothesis to be `SUPPORTED`. Otherwise `REFUTED`, or `UNMEASURED` for incomplete/noncomparable evidence. These are **not new product SLAs**.
- No horizontal scaling trial or additional load tier is introduced in this ADR.

## 8. Additional ADR-007 configuration/preflight tests (APPROVED 2026-10-18; NOT_RUN)

These checks are **config verification**, not a replacement for the already approved `PER-01..06` and `SCA-01..06` scenario tests. All remain `NOT_RUN`.

| ID | Exact action / evidence | Binary PASS oracle; otherwise |
|---|---|---|
| `LDCFG-01-RESET` | Snapshot hashes/row counts before all three 1x runs; record code/config/runner digests | Every baseline snapshot hash/count and code/config digest identical; mismatch => `BLOCKED` |
| `LDCFG-02-DATA` | SQL count and integrity checks on baseline fixture | Exactly `200/600/12000/600`; 552 Clients/147 Workers/37 Admin with role-correct own-readable records; zero expired evidence, invalid FK/ownership or missing Signed Result; else `BLOCKED` |
| `LDCFG-03-ROLE-MIX` | Instrument VU count each plateau second and action-selection logs | VU counters always 552/147/37; selected-action distribution uses fixed documented role weights and per-VU deterministic PRNG; every generated operation maps to a permitted action, no dropped/skipped actions; else `BLOCKED` |
| `LDCFG-04-ENV` | Collect host/container resource snapshots and process/Simulator settings | Generator 4vCPU/8GiB, SUT 8vCPU/16GiB SSD, API 2 execution units, Manager 1, Simulator 1 with cap 128; DB/process versions, image digests, pool settings and network baseline recorded identically per matched run; else `BLOCKED` |
| `LDCFG-05-GENERATOR` | Generator host CPU/RSS and transport counters sampled over plateau | CPU p95_1s <=80% of 4 vCPU, peak RSS <=85% of 8GiB, dropped/skipped=0, unexpected transport error=0; else `BLOCKED` |
| `LDCFG-06-METRICS` | Match server-side samples to selected plateau requests via request identifiers/timestamps | `n_read>=1000`, `n_submit>=500` per run, valid category labels and exact percentile implementation, timestamps all within scored window; no missing data; else `BLOCKED/ERROR` |
| `LDCFG-07-BUSINESS` | At fixed checkpoints and plateau end, reconcile live DB with signed result, allocation and reputation event records; verify response RBAC | Zero GPU-capacity, FIFO, Job-state, accepted-result uniqueness, duplicate reputation and authorization violations; any counterexample => **mandatory `FAIL`** |
| `LDCFG-08-SCALE` | Compare restored `SCA-1X` and `SCA-5X` snapshots and active principal IDs | Exactly 5x Worker/Listing/history/queued counts; all original 1x records identical and present in 5x; same VU identities/traffic selectors; else `BLOCKED` |
| `LDCFG-09-REPORT` | Verify persisted manifests and raw measurements for all 3 1x and 3 5x runs | Complete code/config/seed/host/runner manifest, timestamps, endpoint stats, generator and server metrics, SQL invariants, per-run NFR decisions, paired ratio calculations; missing evidence => `BLOCKED` |

**Acceptance separation:** The user approved all nine configuration tests on 2026-10-18. This design `ACCEPTED` status does not mean any test passed. The baseline performance NFR verdicts, product invariants, and comparative hypotheses are always reported independently.

## 9. Dependencies, risks and acceptance record

- **Before executing:** application and API contract implemented; reproducible PostgreSQL migration and seed generator; real single-node SUT and separate load generator available; authenticated test accounts; server-side instrumentation; SQL invariant check runner; load tool and runtime versions pinned. Until then: `NOT_RUN`, and later `BLOCKED` if a required precondition is missing.
- `PERF-736-V1` benchmarks synthetic user session traffic, not 736 concurrently RUNNING GPU Jobs. A long FIFO queue is reported as a bottleneck; the benchmark is not authorized to change the FIFO rule.
- Price updates occur on reserved separate Listings, so benchmark fixture errors do not turn otherwise valid Client POSTs into expected 4xx responses.
- Retry/deadline/Dispute behavior stays exactly as ADR-005/006; the configured Simulator concurrency must not change those semantics.
- No benchmark has been run; no hardware availability or achieved p95 is asserted.

**Accepted decision (2026-10-18):** Option B, the Section 4 new-Job distributions, Section 5 fixed environment/128 in-flight Simulator attempts, generator validity guard and Section 8 nine `LDCFG` test designs are approved. QA-PER-01 and QA-SCA-01 criteria are unchanged. The hardware, scripts, pinned image digest and measured results do not yet exist in this work: all execution checks remain `NOT_RUN`.
