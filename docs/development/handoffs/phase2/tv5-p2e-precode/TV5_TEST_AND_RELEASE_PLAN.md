# TV5-P2E-06 — Test and Release Plan

**Status:** test designs only; all Phase 2 runtime tests `NOT_RUN`. DRT-04 is blocked by `P2E-CACHE-GAP-01`; DRT-20 belongs to Phase 3 and is `BLOCKED_BY_PHASE_3`.

## Reputation and durable-state oracle

| Accepted path | Job | Contribution | Aggregate |
|---|---|---|---|
| SUCCESS | COMPLETED | one `SUCCESS` | successful +1 |
| FAILED / WORKER_FAULT | FAILED | one `WORKER_FAULT` | worker_fault +1 |
| FAILED / JOB_FAULT | FAILED | one explicit `NONE` | no delta |
| FAILED / SYSTEM_FAULT | FAILED | no row | no delta |
| queued cancel / invalid / late | unchanged or CANCELLED | no new row | no delta |

For accepted finalization, one transaction commits result, terminal state, release, `allocated_gpu_count` decrement, Inbox state, contribution and aggregate. Retries, restart, duplicate callbacks, concurrent finalizers, and ambiguous commit must produce no second effect.

## Normative Phase 2E matrix (P2E-DRT-01..20)

| ID | Scenario / acceptance oracle | Status |
|---|---|---|
| 01 | Concurrent identical dispatch while cache entry retained; one competing execution max | NOT_RUN |
| 02 | Altered immutable request with retained attempt → 409; original work unchanged | NOT_RUN |
| 03 | Cold restart + original persisted dispatch; stable logical IDs/output/digest, new receipt allowed, one finalization | NOT_RUN |
| 04 | Cold restart + authenticated altered same-attempt dispatch; blocked until cache-gap decision | BLOCKED |
| 05 | Missing/incompatible signer key and restart recovery fail closed | NOT_RUN |
| 06 | Quiescent K1→K2 rotation; retained K1 result still verifies | NOT_RUN |
| 07 | V1–V4 and exact nine-field output across independent JCS implementations | NOT_RUN |
| 08 | ADR-004 V1 positive and tampered field/key/UUID/time/signature negatives | NOT_RUN |
| 09 | Wrong/missing/opposite service token and end-user JWT; 401, no accepted work/Inbox | NOT_RUN |
| 10 | Lost callback 202 then original byte/ID replay; one Inbox, stable received_at | NOT_RUN |
| 11 | Concurrent same result_id same/different raw bytes; exact duplicate vs 409 collision | NOT_RUN |
| 12 | Two on-time distinct valid receipt IDs; deterministic first eligible wins once | NOT_RUN |
| 13 | Invalid earlier candidate then valid candidate; later valid wins | NOT_RUN |
| 14 | On-time Inbox persisted before deadline, Manager restarts after; result before fallback | NOT_RUN |
| 15 | Callback lock at/after deadline; late rejection, drain older candidate before fallback | NOT_RUN |
| 16 | Candidate count exceeds batch; drain in bounded passes before fallback | NOT_RUN |
| 17 | Crash around commit / lost commit ACK; atomic rollback or reconciliation, no duplicate effects | NOT_RUN |
| 18 | SUCCESS/WORKER_FAULT/JOB_FAULT/SYSTEM_FAULT; expected contribution and delta table | NOT_RUN |
| 19 | Native-role grants and oracle/raw evidence confidentiality; no Simulator DB | NOT_RUN |
| 20 | Authorized 23-day purge + OPEN Dispute evidence/key hold; Phase 3 fixture required | BLOCKED_BY_PHASE_3 |

## Additional suites required before merge of runtime work

- **UNIT:** pure version selection, DTO strictness, outcome policy, error taxonomy, cache transitions and signer/verifier adapters with deterministic test doubles.
- **WIRE/SIG:** RFC 8785 cross-runtime vectors, exact signed bytes/prefix, base64url length, tamper cases, V1–V4 values, no extra fields, canonical UUID/time, worker/key binding.
- **API/HTTP:** dispatch/callback direction-specific Bearer, request size/depth limits, 202 semantics, 409 replay/collision and redacted error/log checks.
- **POSTGRES:** disposable isolated cluster only; migrations, actual native roles/grants, Inbox/Outbox uniqueness, Listing→Job lock barriers, clock_timestamp boundaries, rollback/unknown commit, allocation/reputation persisted assertions using independent connections. No persistent/dev DB destructive tests.
- **CONCURRENCY/RESTART:** 2+ sessions and deterministic barriers for duplicate dispatch/finalizer, invalid-first/valid-second, deadline, SIGTERM/restart, and cold-cache gap options.
- **COMPOSE E2E:** existing five services only, actual internal Bearers and callback, no direct Simulator DB, role-safe read, accepted signed result and exact durable effects.

## Evidence and release gates

Each test report records commit SHA, command, collected/passed/failed/skipped counts, migration head, DB isolation/safety proof, native role, clock/barrier, before/after persisted rows, logs redacted and owner ACKs. `PASS` requires execution on exact reviewed SHA; skipped does not count as pass.

1. **Design gate:** retain approved conditional decisions; close required owner decisions and cross-phase ACKs against exact document SHA.
2. **Coding gate:** separate explicit lead sprint authorization for each task. Documentation approval does not authorize code.
3. **Implementation PR gate:** one task/branch/PR; independent human review per L0/L1 or L2/L3, exact-SHA re-review after new commits, relevant CI and disposable PG tests.
4. **Release gate:** all applicable mandatory tests pass; no unresolved P0/P1; rollback/disable plan; owner integration ACKs; no automatic merge.

PR #39's CI run is Phase 1 baseline only. It cannot be used as a Phase 2 test verdict. No Phase 2 tests were run for this documentation review.

## TV5-P2E-07..19 implementation readiness (not authorization)

| Task | Work package | Can proceed after coding gate? | Remaining prerequisite / blocker |
|---|---|---|---|
| 07 | Simulator dispatch endpoint | Partly; route/allowlist/auth adapter can be a bounded task | E-IF-01/06 ACK, service token and error/budget details; no Manager wiring until TV1 integration |
| 08 | Bounded Attempt cache | No full implementation yet | `P2E-CACHE-GAP-01`, cap/TTL/concurrency/shutdown parameters |
| 09 | Deterministic workload | Pure generator integration can proceed once versioning settled | Algorithm-version pin across queue/deploy; TV3 wire ACK; preserve approved vectors/schema |
| 10 | Signer/key loading | No | TV1 injection, TV2 registry, TV3 verifier and rotation ACK; compromise policy decision for affected incident behavior |
| 11 | Callback client | Only isolated client contract after ACK | TV3 ingress/auth, TV1 orchestration, body/time/retry budgets, TV2 Inbox semantics |
| 12 | Cold restart/re-execution | No | Cache-gap resolution and key recovery/receipt identity ACK |
| 13 | Pure finalization policy | Potentially independent after coding gate | Freeze `P2E-VERDICT-CONTRACT-01`; no SQL/commit in this slice |
| 14 | Manager Finalizer integration | No | TV1 loop and TV2 TX-FINALIZE/UoW/lock/commit-reconcile ACK |
| 15 | Multi-candidate winner handling | No | TV2 Inbox schema/permissions + TV3 verdict and TV1 batch-loop ACK |
| 16 | Deadline/System Fault fallback | No | TV1 scheduler loop + TV2 TX-DEADLINE-FALLBACK and DB-clock/drain ACK |
| 17 | Reputation/read compatibility | Pure policy review may proceed after decisions | TV2 ledger/aggregate ownership; no Phase 3 Dispute implementation |
| 18 | Full test/fault injection | No integrated suite | Runtime slices and all applicable owner interfaces; disposable PG and five-service environment |
| 19 | PR/handoff/release evidence | Docs preparation can continue; implementation closeout cannot | Exact reviewed HEAD, evidence, owner ACKs, independent human reviews and rollback plan |

The “can proceed” column is a dependency assessment only. It does not grant coding authorization, approve any unresolved decision, or imply that a future task must wait for all of Phase 2E to merge if its own gates are satisfied.

---

## Cross-phase regression addendum — 2026-11-13 (all NOT_RUN)

| Additional test | TV5 proposed pass oracle |
|---|---|
| TV2 P2B-DRT-08/18 | Current-owner expired lease ACK allowed absent takeover; stale version zero write; original 10-key raw HTTP bytes identical across retries/restarts |
| TV2 P2B-DRT-20..23 | Earlier PENDING candidate blocks later valid candidate; late fallback cannot skip committed on-time Inbox; swapped rejection result ID/hash/Job no-op; signed bytes equal locked extracted envelope |
| TV2 P2B-DRT-24..28 | Shared/exclusive Worker advisory races in both orders, two-active-key fence across crash, K1 restore before abort fence release, no unexpected-key retirement |
| **TV2 P2B-DRT-29** | Cached proof K1 after K2 activation fails locked active-key ID/fingerprint check; wrong Worker/fingerprint/expired proof blocks without Job/GPU/Outbox writes |
| TV3 P2C-SIGN-01..06 + TV5 P2E-GATE-01 | G1 nonce/domain/key matching; proof-replay and cross-domain signatures rejected; Manager restart requires fresh proof; no HTTP in UoW |
| TV5 P2E-GATE-02 / ROTATE-01 | G2 bootstrap inconsistency addressed explicitly if chosen; signer restart *within* still-valid proof TTL measured, not assumed safe |
| TV5 P2E-API-01 | 16,384/16,385 raw bytes and depth 4/5, 404/409/422/503 status, same-stored received_at deadline equality |

Keep P2E-DRT-01..20 and original release gates. Every Phase 2 native-role PG, crypto, concurrency and five-service runtime test remains **NOT_RUN**, regardless of existing repository CI. Record source/consumer SHA, native role, migrations, barriers, stored rows, exact wire bytes and reviewer ACK before claiming PASS.
