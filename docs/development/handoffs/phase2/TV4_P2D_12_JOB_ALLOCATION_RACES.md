# TV4-P2D-12 — Job admission, cancellation and allocation races

**Status:** Test fixtures and acceptance cases prepared. `TX-ALLOCATE` is not available on `main`; the Phase 2 PostgreSQL cases below are `NOT_RUN`. TV2 owns allocation and locking, TV5 owns Job semantics, and TV4 owns the FIFO and capacity verification.

## Real-port cases

| Case | Required committed result |
|---|---|
| Cancel first (`P2D-RACE-03`, `P2D-TX-05`) | Use just the head Job so the later Allocate has no eligible Job. CANCELLED with no Allocation/Attempt/Outbox and no capacity delta. |
| Allocate first (`P2D-RACE-04`, `P2D-TX-05`) | Original head RUNNING; Cancel returns HTTP 409 `JOB_NOT_CANCELLABLE`; one linked Allocation/Attempt/Outbox and the exact counter delta. |
| Two Managers contend (`P2D-RACE-05`, `P2D-TX-04`, `DBTX-04-CAPACITY-RACE`) | Capacity 4; queue contains two distinct 3-GPU Jobs. First call commits the true head, second sees one free GPU and blocks the next head, or returns `LOCK_BUSY` in the separate lock-timeout case. Swap the roles of the two contenders and keep the same winner Job. |
| A real head Job lock is held (`P2D-DRT-02`, FIFO no bypass) | Seed enough GPUs for both Jobs. Hold only the head Job lock in a disposable fixture connection so an incorrect Job `SKIP LOCKED` would reach the later Job. Prove Allocate waits or returns `LOCK_BUSY` after rollback. No reservation or state transition for either Job in the timeout variant. The fixture transaction acquires no Listing lock afterwards. |
| Replay after PAUSE (`P2D-RACE-08`) | Accepted key and unchanged body return HTTP 200 with the original Job ID. New key returns paused conflict, and the old key with changed body remains an idempotency conflict. Job/reference counts and the allocation graph do not change. |
| Cancel while PAUSED (`P2D-TX-09`) | For a QUEUED Job, both Pause/Cancel commit orders preserve the right to cancel. With no allocation in this control, Listing remains PAUSED, Job CANCELLED, and allocation graph empty. |

## Fixtures and evidence

- The assertion in `backend/tests/phase2d_job_race_support.py` expects an isolated Listing whose baseline has no allocations. Capture all rows for the fixture's Jobs, including attempts and Outbox rows when testing zero effects. Read the snapshot in a fresh connection after worker transactions have closed. Check the exact counter against the sum of ACTIVE reservations, one matching graph for the original head, and unchanged QUEUED state for later Jobs. Compare complete before/after snapshots, Job/reference counts and resulting stable IDs for replay.
- Use the Phase 1 facilities `jobs_cancel_pg_support.ListingLockAttempt` and the transaction gates in `test_listing_submit_concurrency_postgres.py` as patterns. Exercise the native API and Manager roles in separate connections. In contention cases establish the intended lock order with gates and `pg_blocking_pids`, then release and join with bounds. Prove the waiter saw fresh state. Record role, Alembic head, actual commit order and resulting rows. Run deliberate lock-timeout cases separately from the successful wait/re-read test.
- The Phase 1 Submit and Cancel suites cover replay and cancellation guards independently. Snapshot unit tests validate the assertion helper only. Mark Phase 2 DB cases `NOT_RUN` until the actual TV2 port and disposable PostgreSQL run are available.
