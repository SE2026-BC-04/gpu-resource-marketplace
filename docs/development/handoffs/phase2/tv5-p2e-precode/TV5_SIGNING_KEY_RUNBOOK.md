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
