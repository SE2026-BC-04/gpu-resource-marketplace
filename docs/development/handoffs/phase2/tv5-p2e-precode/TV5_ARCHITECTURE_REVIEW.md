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
