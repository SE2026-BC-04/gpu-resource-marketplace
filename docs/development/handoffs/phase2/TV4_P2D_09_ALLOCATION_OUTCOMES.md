# TV4-P2D-09 — Allocation outcomes and reconciliation preparation

**Status:** TV4 unit adapter only. Nothing here freezes the shared Python API. TV2 owns the authoritative `B-IF-06` port, result types and transaction state. TV1 owns scheduling and reconciling through that port. See Phase 2D §7.3 and `D-IF-01/02`.

## Policy handover

| TV4 assessment | Adapter output through the caller's constructor |
|---|---|
| `EMPTY` | `Noop(NO_QUEUED_HEAD)` |
| `HEAD_DOES_NOT_FIT` | `Blocked(HEAD_DOES_NOT_FIT)` |
| `LISTING_NOT_ACTIVE` | `Blocked(LISTING_NOT_ACTIVE)` |
| `ELIGIBLE` | No policy no-write result. TV2 still owns all guards, writes and the COMMIT decision. |

TV2 can inject the concrete constructors once the interface is agreed. Return a business outcome to TV1 only after the UoW has closed. Its port still owns `SIGNER_NOT_READY`, `LISTING_NOT_FOUND`, `LOCK_BUSY`, `Allocated`, `CommitOutcomeUnknown` and a sanitized `DependencyUnavailable`. A lock-busy result indicates rollback and can be reconsidered on a later pass. A dependency error is not an empty queue. Neither case should cause a FIFO bypass or an immediate local retry.

## Reconciliation test cases for the real port

Start from the original `(listing_id, job_id, attempt_id, event_id)` reported with an unknown COMMIT. Compare with a fresh read through TV2's actual port; record calls to TV1's allocation boundary and verify no second reservation while the outcome is uncertain. Use trusted before/after snapshots from a disposable PostgreSQL cluster.

| Case | Expected authoritative result and follow-up | Status |
|---|---|---|
| COMMIT succeeded, response lost and the active graph matches all four IDs | `AllocationCommitted`; one durable reservation/Attempt/Outbox graph. No second allocation. | `NOT_RUN` |
| The same committed graph is already terminal and allocation is RELEASED | `AllocationCommitted`; terminal state does not undo earlier COMMIT. No reallocation. | `NOT_RUN` |
| COMMIT did not occur, whole graph absent and Job remains QUEUED | `AllocationNotCommitted`; any later retry follows the separately agreed TV1 policy. | `NOT_RUN` |
| Graph is incomplete, has an identity mismatch in any of the four IDs, or Job advanced without a graph | `AllocationUnknown`; escalate. No retry, new IDs or second counter delta. | `NOT_RUN` |
| Reconcile read unavailable | Preserve uncertainty and surface a sanitized error. Do not allocate again based on a failed read. | `NOT_RUN` |

These cases target `P2D-DRT-06/13` and `P2D-TX-07/08`. Unit evidence for reason mapping is separate from a real lost-COMMIT, connection failure, native role, or rollback verification. DB and runtime cases are pending the TV2 port and disposable environment.
