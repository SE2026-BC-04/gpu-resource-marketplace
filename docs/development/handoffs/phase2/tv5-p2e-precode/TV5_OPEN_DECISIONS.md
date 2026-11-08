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
