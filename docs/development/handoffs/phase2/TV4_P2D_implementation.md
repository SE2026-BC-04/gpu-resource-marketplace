# TV4 — Phase 2D implementation intake

**Owner:** Nguyễn Ngọc Việt (`@VietNguyen865`) · **Date:** 2026-11-08

**Branch:** `codex/phase2d-fifo-allocation` · **Status:** independent policy implemented; integration pending ACK. This is the ongoing TV4 work package, not a completed Phase 2D handoff.

## 1. Authority and frozen baseline

- The team-lead Phase 2 assignment supplied by the contributor authorizes TV4 to implement FIFO/allocation policy, with independent work allowed in parallel while TV2 prepares transactions. Dependent interfaces still require owner/consumer ACK. This assignment is the coding authorization; the older design documents alone are not. The PR requests the lead's GitHub confirmation of this intake for traceability.
- Source designs: [Phase 2D v0.9](../../../architecture/phases/phase2/Phase_2D_v0.9.md), [TV4 handoff v1.1](HANDOFF_TV4_Phase2D_v1.1.md). This file records implementation progress/proposals; it does not silently amend either approved source.
- Accepted `main` at branch creation: `bee832eaf5463df20f6c6815174322871eb6685a` ([docs intake #44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44)). [Phase 1 integration #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) was merged as `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`, source head `3482bce3cc9726543b9345a5224d8db1b9fc6454`.
- Local read-only migration graph: one head `0005_listing_d7`, Alembic `1.20.0`, Python `3.12.14`. No database was connected or migrated; database-installed revision and native `current_user/session_user` are **NOT_RUN**, not inferred from the graph.
- Phase 1 follow-up: the [role-rejection audit finding](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#discussion_r4502535120) remains recorded. Phase 1 merge is not evidence that this finding was fixed. API audit remediation is outside this policy-only patch.

## 2. Independent code delivered

`backend/src/gpu_marketplace/manager/fifo_policy.py` supplies a DB-free oracle for `TV4-P2D-07` and the FIFO/capacity subset of `TV4-P2D-15`. No production caller mounts it yet.

`assess_fifo(ListingSnapshot, Iterable[JobSnapshot]) -> FifoAssessment` uses immutable local snapshots:

| Input/state | Local assessment | Head |
|---|---|---|
| PAUSED | `INACTIVE_LISTING`; do not inspect jobs | None |
| ACTIVE, no QUEUED job | `EMPTY_QUEUE` | None |
| ACTIVE, first QUEUED needs more than `total_gpu_count - allocated_gpu_count` | `BLOCKED_CAPACITY`; never try a later fitting job | True minimum `enqueue_seq` |
| ACTIVE, first QUEUED fits (including exact fit) | `ELIGIBLE` | True minimum `enqueue_seq` |

- FIFO uses only `enqueue_seq`; UUID/input order, sequence gaps and timestamp ties cannot change it. CANCELLED/RUNNING/terminal jobs are excluded. Independent Listings can be assessed separately; this is not proof of runtime scan fairness.
- Invalid counts/status/identity, mixed-Listing input or duplicate Job IDs/sequences fail closed with `ValueError`. These are internal invalid-snapshot errors, not a new public API error mapping. Integer bounds mirror PostgreSQL integer/bigint; no new positive-sequence constraint is imposed.
- The caller must supply the true queued head. The future TV2 adapter must read current Listing and `ORDER BY enqueue_seq LIMIT 1 FOR UPDATE` under Listing → Job locks, never Job `SKIP LOCKED`. It can supply that one head; loading the whole queue under locks is unnecessary. Unit tests may supply model queues.
- `ELIGIBLE` describes FIFO/capacity only. It neither checks signer readiness nor allocates, mutates a Job/counter, creates Attempt/Outbox, or authorizes dispatch. Snapshots, result names and function signature are local implementation details proposed for review, **not** a frozen `D-IF-01/02` transaction port.

Traceability: `FR-JL-02/03`, `BR-03/04/07`, ADR-002/003, Database Design §11 and Phase 2D §2.1/3/7. No schema, API, dependency, service or runtime configuration changed.

## 3. Proposal to ACK before dependent implementation

### Erratum X-01 — TV4 statement, TV2/lead confirmation pending

Phase 2D §7.3 says `reserved_gpu_count`. The actual schema, Phase 2D §2.1 and TV2/TV4 handoffs use **`gpu_listings.allocated_gpu_count`**. TV4 confirms the latter as the policy input/counter. Request TV2 and the lead record the erratum; do not add or rename a column to match the typo.

### Transaction handoff — proposal, not implemented

TV2 owns `allocate_one_listing(listing_id)` in one synchronous, native `gpm_manager_app`, `READ COMMITTED` UoW. TV1 owns the bounded executor/caller; TV5 confirms Job/Attempt/Outbox lifecycle semantics. Proposed information to freeze together:

| Proposed category | Required meaning / safely known data |
|---|---|
| `ALLOCATED` | Definite durable commit; Listing/Job/Allocation/Attempt/Outbox identities, with exactly one head allocated |
| `EMPTY_QUEUE` | Locked current Listing has no QUEUED head; no writes |
| `BLOCKED_CAPACITY` | Locked current head ID/sequence, requested/free GPU; no writes, no head bypass |
| `INACTIVE_LISTING` | Current Listing is not ACTIVE; no new allocation |
| `LOCK_BUSY` | Only if agreed Listing-claim policy uses a non-waiting claim; never skips a Job |
| `DEPENDENCY_UNAVAILABLE` | Sanitized failure; no claim of successful allocation |
| `COMMIT_OUTCOME_UNKNOWN` | Commit may have succeeded; fresh trusted DB reconciliation is required before any retry; never blind reallocation |

Category names/types, missing-Listing handling, optional IDs, no-op commit versus rollback, SQLSTATE/error mapping and retry/timeout policy remain **PENDING_ACK**. No Python transaction port, fake production adapter, SQL writer or `ALLOCATED` result is implemented here.

The agreed transaction must recheck ACTIVE/capacity/current head after Listing → Job locks, apply the separately ACKed signer-readiness guard, obtain DB time after locks and atomically write counter + RUNNING Job + Allocation + Attempt + Outbox. No live Session crosses threads; no HTTP under locks. Existing PAUSED RUNNING repair retains the same Attempt/event/payload and deadlines; it is not another allocation.

### Owner requests / next gate

| Interface | Requested confirmation | Status |
|---|---|---|
| `D-IF-01` | TV1/TV2/TV5 review this oracle/proposed result information; TV4 supplies policy, not peers' ACK | PENDING_ACK |
| `D-IF-02` | TV2 publishes transaction/UoW port and native-role/commit/error semantics; TV1/TV4 consume only after ACK | PENDING_ACK |
| `D-IF-03/04` | TV1+TV2+TV4 agree stable Listing scan/cursor, lock-busy policy and measured Listing/time/executor/pool/SQL-timeout budgets | PENDING_ACK / PENDING_PARAMS |
| `D-IF-05/06/08` | TV1/TV2/TV5 confirm PAUSED repair, both-order races and exactly-once release/counter conservation | PENDING_ACK |
| `D-IF-07` | TV2/TV3/TV5 confirm atomic signer readiness and planned rotation; lead decides compromised-key handling if required | PENDING_ACK / NEEDS_OWNER_DECISION |
| `D-IF-09` | Owners acknowledge merged Phase 1 baseline and outstanding audit disposition; no blanket closure from merge alone | PENDING_ACK |

Only the configurable 2s initial Scheduler interval is already approved; no numerical scan/pool/time budget is selected here. No Scheduler loop, scan helper, runtime mount, Outbox dispatcher or key provisioning is added. ACK replies must cite reviewed producer/consumer SHAs, fields/errors and test scenarios; the PR provides the code SHA. A contributor cannot supply another owner's ACK or independent human approval.

## 4. Verification and remaining work

| Check | Command / environment | Actual result |
|---|---|---|
| FIFO/capacity unit tests | `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_fifo_policy.py -q -p no:cacheprovider` | **PASS: 55 passed** |
| Backend regression | `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -q -p no:cacheprovider -rN`; DB URL/destructive-test/cluster-token variables removed in the child environment | **PASS: 906 passed, 372 skipped**, 2 existing dependency/config deprecation warnings; skipped DB/browser-dependent checks are not PASS |
| Scoped lint/format | Ruff `0.14.0` `check` and `format --check` on the two Python files | **PASS** |
| Migration graph | Alembic `ScriptDirectory.get_heads()` (read-only; no connection) | **PASS: `0005_listing_d7`**; installed DB revision NOT_RUN |
| Native PG transaction/races/recovery | `P2D-TX-01..12`, `P2D-RACE-01..08`, `P2D-DRT-01..15`, relevant `DBTX-*`/`API-LIST-*` allocation branches | **NOT_RUN**; TV2 transaction port/native disposable PG fixture needed; signer/rotation cases **BLOCKED** until ACK |
| Scheduler fairness/pressure/restart | `P2D-SCHED-01..05` | **NOT_RUN**; TV1 runtime + TV2 resource/interface ACK needed |

The unit suite covers input permutations/UUID reversal, sequence gaps, capacity boundaries, cancelled-head advancement, PAUSE/RESUME snapshots, independent Listing assessment, unchanged inputs and corrupt snapshots. It does **not** close any full PG/runtime acceptance ID. Full-slice completion requires `TV4-P2D-08..14/16`, the remaining scan subset of `-15`, cross-owner ACKs and two independent human reviews for L2. Keep one branch/PR for this assignment; do not self-merge.
