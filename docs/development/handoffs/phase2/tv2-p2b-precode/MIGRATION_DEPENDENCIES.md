# MIGRATION_DEPENDENCIES — Phase 2B pre-code task TV2-P2B-02

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` · **Date:** 2026-11-08 · design only; no revision file exists.

## 1. Revision plan (`P2B-DEC-02`, `P2B-OPEN-03C`)

| Revision | Content | Notes |
|---|---|---|
| **R1 schema** (one transactional revision) | the six tables, PK/FK/UNIQUE/CHECK/indexes, the transitional contribution CHECK | `down_revision` = accepted `main` head read immediately before coding (observed today: `0005_listing_d7`). Revision ID is **not** pre-assigned. |
| **R2 grants + guards** (separate revision, allowed by `P2B-DEC-02` item 4) | column grants for both groups, the two required guard triggers (`allocations`, `result_inbox`), post-grant excess-privilege check | needs its own review; Phase 2 runtime stays disabled until R1 and R2 are both applied and verified |

PostgreSQL DDL is transactional, so a failure inside R1 leaves none of its objects. R1 and R2 together are **not** one transaction; the activation gate (`P2B-MIG-05`) covers the gap.

## 2. Creation order inside R1

| # | Table | Depends on (already exists unless noted) |
|---|---|---|
| 1 | `execution_attempts` | `jobs(id)` |
| 2 | `allocations` | `jobs(id, listing_id)` (`uq_jobs_id_listing_id`) |
| 3 | `execution_outbox` | `execution_attempts(attempt_id)` (#1) |
| 4 | `result_inbox` | `execution_attempts(job_id, attempt_id)` (#1) |
| 5 | `signed_results` | `execution_attempts(job_id, attempt_id)` (#1), `jobs(id, listing_id, worker_id)`, `worker_public_keys(worker_id, key_id)` |
| 6 | `job_reputation_contributions` | `jobs(id)`, `jobs(id, worker_id)` |

Order among #2–#4 is free; the list is a fixed order so the file is reviewable. Every Phase 1 composite unique target above was verified in `0001_phase1b_baseline.py` (`uq_jobs_id_listing_id`, `uq_jobs_id_worker_id`, `uq_jobs_id_listing_id_worker_id`, `uq_worker_public_keys_worker_id_key_id`). **No Phase 1 table is altered.**

## 3. Downgrade (documented, not authorized to run on real data)

Reverse order: `job_reputation_contributions` → `signed_results` → `result_inbox` → `execution_outbox` → `allocations` → `execution_attempts`, then R2 reversed first (revoke grants, drop the two functions/triggers).
Boundary: downgrade **drops the Phase 2 evidence** (Inbox bytes, signed results, contributions) and is therefore refused by the migration when any Phase 2 row exists, unless an explicit operator flag says the database is disposable. R2's downgrade only revokes what R2 granted and never re-grants `PUBLIC` (same policy as `0002`).
Round-trip `upgrade → downgrade → upgrade` runs on a disposable DB only (`P2B-MIG-04`).

## 4. Drift and preflight (fail closed)

R1 refuses to run (raises before DDL) if: `alembic_version` is not the recorded parent; any of the six tables already exists; a Phase 1 unique target above is missing; or a second head exists. R2 refuses if R1 is absent, the runtime groups/logins are missing or have unexpected members, or the grant self-check finds any privilege outside the Phase 2 matrix (direct, inherited or via `PUBLIC`). Application preflight (`tools/verify_alembic_head.py` plus a new "Phase 2 schema + ACL ready" probe owned by TV1/TV2) keeps the Manager from starting Phase 2 loops on a half-applied database (`P2B-MIG-05`).

## 5. Phase 3 hand-over notes

- `disputes` and `retention_exceptions` are created in Phase 3 in their own revision.
- That revision drops the transitional CHECK, adds the final CHECK and the composite FK `(job_id, corrected_by_dispute_id) → disputes(job_id, id)`; it preflights existing contributions and aborts on a contradictory row. No Phase 2 row needs a backfill.
- Guarded delete (D3) must be extended deliberately for the new children; `signed_results` must not get an unconditional `DELETE`-reject trigger (it would block the 23-day purge).
