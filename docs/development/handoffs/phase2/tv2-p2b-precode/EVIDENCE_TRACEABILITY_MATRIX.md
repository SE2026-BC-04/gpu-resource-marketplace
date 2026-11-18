# EVIDENCE_TRACEABILITY_MATRIX — Phase 2B pre-code (lead revision request P2-06)

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` (TV1, TV3, TV5; the lead for D-04) · **Date:** 2026-11-19
**Basis:** `PHASE2_SCHEMA_MATRIX.md` §2–§7, `PHASE2_ROLE_GRANTS.md`, `P2B_UOW_INTERFACES.md` (B-IF-02, -04, -06, -07, -08), Phase 2A (#47 @ `001619d`) Blockchain Option A.
**This is a design matrix, not DDL and not evidence that anything works.** No table, column, grant, migration or code is added by this file. Every proof listed here is `NOT_RUN` (`P2B-DRT-38`).

**Scope boundary (Phase 2B).** Evidence stays off-chain in PostgreSQL. There is **no** blockchain table, wallet, key custody, Solidity contract or Node bridge in Phase 2B. Nothing sensitive is ever published on-chain. Later EVM anchoring (Phase 4 only) may publish identifiers and hashes that already exist after COMMIT; it never reads or writes the Phase 2B tables through a new path and it is not decided here.

## 1. The chain

`Worker → Listing → Job → Attempt (+ Outbox event) → Result Inbox → Signed Result → Reputation Contribution → Aggregate`

Every hop is a join on identifiers that PostgreSQL already enforces with a foreign key or unique constraint. A reviewer or the Phase 3 Dispute Mock can walk the chain from a `job_id` without any application state.

## 2. Matrix

| # | Link (from → to) | Link ids and constraint | Immutable hash / digest | Trusted time source | Producer (writer) → consumer (reader), PG privileges | Retention | Dispute Mock support |
|---|---|---|---|---|---|---|---|
| 1 | Worker → Listing → Job | `gpu_listings.worker_id` (D7 identity guard: immutable); `jobs(listing_id)`, `jobs(worker_id)`; unique `uq_jobs_id_listing_id_worker_id` | none Manager-readable (`request_sha256` is API-side; the Manager has no `SELECT` on it) | `jobs.submitted_at`, DB time in the API UoW; `started_at`, `terminal_at` from Manager `clock_timestamp()` after the locks | API (submit, cancel) and Manager (`QUEUED→RUNNING`, terminal edges, D2 trigger) → both read column-wise (`PHASE2_ROLE_GRANTS.md` §2) | Job lifecycle; guarded delete 552 h after `terminal_at` (Phase 1 D3 trigger); no runtime `DELETE` | identifies who ran what and for whom |
| 2 | Job → Attempt | `execution_attempts.job_id` FK, `uq_execution_attempts_job_id`; `uq_execution_attempts_job_id_attempt_id` is the target of the composite FKs below | none stored; the dispatch body is derived deterministically from the Outbox payload | `started_at = t`, `finish_due_at = t + duration`, `hard_deadline_at = finish_due_at + 120 s`, all from **one** `clock_timestamp()` after the Listing/Job locks (`TX-ALLOCATE`) | Manager `INSERT` (no `UPDATE`/`DELETE`) → API `R(job_id, attempt_id, hard_deadline_at)`, Manager `R(all)` | follows the Job (guarded cascade) | the deadline against which lateness is judged |
| 3 | Attempt → Outbox event | `execution_outbox.attempt_id` FK; `uq_execution_outbox_attempt_id_event_type`; `event_id` = payload `outbox_event_id` | `dispatch_payload` is immutable jsonb (ten keys, `ck_execution_outbox_payload_shape`); no digest column; `canonical_dispatch_body` bytes are reproducible from it | `created_at` DB time; `next_retry_at`, `acked_at`, lease columns from Manager time; delivery facts only | Manager `INSERT`/`UPDATE` (column list in `PHASE2_ROLE_GRANTS.md` §1) → Manager | follows the Job | proves what the Simulator was told, once, with the same bytes on every resend |
| 4 | Attempt → Result Inbox | composite FK `(bound_job_id, bound_attempt_id)` → `execution_attempts(job_id, attempt_id)`; `result_id` unique (`uq_result_inbox_result_id`) | `envelope_sha256 = sha256(original_envelope_raw)` by CHECK (32 bytes); exact wire bytes retained | `received_at DEFAULT clock_timestamp()` read inside the ingress UoW after the Job lock; the API has no `INSERT` on it and reads it only through `RETURNING` (D-17) | API `I(result_id, claimed_*, bound_*, original_envelope_raw, envelope_sha256)` + `R(id, received_at)` + the restricted duplicate probe → Manager `R(all)`, `U(state, rejection_code, processed_at)` | Inbox rows purge on their own schedule: a Phase 3 decision, not decided here | the first on-time candidate and every rejection code remain visible until purge |
| 5 | Result Inbox → Signed Result | `signed_results.result_id` = Inbox `result_id`; `uq_signed_results_job_id`; composite FKs `(job_id, attempt_id)` → attempts, `(job_id, listing_id, worker_id)` → jobs, `(worker_id, key_id)` → `worker_public_keys` `ON DELETE RESTRICT` | `original_envelope_raw` copied from the Inbox row in the same UoW and byte/hash-equal to it; `payload_jcs_raw` and `signature_raw` equal `extract_signed_parts_v1` of those bytes; `result_digest` is the signed value | `verified_at`, `accepted_at` from Manager `clock_timestamp()` in the Finalization UoW; `finished_at_wire` is a signed string and is never used for admission or retention | Manager `INSERT` only (no `UPDATE`/`DELETE`) → Manager; no API access in Phase 2 (a safe projection is a separate design) | guarded delete with the Job after 552 h (Phase 3 purge path); retired key rows are kept while referenced | the signed bytes, the key that verified them and the instant accepted |
| 6 | Signed Result → Reputation Contribution | joined by `job_id` (`uq_signed_results_job_id` ⇒ at most one result per Job; contribution PK `job_id`; composite FK `(job_id, worker_id)` → jobs); no separate `result_id` column | none; the category is derived by TV5's policy | `applied_at`, `updated_at` from Manager `clock_timestamp()` in the same UoW | Manager `INSERT` only (`correction_version`, `corrected_by_dispute_id` stay at defaults) → Manager | follows the Job | `initial_category` and `effective_category` (Phase 3 can correct); `SYSTEM_FAULT` and `JOB_FAULT` write no signed result or contribution (`NONE` writes a contribution with no counter change) |
| 7 | Contribution → Aggregate | `worker_reputation_aggregates.worker_id`; per-Job attribution is the contribution row, not an aggregate column | none; counters are derivable: `successful_jobs`/`worker_fault_jobs` equal the count of `SUCCESS`/`WORKER_FAULT` contributions per Worker | `updated_at` advanced from DB time only in the first-contributing UPSERT (D-11/D-12) | Manager `UPSERT` (grant `I` + `U(successful_jobs, worker_fault_jobs, updated_at)`) → API reads through the Listing projection | Worker lifetime | the reconciliation `aggregate = COUNT(contributions)` is a Dispute Mock/audit check |

## 3. Trusted time rule

Every business instant in the chain is a PostgreSQL `clock_timestamp()` read **inside the transaction after the locks it depends on**, or a column default evaluated at insert in the same transaction. Wire strings (`finished_at_wire`, the RFC 3339 strings inside `dispatch_payload`) are signed or derived values: they are never used to admit a callback, to decide lateness or to set retention. Tests compare instants, not text (`P2B-DRT-17`, T-D1/T-D2).

## 4. Dispute Mock support (Phase 3, design only)

For a `job_id` the Dispute Mock needs, and the chain provides: the Job and its Worker/Listing (row 1), the Attempt and its deadlines (2), the dispatch that was sent (3), the on-time candidates and rejection codes (4), the accepted bytes with the verifying key row (5) and the contribution it produced (6). `corrected_by_dispute_id` has no FK in Phase 2 (`disputes` does not exist); Phase 3 adds it. The protected oracle (`simulation_references`) is **not** in this chain and the Manager has no `SELECT` on it (D-14); only the Phase 3 dispute workflow reads it.

## 5. What this matrix deliberately does not do

- No new table, column, index, grant or trigger; the optional repair columns of `B-IF-06R` are separate and unapproved.
- No on-chain anchor design. If Phase 4 anchors anything it must come from the already published identifiers and digests (`result_id`, `envelope_sha256`, `result_digest`) after COMMIT, and never from raw envelopes, signatures, Worker keys, personal data or the oracle. Which fields, if any, is a Phase 4 owner decision.
- No retention numbers beyond what Phase 1 already enforces (guarded delete 552 h after `terminal_at`); Inbox and `signed_results` purge policy is Phase 3.
- No new audit write (see §6).

## 6. D-04 — Manager audit writes: options and audit-coverage impact (TV2 presents, TV1 / the lead decide; **no GRANT is changed**)

Baseline: the Manager has **no** `audit_events` privilege. `audit_events` has no FKs (rows outlive Jobs), `actor_kind IN ('USER','SERVICE')`, `outcome IN ('SUCCESS','REJECTED','ERROR')`, `metadata_redacted` a JSON object; the API inserts through `repositories/audit.py` without `RETURNING`.

| Option | Grant | Audit coverage | Risk and cost |
|---|---|---|---|
| **0 — none (baseline)** | none | no `audit_events` row for `ALLOCATE`, `FINALIZE`, `SYSTEM_FAULT`, repair; the business effects remain in the chain above (Job/Attempt/Allocation/Signed Result/Contribution rows give who, what, when); not durable: `Blocked`/`Noop` outcomes, repair resends, ingress `4xx` (redacted structured log only); no queryable Manager actor or correlation id | no new privilege; the Manager stays unable to write rows that look like user actions |
| **1 — column-limited `INSERT`, every Phase 2 event** | Manager `I(actor_kind, actor_ref, correlation_id, subject_type, subject_id, event_type, outcome, metadata_redacted)` only; no `SELECT`/`UPDATE`/`DELETE`; no `RETURNING` | allocation, finalization, rejection verdicts, fallback, repair claims recorded with a correlation id, in the **same UoW** as the effect (atomic) | one more `INSERT` per UoW; a grant cannot restrict `event_type` or `actor_kind`, so the adapter allow-list (`actor_kind='SERVICE'`, fixed event types) and a native-role test are the only guard; an audit insert failure now fails the business UoW unless TV1 decides best-effort (not atomic) |
| **2 — same grant, terminal and exceptional events only** | as option 1 | `FINALIZE`, `SYSTEM_FAULT`, verdict `REJECTED`, repair claim; allocation is not audited (the Allocation/Attempt rows are its record) | lower volume; leaves allocation `Blocked`/`Noop` outcomes uncovered |
| **3 — separate Manager audit table** | new table | any | **not available in Phase 2B**: no seventh table (`PHASE2_SCHEMA_MATRIX.md` §8) |
| **4 — `SECURITY DEFINER` function limited to Phase 2 event types** | `EXECUTE` to `gpm_manager_rw`, new function owner | any | adds an owner role and a definer surface (the same objection as `INBOX_DUPLICATE_PRIVILEGES.md` Option B); not recommended |

If TV1 or the lead picks 1 or 2, the changes are one row in `PHASE2_ROLE_GRANTS.md` §2, one expected-grant entry and negative cases in `P2B-DRT-02`/`G-02`/`G-03`, and an audit-failure policy in the UoW contracts; none is made now. TV2 makes no recommendation beyond the privilege and coverage facts above.

## 7. Consumer ACK checklist

| Consumer | What to confirm | Status |
|---|---|---|
| TV1 | the chain, the time rule, D-04 option choice and audit-failure semantics | `PENDING_ACK` |
| TV3 | rows 4 and 5 (hash/CHECK, extractor equality, key FK) | `PENDING_ACK` |
| TV5 | rows 5–7 (signed result, contribution categories, aggregate derivability) | `PENDING_ACK` |
| lead | D-04; the "no blockchain artefact in 2B" boundary | `PENDING_DECISION` |
