# RUNTIME_BUDGET — Phase 2B pre-code task TV2-P2B-06 (`B-IF-09`)

**Owner:** TV2 with TV1 · **Status:** `PENDING_PARAMS` · **Date:** 2026-11-08
`P2B-OPEN-04` says pool, executor, timeout and shutdown numbers are **not approved** and must come from measurement. This file lists the knobs, their owner, the relations they must satisfy and how each will be measured. **It contains no numeric proposal for any measured knob.**

## 1. Fixed by ADR-005 (not tunable here)

Outbox lease 30 s; retry backoff `2, 4, 8, 16, 30, 30, …` s; poll default 2 s; connect/total HTTP timeouts 2 s / 5 s; missing-receipt repair probe at `finish_due_at + 10 s`; `hard_deadline_at = finish_due_at + 120 s`. No parameter may be changed to relieve DB saturation (handoff §6.4).

## 2. Knobs to be measured

| Knob | Owner | Relation it must satisfy | Measurement |
|---|---|---|---|
| executor worker count (sync DB work) | TV1 | ≤ pool capacity; finalization must keep a reserved share | `P2B-DRT-14` with slow UoWs |
| executor queue bound (waiting work) | TV1 | bounded, drops/backs off instead of growing; metric on depth | same |
| SQLAlchemy pool size / max overflow / pool timeout (Manager) | TV2 + TV1 | `pool_size + overflow` ≥ workers actually holding a connection; pool timeout < the loop's deadline budget; API pool sized separately | same, per process |
| `lock_timeout` | TV2 | < `statement_timeout`; short enough that a missed lock fails a UoW rather than a loop | lock-wait histogram in race tests |
| `statement_timeout` | TV2 | a fixed bound per statement, **independent of `hard_deadline_at`** (P1-02): processing an already-committed on-time Inbox candidate is required even after `now() > hard_deadline_at` (restart, backlog), so the wall-clock deadline is never a processing budget. It must be < the graceful-shutdown budget and, for ingress, short enough that the API request budget is met | slow-statement injection; post-deadline finalization of an on-time candidate after a simulated restart |
| candidate batch bound (Inbox) | TV2 + TV3 + TV5 | bounded memory/time; `has_more` blocks fallback | `P2B-DRT-06` |
| Outbox claim batch limit | TV1 | claim transaction short; lease (30 s) ≫ batch HTTP time or claims are renewed | dispatcher test with stale lease |
| Scheduler scan size (Listings per pass) | TV1 + TV4 | no Listing starved; blocked head does not stop other Listings | `P2D-TX-03` |
| graceful-shutdown budget | TV1 | ≥ longest UoW (`statement_timeout` + commit) so in-flight UoWs resolve | `P2B-DRT-11`, `P2B-UOW-05` |
| retry budget for `40001`/`40P01` | TV2 | finite; stable identifiers; never for `23xxx`/`40003` | `P2B-UOW-04` |

## 2.1 Admission deadline vs processing budget (P1-02)

- **Admission deadline:** applies only to *new* callbacks. A receipt is admissible iff its **stored** `received_at < hard_deadline_at` (equality is late). It is enforced in the ingress UoW and re-checked on the stored value in finalization.
- **Processing budget:** the lock/statement/pool limits above bound the *work*, not the *eligibility*. Finalization of an on-time candidate that was committed before the deadline is not abandoned because the wall clock has passed `hard_deadline_at`.
- **Fallback:** `deadline_fallback` needs `now() >= hard_deadline_at` **and** no on-time `PENDING` candidate. A transiently unverifiable `PENDING` candidate blocks `SYSTEM_FAULT` until it is settled or the dependency recovers (`P2B-DRT-21`); the loop keeps retrying it within the processing budget.
- Tests: `P2B-DRT-10` and `-21` include "restart after `hard_deadline_at`, committed on-time candidate still finalizes".

## 3. Structural rules (decided, not numbers)

1. One `Session` per UoW, closed inside the same executor call; a UoW never spans an `await`.
2. Scheduling, dispatch and finalization are independent loops; saturation of one must not starve finalization. Preferred shape: finalization gets a guaranteed share (separate executor or reserved connections); to be confirmed by `P2B-DRT-14`.
3. No HTTP, no sleep and no waiting on another task while a UoW is open.
4. `asyncio` cancellation does not prove the worker thread or the PostgreSQL transaction stopped; shutdown waits for the in-flight UoW outcome and does not dispose the engine early.
5. The API process has its own pool; ingress UoWs are short (lock, probe, insert, commit) and must not share a pool with Manager work.

## 4. Evidence plan

Pool and executor utilization, queue depth, lock-wait and statement times from the `P2B-DRT-14` run on the disposable cluster at the accepted 736-VU profile where it applies (that profile and C1 evidence are not done and are not claimed). Numbers are recorded here with Git SHA and cluster description only after they are measured; until then every row stays `PENDING_PARAMS`.
