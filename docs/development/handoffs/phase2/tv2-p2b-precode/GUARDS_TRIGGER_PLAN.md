# GUARDS_TRIGGER_PLAN — Phase 2B pre-code task TV2-P2B-03 (triggers)

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` · **Date:** 2026-11-08
**Rule (`P2B-OPEN-03B`):** PK/FK/UNIQUE/CHECK and narrow grants first; a trigger only where an *allowed* `UPDATE` must be limited to a legal transition. Triggers follow the existing style (D7): `SECURITY INVOKER`, `SET search_path = pg_catalog`, `REVOKE ALL ON FUNCTION ... FROM PUBLIC`, stable error `ERRCODE` and `CONSTRAINT` names so adapters can map errors without parsing messages. A superuser can disable triggers, so none of this replaces keeping superusers out of the runtime.

## 1. Decision per object

| Object | Grants already prevent | Gap that remains | Verdict |
|---|---|---|---|
| `execution_attempts` | any UPDATE/DELETE (no grant) | none for runtime roles | **no trigger**; test that `started_at/finish_due_at/hard_deadline_at` cannot change under either login |
| `allocations` | changing `job_id/listing_id/gpu_count/allocated_at` (Manager has `U(state, released_at)` only) | `RELEASED → ACTIVE`, `RELEASED → RELEASED` with a new `released_at`, `ACTIVE → ACTIVE` with `released_at` set (the CHECK blocks the last one, not the first two) | **trigger required**: `BEFORE UPDATE`, only `ACTIVE → RELEASED` once; any other change raises |
| `execution_outbox` | identity/payload changes (UPDATE column list) | illegal state edges (for example `EXHAUSTED → PENDING`) by a buggy Manager | **no trigger by default**; CAS (`WHERE lease_version = :observed ... RETURNING`) is the real guard and a trigger comparing versions cannot replace it. Use the CHECKs from the schema matrix (D-06). Revisit only if `P2B-DRT-08` finds a gap. |
| `result_inbox` | changing bytes/hash/binding/`received_at` (Manager has `U(state, rejection_code, processed_at)` only) | `ACCEPTED → REJECTED`, `REJECTED → ACCEPTED`, `ACCEPTED → PENDING` | **trigger required**: `BEFORE UPDATE`, only `PENDING → ACCEPTED` or `PENDING → REJECTED`; `rejection_code` set iff `REJECTED`; `processed_at` set |
| `signed_results` | any UPDATE (no grant) | owner/superuser mistakes only | **optional** defense in depth: `BEFORE UPDATE` always raises. **No `DELETE` trigger** (it would block the 23-day purge). Decide at review (D-15). |
| `job_reputation_contributions` | UPDATE (no grant) and the transitional CHECK | none in Phase 2 | **no trigger**; Phase 3 adds correction behavior |
| `worker_reputation_aggregates` (Phase 1) | wrong columns (Manager `U(successful_jobs, worker_fault_jobs, updated_at)`), negative values (CHECKs) | counters can be changed by any Manager statement; attribution to the right Job is a transaction rule, not a trigger rule | **no trigger**; coupling to the contribution insert is a UoW contract and test (`P2B-DRT-07`, `-10`) |
| `jobs` (D2), `gpu_listings` (D7), delete guard (D3) | — | — | **unchanged**; Phase 2 adds Manager coverage tests only (`QUEUED→RUNNING`, `RUNNING→COMPLETED/FAILED`) |

## 2. Required trigger contracts

### `allocations` guard (`BEFORE UPDATE`)
Allow exactly one update shape: `OLD.state='ACTIVE' AND NEW.state='RELEASED' AND NEW.released_at IS NOT NULL`, with every other column unchanged. Anything else raises `ERRCODE '23514'`, `CONSTRAINT 'ck_allocations_release_once'`. Combined with the CHECK `(state='RELEASED') = (released_at IS NOT NULL)` this makes release-once a DB fact. Decrementing the Listing counter and finalizing the Job stay in the same transaction (UoW, not trigger).

### `result_inbox` guard (`BEFORE UPDATE`)
Allow exactly `OLD.state='PENDING' AND NEW.state IN ('ACCEPTED','REJECTED')`, `NEW.processed_at IS NOT NULL`, `(NEW.state='REJECTED') = (NEW.rejection_code IS NOT NULL)`, all other columns unchanged. Anything else raises `ERRCODE '23514'`, `CONSTRAINT 'ck_result_inbox_transition'`.

## 3. Tests (each failing-first; `NOT_RUN`)

| ID | Statement | Required result |
|---|---|---|
| `P2B-GUARD-01` | API changes Manager-owned `allocations/execution_outbox/signed_results` data | `42501` |
| `P2B-GUARD-02` | Manager edits attempt times, Inbox bytes/hash/binding/`received_at`, signed-result bytes | `42501` (no grant) |
| `P2B-GUARD-03` | Manager releases an allocation twice, or sets `RELEASED → ACTIVE` | trigger error, counters unchanged |
| `P2B-GUARD-04` | stale Outbox ACK after `lease_version` moved | `UPDATE ... RETURNING` returns 0 rows |
| `P2B-GUARD-05` | duplicate `result_id`, same bytes then different bytes | idempotent, then conflict |
| `P2B-GUARD-06` | two concurrent finalizers | one terminal state, one release, one contribution |
| `P2B-GUARD-07` | `correction_version=1`, non-NULL dispute id, changed effective category | CHECK failure (`23514`) |
| `P2B-GUARD-08` | purge on a Phase 3 fixture | out of Phase 2 scope; only assert no unconditional `DELETE` trigger exists on `signed_results` |
| `P2B-GUARD-09` | new: Inbox `ACCEPTED → REJECTED` and `PENDING → PENDING` without `processed_at` | trigger error |
| `P2B-GUARD-10` | new: Manager `UPDATE gpu_listings SET allocated_gpu_count` still fires D7 `updated_at` and D7 identity guard | `updated_at` advances; identity change still blocked |

## 4. Not in scope

Cross-row conservation (`allocated_gpu_count = SUM(active allocations)`), replay fencing and once-only reputation are enforced by locked transactions and tested, not by triggers (a trigger cannot know which Job an aggregate delta belongs to).
