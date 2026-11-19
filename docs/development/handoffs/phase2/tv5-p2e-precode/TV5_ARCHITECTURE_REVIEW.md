# TV5 Phase 2E — Architecture Review Findings

**Review baseline:** `main@bee832eaf5463df20f6c6815174322871eb6685a`
**Disposition:** conditional design preserved; no Phase 2 runtime implementation reviewed. Finding severity denotes design risk, not proof that a runtime defect exists.

| ID / severity | Evidence | Failure scenario / impact | Proposed resolution and owner | Status |
|---|---|---|---|---|
| P2E-F-01 / P1 | `Phase_2E_v1.8.md` lines 1, 570–574 describes #39 as Draft/unmerged at old SHA; GitHub now says #39 merged with head `3482...`, CI 42385995533 success | A stale baseline can falsely block start or misstate evidence; not a product runtime defect | Add dated baseline sync with exact merge/head/CI; TV5 + lead verify Phase 1 gate | CONFIRMED_DOCUMENT_STALENESS |
| P2E-F-02 / P1 | API §13.1 has 10 dispatch keys and exact `demo-v1`; DR-E3 says no algorithm_version in dispatch/Signed V1; public reference is V1 | A queued Job/reference from V1 may be processed after Simulator V2 deployment and produce digest mismatch or ambiguous verification | Decide trusted version pinning, allowed discriminator/change-control, or drain/fence deployment; lead, TV1/2/3/5 | NEEDS_OWNER_DECISION |
| P2E-F-03 / P1 | Phase2E §2.3 / DR-E2 lines 480 and API §13.1 require changed same-attempt input → 409; live cache is volatile | After cold restart no cache proof exists to distinguish a contradictory authenticated request; violating global conflict guarantee or unsafe trust assumption | Decide `P2E-CACHE-GAP-01`; no Simulator DB | NEEDS_OWNER_DECISION |
| P2E-F-04 / P1 | Phase2E §2.4 lines 499 and E-IF-08 row; handoff §7.3 records `P2E-VERDICT-CONTRACT-01` | TV1/TV2/TV3 may implement incompatible names, provenance, or stale-verdict rules; stale verification could authorize a changed DB state if recheck omitted | Freeze typed verdict and mandatory locked re-read; TV1/2/3/5 | PENDING_ACK |
| P2E-F-05 / P1 | Phase2E §2.4 and DR-E5 lines 503–509; DB transaction ownership is TV2 | Multiple result IDs, invalid-first, bounded batches or unknown COMMIT can cause premature fallback, missed valid receipt, duplicate release or reputation | Explicit candidate states/order, drain-before-fallback, one UoW, independent persisted-state assertions; TV1/2/3/5 | PENDING_ACK |
| P2E-F-06 / P2 | Phase2E §2.3 says bounded cache but parameters pending; DR-E4 says parser/body limits pending | Unbounded memory/body parse or unsafe in-flight eviction can exhaust service or lose callback bytes | Set measured limits, admission/backpressure, shutdown and redaction policy; TV1/TV3/TV5 | PENDING_PARAMS |
| P2E-F-07 / P2 | Phase2E DR-E3 lines 486; incident remains `NEEDS_OWNER_DECISION` | Lost/compromised signer key could permit forgery or cause valid historical evidence to be unverifiable | Define quarantine, registry revocation, K1/K2 continuity and historical retention; no rewriting signed bytes | NEEDS_OWNER_DECISION |
| P2E-F-08 / P2 | Phase2E DR-E7 and API §11; one UoW required | Independent aggregate update or retry after unknown commit double counts success/fault or releases twice | Contribution unique by Job and atomic ledger + aggregate; TV2 owns persistence; test commit loss/replay | PENDING_ACK |
| P2E-F-09 / P2 | Phase2E DR-E6 lines 509 and API §13.2 require DB time after Listing→Job lock | Trusting Worker `finished_at`, pre-lock time, or skipping a later Inbox batch can produce false late failure | Use trusted receipt time, stable deadline, drain committed candidates before fallback; TV1/TV2/TV3 | PENDING_ACK |
| P2E-F-10 / P2 | Phase2E DR-E9 lines 547–568 labels designs NOT_RUN; PR #39 CI is Phase 1 | Phase 1 green can be mistaken for cross-runtime, native-role, deadline or crash tests | This package keeps all Phase 2 runtime tests NOT_RUN; exact SHA evidence required | CONFIRMED_TEST_GAP (expected pre-code) |
| P2E-F-11 / P3 | Handoff v1.1 line 7 and Phase2E line 1 preserve #39 old PR state; handoff hash table has a correct Phase2E file hash but old PR snapshot | Reviewers may rely on obsolete evidence; handoff also says Phase2 design approval is local-only though #44 has since merged source docs | Dated addenda link to #44 and current main; preserve historical text | DOC_SYNC_REQUIRED |
| P2E-F-12 / P2 | Handoff v1.1 task table row P2E-19 says one branch/PR for whole TV5 work package, while task workflow now says one design branch/PR and one implementation task/branch/PR | Conflicting branch/process expectations can bundle unrelated future code tasks | Append proposed policy sync and obtain lead ACK; do not silently edit team rules | PENDING_LEAD_ACK |
| P2E-F-13 / P2 | Phase2B §4.1/4.4 and current #46 comment ask TV5 about dispatch_payload, signed-results evidence copy, aggregate row owner, reference use; #46 is open/not merged | Consumers may assume TV2 proposal is approved DB contract or disagree on fields/grants | Ask TV2 directly; this package marks unresolved and does not import #46 proposal | PENDING_TV2_ACK |
| P2E-F-14 / P2 | Phase2D § erratum reported in #45 Draft; actual schema source uses `gpu_listings.allocated_gpu_count` | Using unapproved `reserved_gpu_count` causes SQL/schema mismatch | Keep exact existing column name; ask TV2/lead to close erratum | PENDING_OWNER_CONFIRMATION |

## Cross-document consistency disposition

Preserved: five-service boundary; no Simulator PostgreSQL; fixed simulation input; nine-field mock vs eleven-field Signed V1; Listing-first lock order; no HTTP under locks; DB clock; one finalization UoW; signed claims are not oracle truth; `allocated_gpu_count`; Phase 3 Dispute is out of scope. No accepted contract or Phase 2A–D file is changed. Findings concern stale snapshots or unresolved interfaces and do not imply unobserved runtime failures.

## Documentation review verification

| Check | Result | Evidence |
|---|---|---|
| Baseline branch/HEAD/worktree | PASS | `main@bee832e...`, clean before docs branch |
| PR #39/#44/#45/#46/#47 state | PASS | Live GitHub PR metadata checked 2026-11-08; exact states listed in `TV5_BASELINE.md` |
| Phase 1 CI | PASS (baseline evidence only) | Actions run 42385995533 succeeded on exact PR #39 head `3482bce...` |
| Alembic source head | PASS | `alembic -c backend/alembic.ini heads` → `0005_listing_d7 (head)`; system Alembic 1.13.1; no DB connection |
| Live PostgreSQL schema/roles | NOT_RUN | No disposable-cluster authorization/evidence; no DB contacted |
| Markdown H1 and relative links | PASS | Local validation across 11 changed Markdown files; all relative targets resolve after correcting Phase2E links |
| E-IF / DRT / TV5 task IDs | PASS | Matrix contains E-IF-01..12; release plan contains DRT-01..20; handoff traces TV5-P2E-01..19 |
| Source file SHA-256 manifest | PASS | `sha256sum` over API/DB/module/test/FR/NFR, ADR-002..005, Phase2A..E, and TV1..TV5 handoffs |
| Secret-shaped content scan | PASS | Checked changed Markdown for private-key PEM, GitHub token shapes, and PostgreSQL URL credentials; none found |
| Whitespace | PASS | `git diff --check` |
| Phase 2 runtime tests / Compose E2E | NOT_RUN | Documentation-only review; no Phase 2 implementation exists on this baseline |

---

## Findings disposition addendum — 2026-11-13 (design changes, not executed fixes)

| Finding | New design mitigation | Status |
|---|---|---|
| P2E-F-02 (version) | Preserve ten-key dispatch and eleven-field Signed V1; trusted version pin/operational drain decision still required | NEEDS_OWNER_DECISION |
| P2E-F-03 (cold cache) | Outbox immutable payload/CAS does **not** create a verifiable conflicting-dispatch history inside restarted Simulator | P2E-CACHE-GAP-01 OPEN |
| P2E-F-04 (verdict) | TV3 four-code definitive enum, full RejectedV1Receipt, V-OUT with TV2 locked hash/result_id/key and signed-part extractor | TV1/lead E-C4 + exact SHA ACK, NOT_RUN |
| P2E-F-05 (winner/fallback) | TV2 PrecedingPending, stored received_at and locked no-PENDING fallback, one Finalization UoW | TV1/TV2/TV3/TV5, NOT_RUN |
| P2E-F-07 (rotation) | TV2 D-18 two-active-key durable fence, exact {K1,K2} activation, K1 historical retention and safe abort | E-C3/D4 and L2 pending |
| **P2E-F-15 / P1 (new)** | TV2 #46 @ ba63466 adds SignerReadiness checked against sole active key/fingerprint/worker/DB expiry under advisory+Listing locks, preventing stale K1 proof after K2 | TV1/TV2/TV3/TV4/TV5 typed port ACK; P2B-DRT-29 NOT_RUN |
| **P2E-F-16 / P1 (new)** | G2 lacks safe cold-Manager bootstrap if no allocation is permitted without proof; TV5 prefers G1 | Lead G1/G2 + L2 endpoint decision |
| **P2E-F-17 / P2 (new)** | Signer restart/loss inside cached valid proof TTL requires measured residual/explicit invalidation | TV1/TV3/TV5 test/TTL decision |
| P2E-F-13 (DB integration) | TV2 byte-exact independent signed result, first-contribution reputation UPSERT and no Phase 2 oracle SELECT | Owner SHA ACK + native SQL tests |

These are **documentation-level** mitigations, not demonstrated runtime corrections. TV3's PR #50 comment at original HEAD 7b5ee16 provided ACK_WITH_ACTIONS, and TV5's [#46 review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#pullrequestreview-5887153391) / [#49 review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49#pullrequestreview-5887054059) were ACK_WITH_ACTIONS. No prior reviewer is automatically deemed to have approved this new PR #50 HEAD. Tests NOT_RUN.

---

## Reclassification after lead's L2 decisions — 2026-11-18

**Authority:** [TV1 decision on PR #46 @ `531805b`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771). The earlier 2026-11-13 finding table reports **historical** conditional choices, not current open decision status.

| Finding | Decision/mitigation state | Still required |
|---|---|---|
| `P2E-F-02` algorithm version | **MVP DESIGN RESOLVED** by `P2E-GPU005B-DEC-06`: immutable `demo-v1` → `demo-v1-public1`; no dispatch/Signed V1 field added | Exact-HEAD owner ACK and release preflight for V1–V4, queued/running retries, rollback and historical evidence; future V2 needs separate L2 change control |
| `P2E-F-03` cold cache | **D-16/P2E-CACHE-GAP-01 STILL OPEN**, Outbox persistence does not prove original dispatch to DB-less restarted Simulator | Lead contract qualification or approved authenticated persisted proof |
| `P2E-F-04` verifier DTO/V-OUT | **E-C4 V-OUT CONDITIONALLY SELECTED**; four-code definitive rejection and locked original-bytes/JCS extractor | Exact producer/consumer ACK, normative TX-FINALIZE pseudocode, P2B-DRT-23 |
| `P2E-F-05` first winner/late fallback | TV2 first `PrecedingPending`, stored timestamp and one UoW design | B-IF-05/07 exact owner ACK and real PostgreSQL race tests |
| `P2E-F-07` key rotation | **D-18/E-C3 CONDITIONALLY SELECTED** two-key fence/Worker-first lock (no partial unique active-key index) | Approved DB/Phase1B/Phase2C L2 source reconciliation, D-03/S-10, abort/restart tests |
| `P2E-F-15` proof-to-active-key TOCTOU | **G1 selected conditionally**; TV2 internal `SignerReadiness` checked against sole key ID and 64-lowercase-hex SHA-256 of 32 raw public-key bytes | G1 API endpoint/wire, TTL/restart and P2B-DRT-29 / P2C-SIGN-08 |
| `P2E-F-16` G2 bootstrap | **G2 NOT SELECTED**; historical issue, not a blocker to the *chosen* G1 design | Avoid adopting G2 silently; G1 endpoint/replay contract still pending |
| `P2E-F-17` signer loss within proof TTL | **Residual under G1**, not eliminated by a short TTL | `P2C-SIGN-07` and `P2E-ROTATE-01`: SYSTEM_FAULT without Worker penalty; owner TTL policy |
| `P2E-F-13` physical DB integration | **D-01 Option C, D-12 UPSERT, D-17 stored RETURNING conditionally selected** | Native role CHECK/grant/clock and two-Job aggregate tests |

**Remaining decisions:** D-02/E-C2, D-03/S-10, D-16, D-19 repair, DEC-07 vs TV2 D-14/TV3 oracle-access supersession, private-key compromise, cache bounds/TTL and L2 API/proof contract. Algorithm MVP mapping is decided; release evidence and exact-SHA ACKs are outstanding. All Phase 2 runtime/SQL/crypto/concurrency/E2E tests **NOT_RUN**. Distinguish `APPROVED_DESIGN_DIRECTION_CONDITIONAL` from an owner ACK, human L2 approval, merge or implementation authorization.

## Cross-interface re-review actions — 2026-11-19

The original findings table above is a historical snapshot. Current disposition for the five requested PR #50 actions:

| Finding | Current disposition | Required closure |
|---|---|---|
| P1-01 / D-16 cold restart | `NEEDS_OWNER_DECISION`; lead prefers retained-cache-scope Option B for MVP, not an approved API change. In-memory dedup and PostgreSQL once-only effects are distinct; G1/Outbox do not prove dispatch history. | Lead L2 decision, TV1/TV2/TV3/TV5 exact-SHA ACK and API change control; DRT-04 stays BLOCKED |
| P1-02 algorithm version | MVP mapping approved by DEC-06; queued/running compatibility and rollback are release preflight conditions, not an unresolved MVP mapping. | Execute V1–V4/retry/rollback/historical-evidence preflight after authorization; all NOT_RUN |
| P1-03 oracle access | DEC-07's Manager-read allowance conflicts with current TV2 D-14 and TV3 Phase 2C no-SELECT boundary. Proposed Phase 2-only supersession is not approved. | Lead + TV2/TV3/TV5 L2/source reconciliation; Phase 3 owner separately reviews Dispute access; no grants/migration here |
| P1-04 missing-receipt repair | D-19 / B-IF-06R remains `PROPOSED_FOR_ACK`; only the existing committed ACKED Outbox / still-RUNNING Job boundary is described. | TV1/TV2/TV5 + lead decide authorization/fence and race matrix before implementation |
| P2-05 E-IF-11 collision | E-IF-11 denotes PAUSED replay / RUNNING repair; signer readiness cross-references E-IF-04 / D-IF-07. | Renew exact-SHA owner review; no ACK inferred from identifier correction |

Current producer tips at review start: TV2 #46 `c4956777512efc260fbf180898af2c041d0a16d6`; TV3 #49 `f3edb94d7f11a5759d8308e64c17927ce947af19`; TV4 #48 `813aa3ed67f5da7f3343f2c553ffbf24025eacaf`; TV5 consumer #50 `edb247f8ffb657ad784673d25481b64bd450f659`. These are traceability references, not ACKs. Phase 2 runtime tests remain `NOT_RUN`.
