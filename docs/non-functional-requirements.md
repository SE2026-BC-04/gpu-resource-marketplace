
GPU Resource Marketplace - Non-functional Requirements (NFR)
Version: 1.0 baseline
Date: 2026-10-17
Status: Requirements baseline; performance/recovery targets are proposed acceptance targets, NOT measured results.
Related document: docs/functional-requirements.md (FR baseline v1.0).
System: Simulation-only GPU marketplace; no real GPU execution, valuable tokens, or real payments.

1. Confirmed business and operational decisions
Key	Baseline decision	Interpretation
BL-01	736 concurrent users	Load-test design target: 736 concurrently active virtual users, not 736 simultaneously running GPU jobs.
BL-02	23-day history retention	Detailed terminal-job history and dependent artifacts are eligible for cleanup 23 x 24 hours after job terminal time. Active records remain.
BL-03	18-hour change-request response	Time to acknowledge, triage, and provide an initial assessment; NOT time to implement the change.
BL-04	Lifetime aggregated reputation	Persist per-worker aggregate successful-job and worker-fault counts beyond the history-retention window.
BL-05	Deterministic simulation	Reference outcomes are derived reproducibly, stored before worker receipts, and inaccessible for mutation by Client/Worker.
BL-06	Signed-result trust model	Worker Simulator signs Ed25519 receipts; Manager verifies against Worker Registry public keys.
BL-07	Approved job/listing behavior	FIFO per listing; ACTIVE/PAUSED freeze semantics; Client may cancel only QUEUED jobs.
NFR conventions
MUST: compulsory MVP invariant, to be tested.
Target: numeric initial goal to be tested in a specified environment; may be revised based on measurements.
Terminal job: job in COMPLETED, FAILED, or CANCELLED.
Eligible outcome: verified terminal result with effective classification SUCCESS or WORKER_FAULT, including any settled dispute correction.
Normal operating conditions: database is available and durable; the backend and Manager have access to configured secrets and a monotonic/reliable wall-clock source.
2. Performance and capacity
ID	Requirement	Acceptance criterion / test
NFR-P01	The prototype SHOULD handle 736 concurrently active virtual users with representative Client/Worker/Admin traffic.	Perform a repeatable load test using 736 VUs for a proposed 10-minute steady-state period; record throughput, p95 latency, errors, DB contention, and queue growth. Fix the user-action mix and environment before declaring pass/fail.
NFR-P02	Read APIs SHOULD be responsive at the target workload.	Target: at least 95% of successful catalog, listing, job-status, and dashboard reads finish within 2 seconds server-side.
NFR-P03	Job-submission API SHOULD remain responsive at target workload.	Target: p95 latency <= 3 seconds for valid submissions; the endpoint returns the created QUEUED job rather than waiting for simulation.
NFR-P04	Unexpected server errors SHOULD be rare under load.	Target: unexpected 5xx responses < 1% of requests; expected 4xx validation/conflict responses are reported separately.
NFR-P05	Correctness MUST NOT be relaxed to hit performance targets.	No GPU overallocation, unauthorized reads, double finalization, or negative counters during load and concurrency testing.
Important: 736 users does not imply 736 RUNNING GPU jobs. Queue size, simulated GPU capacity, response latency, and scheduler throughput are separate measurements. The test environment, traffic mix, and seeded dataset must be documented with the results.

3. Reliability and concurrency
ID	Requirement	Acceptance criterion / test
NFR-R01	All committed jobs, allocations, simulation deadlines, results, and disputes MUST survive a Manager process restart.	Stop Manager with both queued and running jobs; restart with DB intact; verify no committed job is missing and no allocation is duplicated.
NFR-R02	Manager SHOULD resume work promptly after restart.	Target: recover runnable work within 120 seconds of Manager restart, assuming DB connectivity; replay due simulations from persisted started_at/finish_due_at.
NFR-R03	Capacity updates MUST be atomic.	Concurrent submissions, allocations, cancels, and listing changes always preserve 0 <= allocated_gpu <= total_gpu; prove via DB-backed concurrent tests.
NFR-R04	Terminal-job processing MUST be idempotent.	Re-deliver finish/result events; terminal transition, GPU release, accepted receipt, and reputation contribution occur at most once in persistent state.
NFR-R05	Dispute resolution and reputation adjustment MUST be idempotent.	Retry UPHELD/REJECTED decisions; each job contributes at most one effective reputation classification; aggregate counters never become negative.
NFR-R06	Pause, resume, cancellation, and allocation MUST be concurrency-safe.	PAUSED blocks NEW submissions and NEW allocations; in-flight RUNNING jobs finish. Cancel/allocate race yields exactly one committed outcome.
NFR-R07	Manager MUST have a bounded failure path for invalid or unavailable signed results.	Reject invalid receipts without penalizing Worker; retry as configured; on expiration close as FAILED/SYSTEM_FAULT and release resources exactly once.
NFR-R08	Recovery mechanisms MUST not use only in-memory timers as the source of truth.	A restarted Manager can reconstruct every in-progress simulation from persisted job deadlines and deterministic reference data.
Failure boundary: NFR-R01/R02 assume durable DB survives. Disaster recovery for lost DB volumes, geo-replication, and production high availability are out of scope.

4. Security, signature validation, and trust
ID	Requirement	Acceptance criterion / test
NFR-S01	Authenticate every non-public API and enforce role-based permissions.	Missing/invalid credentials -> 401; authenticated but unauthorized role -> 403; verify Worker, Client, Admin routes.
NFR-S02	Enforce object-level ownership checks.	Worker cannot change other Workers' listings; Client cannot access other Clients' private jobs/results/disputes; Admin is read-only in MVP.
NFR-S03	Keep Worker Simulator Ed25519 private keys secret.	No private key in repository, front end, API responses, runtime logs, or persisted public Worker Registry. In development, inject test keys through local secrets, never tracked source.
NFR-S04	Verify signed receipts against a deterministic canonical payload and the registered Worker key.	Tampering with any signed field, incorrect key_id, mismatched Worker/listing/job, or incorrect signature is rejected. Preserve signer public key/version for retained receipts.
NFR-S05	Prevent replay and duplicate acceptance.	Unique result_id and one accepted final result per job; duplicate receipt does not change job state or reputation again.
NFR-S06	Protect simulation reference (oracle) integrity.	Client/Worker cannot write or retrieve hidden expected outcome/digest; it is generated and persisted before receipt verification.
NFR-S07	Maintain security-relevant audit events without secrets.	Record actor/service ID, target ID, action, event time, outcome, and correlation ID; redact private keys, credentials and sensitive tokens.
Threat-model boundary: Logical separation of Worker Simulator and Manager within one controlled prototype is not independent hardware attestation. A valid signature proves key possession/payload integrity, NOT actual GPU computation or truthfulness of a reported outcome.

5. Data retention, cleanup, and lifetime reputation
ID	Requirement	Acceptance criterion / test
NFR-D01	Keep active identities and resources independent of 23-day job-history expiration.	Active/paused users, Worker Registry, listing records, necessary signer key metadata, and lifetime reputation aggregates are NOT deleted by history cleanup.
NFR-D02	Apply 23-day retention to terminal job detail.	expires_at = terminal_at + 23 days; queued/running jobs have no terminal expiry. A proposed hourly cleanup removes eligible expired records within 1 hour of their expiry.
NFR-D03	Couple dependent evidence to job retention.	Delete terminal job detail, accepted signed receipts, simulation references, completed disputes, and per-job reputation contribution records together; no orphaned foreign-key references.
NFR-D04	Retain operational audit events for 23 days from event creation.	Periodic cleanup removes expired logs; cleanup itself emits redacted operational metrics.
NFR-D05	Persist lifetime reputation counters beyond job-detail retention.	Each Worker stores aggregate successful_jobs and worker_fault_jobs. success_rate = successes/(successes+worker_faults); zero denominator -> N/A. Expiring an already-accounted job does NOT decrement lifetime counters.
NFR-D06	Apply dispute corrections before deleting their evidence.	An upheld dispute atomically changes the job's effective contribution (subtract old category, add corrected category) exactly once; original signed receipt is immutable. Cleanup must not silently delete an unresolved dispute.
NFR-D07	Cleanup MUST be restartable/idempotent.	Re-run a partially completed cleanup; no deleted account/active listing, dangling evidence, negative reputation counters, or duplicate adjustments.
NFR-D08	Disputes MUST be limited to retained evidence.	A Client cannot open a dispute after its job evidence has expired/deleted. Normal MVP disputes are deterministic and auto-resolved promptly; unexpected unresolved items at expiry are flagged as explicit retention exceptions until resolved.
Reputation accounting invariant
Per Worker, persist only the two lifetime counters required for the displayed score:

successful_jobs >= 0
worker_fault_jobs >= 0
eligible_jobs = successful_jobs + worker_fault_jobs
reputation = N/A                      if eligible_jobs == 0
reputation = successful_jobs / eligible_jobs  otherwise
A verified SUCCESS contributes (1, 0); a verified WORKER_FAULT contributes (0, 1).
CANCELLED, unfinished jobs, invalid receipts, JOB_FAULT, and SYSTEM_FAULT contribute (0, 0).
An upheld dispute replaces the effective classification; it does not rewrite the signed receipt. Apply the delta and mark the dispute resolved in the same transaction.
Per-job contribution/idempotency evidence is kept with job history for 23 days. Once deleted, late dispute requests/replayed receipts are rejected because the job is no longer retained.
Once detailed evidence expires, lifetime aggregates can still be displayed but CANNOT be fully recomputed/audited from deleted jobs. The UI and docs should disclose this limitation.
Retention edge case (explicit exception)
If an unexpected unresolved dispute remains when its job reaches expiration, do NOT silently delete its reference/evidence. Record the exception and resolve/retry the deterministic dispute workflow as a priority. Define a maximum exception-hold duration and a final dispute-submission cutoff before claiming a strict hard-delete guarantee of exactly 23 days. This is a narrow policy detail to finalize with the architecture, not a change to the 23-day default history window.

Any backups containing historical data require a corresponding expiry policy if backups are added later; backups are not an MVP feature.

6. Maintainability and delivery process
ID	Requirement	Acceptance criterion / test
NFR-M01	Keep the six business modules logically separated in a modular monolith.	Dependency diagram shows clear module boundaries; signing secrets and simulation oracle are not exposed to user APIs.
NFR-M02	Automate correctness tests in CI.	Every PR runs formatting/linting and automated tests for state transitions, allocation races, restart recovery, signing, replay, disputes, lifetime counters and retention cleanup.
NFR-M03	Provide reproducible local setup.	Fresh developer can start API, DB, Manager, Worker Simulator and front end using documented commands and synthetic fixtures.
NFR-M04	Keep environment configuration external to source.	Repo includes .env.example but excludes live secrets, test private keys and user data; deployment changes do not require editing source code.
NFR-O01	Respond to change requests within 18 elapsed hours.	Tracking item records received timestamp, owner, preliminary impact/priority and first substantive response timestamp; no requirement to finish implementation within 18 hours.
7. Acceptance test matrix
ID	Integration/verification scenario	Pass condition
AT-P01	736-user replayable workload	Document actual p95/errors/throughput/queue; evaluate P02-P04 targets; no invariant failure.
AT-R01	Kill Manager with RUNNING and QUEUED jobs	Existing jobs resume from DB; no duplicate allocation/result.
AT-R02	Concurrent allocate/cancel/pause	No over-allocation; exact one valid final transition per race.
AT-S01	Modify signed receipt field	Signature/context verification fails; no Worker reputation penalty.
AT-S02	Replay verified receipt	No duplicated result, release, or aggregate-counter update.
AT-D01	Signed but false outcome; Client disputes	UPHELD, immutable original receipt, corrected effective reputation once.
AT-D02	Correct signed outcome; Client disputes	REJECTED, reputation unchanged by dispute.
AT-D03	Cleanup at 22d 23h 59m vs. 23d+	Retained before expiry; expired terminal history purged on schedule; active resources intact.
AT-D04	Job expires after settled upheld dispute	Lifetime counters remain unchanged during cleanup; no per-job evidence left.
AT-S03	Read another Client's private job	403/404 without data leak (API convention must be consistent).
AT-O01	Change-request ticket	First substantive reply within 18 elapsed hours.
Use an injectable/fake clock for TTL and simulation-time tests; never wait 23 real days.

8. Open, bounded design decisions for System Architecture
These do NOT reopen approved MVP behavior:

Implementation stack: select API framework, DB, and frontend framework.
Process boundary: decide whether Manager and Worker Simulator run as separate Docker Compose processes (recommended) or modules in one process for the earliest demo; maintain distinct ownership of signing keys regardless.
Transactions and idempotency: specify DB locking/unique constraints for allocation, result acceptance, dispute contributions and cleanup.
Crypto encoding: choose a documented canonical Ed25519 payload byte format and verification library.
Dispute/retention edge: pick a bounded submission window and retention-exception deadline; the 23-day default is fixed, but a hard legal deletion SLA is NOT claimed.
Load-test profile: fix operation distribution, dataset size, and test-machine specification before asserting that latency targets are met.
9. Scope exclusions
Production SLA/HA, actual GPU provisioning/execution, Kubernetes, distributed consensus, blockchain, money/token settlement, true independent compute attestation, manual dispute arbitration, advanced scheduling, and long-term individual-job auditability are out of scope.

