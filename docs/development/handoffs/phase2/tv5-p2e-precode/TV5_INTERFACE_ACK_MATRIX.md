# TV5 Interface Review Matrix — E-IF-01..12

**Snapshot:** main `bee832eaf5463df20f6c6815174322871eb6685a`; all rows below are review status, not ACKs. `ACK_COMPATIBLE` and `ACK_WITH_ACTIONS` require actual owner evidence; none is manufactured here.

## Source manifest

SHA-256 values identify exact files at baseline `bee832e...`; pair with the immutable baseline commit for ACK traceability.

| Ref | Source file / version | SHA-256 |
|---|---|---|
| S-API | `docs/design/api-contract.md` | `cfafdaa10959415abe62c4187ef33bb6b0fffff3a88642c20cfca94bf8f6050f` |
| S-DB | `docs/design/database-design.md` | `4cc45cba16c8c1c02e5c3c86dbaf8eac0fed420a0ee74c1053bd00e60a0cccfb` |
| S-MOD / S-TEST | `module-design.md` / `test-design.md` | `05931e1e7369fa454616ca29fb4ad3a8499c5098d3c28f505ef910424927a87b` / `d72fd06a8a3be08ea57daf67ce1acee8b79990efc5eb77e3e9080913afe3e042` |
| S-ADR2..5 | ADR-002 / ADR-003 / ADR-004 / ADR-005 | `4d35f649b69cd1a6e7d11f00f1cae3f8c6a3d1a15e09dfde7bd03f8f4b972a89` / `576c5966337f308cc2268e7ca00b29bcbf48b2e8e1ea033a74e9de2b017511dc` / `8753d5451df5df1364eab09ba882f1f32a00f4817ede1b197611cdb04acc8ca8` / `a67427b8fe07c78ce91436ca094974223f7a3afee929a578074f1a0d0f081aa9` |
| S-2A..2E | Phase_2A_v0.9 / 2B_v1.3 / 2C_v0.9 / 2D_v0.9 / 2E_v1.8 | `2168e036203c1370b56c2ffe7e5633d398266f72423a370254df33273f7162a2` / `27c59f3e2eddc2584fc9c904aacfc7d45aa323b8745ec77eb5775d59b1af3371` / `d92901a412aaaaa3a2e601781b3991019de9eeee1f45b891564a64d3fbd33902` / `fdb7f79a1b89b9ed911fddce67da1763ea88a5417ab946a3121f8701f8758c60` / `90af557a46a0f7bcb663eb9d17de3a2db866c4c0b2f1e5006a9160eed2d6609f` |
| S-H1..H5 | Phase2 handoffs TV1..TV5 v1.2/v1.1 | `9909697334dd17c2e151eafc0cf6b474a92928c1605faeb8429ad5ca79d4b40c` / `b7eed00af7530cc515d2eb8e8d4be4ff63074dba1b969d7d77d0d81cc44494a9` / `53ffadf57054481d1b709d79ac7f662113d75eba66643c13896cadf122f2a236` / `6e82d0a84c672293d74bb0e9ac2c6d57102fe84cfc3f440c38e3e71dd1740503` / `b04a206357f9d3a5cfa1afbd441742b407a8656972a82cf709a8941b66019a0b` |

S-2E is the baseline version before its status addendum in this PR.

| ID | Producer → consumer / owner | Contract and boundary | Source / tests | Decision owner; open question | Status |
|---|---|---|---|---|---|
| 01 | TV2 Outbox + TV1 dispatch → TV5 Simulator | Immutable ten-key dispatch, stable event/attempt, exact `simulation_input`, no oracle; HTTP outside DB locks | S-API §13.1; S-2E DR-E2; DRT-01..03 | TV1/TV2/TV5: payload canonicalization/fingerprint and source-of-truth bytes? | PENDING_ACK |
| 02 | TV1/TV3 dispatch auth → TV5 Simulator | Same-attempt altered request after cold restart; no Simulator DB | S-API §13.1; S-2E `P2E-CACHE-GAP-01`; DRT-04 | Lead + TV1/TV3/TV5: choose enforceable binding or contract qualification? | NEEDS_OWNER_DECISION |
| 03 | TV5 cache → TV1 runtime | bounds, TTL, in-flight handling, eviction, shutdown | S-2E §2.3 / DR-E2; DRT-01..04 | TV1/TV5: measured cap/time/memory and shutdown policy? | PENDING_PARAMS |
| 04 | TV3 key policy + TV2 registry → TV5 signer / TV1 runtime | Worker/key_id binding, injection/recovery, K1/K2, incident response | S-ADR4; S-2E DR-E3; DRT-05/06/08 | TV1/TV2/TV3/TV5: registry lifecycle and key-compromise response? | PENDING_ACK / NEEDS_OWNER_DECISION |
| 05 | TV5 signer → TV3 verifier | Nine-field mock vs exact eleven-field Signed V1; prefix/JCS/Ed25519/V1–V4 | S-ADR4; S-API §13.2; DRT-07/08 | TV3/TV5: exact dual-runtime fixtures and signer/verifier API ACK? | PENDING_ACK |
| 06 | TV5 callback client → TV3 API / TV1 wiring | callback Bearer, raw bytes, body limits, 202/401/409/422/5xx and retries | S-API §§13.2–13.3; S-ADR5; DRT-09..11 | TV1/TV3/TV5: concrete size/depth/time budgets and route wiring? | PENDING_PARAMS / ACK |
| 07 | TV3 API ingress → TV2 Inbox | scoped INSERT/read duplicate path, raw-byte equality, unique conflict, commit-unknown | S-API §13.2; S-2B §4; DRT-10/11/19 | TV2/TV3/TV5: exact duplicate context and DB privilege/function? | PENDING_ACK |
| 08 | TV3 verifier → TV1/TV5 Manager finalizer | Trusted typed verdict bound to Inbox ID/raw hash/IDs/key; locked recheck | S-2E §2.4 / DR-E5; DRT-08/17 | TV1/TV2/TV3/TV5: exact fields/types, provenance and stale handling? | PENDING_ACK (`P2E-VERDICT-CONTRACT-01`) |
| 09 | TV2 Inbox → TV1 Manager/TV5 policy | Multiple result IDs, `(received_at,inbox_id)`, invalid-first, non-winner cleanup | S-API §13.2; S-2E DR-E5; DRT-12/13/16 | TV1/TV2/TV3/TV5: terminal cleanup using existing states only? | PENDING_ACK |
| 10 | TV5 policy + TV1 Manager → TV2 TX-FINALIZE | one UoW: signed result, terminal Job, release, Listing decrement, Inbox, contribution/aggregate | S-DB §11; S-2E §2.5 / DR-E7; DRT-17/18 | TV1/TV2/TV5: exact SQL/UoW ports, aggregate row ownership, commit reconciliation? | PENDING_ACK |
| 11 | TV4 Listing/TV2 TX-ALLOCATE → TV5 policy | PAUSED forbids new allocation, permits repair of already RUNNING Attempt; Listing counter is `allocated_gpu_count` | S-2D; S-API §§8/13; DRT-03/05 | TV2/TV4/TV5: same-key PAUSED replay distinct from RUNNING repair? | PENDING_ACK / TEST |
| 12 | All phase owners → TV5 / lead | Phase 1 accepted SHA, CI/review and cross-phase compatibility | PR #39 merged head `3482...`, exact CI run 42385995533; S-2A..2E; DRT-07/19 | TV1–TV5: ACK this exact baseline and outstanding compatibility? | PENDING_PHASE1_GATE |

## Contract detail for owner review

| ID | Required DTO/data and failure/retry behavior | Transaction boundary and security | Acceptance oracle |
|---|---|---|---|
| 01 | Ten exact dispatch fields listed in `TV5_WIRE_AND_REFERENCE.md`; same attempt/event/payload on Outbox retry; accepted `202` is not terminal | Outbox claim/ACK commits separately; HTTP outside DB locks; Manager Bearer only; no oracle/private key/DB connection in Simulator | DRT-01..03; API-INT-01..04 |
| 02 | Immutable fingerprint tied to attempt; retained altered body → 409; cold-start behavior undecided | No DB access for Simulator; distinct scoped Bearer; no public truth sent | DRT-04 expected 409 only if selected policy makes it enforceable |
| 03 | Cache states IN_FLIGHT/FINISHED; cap/full/TTL/eviction/shutdown semantics need concrete parameters | Process memory only; no durable state or DB transaction in Simulator | DRT-01..04 plus capacity, shutdown and concurrent-entry stress |
| 04 | `(worker_id,key_id)` binding; missing/wrong key fails closed; historical K1 verifies after planned K2 rotation; incident response open | Private Ed25519 material only in Simulator/Worker secret boundary; public key registry in TV2 DB | DRT-05/06/08; key custody negative tests |
| 05 | Nine-field mock is distinct from exact eleven-field Signed Result V1; strict JCS, prefix and Ed25519 | Signing is local to trusted simulator; TV3 verification binds trusted registry/context; no private material leaves signer | DRT-07/08; byte-exact cross-runtime fixtures |
| 06 | Callback resends original raw envelope/result_id; 202 STORED/DUPLICATE; 409 changed-byte collision; bounded retry per ADR-005 | API token check before Inbox lookup/write; DB commits original bytes before 202 | DRT-09..11; API-INT-05..11 |
| 07 | Inbox retains original bytes/hash, result_id, trusted context/time and processing status; same ID exact bytes+context duplicate, changed bytes/context conflict | API scoped INSERT; Manager state-only update; Listing→Job admission locks and DB clock after Job lock | DRT-10/11/19; P2B DBTX/privilege tests |
| 08 | Typed verdict binds Inbox row/hash, result/job/attempt/worker/listing/key and classification or rejection; exact Python types unresolved | Verifier cannot mutate Job; finalizer must re-read evidence/state under DB locks | DRT-08/17; stale verdict and mismatched context tests |
| 09 | Candidates ordered `(received_at,inbox_id)`; reject invalid then continue; existing Inbox state enum only; no new receipt on retry | TV2 owns bounded candidate reads/updates; finalizer serializes with Listing→Job locks | DRT-12/13/16; invalid-first/valid-second and later-batch tests |
| 10 | One durable finalization outcome; replay/unknown commit reconciles, not blind retry | One TV2 UoW for signed result, terminal Job, allocation release, `allocated_gpu_count`, Inbox, contribution and aggregate; no HTTP under locks | DRT-17/18; independent connection checks all affected rows |
| 11 | PAUSED blocks new allocations but not repair of same RUNNING attempt; no new Attempt/deadline | TV2 Listing-first allocation/release transactions; TV4 owns FIFO/admission policy | DRT-03/05 and Phase2D allocation/PAUSED barriers |
| 12 | Exact reviewed Phase 1 contract/source SHA, migration head and test evidence | ACK record must name both producer and consumer and their reviewed document SHA; no inferred ACK from CI | DRT-07/19 plus owner signature/evidence; current status remains pending |

## Change-control for ACK

An ACK must come from the named owner and cite this matrix/document version or SHA, exact DTO/data shape, failure/retry/transaction semantics, and test oracle. A PR being open/Ready, green CI, a Codex review, or this report is not an owner ACK. If a proposal changes an accepted API/ADR/database or Phase 2 design, use formal inter-phase change control before implementation.
