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
| 07 | TV3 API ingress → TV2 Inbox | scoped INSERT/read duplicate path, D-01 Option C hash+context equality, unique conflict, commit-unknown | S-API §13.2; S-2B §4; DRT-10/11/19 | TV2/TV3/TV5: exact duplicate context and DB privilege/function? | PENDING_ACK |
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
| 07 | Inbox retains original bytes/hash, result_id, trusted context/time and processing status; same ID cryptographic digest+trusted context duplicate under D-01 Option C, different digest/context conflict; raw evidence preserved | API scoped INSERT; Manager state-only update; Listing→Job admission locks and DB clock after Job lock | DRT-10/11/19; P2B DBTX/privilege tests |
| 08 | Typed verdict binds Inbox row/hash, result/job/attempt/worker/listing/key and classification or rejection; exact Python types unresolved | Verifier cannot mutate Job; finalizer must re-read evidence/state under DB locks | DRT-08/17; stale verdict and mismatched context tests |
| 09 | Candidates ordered `(received_at,inbox_id)`; reject invalid then continue; existing Inbox state enum only; no new receipt on retry | TV2 owns bounded candidate reads/updates; finalizer serializes with Listing→Job locks | DRT-12/13/16; invalid-first/valid-second and later-batch tests |
| 10 | One durable finalization outcome; replay/unknown commit reconciles, not blind retry | One TV2 UoW for signed result, terminal Job, allocation release, `allocated_gpu_count`, Inbox, contribution and aggregate; no HTTP under locks | DRT-17/18; independent connection checks all affected rows |
| 11 | PAUSED blocks new allocations but not repair of same RUNNING attempt; no new Attempt/deadline | TV2 Listing-first allocation/release transactions; TV4 owns FIFO/admission policy | DRT-03/05 and Phase2D allocation/PAUSED barriers |
| 12 | Exact reviewed Phase 1 contract/source SHA, migration head and test evidence | ACK record must name both producer and consumer and their reviewed document SHA; no inferred ACK from CI | DRT-07/19 plus owner signature/evidence; current status remains pending |

## Change-control for ACK

An ACK must come from the named owner and cite this matrix/document version or SHA, exact DTO/data shape, failure/retry/transaction semantics, and test oracle. A PR being open/Ready, green CI, a Codex review, or this report is not an owner ACK. If a proposal changes an accepted API/ADR/database or Phase 2 design, use formal inter-phase change control before implementation.

---

## E-IF live cross-PR status — 2026-11-13 (no automatic owner ACK)

Initial table above is a baseline snapshot; use these **newer unmerged producer SHAs** when requesting re-review: TV2 [#46 @ ba6346655cc7c7f02619a657d35bd8c5a0ad17b7](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46); TV3 [#49 @ 9b337f5d9b2ccea60dea790d76a2b9420cf94605](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49); TV4 [#48 @ b8be72527eb1f9a7f485fd4260cbe86e5db40ab9](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/48). TV5 [#46 review @ ed19a51](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#pullrequestreview-5887153391) and [#49 review @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49#pullrequestreview-5887054059) are **ACK_WITH_ACTIONS**, and do not approve subsequent TV2 changes or this new PR #50 HEAD.

| E-IF | Updated design direction | Status / remaining decision |
|---|---|---|
| 01 | **TV1 conditionally selected P1**, full immutable ten-key Outbox, canonical wire; P2 not selected | TV1/TV2/TV5 exact-SHA ACK; native grants and PG tests NOT_RUN |
| 02–03 | Volatile cache and cross-restart altered Attempt are separate from signing proof; cap/TTL/shutdown measured | P2E-CACHE-GAP-01 NEEDS_OWNER_DECISION; numeric limits PENDING |
| 04 | **TV1 conditionally selected D-18/E-C3 and G1**, Worker-first advisory/two-key fence with internal SignerReadiness checked under locks | TV1/TV2/TV3/TV4/TV5 exact-SHA ACK; normative API/DB source correction, provisioning, TTL tests |
| 05 | ADR-004 nine-field mock vs eleven-field Signed V1 and independent canonical/Ed25519 | TV3/TV5 fixture and owner ACK; NOT_RUN |
| 06 | Callback 202 STORED/DUPLICATE, 401, 404 context, 409 collision/unacceptable, 422 invalid, 503 unresolved; 16,384 B/depth 4 proposed | TV1 budget & TV3/TV5 ACK, NOT_RUN |
| 07 | **TV1 D-01 Option C approved conditionally**, retain original bytes, SHA-256 CHECK and digest + trusted Job/Attempt probe; target-less conflict D-02 still proposed | D-02/E-C2 exact source/owner approval, real API-role SQL NOT_RUN |
| 08 | **TV1 conditionally selected E-C4 V-OUT**, full immutable verified/rejected DTO, four definitive codes, locked extractor | Normative DB pseudocode and TV1/TV2/TV3/TV5 exact-SHA freeze; tests NOT_RUN |
| 09 | PrecedingPending, valid-A/valid-B deterministic earliest winner, no premature fallback | TV1/TV2/TV3/TV5 B-IF-05/07 ACK and tests |
| 10 | One TV2 Finalization UoW; **TV1 conditionally approved D-12 first-contributing UPSERT** | Owner ACK, physical grants, two-Job concurrency and unknown-COMMIT tests NOT_RUN |
| 11 | TV4 scheduler must supply fresh SignerReadiness for eligible Worker and handle Blocked(SIGNER_NOT_READY), without bypassing FIFO | TV4/TV1 integration ACK and P2B-DRT-29 |
| 12 | Main bee832e Phase 1 accepted source baseline; #39/#44 merged; TV3 earlier scoped PR #50 feedback exists | New exact #50 SHA reviewer/independent human L2 ACK + lead docs/coding gates |

TV3 [scoped comment on PR #50](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/50) addressed thin rejection DTO, conditional D-01 language, 404/503 mapping and retire-vs-delete at this **proposal** level; re-review is needed on the new SHA. Do not mark approvals or test PASS based on a previous SHA or green foundation CI.

## Current cross-owner decision/ACK ledger — 2026-11-18

**This is the current status; the earlier baseline table and 2026-11-13 notes are historical snapshots.** Source authority: [TV1 conditional L2 architecture decision on PR #46 @ `531805b`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771); producer heads [TV2 PR #46 @ `a27526e479dbb2d915495e4bbe40327cc56427af`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) and [TV3 PR #49 @ `62bded701a7b1cd371307915c7ce746736fc9325`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49).

| E-IF | Lead architecture direction | Still pending on the new TV5 SHA |
|---|---|---|
| E-IF-01 | D-05/D-13 P1 ten-key immutable Outbox **selected** | TV1/TV2/TV5 exact producer/consumer ACK, canonical raw bytes and restricted PG role tests |
| E-IF-02/03 | **NOT DECIDED:** contradictory same-attempt dispatch after Simulator cold restart; cache limits | D-16/P2E-CACHE-GAP-01 and runtime bounds/TTL/eviction |
| E-IF-04 | D-18 two active rows + Worker-first advisory **selected**; signer **G1 selected**, G2 not | API internal proof endpoint L2 text; D-03/S-10, signer TTL/nonce/restart/recovery and TV1/TV2/TV3/TV4/TV5 exact ACK |
| E-IF-05 | ADR-004 strict Signed V1 unchanged | TV3↔TV5 cross-runtime vectors |
| E-IF-06/07 | D-01 **Option C** and D-17 stored INSERT RETURNING **selected** | D-02/E-C2 source/probe contract, TV1 16,384-byte/depth-4 resource ACK, native-role SQL |
| E-IF-08/09 | E-C4 **V-OUT selected**, four-code verifier, locked evidence and earliest valid candidate | Normative DB TX-FINALIZE pseudocode, exact-SHA owner ACK and race tests |
| E-IF-10 | D-12 **first contributing UPSERT selected** | TV1/TV2/TV5 UoW/grant ACK, real 2-Job/Worker PG concurrency tests |
| E-IF-11 | PAUSED same-key Submit replay / already-RUNNING dispatch repair | TV4 FIFO/Blocked compatibility ACK; D-19 missing-receipt repair port remains proposed |
| E-IF-12 | Phase1 main baseline accepted; PRs #46/#49/#50 still open docs | **Two independent human L2 reviews** at final SHA, G1 docs gate, separate merge/coding authorization |

**TV2 and TV3 reviews on PR #50 @ `c8c241c` were `ACK_WITH_ACTIONS`**, not independent human approval of the final head. ACKs must cite new SHA, field/byte contracts, failure/retry/transaction semantics and test oracle. All Phase 2 native-role PG, signing, concurrent locks and E2E tests remain `NOT_RUN` despite foundation CI.

## Current exact-HEAD producer/consumer traceability — 2026-11-19

**Reviewed consumer baseline (before this edit):** PR #50 `52c23eabd6948ad7db13d3d39d65ed920d996c9a`. This is the consumer SHA reviewed for this reconciliation; the final documentation commit is reported separately and is not implied to have been reviewed. PR #50 is OPEN/Draft, base `main`, not merged. Current fetched producer tips: TV2 PR #46 `c4956777512efc260fbf180898af2c041d0a16d6`; TV3 PR #49 `e73fb107d15296a6f317d9bed25ce76fe0657ac2`; TV4 PR #48 `a9888ee0b4b70940497c0a6047a5cf414fbcd7bc`. All three are unmerged proposals. Earlier matrices and SHA references above remain historical snapshots; in particular #48 advanced from `813aa3ed67f5da7f3343f2c553ffbf24025eacaf` and must not be used as its current source.

The exact producer documents are identified by path **at the full PR HEAD listed above**. Compatibility describes this documentation review only; it is not owner ACK, merge approval, or implementation evidence. No exact-SHA ACK for the pairs below is provided.

| E-IF | Producer → consumer / owners | Required contract and source trace at current producer HEAD | Compatibility / blocker / decision | Required ACK owners | Planned verification (all Phase 2 runtime tests `NOT_RUN`) |
|---|---|---|---|---|---|
| 01 | TV2/TV1 → TV5; TV1, TV2, TV5 | TV2 #46 `P2B_UOW_INTERFACES.md` B-IF-06 (allocation/Outbox); TV4 #48 `Phase_2D_v0.9.md` D-IF-01/02; TV3 #49 handoff C-IF-01. Immutable 10-key dispatch; no oracle fields; HTTP outside locks. | Compatible with actions. Exact raw-byte/canonicalization and role-grant evidence pending; no ACK. | TV1, TV2, TV5 | P2E-DRT-01..03; P2B-DRT-08/18; API-INT-01..04 |
| 02 | TV1/TV3 → TV5; TV1, TV3, TV5, lead | TV3 #49 handoff C-IF-01; TV4 #48 D-IF-05; TV2 #46 B-IF-06R (proposal only); Phase 2E D-16. Same-attempt altered dispatch after cold restart. | **Blocked by D-16 / P2E-CACHE-GAP-01.** Lead preference for Option B is not approval; no cross-restart guarantee may be claimed. | Lead, TV1, TV2, TV3, TV5 | P2E-DRT-04 remains `BLOCKED`; test oracle awaits L2 decision/change control |
| 03 | TV5 cache → TV1 runtime; TV1, TV5 | TV3 #49 C-IF-01; TV4 #48 D-IF-04; TV2 #46 B-IF-06 for bounded scheduling dependencies. Cache cap/TTL/in-flight/eviction/shutdown. | Compatible with actions; resource and lifecycle values remain `PENDING_PARAMS`. | TV1, TV5 | P2E-DRT-01..04 plus capacity, shutdown and concurrent-entry tests; `NOT_RUN` |
| 04 | TV3/TV2/TV4 → TV5 signer and TV1 Manager; TV1–TV5 | TV3 #49 `e73fb107d15296a6f317d9bed25ce76fe0657ac2` C-IF-07/08, C-FINAL-01/03 and Phase_2C §7.2; TV2 #46 B-IF-06; TV4 #48 D-IF-07. G1 proof uses fresh single-use Manager nonce outside UoW, stateless Simulator proof endpoint, internal `SignerReadiness`, Worker advisory → Listing → Job recheck. | Conditional design direction is compatible; L2 endpoint/API source reconciliation, provisioning, exact TTL/timeout/concurrency and Manager nonce/cache/restart parameters and exact-SHA ACKs remain open. Simulator has no replay cache. | TV1, TV2, TV3, TV4, TV5, lead | P2C-SIGN-01/02/07/08/09/10, P2C-KEY-10, P2C-DRT-20/21/24; P2B-DRT-24..29; P2E-GATE-01, all `NOT_RUN` |
| 05 | TV5 signer → TV3 verifier; TV3, TV5 | TV3 #49 C-IF-05/06 and Phase_2C §6.6; ADR-004 Signed Result V1. Exact signed fields/JCS/Ed25519; no wire-format change. | Compatible with actions; exact dual-runtime vectors and owner ACK remain pending. Signed Result V1 unchanged. | TV3, TV5 | P2E-DRT-07/08; TV3 V1 vectors; cross-runtime byte fixtures, `NOT_RUN` |
| 06 | TV5 callback → TV3 API / TV1 wiring; TV1, TV3, TV5 | TV3 #49 C-IF-01/02; TV2 #46 B-IF-02/04. Directional Bearer, raw bytes, strict ingress, bounded responses and retry semantics. | Compatible with actions; route budgets, resource limits and wiring ACK pending. | TV1, TV3, TV5 | P2E-DRT-09..11; API-INT-05..11, `NOT_RUN` |
| 07 | TV3 ingress → TV2 Inbox; TV2, TV3, TV5 | TV2 #46 B-IF-02/03/04; TV3 #49 C-IF-02/03/04. Retained raw bytes/hash/context, trusted `received_at`, duplicate/collision and unknown-COMMIT boundaries. | Compatible with conditional D-01 Option C; D-02/E-C2 source alignment, physical grants and native-role verification remain pending. | TV2, TV3, TV5; lead for any source change | P2E-DRT-10/11/19; P2B-DRT-17/19..23; `NOT_RUN` |
| 08 | TV3 verifier → TV1 Manager / TV2 UoW / TV5 policy; TV1, TV2, TV3, TV5 | TV3 #49 C-IF-06/10, C-FINAL-03, §6.6.1–6.6.4; TV2 #46 B-IF-05/07. V-OUT typed verdict, strict closed rejection enum, locked evidence recheck. | Compatible with actions under conditional V-OUT. Exact-SHA ACK and normative TX-FINALIZE reconciliation pending; admitted-byte parser drift is fail-closed invariant error. | TV1, TV2, TV3, TV5 | P2E-DRT-08/17; P2B-DRT-20..23; stale/mismatched verdict and extractor tests, `NOT_RUN` |
| 09 | TV2 Inbox → TV1 Manager / TV3 verifier / TV5 policy; TV1, TV2, TV3, TV5 | TV2 #46 B-IF-05/07 in `P2B_UOW_INTERFACES.md`; P2B `P2B_TEST_MATRIX.md` P2B-DRT-06/-20/-21/-23/-37; TV3 #49 C-IF-10. Exact batch/cursor/restart and winner semantics are specified below and in the Receipt Contract addendum. | Compatible with actions; no durable cursor, premature fallback or duplicate effects. Owner ACK and all PostgreSQL/runtime evidence pending. | TV1, TV2, TV3, TV5 | P2E-DRT-12/13/14/16/21..28; P2B-DRT-06/-20/-21/-23/-37; P2C-DRT-20/21/24; `NOT_RUN` |
| 10 | TV5 policy / TV1 Manager → TV2 TX-FINALIZE; TV1, TV2, TV5, TV4 | TV2 #46 B-IF-07; TV4 #48 D-IF-08; TV3 #49 C-IF-06/10. One UoW for evidence, terminal Job, release/counter, Inbox, contribution/aggregate; unknown-COMMIT reconciliation. | Compatible with actions under conditional D-12/D-17/V-OUT; exact SQL/grants/ACK, two-Job concurrency and unknown-COMMIT tests pending. | TV1, TV2, TV4, TV5 | P2E-DRT-17/18; P2B-DRT-17/19..23; independent-connection checks, `NOT_RUN` |
| 11 | TV2 TX-ALLOCATE / TV4 Listing → TV5 policy and TV1; TV1, TV2, TV4, TV5 | TV4 #48 D-IF-05/07; TV2 #46 B-IF-06/06R; Phase 2E E-IF-11. PAUSED blocks new allocation, not same-key replay or already-RUNNING repair. | Compatible with actions. D-19/B-IF-06R remains `PROPOSED_FOR_ACK`; no repair authorization or exact-SHA ACK. Signer readiness is E-IF-04/D-IF-07, not this interface. | TV1, TV2, TV4, TV5; lead for D-19 | P2E-DRT-03/05; P2D-DRT-12/15; D-19 both-order races, `NOT_RUN` |
| 12 | All phase owners → TV5 / lead; TV1–TV5 | TV4 #48 D-IF-09; TV2 #46 evidence traceability; TV3 #49 G1 / C-IF-01..11; consumer PR #50 design/test gates. | **Blocked for gate closure.** Exact baseline and source tips are recorded, but independent exact-SHA ACKs, two human L2 reviews and lead docs-gate closure are absent. No coding authorization implied. | TV1–TV5, lead, independent human L2 reviewers | P2E-DRT-07/19 and applicable tests on exact reviewed SHA; runtime tests `NOT_RUN` |

For every row above, `ACK status = NOT PROVIDED` for the reviewed consumer baseline `52c23eabd6948ad7db13d3d39d65ed920d996c9a` paired with the listed current producer tips, unless a future owner supplies new explicit evidence. The final commit for this revision is deliberately not prefilled as reviewed. Refresh all remote heads before requesting ACKs.

### E-IF-11 identifier reconciliation

`E-IF-11` means only **PAUSED same-key Submit replay / already-RUNNING dispatch repair**, as defined by Phase 2E and handoff §7. Signer readiness is cross-referenced under **E-IF-04** and Phase 2D **D-IF-07**. No signer-readiness ACK closes E-IF-11, and no E-IF-11 ACK closes D-19. D-19 / B-IF-06R remains `PROPOSED_FOR_ACK`; the `E-IF-11` producer/consumer ACK and PostgreSQL tests remain pending.

| E-IF | Corrected consumer meaning | Producer → consumer | Current status |
|---|---|---|---|
| E-IF-04 | Worker key lifecycle, signer G1 readiness and the D-18/D-IF-07 dependency | TV2 + TV3 + TV4 → TV1/TV5 | Conditional design direction exists; exact-HEAD ACK and runtime tests pending |
| E-IF-11 | PAUSED same-key Submit replay; already-RUNNING Attempt/event/payload retry; proposed separate ACKED missing-receipt repair | TV2 + TV4 → TV1/TV5 | `PENDING_ACK / TEST`; D-19 remains `PROPOSED_FOR_ACK`, no repair authorization |
