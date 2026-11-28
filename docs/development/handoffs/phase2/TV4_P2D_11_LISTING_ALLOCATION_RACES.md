# TV4-P2D-11 — Listing mutation vs allocation race preparation

**Status:** Phase 1 Listing guards can be exercised now. Phase 2 PostgreSQL races are `NOT_RUN` pending TV2's `TX-ALLOCATE` port, its accepted migration/grants and a disposable test database. The unit tests provide committed input snapshots to the existing Listing HTTP route through its test UoW. They exercise the guard, rather than simulating an allocation or row lock.

## Cases for the real port

| Schedule | Checks after both calls and fresh reads |
|---|---|
| PAUSE commits before Allocate (`P2D-RACE-01`, `P2D-TX-06`) | Listing PAUSED. Target Job remains QUEUED. Zero new Allocation, Attempt and Outbox. Counter unchanged. |
| Allocate commits before PAUSE (`P2D-RACE-02`) | Listing PAUSED. The Job stays RUNNING with one matching Allocation, Attempt and Outbox. Preserve the committed IDs and deadlines. |
| Downsize commits before Allocate (`P2D-DRT-08`) | Start at total 8, allocated 3 and the queued head requesting 4. PATCH total to 4. This satisfies both existing PATCH guards. Allocate sees one free GPU and blocks the same head with no allocation graph or counter change. |
| Allocate commits before Downsize (`P2D-DRT-08`) | Use the same seed. Allocation raises the counter to 7. PATCH to 4 is HTTP 409 `LISTING_CAPACITY_BELOW_ALLOCATED`; no partial PATCH fields change and the new graph remains intact. |
| Hardware PATCH vs an initially QUEUED head, both orders | HTTP 409 `LISTING_HARDWARE_LOCKED` while QUEUED or RUNNING. Rejected GPU model/VRAM and other submitted changes are never persisted. PAUSED is not an exception to the nonterminal guard. |
| RESUME with a retained QUEUED Job (`P2D-TX-11`) | The blocked Allocate against PAUSED writes nothing. RESUME changes Listing status only. A distinct later Allocate can succeed under its own checks. If RESUME wins before the competing Allocate, that Allocate can proceed after its locked recheck. |

## Deterministic setup and verification

- Reuse the Phase 1 Listing/Submit test gates in `backend/tests/test_listing_submit_concurrency_postgres.py` as a pattern for events before and after the Listing lock. Use native API and Manager sessions and separate connections. Observe the blocked backend with `pg_blocking_pids` as in `ListingLockAttempt` in `backend/tests/jobs_cancel_pg_support.py`. Signal from inside the real port once its Listing lock is held. This covers the production Worker-advisory → Listing → Job order without inventing a second allocator.
- For successful commit-order cases, wait for the intended blocked PID before releasing the winner and bound the gate and joins. Assert the blocked call rechecks state after the first commit. A forced timeout is a separate `LOCK_BUSY` case with rollback and no writes. Use events and DB lock observation to establish order.
- Record native roles, migration revision and committed before/after Listing, Job, Allocation, Attempt and Outbox identities. After each case require `0 <= allocated_gpu_count <= total_gpu_count` and equality with the sum of ACTIVE allocations. Keep all real-port cases `NOT_RUN` until executed.
