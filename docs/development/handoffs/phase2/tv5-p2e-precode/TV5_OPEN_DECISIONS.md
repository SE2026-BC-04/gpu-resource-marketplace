# TV5 Phase 2E — Open Decision Register


> **Current D-16 decision reconciliation (2026-11-28):** `P2E-CACHE-GAP-01 / D-16 = APPROVED_DESIGN — Option B` via merged PR #53 / `DEC-P2-L2-SOURCE-SYNC-01` and API Contract §13.1 + `API-INT-04`. **E-IF-02 = PENDING_ACK_AND_TESTS** (not `NEEDS_OWNER_DECISION`): conflict `409` only during retained in-process Attempt fingerprint; after eviction/cold restart no historical `409` guarantee. Manager retransmits only the original authenticated immutable ten-key Outbox payload; a reexecution may create a new signed `result_id`, while callback retries of an existing receipt preserve its original bytes and ID. PostgreSQL retains exactly-once business effect authority. Test `P2E-DRT-04` must distinguish live-retained `409` from lost-cache no guarantee and remain **NOT_RUN** at runtime. **E-IF-01 PENDING_ACK, E-IF-03 PENDING_PARAMS, D-19 repair NOT_AUTHORIZED.** The dated decision table and preservation note below are historical snapshots and must not be construed as superseding this approved source.


All recommendations below are **PROPOSED — NOT OWNER APPROVED** unless the row explicitly cites an already approved design decision. Status is as of baseline `bee832eaf5463df20f6c6815174322871eb6685a`.

| ID | Current status | Options / recommendation for review | Trade-off and contract impact | Required ACK / owner | Blocks |
|---|---|---|---|---|---|
| P2E-CACHE-GAP-01 / D-16 | NEEDS_OWNER_DECISION | Option A: trusted durable-dispatch verification via an authorized component, without Simulator DB. Option B: formally qualify `409 EXECUTION_CONFLICT` to retained-cache scope; **lead prefers B for MVP, but has not approved an API change**. | A adds a reviewed transport/auth proof; B narrows the cross-restart guarantee and relies on trusted Manager + immutable Outbox. Neither is authorized for implementation. | Lead, TV1, TV2, TV3, TV5 | DRT-04 remains BLOCKED until an L2 decision and required source reconciliation |
| P2E-VERDICT-CONTRACT-01 | PENDING_ACK | Freeze immutable verdict bound to Inbox id + original hash + trusted identities; recommendation semantic proposal in Receipt Contract | Exact types and provenance affect TV1/TV2/TV3 interfaces | TV1/TV2/TV3/TV5 | P2E-13..15 |
| Cache cap/TTL/memory/concurrency | PENDING_PARAMS | Measure workload, bound entry/count/time and reject/backpressure at cap | Runtime availability vs memory; no invented constants | TV1 + TV5 | P2E-08/12 |
| Cache shutdown/in-flight eviction | PENDING_PARAMS | Drain bounded work or abandon and let Outbox redeliver; never evict in-flight unsafely | Shutdown latency vs recovery; stable logical identity | TV1 + TV5 | P2E-08/12 |
| Algorithm-version compatibility | **APPROVED_DESIGN:** `demo-v1` maps immutably to `demo-v1-public1`; TX-SUBMIT persists that version. Future algorithm/profile V2 is a separate proposal, not an unresolved MVP decision. | No new dispatch or Signed Result V1 field. Release preflight must show V1–V4 compatibility, queued/running retry behavior, rollback compatibility and historical evidence verification before enabling the release. | Compatibility cost constrains deployments; violating it is a release blocker, not permission to rewrite old references or reinterpret old Jobs. | TV1/TV2/TV3/TV5 exact-HEAD ACK for implementation plan; lead for any contract/version change | P2E-VERSION release preflight and deployment gate |
| K1→K2 rotation | PENDING_ACK | Quiesce, activate K2, retain K1 public verification; define overlap/rollback | Availability and retained evidence | TV1/TV2/TV3/TV5 | P2E-10/12 |
| Compromised private-key incident | NEEDS_OWNER_DECISION | Quarantine/revoke policy and historical evidence disposition to be selected | Any retroactive invalidation risks immutable ADR-004 V1 evidence | Lead + TV1/TV2/TV3/TV5 | P2E-10, recovery |
| Internal auth + HTTP/body budgets | PENDING_PARAMS / ACK | Keep distinct >=256-bit directional tokens and ADR-005 timeouts; measure body/depth limits | No user JWT reuse; numerical ingress constraints need measured budgets | TV1/TV3/TV5 | P2E-07/11/18 |
| Inbox exact duplicate identity | APPROVED_DESIGN_DIRECTION_CONDITIONAL / OWNER_ACK_PENDING | D-01 Option C: original raw envelope preserved, DB CHECK binds SHA-256 to original bytes; restricted probe compares digest plus bound Job/Attempt context, cryptographic equivalence rather than literal raw-byte equality | Requires TV2 grant/unique-race path; no reserialization | TV2/TV3/TV5 | P2E-11/15 |
| Multi-candidate winner/non-winner cleanup | PENDING_ACK | Order `(received_at,inbox_id)`, invalid then continue; existing states only | Avoid new enum; bounded cleanup affects recovery | TV1/TV2/TV3/TV5 | P2E-15/16 |
| Deadline fallback | PENDING_ACK | Exhaust committed on-time candidates in bounded batches before fallback | DB clock and lock order; no Worker finished_at | TV1/TV2/TV3/TV5 | P2E-16 |
| Protected oracle access: DEC-07 vs TV2 D-14 / TV3 Phase 2C | **SOURCE CONFLICT — L2 SUPERSESSION REQUIRED** | DEC-07 previously approved a logical design allowing Manager reads of limited reference columns. Current TV2 D-14 and TV3 Phase 2C proposal say Phase 2 Manager/Finalizer has no SELECT; Simulator has no DB credentials; Phase 3 Dispute Mock requires separate authorization. Proposed erratum: supersede DEC-07's Manager-read allowance for Phase 2 only, preserving protected storage and no Simulator access. | Removes Phase 2 oracle read capability; requires explicit L2 source reconciliation. Signature verification/finalization proves neither oracle truth nor real execution. No GRANT/migration is implied. | Lead, TV2, TV3, TV5; Phase 3 owner before any dispute path | L2 decision + change-controlled API/DB/2E source updates; physical grants remain TV2 implementation scope |
| Phase 1 accepted baseline | PHASE1_GATE: evidence present, cross-owner ACK pending | Keep PR #39 merged head and exact CI evidence; obtain E-IF-12 ACKs | CI is exact head only; no live PG claim in this review | TV1–TV5 | Phase 2 implementation gate |
| Phase 2E coding gate | NOT AUTHORIZED BY THIS PACKAGE | Lead issues separate task/sprint authorization after docs/ACKs | Conditional design approval is not coding approval | Group lead | All implementation tasks |
| Design branch policy sync | PENDING_LEAD_ACK | One Phase2E design docs branch/PR; after coding gate, one task/branch/PR | Handoff v1.1 says “one branch/PR TV5 work package”; process wording must be reconciled | Lead; rules owner if needed | Future PR workflow only |

Already approved design retained (not reopened here): `P2E-OPEN-01` Option A in-process bounded cache; `P2E-OPEN-02` typed-verdict boundary; `P2E-OPEN-03` contribution-ledger-first atomic UoW; `P2E-OPEN-04` GPU-005-B review order; GPU-005-B DEC-02..07 and conditional gate. Those approvals do not resolve the pending details in this register.

### D-19 / B-IF-06R — proposed ACKED missing-receipt repair boundary

TV2 #46 at current fetched head `c4956777512efc260fbf180898af2c041d0a16d6` labels D-19 / B-IF-06R `PROPOSED_FOR_ACK`, not approved. TV5's compatibility proposal is limited to a committed `ACKED` Outbox row whose Job is still `RUNNING`: preserve the same `attempt_id`, `event_id`, exact immutable ten-key payload and persisted deadlines; create no Allocation, Attempt, Event or deadline extension; do not repeat release or reputation effects. The ordinary claim/ACK lease remains distinct from any proposed repair lease/fence. Proposed lock order is Listing → Job → Outbox, with HTTP only after commit; authorization when no on-time PENDING/ACCEPTED receipt exists is still unresolved. TV1/TV2/TV5 and the lead must decide the port and both commit orders against callback, finalization, fallback, restart and stale-owner takeover before implementation. This compatibility statement is not D-19 approval or a schema/grant authorization.

Required D-19 race evidence (all `NOT_RUN`; no scenario is implied PASS):

| Race | Both commit orders to exercise | Required invariant |
|---|---|---|
| Repair vs callback receipt | repair first / receipt first | same Attempt/event; reconcile a committed on-time receipt before repair admission; no second Inbox/business effect |
| Repair vs Finalization | repair first / finalization first | finalizer terminalization fences later repair; no second release or reputation contribution |
| Repair vs deadline fallback | repair first / fallback first | lock/recheck makes only one legal terminal outcome; no reopening terminal Job or duplicate effect |
| Repair vs Simulator/Manager restart | restart before repair / repair before restart | immutable payload and deadlines remain stable; no extra Attempt/Event/Allocation |
| Repair vs stale-owner takeover | repair wins fence / takeover wins fence | stale lease owner is zero-write; exactly one current fence controls repair and ACK state |

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

---

## Exact producer reconciliation — 2026-11-19

Reviewed consumer baseline before this edit: PR #50 `52c23eabd6948ad7db13d3d39d65ed920d996c9a`. Current fetched unmerged producer tips: TV2 #46 `c4956777512efc260fbf180898af2c041d0a16d6`, TV3 #49 `e73fb107d15296a6f317d9bed25ce76fe0657ac2`, TV4 #48 `a9888ee0b4b70940497c0a6047a5cf414fbcd7bc`. Exact source paths and all E-IF rows are in `TV5_INTERFACE_ACK_MATRIX.md`. This is a documentation comparison only; exact-SHA ACKs are `NOT PROVIDED`.

| Contract area | Current source-aligned statement | Remaining status |
|---|---|---|
| E-IF-09 candidate scan | Adopt the B-IF-05 signature and semantics: bounded `Batch(candidates, has_more, scanned_through)`, ordered `(received_at, inbox_id)`, eligible PENDING on-time Inbox rows only; cursor is volatile; restart/crash starts at `None`; durable progress is PostgreSQL Inbox state. `has_more` and `PrecedingPending` block fallback. Transient failures stay PENDING; definitive rejection may advance; earliest valid context-eligible candidate wins; housekeeping is distinct and settled rows cannot repeat business effects. | Semantics now recorded for review. TV1/TV2/TV3/TV5 exact-SHA ACK and P2B/Phase2E runtime evidence remain pending / `NOT_RUN`; no cursor persistence is proposed. |
| Signer G1 / E-IF-04 | Two stages: Manager uses fresh single-use 32-byte nonce and distinct signer-proof domain; authenticated proof is verified against trusted registered key and Worker/key binding outside UoW; construct `SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at)`. Simulator endpoint is stateless (no replay cache). Then TV2 UoW locks Worker shared advisory → Listing → Job → dependent rows and rechecks registry/key, fingerprint, expiry, D-18 quiescence, Listing and FIFO Job. Invalid proof returns `Blocked(SIGNER_NOT_READY)` with no Job/Allocation/Attempt/Outbox/counter writes. No network under locks. | Design boundary aligns B-IF-06/C-IF-07/08/D-IF-07. L2 endpoint/API source reconciliation, TTL, timeout/concurrency limits, Manager nonce lifetime/reuse policy, cache/restart behavior and provisioning remain `PENDING_PARAMS` / owner decisions; tests P2B-DRT-24..29, P2C-SIGN-01/02/07/08/09/10, P2C-KEY-10, P2C-DRT-20/21/24, P2E-GATE-01 `NOT_RUN`. |
| Typed V-OUT / E-IF-08 | Receipt Contract now lists the exact current TV3 `VerifiedV1Receipt` and `RejectedV1Receipt` fields and semantics; only four definitive post-ingress rejection codes. Admitted-byte structural/schema drift is an invariant break; transient failures leave PENDING. TV3 verifies outside locks; TV2 rechecks original evidence/context under the sole finalization UoW. | E-C4 remains `APPROVED_DESIGN_DIRECTION_CONDITIONAL`; DTO/DB pseudocode and exact-SHA owner ACK remain `PENDING_ACK`. No alternate TV5 finalizer UoW. |
| Traceability / E-IF-01..12 | Current exact producer tips are enumerated with source paths, responsible owners, compatibility disposition, unresolved decision and planned tests in the matrix. Consumer SHA there remains the reviewed pre-edit baseline. | No owner ACK, human L2 approval, runtime PASS, docs-gate closure or coding authorization is inferred. |

Preserve previous statuses unchanged: D-16 remains unresolved (Option B only a lead preference, not approved; P2E-DRT-04 blocked); D-19/B-IF-06R remains `PROPOSED_FOR_ACK`; DEC-07/D-14 remains a protected-reference source conflict requiring L2 supersession; key provisioning and compromise response remain open; DEC-06 demo-v1 mapping is unchanged. Phase 2 runtime tests remain `NOT_RUN`.
