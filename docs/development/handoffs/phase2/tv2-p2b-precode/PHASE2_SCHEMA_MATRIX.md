# PHASE2_SCHEMA_MATRIX — Phase 2B pre-code task TV2-P2B-02

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` (TV1, TV3, TV4, TV5 for the columns they consume) · **Date:** 2026-11-08
**Source of truth:** `docs/design/database-design.md` §9.2 tables 09–13 and 16, §9.3 FK directions, §9.4 indexes; `Phase_2B_v1.3.md` §2.1, §2.2.
**This file is a design matrix, not DDL.** Constraint names follow the Phase 1 convention (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`) and become a contract once migrated (`test_schema_metadata.py` pins names; repositories map DB errors by name).

Rows marked **[Δ]** are where this matrix adds something the design does not spell out. Each [Δ] is a proposal that needs the named ACK; none changes the approved table list or the 18-table catalog.

## 1. Dependency order inside the single schema revision

`execution_attempts` → `allocations` → `execution_outbox` → `result_inbox` → `signed_results` → `job_reputation_contributions`
(details and reverse order in `MIGRATION_DEPENDENCIES.md`).

## 2. `execution_attempts`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `attempt_id` | `uuid` | NN, `gen_random_uuid()` | PK `pk_execution_attempts` |
| `job_id` | `uuid` | NN | FK → `jobs(id)` `fk_execution_attempts_job_id`, guarded `ON DELETE CASCADE`; `uq_execution_attempts_job_id` |
| `started_at` | `timestamptz(6)` | NN | Manager trusted time (same `t` as the Job's `started_at`) |
| `finish_due_at` | `timestamptz(6)` | NN | `t + duration_seconds` |
| `hard_deadline_at` | `timestamptz(6)` | NN | `finish_due_at + 120 s` |
| `created_at` | `timestamptz(6)` | NN, DB time | audit of insertion |

Constraints: `uq_execution_attempts_job_id_attempt_id (job_id, attempt_id)` (target of composite FKs); `ck_execution_attempts_deadlines`: `finish_due_at > started_at AND hard_deadline_at = finish_due_at + interval '120 seconds'`.
Indexes: none beyond the unique keys.
Cross-row rule (not a CHECK): `finish_due_at - started_at = jobs.duration_seconds`; enforced and tested in `TX-ALLOCATE`.

## 3. `allocations`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `id` | `uuid` | NN, `gen_random_uuid()` | PK |
| `job_id`, `listing_id` | `uuid`, `uuid` | NN | `uq_allocations_job_id`; composite FK `(job_id, listing_id)` → `jobs(id, listing_id)` (existing `uq_jobs_id_listing_id`) |
| `gpu_count` | `integer` | NN | `ck_allocations_gpu_count_positive` (`> 0`) |
| `state` | `varchar(8)` | NN, `'ACTIVE'` | `ck_allocations_state` (`ACTIVE`,`RELEASED`) |
| `allocated_at` | `timestamptz(6)` | NN | Manager trusted time |
| `released_at` | `timestamptz(6)` | nullable | `ck_allocations_released_at` : `(state='RELEASED') = (released_at IS NOT NULL)` |

Index [Δ]: partial `ix_allocations_listing_active (listing_id) WHERE state='ACTIVE'` for the test/reconciliation query `allocated_gpu_count = SUM(active gpu_count)`. Not in §9.4; add only if TV4/TV1 want reconciliation in production; otherwise tests use a seq scan. **Decision D-09.**
Cross-row rule: `allocations.gpu_count = jobs.requested_gpu_count` and counter reconciliation are transaction rules, tested (`P2B-DRT-09`).

## 4. `execution_outbox`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `event_id` | `uuid` | NN, `gen_random_uuid()` | PK |
| `attempt_id` | `uuid` | NN | FK → `execution_attempts(attempt_id)` guarded cascade; `uq_execution_outbox_attempt_id_event_type (attempt_id, event_type)` |
| `event_type` | `varchar(16)` | NN, `'EXECUTE_JOB'` | `ck_execution_outbox_event_type` |
| `dispatch_payload` | `jsonb` | NN | immutable; P1 (D-05, approved by the lead, conditional, @ `531805b`): exactly the ten wire keys, `ck_execution_outbox_payload_shape` (key set, `outbox_event_id = event_id`, `attempt_id` match, fixed `simulation_input`); fallback P2: eight-key core. See `P2B_UOW_INTERFACES.md` B-IF-06. lead conditional approval @ `531805b`; TV5 exact-SHA ACK pending |
| `state` | `varchar(12)` | NN, `'PENDING'` | `ck_execution_outbox_state` (`PENDING`,`CLAIMED`,`ACKED`,`EXHAUSTED`) |
| `delivery_attempts` | `integer` | NN, `0` | `>= 0` |
| `next_retry_at` | `timestamptz(6)` | NN | due time |
| `lease_owner` | `varchar(128)` | nullable | |
| `lease_until` | `timestamptz(6)` | nullable | claim time + 30 s (ADR-005) |
| `lease_version` | `bigint` | NN, `0` | `>= 0`; fencing token |
| `acked_at`, `created_at`, `updated_at` | `timestamptz(6)` | `acked_at` nullable | |

Index: `ix_execution_outbox_due (next_retry_at, event_id) WHERE state IN ('PENDING','CLAIMED','ACKED')` (§9.4).
[Δ] Coherence CHECKs (**D-06**, need TV1 + lead ACK because they constrain how the dispatcher clears a lease): `ck_execution_outbox_lease_pair`: `(lease_owner IS NULL) = (lease_until IS NULL)`; `ck_execution_outbox_state_lease`: `(state = 'CLAIMED') = (lease_owner IS NOT NULL)` (so `PENDING`, `ACKED` and `EXHAUSTED` always carry **no** lease); `ck_execution_outbox_acked_at`: `(state = 'ACKED') = (acked_at IS NOT NULL)`. Together with the CAS predicates in `P2B_UOW_INTERFACES.md` B-IF-06 (claim only `PENDING`-due or `CLAIMED`-expired; ACK/RETRY/EXHAUSTED only `WHERE state='CLAIMED' AND lease_version=:v AND lease_owner=:o`; lease columns cleared on all three; `lease_version` never reset) an expired lease can never resurrect an `ACKED` or `EXHAUSTED` row.
[Δ] `ck_execution_outbox_payload_object` is subsumed by `ck_execution_outbox_payload_shape` (object, exact key set, fixed `simulation_input`, id keys are JSON strings equal to the columns; the whole predicate is `COALESCE(..., false)` because a CHECK accepts NULL). The shape CHECK uses only immutable jsonb operators; it never casts payload text to `timestamptz` (that cast is not immutable), so timestamp equality with the `execution_attempts` columns is a transaction rule plus test (`P2B-DRT-18`).

## 5. `result_inbox`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `id` | `uuid` | NN, `gen_random_uuid()` | PK |
| `result_id` | `uuid` | nullable | partial unique `uq_result_inbox_result_id WHERE result_id IS NOT NULL` |
| `claimed_job_id`, `claimed_attempt_id` | `uuid`, `uuid` | nullable | untrusted claims, no FK |
| `bound_job_id`, `bound_attempt_id` | `uuid`, `uuid` | nullable | composite FK → `execution_attempts(job_id, attempt_id)` |
| `original_envelope_raw` | `bytea` | NN | exact body bytes |
| `envelope_sha256` | `bytea` | NN | `octet_length = 32` |
| `received_at` | `timestamptz(6)` | NN | **[Δ] `DEFAULT clock_timestamp()`; API has no INSERT grant on the column** (see below) |
| `state` | `varchar(12)` | NN, `'PENDING'` | `PENDING`,`ACCEPTED`,`REJECTED` |
| `rejection_code` | `varchar(64)` | nullable | redacted code, no secrets; **[Δ] `ck_result_inbox_rejection_code`** (TV3 action 1): `COALESCE(((state = 'REJECTED') = (rejection_code IS NOT NULL)) AND (rejection_code IS NULL OR rejection_code IN ('UNKNOWN_KEY','KEY_WORKER_MISMATCH','CONTEXT_MISMATCH','INVALID_SIGNATURE','NOT_SELECTED','ALREADY_TERMINAL')), false)`. The first four are TV3 verifier verdicts definitive after ingress admission (`INVALID_STRUCTURE` and `UNSUPPORTED_SCHEMA_VERSION` were removed: a parse or schema failure on admitted bytes is an invariant break, the row stays `PENDING`) (proposal `PROPOSED_FOR_ACK`, to be frozen in TV3's PR #49); the last two are TV2 housekeeping codes. No free-form code can be stored |
| `processed_at` | `timestamptz(6)` | nullable | |

Constraints (from §9.2): `(bound_job_id IS NULL) = (bound_attempt_id IS NULL)`; `state <> 'PENDING' OR bound_job_id IS NOT NULL`; `(state = 'PENDING') = (processed_at IS NULL)`.
[Δ] `ck_result_inbox_sha256_matches` cannot be a CHECK on `bytea` content without `sha256()`; PostgreSQL has built-in `sha256(bytea)` since 11, so `envelope_sha256 = sha256(original_envelope_raw)` is expressible and removes any chance that a caller stores a hash for different bytes. Proposed as CHECK; costs one hash per insert on a bounded body. **Decision D-07** (TV3 owns body size bound).
[Δ] `received_at` default: the design says the time is the DB clock read after the Job lock. A column default of `clock_timestamp()` is evaluated when the row is inserted, which in `TX-INBOX-INGRESS` is after the lock. Leaving the column out of the API's `INSERT` grant makes the timestamp unforgeable by the API process. The same reasoning applies to `state` (default `PENDING`), `id`, `rejection_code`, `processed_at`: the API inserts only `result_id, claimed_*, bound_*, original_envelope_raw, envelope_sha256`.
Single-instant rule (TV3 review): the adapter must not read `clock_timestamp()` separately to test the deadline, because the default would read the clock again at insert. It uses `INSERT ... RETURNING id, received_at` and rolls back as `Ineligible(late)` when the stored `received_at >= hard_deadline_at`; alternative is a `BEFORE INSERT` guard (**D-17**).
Indexes (§9.4): `ix_result_inbox_pending (bound_job_id, received_at, id) WHERE state='PENDING'`.
Open: unbound rejected rows (`bound_job_id IS NULL`, `state='REJECTED'`). Baseline design rejects unbindable callbacks without a row; if a row is wanted, `state`, `processed_at` and the insert path must be specified (**D-08**).

## 6. `signed_results`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `result_id` | `uuid` | NN | PK |
| `job_id`, `attempt_id` | `uuid`, `uuid` | NN | `uq_signed_results_job_id`; composite FK `(job_id, attempt_id)` → `execution_attempts` |
| `worker_id`, `listing_id` | `uuid`, `uuid` | NN | composite FK `(job_id, listing_id, worker_id)` → `jobs` (`uq_jobs_id_listing_id_worker_id`) |
| `key_id` | `uuid` | NN | composite FK `(worker_id, key_id)` → `worker_public_keys` `ON DELETE RESTRICT` |
| `schema_version` | `varchar(4)` | NN | `= '1'` |
| `outcome` | `varchar(8)` | NN | `SUCCESS`,`FAILED` |
| `failure_reason` | `varchar(16)` | nullable | NULL iff SUCCESS; else `WORKER_FAULT`,`JOB_FAULT` |
| `result_digest` | `varchar(71)` | NN | `'sha256:'` + 64 lowercase hex (CHECK on pattern) |
| `finished_at_wire` | `varchar(27)` | NN | signed string, never used for retention |
| `payload_jcs_raw`, `original_envelope_raw`, `signature_raw` | `bytea` ×3 | NN | `octet_length(signature_raw) = 64` |
| `verified_at`, `accepted_at` | `timestamptz(6)` | NN | trusted times |

Extra unique `uq_signed_results_job_id_result_id (job_id, result_id)` for the Phase 3 dispute FK. `uq_signed_results_job_id` already guarantees one result per Job.
[Δ] `ck_signed_results_outcome_reason`: `(outcome = 'SUCCESS') = (failure_reason IS NULL)`.
[Δ] The Inbox row that produced an accepted result keeps its own copy of the bytes; `signed_results.original_envelope_raw` equals it. A CHECK cannot compare across tables; `TX-FINALIZE` copies the Inbox bytes in the same statement set and the test asserts equality (**D-10**: do we store the bytes twice or reference the Inbox row; the design chooses twice because Inbox rows can purge on their own schedule; **TV5 ACK_COMPATIBLE**: keep the independent byte-exact copy, copy it in the same UoW from the selected Inbox row, assert byte and hash equality and `UNIQUE(job_id)`, never overwrite on replay or after an unknown `COMMIT`).

## 7. `job_reputation_contributions`

| Column | Type | Null / default | Constraint |
|---|---|---|---|
| `job_id` | `uuid` | NN | PK; FK → `jobs(id)` guarded cascade |
| `worker_id` | `uuid` | NN | composite FK `(job_id, worker_id)` → `jobs` (`uq_jobs_id_worker_id`) |
| `initial_category`, `effective_category` | `varchar(12)` | NN | `SUCCESS`,`WORKER_FAULT`,`NONE` |
| `corrected_by_dispute_id` | `uuid` | nullable | **no FK in Phase 2** (`disputes` does not exist) |
| `correction_version` | `smallint` | NN, `0` | transitional CHECK below |
| `applied_at`, `updated_at` | `timestamptz(6)` | NN | |

Transitional CHECK `ck_job_reputation_contributions_phase2_no_correction` (`P2B-DEC-01`, marked **TRANSITIONAL**):
`correction_version = 0 AND corrected_by_dispute_id IS NULL AND effective_category = initial_category`.
Phase 3 replaces this CHECK and adds the composite FK `(job_id, corrected_by_dispute_id) → disputes(job_id, id)`; the final CHECK in §9.2 allows `correction_version IN (0,1)`.

## 8. What this matrix deliberately does not do

- No seventh table, no `disputes`, no `retention_exceptions`, no placeholder.
- No change to `jobs`, `gpu_listings`, `worker_public_keys`, `worker_reputation_aggregates`, `simulation_references`, `audit_events`.
- No default numeric parameters (lease, retry, batch size); those come from ADR-005 and TV1 (`RUNTIME_BUDGET.md`).

## 9. Consumer ACK checklist (per column group)

| Consumer | Columns to confirm | Status |
|---|---|---|
| TV1 | outbox state/lease/retry columns and CHECKs (D-06); attempts deadlines | `PENDING_ACK` |
| TV3 | `result_inbox` insert columns, `received_at` default, hash CHECK, body bound (D-07, D-08) | `PENDING_ACK` |
| TV4 | `allocations` columns and counter reconciliation; optional active index (D-09) | `PENDING_ACK` |
| TV5 | `signed_results` columns, category CHECK values, contribution shape, payload contents (D-05, D-10) | `PENDING_ACK` |
