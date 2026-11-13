# TV5-P2E-03 — Attempt Cache, Dispatch and Cold-Restart Gap

**Status:** `P2E-OPEN-01` Option A is approved design; cache numeric parameters and `P2E-CACHE-GAP-01` remain unresolved. No Simulator DB access is proposed.

## Retained-process state machine

Cache key is logical `attempt_id`; entry binds a canonical immutable fingerprint of the approved ten-field dispatch. `IN_FLIGHT` and `FINISHED` describe only volatile cache state, never Job status.

```text
ABSENT --valid dispatch--> IN_FLIGHT --execution/callback constructed--> FINISHED
IN_FLIGHT + identical retry -> coalesce/acknowledge retained work
FINISHED + identical dispatch -> acknowledge; callback retry reuses exact bytes/result_id
retained entry + altered fingerprint -> 409 EXECUTION_CONFLICT
eviction/process stop -> ABSENT (durable Attempt/Outbox remains in DB)
```

Atomic admission must prevent two concurrent identical requests from starting competing retained executions. One produced receipt retried after timeout reuses the exact original `result_id`, raw envelope bytes, timestamp and signature. After a cold restart the logical attempt and Outbox IDs/deadlines remain stable; deterministic work may execute again and create a new receipt ID/candidate. The DB finalizer is responsible for once-only business effects.

## `P2E-CACHE-GAP-01`: alternatives, not a decision

| Option | Behavior / restart | Contract and security impact | Trade-off / oracle | Owners |
|---|---|---|---|---|
| A. Add a trusted dispatch binding/proof checked by Simulator, derived from persisted immutable Outbox state by an authorized component | Restarted Simulator validates the same binding; altered payload fails closed | Requires new/clarified authenticated wire field or transport proof; preserve no-DB Simulator and no oracle; threat model must cover compromised Manager/token | Stronger enforceable cross-restart comparison; additional key/verification lifecycle. Test: same attempt + different canonical request after cold restart returns 409, no execution | Lead, TV1, TV2, TV3, TV5 |
| B. Qualify API Contract guarantee to retained-state scope, while Manager is sole trusted source and sends immutable Outbox bytes | Restart may re-execute only the persisted original; contradictory authenticated input after restart cannot be distinguished by cache alone | Explicit change-control to global `409` guarantee; strict conflict remains while state retained; token/Manager trust is relied upon | No added secret/state, but weaker adversarial guarantee. Test: live-cache contradiction 409; restart original stable; document and test the qualified boundary | Lead, TV1, TV3, TV5; TV2 confirms Outbox immutability |

Do not claim either option approved. No DB reads/writes or persistent store may be added to Simulator as a shortcut.

## Parameters awaiting measurement/ACK

Cache max entries/bytes, TTL, per-entry memory bound, maximum simultaneous executions, behavior when full, in-flight eviction prohibition, shutdown drain/cancel policy, callback queue bound, and cold-start recovery limits are `PENDING_PARAMS`. TV1 owns runtime budget and shutdown orchestration; TV5 owns cache policy; TV2/TV3 review durable source/auth consequences. No number should be invented without measurement and acceptance tests.

## Retry/failure semantics and test oracle

Manager owns redelivery from immutable Outbox using ADR-005 timing and fenced claims. `202` dispatch only means accepted for execution; it does not change Job terminal state. Invalid auth yields no accepted work; malformed immutable input is rejected; same retained attempt/different fingerprint is 409. Network timeout/5xx is uncertain delivery, so resend the same event/attempt/payload, not a new allocation. Never retry a DB mutation with unknown commit blindly.

Required coverage: DRT-01/02 concurrent duplicates and altered retained request; DRT-03 cold restart original; DRT-04 cold altered request (BLOCKED); shutdown/full-cache/eviction barriers; callback ACK loss exact replay; no second Allocation/Attempt/deadline extension. All Phase 2 tests `NOT_RUN`.

---

## TV2 CAS sync — 2026-11-13

TV2 #46 @ ba63466 proposes claim only due PENDING or expired CLAIMED rows. ACK/RETRY/EXHAUSTED requires current `state='CLAIMED'` plus matching lease owner/version; clearing the lease does not reset version. Expired current claim **without takeover** can ACK; after takeover/stale version or terminal state the old ACK updates zero rows. ACKED/EXHAUSTED are never re-claimed through ordinary dispatch; missing-receipt repair is a separate authorized port. Raw ten-key body stays byte-identical after restart (P2B-DRT-08/18 `NOT_RUN`). This DB-backed Outbox CAS **does not** solve the DB-less Simulator's volatile-cache contradictory same-attempt request after *cold restart* (`P2E-CACHE-GAP-01`); signer proof G1 concerns key possession, not dispatch-content history. Lead choice and measured cache bounds remain pending.
