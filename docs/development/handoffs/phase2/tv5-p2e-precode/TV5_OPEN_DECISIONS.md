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
| Inbox exact duplicate identity | APPROVED_DESIGN_DIRECTION_CONDITIONAL / OWNER_ACK_PENDING | D-01 Option C: original raw envelope preserved, DB CHECK binds SHA-256 to original bytes; restricted probe compares digest plus bound Job/Attempt context, cryptographic equivalence rather than literal raw-byte equality | Requires TV2 grant/unique-race path; no reserialization | TV2/TV3/TV5 | P2E-11/15 |
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
| D-01 / E-C1 | **Option C conditionally approved by lead @531805b**: original callback bytes retained, CHECK `envelope_sha256 = sha256(original_envelope_raw)`, probe hash + trusted binding, never mathematical byte equality. Reconcile normative sources. | TV2/TV3/TV5 exact SHA ACK + API/DB/2C/2E L2 reconciliation |
| D-02 / E-C2 | Target-less ON CONFLICT DO NOTHING then fresh probe; known SAME=202 DUPLICATE, unknown-COMMIT reconciled SAME=202 STORED, unresolved ABSENT=503 | Lead change control + native-role SQL |
| D-05/D-13 | **P1 conditionally approved**: exact full immutable ten-key Outbox, UUIDv4 IDs pre-INSERT, narrow INSERT grants and stable canonical HTTP bytes; P2 is NOT SELECTED. | TV1/TV2/TV5 contract ACK and native role tests |
| D-06 | Version/owner-fenced Outbox CAS; terminal rows never reclaimed; repair separate | TV1 + lead |
| D-11/D-12/D-17 | **D-12/D-17 approved design direction**: first contributing UPSERT inside same Finalization UoW; admission uses PostgreSQL `INSERT ... RETURNING id, received_at` with full rollback at >= deadline. D-11 update semantics retained. | TV2/TV3/TV5 exact contract ACK, native-role SQL/concurrency tests |
| D-18/E-C3/D4 | **Conditionally approved** Worker-first advisory shared/exclusive lock, durable two-key quiesce and explicit **no partial active-key UNIQUE index**; source supersession required. | TV1/TV2/TV3/TV4/TV5 exact SHA and human L2, concurrency tests |
| G1 vs G2 (signer option) | **G1 conditionally selected by lead**: authenticated fresh nonce proof under separate signer-proof domain, verified against active DB key outside UoW; **G2 not selected**. | Normative internal endpoint L2 API change; TV1/TV3/TV5 proof wire, nonce replay, TTL/restart policies |
| SignerReadiness | TV2 #46 @ ba63466 proposes (worker_id,key_id,public_key_fingerprint,proof_expires_at) checked under Worker+Listing locks; stale K1 proof after K2 activation must fail | TV1/TV2/TV3/TV4/TV5, P2B-DRT-29 NOT_RUN |
| E-C4 / V-OUT | **V-OUT conditionally approved by lead**: pure TV3 verification outside locks and TV2 locked original Inbox/hash/result_id/context/signed-part extractor; V-IN NOT SELECTED. | Normative TX-FINALIZE pseudocode L2 reconciliation and TV1/TV2/TV3/TV5 exact SHA |
| P2E-VERDICT-CONTRACT-01 | Full immutable Verified/Rejected provenance, four definitive post-ingress reasons; parser drift PENDING | TV1/TV2/TV3/TV5 exact SHA ACK |
| D-03/S-10, D-16, incident, algorithm version | Authorized key provisioning, cold-restart contradictory dispatch and compromise/queued-version decisions unresolved | Lead + owners |
| G1 docs gate (not signer G1), G2 coding gate | Conditional design/review does not authorize code or merge | Lead and independent human L2 reviewers |

TV2 [PR #46 @ ba63466](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) and TV3 [PR #49 @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) remain unmerged. TV5's earlier reviews were ACK_WITH_ACTIONS, not an ACK of the subsequent SignerReadiness amendment. Every Phase 2 PostgreSQL/native-role/concurrency/crypto/E2E test remains NOT_RUN.

---

## Current authoritative L2 decision register — 2026-11-18

**Overrides superseded proposal statuses above** (the 2026-11-13 section remains historical for audit). Source: [TV1 Conditional Architecture Decisions on PR #46 @ `531805b`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771), TV2 [#46 @ `a27526e479dbb2d915495e4bbe40327cc56427af`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46), TV3 [#49 @ `62bded701a7b1cd371307915c7ce746736fc9325`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49).

| Decision | Present status | Remaining obligation |
|---|---|---|
| D-01/E-C1 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL → Option C** SHA-256 + DB CHECK on stored original bytes; restricted hash+trusted context probe; byte equality **not mathematically promised** | API/DB/Phase 2B/2C/2E normative L2 reconciliation; native API-role tests |
| D-05/D-13 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL → P1** full ten-key immutable Outbox, pre-insert UUIDv4 IDs, exact raw retry bytes; P2 not selected | Column grants, SQL/canonicalization tests, owner ACK |
| D-06 | **CONDITIONALLY APPROVED** CAS owner+lease_version; ACKED/EXHAUSTED never reclaimed | Missing-receipt repair authorization/fencing TV1/TV2/TV5 **OPEN** |
| D-18/E-C3/D4 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL** two-active-key quiesce and Worker-first shared/exclusive advisory lock; **no partial unique active-key index** | Supersede approved conflicting DB/Phase1B/Phase2C text, TV4 integration, real-role races |
| Signer G1 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL** authenticated Ed25519 proof of possession, 32-byte nonce and distinct SIGNER-PROOF domain; G2 not selected | L2 internal API endpoint, replay/TTL/timeouts and restart-in-TTL risk, owner ACK |
| E-C4 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL → V-OUT** TV3 pure external verify + TV2 locked Inbox/extractor recheck; V-IN not selected | DB TX-FINALIZE normative pseudocode, producer/consumer exact-SHA freeze |
| D-12 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL** first contributing reputation UPSERT and only real SUCCESS/WORKER_FAULT changes | Concurrent two-Job Worker test, native grants, exact owner ACK |
| D-17 | **APPROVED_DESIGN_DIRECTION_CONDITIONAL** stored `received_at` from `INSERT ... RETURNING`; rollback equal/late | Real-role boundary/barrier tests |
| D-02/E-C2, D-03/S-10, D-16 | **PENDING** | Target-less conflict/source sync; provisioning writer; cold-restart contradictory dispatch |
| Cache bounds, key compromise, queued algorithm version, G1 proof TTL/budgets | **PENDING_PARAMS / NEEDS_OWNER_DECISION** | Lead and affected owners |

**Important:** `APPROVED_DESIGN_DIRECTION_CONDITIONAL` is **not** `MERGE_APPROVED`, `CODE_AUTHORIZED`, `TEST_PASS` or final owner ACK. All Phase 2 PostgreSQL/native-role/concurrency/crypto/E2E tests **NOT_RUN**. The signer option G1 and the team's G1 *docs gate* are different concepts.
