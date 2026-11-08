# P2B_UOW_INTERFACES — Phase 2B pre-code task TV2-P2B-04 (`B-IF-01..09`)

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` — illustrative contracts, **not** approved Python signatures · **Date:** 2026-11-08
**Basis:** `HANDOFF_TV2_Phase2B_v1.1.md` §6, §8; `database-design.md` §11.3; `P2B-OPEN-04`. Ports are the only way other owners touch the database: TV4 pure FIFO, TV3 pure verifier and TV5 domain rules never open a `Session`; TV1 orchestration never shares a `Session` between tasks or threads.

## 1. Contract common to every port (`B-IF-09` part)

1. **One logical transaction = one UoW = one `Session`**, created and closed inside one synchronous executor call. No `await` while a UoW is open. Repositories take the `Session`/connection and never commit.
2. **Native identity check on entry**, same pattern as `repositories/jobs.py`: `current_user` ∈ the role's group/login set **and** `session_user` = the native login (`gpm_manager_app` for Manager ports, `gpm_api_app` for ingress), isolation `READ COMMITTED`, no owner session, no `SET ROLE` outside tests. The existing allow-lists are API-only; Manager ports get their own parameterized guard rather than loosening the API one.
3. **Lock order** (global, `database-design.md` §11.1): `gpu_listings → jobs → allocations/attempt → result_inbox (ordered received_at,id) → job_reputation_contributions → worker_reputation_aggregates`. Outbox transactions lock the Outbox row only. Locators (listing id for a job id) are unlocked reads, rechecked under lock. Never `SKIP LOCKED` on a Job head. Never take an Inbox row lock and then wait for Listing/Job.
4. **Clock:** every business timestamp is `clock_timestamp()` read **after** the locks it depends on, inside the transaction. Tests use a trusted test clock function, never `sleep`.
5. **Commit outcome:** classify with `commit_outcome.is_definite_commit_rollback`. Definite rollback ⇒ typed `Rolled back` result; `40003`, lost connection or unknown code during `COMMIT` ⇒ `CommitOutcomeUnknown`, **never retried blindly**: the caller (TV1) calls the port's `reconcile_*` read, which decides from DB state. Whole-UoW retry only for `40001`/`40P01` with a finite budget and **stable identifiers** (same `attempt_id`, `event_id`, `result_id`).
6. **Errors** are typed, secret-free and raised `from None`: `Noop`, `Blocked(reason)`, `Conflict`, `Ineligible`, `StaleClaim`, `DependencyUnavailable`, `CommitOutcomeUnknown`. No DSN, SQL, bytes, token or key in a message or log.
7. **No network I/O, no waiting on another task, no logging of payload bytes** while a UoW is open.

## 2. The nine interfaces

### `B-IF-01` — TV1 ↔ TV2: baseline and activation preflight
Provides: accepted `main` SHA, Alembic head, expected native roles/grants, a read-only `phase2_ready()` probe (R1 tables present, R2 grants match the checked-in expectation, two guard triggers installed) usable at Manager startup. Fail closed: not ready ⇒ Phase 2 loops do not start. Separate from `/health/ready` (Phase 1 readiness is not widened without the owner's L2 decision). Status: `PENDING_BASELINE`.

### `B-IF-02` — TV2 ↔ TV3 ↔ TV5: duplicate and collision semantics
`ingest_signed_result(raw: bytes, ctx: UntrustedContext, listing_hint: UUID) -> Stored(inbox_id, received_at) | ExactDuplicate | Collision | Ineligible(reason) | CommitOutcomeUnknown`.
Pre-conditions (outside the UoW, TV3): service token valid and direction correct, body within bound, envelope parses, claimed ids are UUIDv4. Inside: Listing → Job lock; probe (`INBOX_DUPLICATE_PRIVILEGES.md`); recheck Job `RUNNING` and the current attempt; `received_at < hard_deadline_at` (equality is late). Mapping: `Stored|ExactDuplicate → 202`, `Collision → 409`, `Ineligible(late|not_running|unbound) → no row, redacted log`. Unauthenticated or unparseable input never reaches the UoW.

### `B-IF-03` — TV2 ↔ TV3: restricted raw comparison
The probe path, grants and the SHA-256 vs function decision are in `INBOX_DUPLICATE_PRIVILEGES.md`. The port exposes only `ABSENT | SAME | DIFFERENT`; it never returns stored bytes.

### `B-IF-04` — TV2 ↔ TV3: `received_at` and trusted identity
`received_at` is a column default `clock_timestamp()` evaluated on insert after the Job lock; the API has no INSERT grant on it. Identity of the caller is the Simulator service token handled by TV3; the worker/listing identity comes from the locked Job row, never from the body. A replay never rewrites `received_at`.

### `B-IF-05` — TV1 ↔ TV2 ↔ TV3 ↔ TV5: candidates, batches, progress
`iter_eligible_inbox(job_id, cursor: (received_at, inbox_id) | None, bound: int) -> Batch(candidates, has_more, scanned_through)`. Order `(received_at, id)`, only `state='PENDING'` and `received_at < hard_deadline_at`; the read runs **after** the Listing/Job locks of the calling finalization UoW or in a locator-only read followed by a recheck. `has_more=True` forbids fallback. The progress marker is the cursor value (data, not process memory) so a restart resumes. After a terminal commit a housekeeping call marks remaining non-winner rows `REJECTED` (reason `NOT_SELECTED`/`ALREADY_TERMINAL`) without any business effect.

### `B-IF-06` — TV1 ↔ TV2 ↔ TV4 ↔ TV5: allocate and Outbox
- `allocate_one_listing(listing_id) -> Allocated(job_id, attempt_id, event_id) | Blocked(reason ∈ LISTING_NOT_ACTIVE, HEAD_DOES_NOT_FIT) | Noop(NO_QUEUED_HEAD) | CommitOutcomeUnknown`. Lock Listing; require `ACTIVE`; select the real FIFO head `ORDER BY enqueue_seq LIMIT 1 FOR UPDATE` (no `SKIP LOCKED`); if `total - allocated < head.requested` return `Blocked`, **never** a smaller later Job; `t = clock_timestamp()` after both locks; guarded counter update (`allocated + n <= total`); Job `QUEUED→RUNNING` with `started_at = t` (`WHERE status='QUEUED'`, row count must be 1); insert `allocations`, `execution_attempts` (`finish_due_at = t + duration`, `hard_deadline_at = finish_due_at + 120 s`), `execution_outbox` (stable `event_id`, immutable payload). One COMMIT. FIFO policy inputs (eligibility, fairness) come from TV4 as data; the port does not choose a different head.
- `claim_due_outbox(batch_limit, owner) -> list[FencedClaim(event_id, attempt_id, payload, observed_lease_version)]`: Outbox-only, `UPDATE ... SET state='CLAIMED', lease_owner, lease_until = now+30 s, lease_version = lease_version + 1 WHERE event_id IN (due and (state='PENDING' or lease expired)) RETURNING ...`. No Listing/Job lock. HTTP happens after COMMIT.
- `ack_or_retry(event_id, observed_lease_version, owner, response_class) -> FencedUpdated | StaleClaimNoop | CommitOutcomeUnknown`, `UPDATE ... WHERE event_id = :id AND lease_version = :observed AND lease_owner = :owner`; zero rows = `StaleClaimNoop`. `202 ACK` sets `ACKED` and `acked_at`; it never terminalizes the Job. Backoff `2,4,8,16,30,30…` s and the repair probe at `finish_due_at + 10 s` come from ADR-005 as parameters, not constants in the port. A PAUSED Listing does not stop retrying an already-allocated event.

### `B-IF-07` — TV1 ↔ TV2 ↔ TV5: finalization and fallback
- `finalize_one(job_id, verified: VerifiedReceiptIdentity) -> Finalized(job_id) | AlreadyTerminalNoop | RejectedCandidate | CommitOutcomeUnknown`. Locator read; Listing → Job → Allocation lock; recheck `RUNNING`; load the Inbox row by id and **recheck bytes, hash, bound context and `received_at < hard_deadline_at` from the database, not from the verifier's memory**; one COMMIT writes `signed_results`, Job terminal (`COMPLETED`, or `FAILED` with `WORKER_FAULT`/`JOB_FAULT`), allocation `RELEASED`, Listing counter `-= gpu_count`, Inbox `ACCEPTED`, and per TV5's policy the contribution (`SUCCESS`, `WORKER_FAULT`, or `NONE` for `JOB_FAULT`) plus the aggregate delta (`+1 successful` / `+1 fault` / `0`). Existing terminal Job or contribution ⇒ `AlreadyTerminalNoop`, no second effect.
- `deadline_fallback(job_id, scan_complete: CompleteScanProof) -> SystemFaultFinalized | ContinueCandidateScan | AlreadyTerminalNoop`. Only after the whole on-time candidate scan is proven complete **under the same locks**; `FAILED/SYSTEM_FAULT`, one release, **no** signed result, **no** contribution, **no** aggregate change. A rejected receipt and a missing receipt are distinguished in the Inbox state, not guessed.
- The classification (what is `WORKER_FAULT`, what is `NONE`) is TV5's; TV2 executes it atomically and does not reinterpret it.

### `B-IF-08` — TV2 ↔ TV3 ↔ TV5: keys
`signed_results (worker_id, key_id)` FKs to `worker_public_keys ... ON DELETE RESTRICT`, so a retired key still verifies old receipts and cannot be deleted while a receipt references it. Key readiness, rotation and compromise rules are owner decisions (D-03); the DB contract here is only "historical key row exists and is referenced".

### `B-IF-09` — TV1 ↔ TV2: environment and budgets
Disposable PostgreSQL with `db_safety` markers; `restored_login_role_credentials` around any test that sets role passwords; `lock_timeout`/`statement_timeout` set per UoW (values from `RUNTIME_BUDGET.md`, none invented); bounded executor and pool; shutdown waits for the in-flight UoW to commit or roll back. Status: `PENDING_PARAMS / TEST`.

## 3. Data returned to callers (for the ACKs)

`Allocated`, `FencedClaim`, `Batch`, `Finalized` carry identifiers and timestamps only. They never carry `dispatch_payload` contents beyond what TV1 must send, raw envelope bytes, signature bytes, public key bytes or protected-reference fields.

## 4. ACK matrix

| Interface | Producer | Consumers to ACK (by file SHA) | Status |
|---|---|---|---|
| B-IF-01 | TV2 | TV1 | `PENDING_BASELINE` |
| B-IF-02, 03 | TV2 | TV3, TV5 (+ lead for D-01) | `PENDING_ACK` |
| B-IF-04 | TV2 | TV3 | `PENDING_SQL_DESIGN` |
| B-IF-05 | TV2 | TV1, TV3, TV5 | `PENDING_ACK` |
| B-IF-06 | TV2 | TV1, TV4, TV5 | `PENDING_ACK` |
| B-IF-07 | TV2 | TV1, TV5 | `PENDING_ACK` |
| B-IF-08 | TV2 | TV3, TV5, lead | `PENDING_ACK / OWNER_DECISION` |
| B-IF-09 | TV2 | TV1 | `PENDING_PARAMS / TEST` |
