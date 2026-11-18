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

The approved design anticipates planned rotation only after quiescing dispatch/signing under K1, preserving K1 public verification for retained receipts, publishing/activating K2 with correct Worker binding, then resuming work. Do not **delete** a historical public key while retained signed evidence references it; **retire** K1 only after safe quiescence and preserve its row for later verification. Exact overlap, activation timestamps, rollback, and in-flight treatment need TV1/TV2/TV3/TV5 ACK and tests. Unknown key/version => fail closed.

## Compromise response remains a decision

`NEEDS_OWNER_DECISION`: revocation/incident policy for a compromised private key, including whether in-flight results are quarantined, how historical signatures are treated, who declares compromise, audit/notification actions, and recovery key. No automatic rewrite, re-sign, deletion, or retroactive invalidation of immutable V1 evidence is proposed. Lead + TV1/TV2/TV3/TV5 must decide.

## Security acceptance checklist

DRT-05/06/08/09/19: wrong/missing key; restart recovery; K1/K2 rotation with historical verify; invalid signature and altered context; wrong/opposite service token; no key/secret in logs, DB, API DTOs, simulator JSON or test artifacts. Runtime/security tests `NOT_RUN`; ACKs `NOT PROVIDED`.

---

## Key rotation, G1/G2 and readiness — 2026-11-13

Source: TV2 [#46 @ a27526e](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) D-18 and TV3 [#49 @ 62bded7](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) §6.6.5. TV1 **conditionally approved D-18/E-C3 and G1 @ 531805b**, but API source reconciliation, provisioning rights, TTL and cross-owner ACKs remain pending. Registration takes an exclusive Worker advisory transaction lock; TX-ALLOCATE a shared Worker lock, first in lock order. Register K2 as **second active key** to persistently quiesce allocation; drain RUNNING Attempts; deploy K2 secret bundle and self-check; under exclusive lock require exactly expected {K1,K2}, trusted K2 readiness and no RUNNING Attempt, then **retire K1 only**. On failure restore usable K1 bundle **before** retiring K2 removes the fence. Unexpected third key fails closed. **Retire** K1 after safe quiescence is permitted; **delete** historical K1 referenced by signed evidence is not. Partial unique active-key index conflicts with two-row fence; E-C3/D4 and new global lock order require lead L2 approval.

Simulator startup checks its private bundle locally, which is **not** proof of matching the active DB public key. TV1 **conditionally approved G1** (not G2), a separate authenticated nonce proof signed with `GPU-MARKETPLACE:SIGNER-PROOF:V1\n` domain, verified by Manager against sole active key *outside* UoW. This **requires normative internal endpoint/API L2 change control**; G2 was **not selected** and is retained only as historical alternative. Do not authorize exploratory real-Job allocation. TV2 @ ba63466 proposes `SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at)` as internal argument; under Worker+Listing locks active key ID/fingerprint, Worker and DB expiry must match or `Blocked(SIGNER_NOT_READY)` with no writes. Stale K1 proof after K2 activation is blocked (P2B-DRT-29 design only). Restart **within** proof TTL remains a residual risk requiring tests/invalidation and cannot be claimed impossible. Provisioning identity D-03/S-10, E-C3, G1/G2, incident response and all runtime tests are pending.

---

## G1 proof wire and fingerprint, approved direction — 2026-11-18

[TV1 L2 decision on #46](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771) chose **D-18 two-active-key quiesce** (do **not** add the conflicting partial unique active-key index), Worker-first shared/exclusive advisory lock and **G1 Ed25519 proof of possession**. This is `APPROVED_DESIGN_DIRECTION_CONDITIONAL`, **not** migration, API change, merge or coding approval.

- **Exact proposed G1 wire from [TV3 #49 @ 62bded7](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) §6.6.5 item 9:** Manager generates 32 CSPRNG nonce bytes; unpadded base64url representation is 43 characters **on wire**. Signed message is the distinct domain `b"GPU-MARKETPLACE:SIGNER-PROOF:V1\n"` plus `worker_id`/ `key_id` as canonical lowercase UTF-8 UUIDs separated by LF, and **raw** nonce bytes. Response signature is Ed25519 64 raw bytes, 86-character unpadded base64url on wire. Auth boundary: `MANAGER_DISPATCH_TOKEN`. Request/response route, error mapping, nonce/replay policy, deadline and proof TTL still need exact L2 API contract/owner ACK. Do not reuse ADR-004 Signed Result signature domain.
- **Fingerprint exactly aligned between TV2 and TV3:** `public_key_fingerprint = SHA256(public_key_raw).hexdigest()`, where the public key is **32 raw bytes**, result exactly **64 lowercase hex characters**; no domain prefix/base64/key ID in the hash. Manager computes `hashlib.sha256(public_key_raw).hexdigest()`; PostgreSQL under Worker+Listing lock compares `encode(sha256(public_key_raw),'hex')`. TV2 `P2B-DRT-29` and TV3 `P2C-SIGN-08` cover stale K1 proof after K2 activation.
- **Manager readiness:** `SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at)` is **in-memory only**, invalidated on registration/activation/retirement, proof expiry, Manager restart and known signer lifecycle events. The DB UoW checks all four identity/time fields against the **sole active** key with Worker advisory→Listing locks; mismatch ⇒ `Blocked(SIGNER_NOT_READY)` and **zero allocation effects**. No HTTP under locks; no Simulator DB key/SQL access.
- **Residual signer restart within proof TTL:** `P2C-SIGN-07` explicitly permits a narrow stale-proof allocation window; absence of usable signer yields no valid receipt, resulting in `SYSTEM_FAULT` with no Worker penalty. TTL alone does not eliminate the risk. `P2C-SIGN-01/02` fail-closed assertions apply **after expiry/invalidation**; `P2C-SIGN-03..06` cover restart/replay/domain/lock I/O. All `NOT_RUN`.
- **Open owner gates:** D-03/S-10 privileged provisioning writer, key-compromise incident, exactly one active key **outside** rotation, K1 abort recovery, TTL/nonce retention, runtime/lock budgets and normative API/DB/Phase2C/2E reconciliation. No implementation authorization.
