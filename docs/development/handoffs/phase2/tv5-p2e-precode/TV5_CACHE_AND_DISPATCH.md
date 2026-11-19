# TV5-P2E-03 — Attempt Cache, Dispatch and Cold-Restart Gap

**Status:** `P2E-OPEN-01` Option A is approved design. Cache numeric parameters remain `PENDING_PARAMS`; `P2E-CACHE-GAP-01` / D-16 remains `NEEDS_OWNER_DECISION`. The lead prefers Option B for the MVP, but this is a proposal only: it does not amend the approved API Contract or authorize implementation. No Simulator DB access, new service, or persistent Simulator store is proposed.

## Retained-process state machine

Cache key is logical `attempt_id`; entry binds a canonical immutable fingerprint of the approved ten-field dispatch. `IN_FLIGHT` and `FINISHED` describe only volatile cache state, never Job status.

```text
ABSENT --valid dispatch--> IN_FLIGHT --execution/callback constructed--> FINISHED
IN_FLIGHT + identical retry -> coalesce/acknowledge retained work
FINISHED + identical dispatch -> acknowledge; callback retry reuses exact bytes/result_id
retained entry + altered fingerprint -> 409 EXECUTION_CONFLICT
eviction/process stop -> ABSENT (durable Attempt/Outbox remains in DB)
```

Atomic admission must prevent two concurrent identical requests from starting competing retained executions. This is **volatile Attempt deduplication**, not durable once-only computation. PostgreSQL Outbox/Inbox/finalization state is responsible for once-only committed business effects (accepted result, release and reputation), not for proving which dispatch bytes a DB-less Simulator saw before a cold restart. One produced receipt retried after timeout reuses the exact original `result_id`, raw envelope bytes, timestamp and signature. After a cold restart the logical Attempt and Outbox IDs/deadlines remain stable; deterministic work may execute again and create a new receipt ID/candidate.

When the cache entry is retained, Simulator can compare the incoming immutable dispatch fingerprint with the retained fingerprint and reject a conflicting same-Attempt request with `409 EXECUTION_CONFLICT`. After eviction/restart, it has no prior fingerprint and cannot distinguish an original resend from a contradictory authenticated request using RAM alone. The immutable Outbox ensures an honest Manager retries the stored payload, but does not prove the request history to the restarted Simulator. G1 signer proof proves possession of a signing key; it is not dispatch-content history. The immutable Outbox and PostgreSQL once-only effects do not close this detection gap.

## `P2E-CACHE-GAP-01`: alternatives, not a decision

| Option | Behavior / restart | Contract and security impact | Trade-off / oracle | Owners |
|---|---|---|---|---|
| A. Trusted durable-dispatch verification | An authorized component supplies a verifiable binding derived from persisted immutable Outbox state; Simulator checks it after restart | Requires a reviewed transport/authentication contract and threat model; Simulator still has no DB access, oracle or persistent store | Stronger enforceable cross-restart conflict check, with new protocol/key lifecycle and integration cost. Test must prove altered payload fails before execution after restart | Lead, TV1, TV2, TV3, TV5 |
| B. Qualify `409 EXECUTION_CONFLICT` to retained-cache scope (**lead-preferred MVP proposal**) | Retained entry: identical fingerprint deduplicates, altered fingerprint gets 409. After cache loss, Simulator may re-execute an authenticated dispatch; Manager is trusted to resend its immutable Outbox payload | Requires formal change-control to the global API Contract conflict guarantee. No extra wire field, Simulator DB access, service or persistent state | Smaller MVP and preserves no-DB Simulator boundary, but weakens cross-restart adversarial detection. DRT-04 must be revised only after that contract decision; test retained-cache conflict and cold restart of the original immutable dispatch | Lead, TV1, TV2, TV3, TV5 |

**Decision status:** Option B is the lead's stated preference, **not an approved API change**. D-16 remains `NEEDS_OWNER_DECISION`; request a recorded L2 decision from the lead and exact-SHA ACKs from TV1/TV2/TV3/TV5. Until then, retain the currently approved contract as unresolved and keep cold-restart altered-dispatch DRT-04 `BLOCKED`, not PASS. Do not implement either option based on this proposal. No DB reads/writes, persistent store or new service may be added to Simulator as a shortcut.

## Parameters awaiting measurement/ACK

Cache max entries/bytes, TTL, per-entry memory bound, maximum simultaneous executions, behavior when full, in-flight eviction prohibition, shutdown drain/cancel policy, callback queue bound, and cold-start recovery limits are `PENDING_PARAMS`. TV1 owns runtime budget and shutdown orchestration; TV5 owns cache policy; TV2/TV3 review durable source/auth consequences. No number should be invented without measurement and acceptance tests.

## Retry/failure semantics and test oracle

Manager owns redelivery from immutable Outbox using ADR-005 timing and fenced claims. `202` dispatch only means accepted for execution; it does not change Job terminal state. Invalid auth yields no accepted work; malformed immutable input is rejected; same retained attempt/different fingerprint is 409. Network timeout/5xx is uncertain delivery, so resend the same event/attempt/payload, not a new allocation. Never retry a DB mutation with unknown commit blindly.

Required coverage: DRT-01/02 concurrent duplicates and altered retained request; DRT-03 cold restart original; DRT-04 cold altered request (BLOCKED); shutdown/full-cache/eviction barriers; callback ACK loss exact replay; no second Allocation/Attempt/deadline extension. All Phase 2 tests `NOT_RUN`.

---

## TV2 CAS sync — 2026-11-13

TV2 #46 @ a27526e records the approved-design-direction of claim only due PENDING or expired CLAIMED rows. ACK/RETRY/EXHAUSTED requires current `state='CLAIMED'` plus matching lease owner/version; clearing the lease does not reset version. Expired current claim **without takeover** can ACK; after takeover/stale version or terminal state the old ACK updates zero rows. ACKED/EXHAUSTED are never re-claimed through ordinary dispatch; missing-receipt repair is a separate authorized port. Raw ten-key body stays byte-identical after restart (P2B-DRT-08/18 `NOT_RUN`). This DB-backed Outbox CAS **does not** solve the DB-less Simulator's volatile-cache contradictory same-attempt request after *cold restart* (`P2E-CACHE-GAP-01`); signer proof G1 concerns key possession, not dispatch-content history. Lead choice and measured cache bounds remain pending.

---

## Distinguish conditional D-06 from D-16 — 2026-11-18

The lead **conditionally approved D-06 CAS**: a claimed owner/version can ACK a lease past expiry if no takeover occurred, but a stale-takeover owner cannot alter an event. `ACKED`/`EXHAUSTED` are never reclaimed through the ordinary claim path. **Missing-receipt repair is still a separate, unapproved operational authorization and fencing contract** (TV1/TV2/TV5 must freeze it with race tests, no new Attempt/Event/deadline). This is not the same as `D-16/P2E-CACHE-GAP-01`, which remains **unresolved**: a restarted DB-less Simulator cannot prove an altered previously observed same-Attempt dispatch only from a volatile cache. Source [TV1 @531805b](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771). All tests `NOT_RUN`.
