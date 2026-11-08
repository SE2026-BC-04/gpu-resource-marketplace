# DB_BASELINE — Phase 2B pre-code task TV2-P2B-01

**Owner:** TV2 (`TranVu2005`) · **Status:** `DRAFT_FOR_TV1_TV2_ACK` · **Date:** 2026-11-08
**Scope:** documentation only. No migration, grant, role or GitHub setting was changed to produce this file.
**Source:** `HANDOFF_TV2_Phase2B_v1.1.md` §5 A (TV2-P2B-01), `Phase_2B_v1.3.md` §2.8 (`P2B-OPEN-05`).

## 1. Accepted Phase 1 baseline (what is proven and what is not)

| Item | Value | Evidence | Verdict |
|---|---|---|---|
| Phase 1 integration PR | [#39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39), state `MERGED`, merge commit `aff538f79997c6e2bfcf359b176a82f2cd9ecc53` (2026-11-08T06:30:31Z) | `gh pr view 39` | observed |
| `main` HEAD used for this baseline | `bee832eaf5463df20f6c6815174322871eb6685a` (merge of docs PR #44) | `git rev-parse origin/main`, GitHub API | observed |
| Alembic heads on that SHA | exactly one: `0005_listing_d7` | `alembic -c backend/alembic.ini heads` run locally on this branch (cut from `bee832e`) | **PASS** |
| Linear graph | `0001_phase1b_baseline` → `0002_phase1b_grants` → `0003_phase1b_jobs_guard_update` → `0004_phase1b_jobs_guard_delete` → `0005_listing_d7` | `down_revision` fields read in `backend/migrations/versions/` | **PASS** (source read) |
| Live DB revision (`alembic_version`) | `0005_listing_d7` after `bootstrap_roles` + `alembic upgrade head` on a reset disposable DB (PostgreSQL 16.15, `gpm-pg-test`, `127.0.0.1:55432`) | probe run 2026-11-08 on this branch (code identical to `bee832e`; only docs added) | **PASS** |
| Tables after upgrade | `alembic_version` plus the 10 Phase 1 tables; no Phase 2 table | same probe | **PASS** |
| Triggers after upgrade | `trg_jobs_guard_update` (D2), `trg_jobs_guard_delete` (D3), `trg_gpu_listings_guard_update` (D7); nothing else | same probe | **PASS** |
| Full backend suite on this baseline | `1223 passed, 0 failed, 0 skipped` (`pytest backend/tests tests`, disposable cluster, local tz `Asia/Bangkok`) | first run had 2 failures caused only by a missing `npm ci` in `frontend/` (the two Chromium E2E tests); rerun after `npm ci` is clean | **PASS** |
| Phase 1 CI on the merged HEAD | the #39 HEAD `3482bce` had 4 green jobs (run #42385995533); the post-merge `main` run is not re-checked here | PR #39 comments | context only, not Phase 2 evidence |
| Phase 1 human review / L2 | not verified by TV2; tracked by the owner on #39 | — | out of TV2 scope |

`0005_listing_d7` is the **observed** parent. Per `P2B-OPEN-05` it is not frozen: the Phase 2 revision's `down_revision` is read again from `main` immediately before coding (see §5).

## 2. Phase 1 objects the Phase 2 revision depends on (all already exist, none is recreated)

| Phase 1 object | Why Phase 2 needs it | Present? |
|---|---|---|
| `jobs` PK `id`, `uq_jobs_id_listing_id`, `uq_jobs_id_worker_id`, `uq_jobs_id_listing_id_worker_id`, `uq_jobs_id_client_id` | composite FK targets for `allocations`, `signed_results`, `job_reputation_contributions` | yes (`0001`) |
| `jobs.enqueue_seq` (identity, `uq_jobs_enqueue_seq`) and partial index `ix_jobs_listing_fifo (listing_id, enqueue_seq) WHERE status='QUEUED'` | FIFO head lookup in `TX-ALLOCATE` | yes (`0001`) |
| `jobs.started_at`, `terminal_at`, `failure_reason` and CHECKs `ck_jobs_terminal_at_consistency`, `ck_jobs_failure_reason`, `ck_jobs_started_at_never_running` | Manager lifecycle writes | yes (`0001`) |
| `gpu_listings.allocated_gpu_count` with CHECK `0 <= allocated <= total` | capacity counter (the column is `allocated_gpu_count`; there is no `reserved_gpu_count`) | yes (`0001`) |
| `worker_public_keys` PK `key_id`, `uq_worker_public_keys_worker_id_key_id` | `signed_results (worker_id, key_id)` FK, `ON DELETE RESTRICT` | yes (`0001`) |
| `worker_reputation_aggregates` (`successful_jobs`, `worker_fault_jobs`, nonnegative CHECKs) | updated in `TX-FINALIZE` | yes (`0001`) |
| `simulation_references`, `audit_events` | protected oracle, operational audit | yes (`0001`) |
| D1 roles/grants (`0002`) | runtime least privilege | yes, **Manager currently has CONNECT only** (see §3) |
| D2 `trg_jobs_guard_update` (`0003`) | Manager edges `QUEUED>RUNNING`, `RUNNING>COMPLETED`, `RUNNING>FAILED` | yes |
| D3 `trg_jobs_guard_delete` (`0004`) | guarded delete 552 h after `terminal_at` | yes |
| D7 `trg_gpu_listings_guard_update` (`0005`) | blocks `id/worker_id/created_at` changes, sets `updated_at := clock_timestamp()`; does **not** block `allocated_gpu_count` updates | yes |

Conclusion: no Phase 1 table needs a structural change for Phase 2B. Only privileges are added (§3).

## 3. Runtime roles and grants (read from source, then confirmed on a live disposable DB, §6)

Read from `0002_phase1b_grants.py`; the live `information_schema` inventory matches (§6, B-02).

- Logins: `gpm_api_app` (member of `gpm_api_rw`) and `gpm_manager_app` (member of `gpm_manager_rw`). Groups and logins are created by `python -m gpu_marketplace.common.db_roles` before `alembic upgrade`; migrations never create roles.
- **API** today: `SELECT` on `roles, users, user_roles, workers, gpu_listings, jobs, worker_reputation_aggregates`; column `SELECT` on `worker_public_keys (key_id, worker_id, registered_at, retired_at)` (never `public_key_raw`); `INSERT`/`UPDATE` on named `gpu_listings` columns; `INSERT` on named `jobs` columns and `UPDATE (status, terminal_at)`; `INSERT` on `simulation_references` and `audit_events` (named columns, no `SELECT`).
- **Manager** today: `CONNECT` and schema `USAGE` only. **Every Manager read/write that Phase 2 needs on Phase 1 tables is a new grant** and must pass the same excess-privilege self-check that `0002` runs. `0002` is an accepted revision and is not rewritten; the Phase 2 grants revision carries its own matrix check (see `PHASE2_ROLE_GRANTS.md` §5).
- Neither group has `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, DDL, `CREATE` on the schema or database, or `TEMPORARY`; `PUBLIC` privileges were removed by `0002`.

## 4. Runtime wiring that already exists in code (reuse, do not copy)

| Code | Fact relevant to Phase 2B |
|---|---|
| `repositories/commit_outcome.py::is_definite_commit_rollback` | only class `23` and `40000/40001/40002/40P01` are definite rollback; `40003` and unknown codes stay `UNKNOWN`. Phase 2 UoWs reuse it unchanged. |
| `repositories/jobs.py`, `job_submit.py`, `listings.py` | native-role guard checks `current_user` and `session_user`, `READ COMMITTED`, single-use UoW, Listing lock before Job lock. **The allow-lists are API-only** (`gpm_api_app`/`gpm_api_rw`). Manager UoWs need a Manager-parameterized guard; do not loosen the API one. |
| `repositories/audit.py::append_audit_event` | `.inline()` INSERT without `RETURNING`, 8 granted columns, per-event metadata allow-list. Event types are API/Phase 1 only; Manager audit is an open decision (`OPEN_DECISION_REGISTER.md`, D-04). |
| `common/database.py`, `common/db_roles.py` | engine factory and role bootstrap; Manager process today is an idle loop with a readiness check. |
| `backend/tests/db_safety.py`, `role_credentials.py` | disposable-cluster safety guard and `restored_login_role_credentials` (from #42). Phase 2 DB tests must use both. |

## 5. Baseline gate procedure (run again immediately before coding)

1. `git fetch origin main`; record `git rev-parse origin/main` and the accepted Phase 1 PR/approval (TV1 owns the acceptance record; an open or Draft PR is not acceptance).
2. `alembic -c backend/alembic.ini heads` must print exactly one head. Any second head, or a head other than the recorded one, is `BLOCKED`.
3. On a **disposable** cluster only: bootstrap roles, `alembic upgrade head`, then `tools/verify_alembic_head.py` and `tools/verify_runtime_roles.py`; read `alembic_version`; dump the grant inventory (§6); run the D2/D3/D7 behavior tests already in the suite.
4. Record: Git SHA, head, DB revision, PostgreSQL version, `current_user`/`session_user`, command lines, result `PASS|FAIL|BLOCKED|NOT_RUN`.
5. Drift (unexpected revision, missing role, excess privilege, unmerged Phase 1 fix) → `BLOCKED`; never widen a grant to make a check pass.

## 6. Live-DB checks (probe and suite run 2026-11-08)

| ID | Item | Result |
|---|---|---|
| B-01 | `alembic_version` on a freshly upgraded disposable DB equals `0005_listing_d7` | **PASS** |
| B-02 | Live grant inventory | **PASS**, matches §3 exactly (below) |
| B-03 | Role attributes and membership | **PASS** for the cluster inventory: `gpm_api_app` and `gpm_manager_app` are `LOGIN`, not superuser/createrole/createdb; `gpm_api_rw` has exactly member `gpm_api_app`; `gpm_manager_rw` has exactly member `gpm_manager_app`. `tools/verify_runtime_roles.py` itself is `NOT_RUN`: it checks Compose DSNs (host `postgres`), which this local cluster does not use. |
| B-04 | D2/D3/D7 and the rest of Phase 1 green on the baseline | **PASS** (1223 passed, 0 failed, 0 skipped) |

**B-02 detail (catalog read as the owner on the migrated disposable DB):**
- `gpm_api_rw`, table level: `SELECT` on `gpu_listings, jobs, roles, user_roles, users, worker_reputation_aggregates, workers`.
- `gpm_api_rw`, column level: `SELECT` on 4 columns of `worker_public_keys` (not `public_key_raw`); `INSERT` on `audit_events` (8 columns), `gpu_listings` (`gpu_model, mock_price_per_hour, total_gpu_count, vram_gb, worker_id`), `jobs` (`client_id, correlation_id, duration_seconds, idempotency_key, listing_id, request_sha256, requested_gpu_count, submitted_at, worker_id`), `simulation_references` (6 columns); `UPDATE` on `gpu_listings` (`gpu_model, mock_price_per_hour, status, total_gpu_count, vram_gb`) and `jobs` (`status, terminal_at`).
- `gpm_manager_rw`: **no table or column privilege at all** (empty inventory). This confirms that every Manager privilege in `PHASE2_ROLE_GRANTS.md` is new.
- Sequences in schema `public` reported by `information_schema`: none.

## 7. Disposition

`B-IF-01` stays `PENDING_BASELINE` until TV1 and TV2 ACK this file by SHA (an open Draft or merged PR #39 alone is not the ACK; TV1 records the Phase 1 acceptance).
Single-head check **PASS**; live disposable-DB checks B-01, B-02, B-04 **PASS**; B-03 **PASS** for the cluster inventory, `tools/verify_runtime_roles.py` **NOT_RUN**. These results are local, not CI, and are valid for `main@bee832e` only. Nothing here authorizes a migration or coding (gate G1 is separate).
