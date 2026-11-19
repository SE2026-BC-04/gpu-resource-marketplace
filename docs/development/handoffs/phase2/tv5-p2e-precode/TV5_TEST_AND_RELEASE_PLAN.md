# TV5-P2E-06 — Test and Release Plan

**Status:** test designs only; all Phase 2 runtime tests `NOT_RUN`. DRT-04 is blocked by unresolved D-16 / `P2E-CACHE-GAP-01`; DRT-20 belongs to Phase 3 and is `BLOCKED_BY_PHASE_3`. The MVP algorithm-version mapping is already approved by `P2E-GPU005B-DEC-06`; release compatibility evidence below remains unrun.

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

### Algorithm-version release preflight — `P2E-VERSION-01..06` (design oracle)

`demo-v1` remains immutably mapped to `demo-v1-public1` for the current MVP, with the exact version persisted by TX-SUBMIT. Dispatch remains the approved ten-key shape and Signed Result remains V1; neither gains `algorithm_version`. A future algorithm or workload-profile version is a separate proposal and cannot silently reinterpret existing Jobs or protected references.

Before enabling a Simulator release, the release record must show:

1. V1–V4 normative vectors produce the existing exact canonical output and digest.
2. QUEUED Jobs submitted before deployment and RUNNING retries after deployment use the same `demo-v1-public1` behavior.
3. The candidate release and rollback artifact both pass the same compatibility suite before either receives old Jobs.
4. Historical Signed Result V1 evidence remains verifiable using retained public keys and its original bytes; no historical reference or signature is rewritten.
5. Any mismatch fails deployment preflight/blocks rollout. It is not resolved by guessing a version from output, adding a wire field, or altering Signed Result V1.

These checks refine, but do not renumber or replace, the existing `P2E-VERSION-01..06` oracles above: exercise the current V1–V4 corpus; process a pre-deploy QUEUED Job and retry a RUNNING Attempt after deployment; validate both candidate and rollback builds; verify retained historical Signed Result V1 evidence; reject an incompatible same-profile candidate before traffic. All are **NOT_RUN**. Runtime owners TV1/TV5 and persistence/contract owners TV2/TV3 must ACK the release procedure on exact SHA. Changing the mapping requires a separate L2 contract decision.

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
| TV3 P2C-SIGN-01..08 + TV5 P2E-GATE-01 | G1 nonce/domain/key matching; proof-replay and cross-domain signatures rejected; Manager restart requires fresh proof; no HTTP in UoW |
| TV5 P2E-GATE-02 / ROTATE-01 | G2 bootstrap inconsistency addressed explicitly if chosen; signer restart *within* still-valid proof TTL measured, not assumed safe |
| TV5 P2E-API-01 | 16,384/16,385 raw bytes and depth 4/5, 404/409/422/503 status, same-stored received_at deadline equality |

Keep P2E-DRT-01..20 and original release gates. Every Phase 2 native-role PG, crypto, concurrency and five-service runtime test remains **NOT_RUN**, regardless of existing repository CI. Record source/consumer SHA, native role, migrations, barriers, stored rows, exact wire bytes and reviewer ACK before claiming PASS.

---

## Additional exact-head regression oracles — 2026-11-18

| Test matrix | Lead-selected design / required checks |
|---|---|
| TV2 `P2B-DRT-19` | First-contributing UPSERT (D-12) with **two concurrent distinct Jobs for one Worker**: unique contribution, +1 each and trusted `updated_at`; NONE/SYSTEM_FAULT/duplicates do not touch aggregate |
| TV2 `P2B-DRT-23` | Reject `INVALID_STRUCTURE`/`UNSUPPORTED_SCHEMA_VERSION` as post-ingress definitive verifier codes, and reject housekeeping `NOT_SELECTED`/`ALREADY_TERMINAL` as TV3 verdicts; transient drift keeps PENDING |
| TV2 `P2B-DRT-29` | `SignerReadiness`: wrong `worker_id`, wrong public key fingerprint, expired proof at **DB timestamp equality**, stale K1 after K2; two allocation/rotation commit orders and zero Job/GPU/Outbox writes |
| TV3 `P2C-SIGN-01/02` | Unknown/mismatched signer blocks allocation **after proof expiration/invalidation**; not a claim that an existing cached TTL proof disappears instantly |
| TV3 `P2C-SIGN-07` / TV5 `P2E-ROTATE-01` | Simulator restart **inside proof TTL** with valid cached proof: document possible allocation and later `SYSTEM_FAULT` with no Worker penalty; do not overclaim no-allocation |
| TV3 `P2C-SIGN-08` / TV2 `P2B-DRT-29` | Proof K1, activate K2, try stale K1 proof ⇒ `Blocked(SIGNER_NOT_READY)`; then fresh K2 proof succeeds; both lock orders |
| TV5 `P2E-GATE-01` | G1 proof: 32 raw nonce bytes and 43-char unpadded wire base64url, canonical UUID IDs, domain-separated 64-byte signature; wrong nonce/key/domain/replay rejected. Endpoint auth scope `MANAGER_DISPATCH_TOKEN`. |
| TV5 `P2E-API-01` | D-01 Option C: retained raw bytes + DB CHECK/hash and bound context; deliberate same-ID different body/context collision and unknown-COMMIT probe. No arbitrary raw SELECT for API role. |

All are **NOT_RUN**. Lead source: [#46 conditional decision @531805b](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771); current TV2 #46 @a27526e, TV3 #49 @62bded7. Existing repository CI cannot serve as the acceptance evidence for any of these checks.

---

## E-IF-09 bounded candidate scan/restart test additions — 2026-11-19

These rows extend, and do not replace, P2E-DRT-12/-13/-14/-16 or TV2 P2B-DRT-06/-20/-21/-23/-37. The producer port is `iter_eligible_inbox(job_id, cursor, bound) -> Batch(candidates, has_more, scanned_through)`; rows use `(received_at, inbox_id)` ordering, PENDING state and the strict on-time predicate. Cursor is volatile; PostgreSQL Inbox state is durable. Every row below is a **planned test, NOT_RUN**.

| ID | Scenario / acceptance oracle | Status |
|---|---|---|
| 21 | Two valid on-time candidates, including equal `received_at`; lower `inbox_id` wins deterministically independent of lock/order race; exactly one terminal result/release/contribution | NOT_RUN |
| 22 | Stop Manager after a bounded batch with more candidates; restart with `cursor=None`; rescan unsettled PENDING rows in order and do not duplicate settled effects | NOT_RUN |
| 23 | Earlier candidate hits transient verifier/key-store failure; it remains PENDING, later candidate cannot win via `PrecedingPending`, and fallback is blocked | NOT_RUN |
| 24 | Reject an invalid earlier candidate, crash before scanning later candidate, restart with `cursor=None`; settled rejection is not repeated and later valid candidate is processed | NOT_RUN |
| 25 | Inbox receipt committed with trusted `received_at < hard_deadline_at`, Manager finalizes after deadline/restart; candidate is accepted before fallback and Worker `finished_at` is ignored | NOT_RUN |
| 26 | Manager restarts while on-time PENDING Inbox rows exist and there is no durable cursor/cache; DB scan rediscovers all unsettled rows, while settled rows are absent | NOT_RUN |
| 27 | Batch returns `has_more=True`, or an earlier on-time PENDING row exists; deadline fallback remains blocked until all preceding candidates settle | NOT_RUN |
| 28 | Winner commits with remaining candidates; TV2 housekeeping marks nonwinners separately (`NOT_SELECTED`/`ALREADY_TERMINAL`), and replay/settled rows produce no second finalization or reputation effect | NOT_RUN |

**Scenario mapping:** invalid-first/valid-second is P2E-DRT-13 and P2B-DRT-20; two valid candidates is P2E-DRT-12 with the tie-break extension in 21; restart halfway is P2B-DRT-37 and P2E-DRT-22; transient failure is P2B-DRT-21/-23 and P2E-DRT-23; crash after rejection is P2E-DRT-24; on-time receipt finalized late is P2E-DRT-14/-25; restart without cursor is P2B-DRT-37 and P2E-DRT-26. P2B-DRT-37 is TV2's producer-level test design, not a claim that the TV5 service/adapter integration has run.

For the current TV3 #49 producer tip `e73fb107d15296a6f317d9bed25ce76fe0657ac2`, G1 proof/error coverage also maps to `P2C-SIGN-09/10`; K1 evidence during two-key quiescence maps to `P2C-KEY-10`; callback/finalizer recovery interfaces map to `P2C-DRT-20/21/24`. These identifiers extend the earlier TV3 test list and remain **NOT_RUN**. The Simulator proof endpoint is stateless; do not add a Simulator nonce replay-cache test or implementation. The Manager must use a fresh single-use nonce and no allocation call may proceed without a valid fresh proof.
