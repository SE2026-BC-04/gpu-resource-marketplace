# PHASE2_ROLE_GRANTS — Phase 2B pre-code task TV2-P2B-03 (grants)

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` (TV1 activation; TV3 + TV5 for Inbox) · **Date:** 2026-11-08
**Basis:** `Phase_2B_v1.3.md` §2.3–2.4 (`P2B-OPEN-03`, `03A` = approved *intent* only), `0002_phase1b_grants.py`.
This is an inventory of intended privileges, not tested GRANT SQL. Every row must be proven with the real logins `gpm_api_app` and `gpm_manager_app` and the SQL the ORM actually emits (`P2B-DRT-02`). **No grant is widened to make a test pass**; a failing statement changes the adapter first, or goes back to review.

Legend: `R(c)` column SELECT, `I(c)` column INSERT, `U(c)` column UPDATE, `—` nothing. Privileges are granted to the **groups** `gpm_api_rw` / `gpm_manager_rw`; logins inherit. `FOR UPDATE`/`FOR SHARE` need `UPDATE` on at least one column of the table, which matters for lock design (§4).

## 1. New Phase 2 tables

| Table | API (`gpm_api_rw`) | Manager (`gpm_manager_rw`) |
|---|---|---|
| `execution_attempts` | `R(job_id, attempt_id, hard_deadline_at)` | `R(all)`, `I(attempt_id, job_id, started_at, finish_due_at, hard_deadline_at)` (`attempt_id` under proposal P1 of D-05/D-13, see `P2B_UOW_INTERFACES.md` B-IF-06); no `UPDATE`, no `DELETE` |
| `allocations` | — | `R(all)`, `I(job_id, listing_id, gpu_count, allocated_at)`, `U(state, released_at)` |
| `execution_outbox` | — | `R(all)`, `I(event_id, attempt_id, event_type, dispatch_payload, next_retry_at)` (`event_id` under P1; under fallback P2 drop `event_id` and `attempt_id` here and in `execution_attempts`), `U(state, delivery_attempts, next_retry_at, lease_owner, lease_until, lease_version, acked_at, updated_at)` |
| `result_inbox` | `I(result_id, claimed_job_id, claimed_attempt_id, bound_job_id, bound_attempt_id, original_envelope_raw, envelope_sha256)` + `R(id, received_at)` so `INSERT ... RETURNING id, received_at` can test the stored instant against the deadline (no bytes readable) + a restricted duplicate-probe path (`INBOX_DUPLICATE_PRIVILEGES.md`; under option C add `R(result_id, bound_job_id, bound_attempt_id, envelope_sha256)`); **no `received_at`, `state`, `id` insert** | `R(all)`, `U(state, rejection_code, processed_at)`; no `INSERT`, no `DELETE` in Phase 2 |
| `signed_results` | — in Phase 2 baseline. A safe projection for the API is a **separate** design (view or function), not a table grant | `R(all)`, `I(all non-default columns)`; no `UPDATE`, no `DELETE` |
| `job_reputation_contributions` | — | `R(all)`, `I(job_id, worker_id, initial_category, effective_category, applied_at, updated_at)` (`correction_version` and `corrected_by_dispute_id` stay at defaults); no `UPDATE`, no `DELETE` |

Notes:
- `attempt_id` and `event_id` are `DEFAULT gen_random_uuid()`. TV5 requires the immutable Outbox payload to contain both ids at its first insert (ten-key wire body, D-05), and a DB default cannot be known before the INSERT without a later UPDATE of an immutable column. Proposal **P1**: grant `INSERT(attempt_id)` and `INSERT(event_id)` so the Manager UoW chooses UUIDv4s up front (stable across a `40001` retry). Fallback **P2**: no extra grants, payload keeps an eight-key core, ids come from the columns at claim time. **D-13** is therefore "P1 unless TV1 or the lead rejects caller-chosen ids".
- `RETURNING` needs `SELECT` on each returned column. Where an adapter returns a column the role cannot `SELECT`, use `.inline()` without `RETURNING` (as `repositories/audit.py` does) or select the value in a second statement.
- Sequence grants: none of the six tables uses a sequence or identity column, so no `USAGE ON SEQUENCE` is needed. The `jobs.enqueue_seq` identity stays API-insert only.
- Neither role gets `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` or DDL on any Phase 2 table. Guarded cleanup (Phase 3) is a separate reviewed path.

## 2. Phase 1 tables: new Manager privileges (Manager has `CONNECT` only today)

| Table | Manager privilege needed | Reason |
|---|---|---|
| `gpu_listings` | `R(id, worker_id, status, total_gpu_count, allocated_gpu_count)`, `U(allocated_gpu_count)` | Listing lock, capacity, counter. `updated_at` is set by the D7 trigger (a trigger assigning `NEW` is not a column-privilege use; to be proven in a test). |
| `jobs` | `R(id, listing_id, worker_id, status, requested_gpu_count, duration_seconds, submitted_at, enqueue_seq, started_at, terminal_at, failure_reason)`; **not** `client_id`, `idempotency_key`, `request_sha256`, `correlation_id` unless TV1/TV4 show a need. `U(status, started_at, terminal_at, failure_reason)` | FIFO head, RUNNING/terminal edges (D2 allows the Manager exactly `QUEUED>RUNNING`, `RUNNING>COMPLETED`, `RUNNING>FAILED`) |
| `worker_public_keys` | `R(key_id, worker_id, public_key_raw, registered_at, retired_at)` | verifier key material for TV3's pure verifier; the API still never reads `public_key_raw` |
| `worker_reputation_aggregates` | `R(worker_id, successful_jobs, worker_fault_jobs)`, `U(successful_jobs, worker_fault_jobs, updated_at)`, `I(worker_id, successful_jobs, worker_fault_jobs, updated_at)` | lifetime counters. No code path creates the row today (`repositories/listings.py` reads it with `coalesce` from an outer join). Adopting TV5's D-12 preference: the first contributing finalization (`SUCCESS` or `WORKER_FAULT`) upserts with `INSERT … ON CONFLICT (worker_id) DO UPDATE` (exact SQL in `P2B_UOW_INTERFACES.md` B-IF-07); `NONE`/`SYSTEM_FAULT` never create or change a row. `updated_at` is advanced from trusted DB time only in that statement (D-11), so `U(updated_at)` is granted instead of a trigger. |
| `simulation_references` | **none** | D-14 (TV5 ACK_COMPATIBLE): the Phase 2 finalization policy does not read the protected oracle and it is not an input of `TX-FINALIZE`; Phase 3 dispute resolution reads it. `G-03` proves `42501` for the Manager. |
| `audit_events` | **none by default** | Manager audit events are an open owner decision (D-04). If approved: `I(actor_kind, actor_ref, correlation_id, subject_type, subject_id, event_type, outcome, metadata_redacted)` only. |
| `workers`, `users`, `user_roles`, `roles` | none | Manager never provisions or reads accounts. |

## 3. Phase 1 tables: API privileges that must stay as they are

`gpu_listings.allocated_gpu_count` stays **out** of the API's `UPDATE` list (current: `gpu_model, vram_gb, total_gpu_count, status, mock_price_per_hour`). `jobs` keeps `UPDATE (status, terminal_at)` for the API's own `QUEUED→CANCELLED`; D2 still rejects any API edge other than that. `simulation_references` stays insert-only for the API.

## 4. Locking consequences of column grants (found while building this table)

- `SELECT ... FOR UPDATE` on `execution_attempts` is **impossible** for the Manager (no `UPDATE` privilege). That is acceptable: attempts are immutable and the Job row lock already serializes every writer. The UoW contracts therefore lock `Listing → Job → Allocation → Inbox candidates` and read the attempt without a row lock.
- `FOR UPDATE` on `result_inbox` candidates and on `allocations` works for the Manager because it holds `UPDATE` on some column of each.
- The API's `FOR UPDATE` on `gpu_listings` and `jobs` (already used by TX-SUBMIT/TX-CANCEL) works because it holds `UPDATE` on named columns. The API's ingress path locks `Listing → Job` the same way and reads `execution_attempts(job_id, attempt_id, hard_deadline_at)` without a lock.
- Foreign-key checks on insert (for example `result_inbox` → `execution_attempts`) run with the table owner's rights, so the API needs no `REFERENCES` or extra `SELECT` for them.
- Column `SELECT` is not row-level security. Any `WHERE` on a column needs `SELECT` on that column for **all** rows; this drives `INBOX_DUPLICATE_PRIVILEGES.md`.

## 5. Grant revision self-check (R2)

R2 repeats the shape of `0002`'s final check, with the Phase 2 matrix: after granting, read `has_table_privilege`, column privileges (`information_schema.column_privileges`), sequence and schema/database privileges for both groups and both logins, and raise (rolling the revision back) if anything exceeds §1–§2, whether direct, inherited or via `PUBLIC`. `0002` is not edited. A new test inventories the grants and compares them to a checked-in expected list so a later revision cannot widen them silently (`P2B-DRT-02`).

## 6. Proof obligations (all `NOT_RUN`)

| ID | Proof | PASS oracle |
|---|---|---|
| `G-01` | Positive: every statement in the six UoW contracts runs as the native login | no `42501` |
| `G-02` | Negative: API `UPDATE allocations/execution_outbox/signed_results/job_reputation_contributions/worker_reputation_aggregates`, `SELECT result_inbox.original_envelope_raw` (outside the probe path), `SELECT simulation_references` | `42501` each |
| `G-03` | Negative: Manager `INSERT result_inbox`, `UPDATE result_inbox.original_envelope_raw/received_at`, `SELECT simulation_references`, any `DELETE`, any DDL | `42501` each |
| `G-04` | ORM emitted SQL under both logins includes no `RETURNING` of an ungranted column | statement log reviewed |
| `G-05` | `current_user`/`session_user` guard rejects an owner session and a `SET ROLE` session for the Manager UoW | `RuntimeError`/sanitized error |
| `G-06` | Phase 1 API behavior unchanged (Submit/Cancel/Listing/Auth suites) | existing tests green |
