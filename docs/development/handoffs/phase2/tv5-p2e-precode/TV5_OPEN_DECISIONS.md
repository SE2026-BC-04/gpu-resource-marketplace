# TV5 Phase 2E — Open Decision Register

All recommendations below are **PROPOSED — NOT OWNER APPROVED** unless the row explicitly cites an already approved design decision. Status is as of baseline `bee832eaf5463df20f6c6815174322871eb6685a`.

| ID | Current status | Options / recommendation for review | Trade-off and contract impact | Required ACK / owner | Blocks |
|---|---|---|---|---|---|
| P2E-CACHE-GAP-01 | NEEDS_OWNER_DECISION | Trusted persisted-dispatch binding with transport proof **or** explicit change-control qualification to retained-cache scope; no DB for Simulator | First adds wire/auth material; second narrows cross-restart 409 guarantee | Lead, TV1, TV3, TV5; TV2 confirms Outbox | DRT-04, P2E-08/12 |
| P2E-VERDICT-CONTRACT-01 | PENDING_ACK | Freeze immutable verdict bound to Inbox id + original hash + trusted identities; recommendation semantic proposal in Receipt Contract | Exact types and provenance affect TV1/TV2/TV3 interfaces | TV1/TV2/TV3/TV5 | P2E-13..15 |
| Cache cap/TTL/memory/concurrency | PENDING_PARAMS | Measure workload, bound entry/count/time and reject/backpressure at cap | Runtime availability vs memory; no invented constants | TV1 + TV5 | P2E-08/12 |
| Cache shutdown/in-flight eviction | PENDING_PARAMS | Drain bounded work or abandon and let Outbox redeliver; never evict in-flight unsafely | Shutdown latency vs recovery; stable logical identity | TV1 + TV5 | P2E-08/12 |
| Algorithm version across queued deploy | NEEDS_OWNER_DECISION | Persist/pin immutable version; future profile discriminator with contract change; or operational drain/fence | Existing dispatch has no algorithm_version; Signed V1/dispatch cannot be silently extended | Lead + TV1/TV2/TV3/TV5 | P2E-02/09/12; compatibility runtime |
| K1→K2 rotation | PENDING_ACK | Quiesce, activate K2, retain K1 public verification; define overlap/rollback | Availability and retained evidence | TV1/TV2/TV3/TV5 | P2E-10/12 |
| Compromised private-key incident | NEEDS_OWNER_DECISION | Quarantine/revoke policy and historical evidence disposition to be selected | Any retroactive invalidation risks immutable ADR-004 V1 evidence | Lead + TV1/TV2/TV3/TV5 | P2E-10, recovery |
| Internal auth + HTTP/body budgets | PENDING_PARAMS / ACK | Keep distinct >=256-bit directional tokens and ADR-005 timeouts; measure body/depth limits | No user JWT reuse; numerical ingress constraints need measured budgets | TV1/TV3/TV5 | P2E-07/11/18 |
| Inbox exact duplicate identity | PENDING_ACK | Exact raw bytes plus trusted bound context; hash only prefilter | Requires TV2 grant/unique-race path; no reserialization | TV2/TV3/TV5 | P2E-11/15 |
| Multi-candidate winner/non-winner cleanup | PENDING_ACK | Order `(received_at,inbox_id)`, invalid then continue; existing states only | Avoid new enum; bounded cleanup affects recovery | TV1/TV2/TV3/TV5 | P2E-15/16 |
| Deadline fallback | PENDING_ACK | Exhaust committed on-time candidates in bounded batches before fallback | DB clock and lock order; no Worker finished_at | TV1/TV2/TV3/TV5 | P2E-16 |
| Native DB grants / reference access | PENDING_ACK | Minimum API/Manager grants, no Simulator DB; exact SQL rights from TV2 | Physical grant policy is not implied by logical boundary | TV2 + TV3 + TV5; lead if contract changes | P2E-14/18 |
| Phase 1 accepted baseline | PHASE1_GATE: evidence present, cross-owner ACK pending | Keep PR #39 merged head and exact CI evidence; obtain E-IF-12 ACKs | CI is exact head only; no live PG claim in this review | TV1–TV5 | Phase 2 implementation gate |
| Phase 2E coding gate | NOT AUTHORIZED BY THIS PACKAGE | Lead issues separate task/sprint authorization after docs/ACKs | Conditional design approval is not coding approval | Group lead | All implementation tasks |
| Design branch policy sync | PENDING_LEAD_ACK | One Phase2E design docs branch/PR; after coding gate, one task/branch/PR | Handoff v1.1 says “one branch/PR TV5 work package”; process wording must be reconciled | Lead; rules owner if needed | Future PR workflow only |

Already approved design retained (not reopened here): `P2E-OPEN-01` Option A in-process bounded cache; `P2E-OPEN-02` typed-verdict boundary; `P2E-OPEN-03` contribution-ledger-first atomic UoW; `P2E-OPEN-04` GPU-005-B review order; GPU-005-B DEC-02..07 and conditional gate. Those approvals do not resolve the pending details in this register.

---

## Decision delta — 2026-11-13 (lead/affected owner decisions pending)

| ID | TV5 proposal / dependency | Authority |
|---|---|---|
| D-01 / E-C1 | Original callback bytes always preserved. Literal byte compare (B) **or** SHA-256 + DB CHECK cryptographic equivalence (C), never silently equate the two | Lead + TV2/TV3/TV5 |
| D-02 / E-C2 | Target-less ON CONFLICT DO NOTHING then fresh probe; known SAME=202 DUPLICATE, unknown-COMMIT reconciled SAME=202 STORED, unresolved ABSENT=503 | Lead change control + native-role SQL |
| D-05/D-13 | TV5 prefers P1 full immutable ten-key dispatch and caller UUIDs; P2 eight-key core remains fallback | TV1 + lead |
| D-06 | Version/owner-fenced Outbox CAS; terminal rows never reclaimed; repair separate | TV1 + lead |
| D-11/D-12/D-17 | First contributing reputation UPSERT; updated_at on real delta only; stored received_at exact-deadline admission | TV2/TV3/TV5 owner freeze + SQL tests |
| D-18/E-C3/D4 | Shared/exclusive Worker advisory lock first and two-active-key quiesce contradict partial unique active-key index proposal | Lead L2 global-lock-order/index decision, TV1/TV4 |
| G1 vs G2 (signer option) | **G1 preferred**: nonce under separate signer-proof domain, verified against active DB key outside UoW. **G2 has cold-Manager bootstrap contradiction** if unknown readiness blocks allocation | Lead L2 internal API change for G1; TV1/TV3/TV5 |
| SignerReadiness | TV2 #46 @ ba63466 proposes (worker_id,key_id,public_key_fingerprint,proof_expires_at) checked under Worker+Listing locks; stale K1 proof after K2 activation must fail | TV1/TV2/TV3/TV4/TV5, P2B-DRT-29 NOT_RUN |
| E-C4 / V-OUT | TV5 prefers pure TV3 verification outside locks and TV2 strict locked evidence/hash/signed-part extractor; V-IN fallback | TV1/lead change to accepted pseudo-code |
| P2E-VERDICT-CONTRACT-01 | Full immutable Verified/Rejected provenance, four definitive post-ingress reasons; parser drift PENDING | TV1/TV2/TV3/TV5 exact SHA ACK |
| D-03/S-10, D-16, incident, algorithm version | Authorized key provisioning, cold-restart contradictory dispatch and compromise/queued-version decisions unresolved | Lead + owners |
| G1 docs gate (not signer G1), G2 coding gate | Conditional design/review does not authorize code or merge | Lead and independent human L2 reviewers |

TV2 [PR #46 @ ba63466](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) and TV3 [PR #49 @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) remain unmerged. TV5's earlier reviews were ACK_WITH_ACTIONS, not an ACK of the subsequent SignerReadiness amendment. Every Phase 2 PostgreSQL/native-role/concurrency/crypto/E2E test remains NOT_RUN.
