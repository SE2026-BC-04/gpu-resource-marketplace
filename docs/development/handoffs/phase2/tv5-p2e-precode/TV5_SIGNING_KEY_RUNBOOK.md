# TV5-P2E-04 — Worker Signing Key Custody Runbook (Design)

**Status:** proposed operational runbook; `PENDING_ACK` TV1/TV2/TV3/TV4. No secrets or real key material belong here.

## Identity and boundary

- Ed25519 private key belongs to the trusted Worker/Simulator signing boundary. Never persist it in PostgreSQL, API, Manager, callback payloads, logs, repository, frontend, or this document.
- The public key registry binds `(worker_id,key_id)` to a 32-byte public key and validity/lifecycle metadata. TV2 owns persistence/grants; TV3 owns verifier lookup and auth validation; TV5 owns signer behavior; TV1 owns process orchestration and secret injection; TV4 confirms Listing/Worker identity interactions.
- A `key_id` selects a registered Worker key; it is not a substitute for verifying the signed Job/Attempt/Listing context. Missing, wrong-owner, malformed or unavailable key must fail closed.
- Callback service Bearer (`SIMULATOR_CALLBACK_TOKEN`) and dispatch Bearer (`MANAGER_DISPATCH_TOKEN`) are separate random ≥256-bit secrets. Neither is a JWT nor an Ed25519 key.

## Provisioning and restart

**PROPOSED — NOT OWNER APPROVED:** deliver per-Worker private material through the approved deployment secret mechanism, scoped to the Simulator process, with no command-line or image-layer exposure. Startup validates key format and key_id/Worker mapping without logging key bytes. On restart, reload the same active key identity for existing in-flight work; missing material disables signing and surfaces a health/readiness failure. Do not generate a replacement identity silently because historical key binding would change.

TV1/TV5 must define injection mechanism, file/secret lifetime, permissions, startup validation and rotation quiescence. TV2/TV3 must define public-key registry lifecycle and how historical verification remains available. Exact deployment mechanism is not inferred from local health/config code.

## Planned K1 → K2 rotation

The approved design anticipates planned rotation only after quiescing dispatch/signing under K1, preserving K1 public verification for retained receipts, publishing/activating K2 with correct Worker binding, then resuming work. Do not retire the historical public key while retained signed evidence or an in-flight attempt may require it. Exact overlap, activation timestamps, rollback, and in-flight treatment need TV1/TV2/TV3/TV5 ACK and tests. Unknown key/version => fail closed.

## Compromise response remains a decision

`NEEDS_OWNER_DECISION`: revocation/incident policy for a compromised private key, including whether in-flight results are quarantined, how historical signatures are treated, who declares compromise, audit/notification actions, and recovery key. No automatic rewrite, re-sign, deletion, or retroactive invalidation of immutable V1 evidence is proposed. Lead + TV1/TV2/TV3/TV5 must decide.

## Security acceptance checklist

DRT-05/06/08/09/19: wrong/missing key; restart recovery; K1/K2 rotation with historical verify; invalid signature and altered context; wrong/opposite service token; no key/secret in logs, DB, API DTOs, simulator JSON or test artifacts. Runtime/security tests `NOT_RUN`; ACKs `NOT PROVIDED`.

---

## Key rotation, G1/G2 and readiness — 2026-11-13

Source: TV2 #46 @ ba63466 D-18 and TV3 #49 @ 9b337f5 §6.6.5, **all PROPOSED_FOR_ACK**. Registration takes an exclusive Worker advisory transaction lock; TX-ALLOCATE a shared Worker lock, first in lock order. Register K2 as **second active key** to persistently quiesce allocation; drain RUNNING Attempts; deploy K2 secret bundle and self-check; under exclusive lock require exactly expected {K1,K2}, trusted K2 readiness and no RUNNING Attempt, then **retire K1 only**. On failure restore usable K1 bundle **before** retiring K2 removes the fence. Unexpected third key fails closed. **Retire** K1 after safe quiescence is permitted; **delete** historical K1 referenced by signed evidence is not. Partial unique active-key index conflicts with two-row fence; E-C3/D4 and new global lock order require lead L2 approval.

Simulator startup checks its private bundle locally, which is **not** proof of matching the active DB public key. TV5 prefers **G1**, a separate authenticated nonce proof signed with `GPU-MARKETPLACE:SIGNER-PROOF:V1\n` domain, verified by Manager against sole active key *outside* UoW. This needs a new internal endpoint/API L2 change. G2 dispatch-refusal has an unresolved cold-Manager bootstrap contradiction if allocation requires pre-existing readiness; no silent exploratory real-Job allocation. TV2 @ ba63466 proposes `SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at)` as internal argument; under Worker+Listing locks active key ID/fingerprint, Worker and DB expiry must match or `Blocked(SIGNER_NOT_READY)` with no writes. Stale K1 proof after K2 activation is blocked (P2B-DRT-29 design only). Restart **within** proof TTL remains a residual risk requiring tests/invalidation and cannot be claimed impossible. Provisioning identity D-03/S-10, E-C3, G1/G2, incident response and all runtime tests are pending.
