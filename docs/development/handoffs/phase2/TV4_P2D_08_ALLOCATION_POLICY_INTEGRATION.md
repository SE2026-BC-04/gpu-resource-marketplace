# TV4-P2D-08 — FIFO policy integration notes

**Scope:** TV4 policy and boundary tests. Port integration is pending the actual TV2 `TX-ALLOCATE` implementation and the applicable interface ACKs. See Phase 2D §7.3, `D-IF-01/02`, and TV2 `B-IF-06`.

## Policy handover

1. TV1 obtains readiness before the transaction and invokes one complete synchronous TV2 UoW in its bounded worker. TV2 owns locks, readiness recheck and cleanup. The agreed lock direction is Worker advisory shared → Listing → Job.
2. During that transaction, TV2 selects the actual `QUEUED` head by `enqueue_seq` for the locked Listing. It can call the existing `assess_fifo_head(listing, head)` directly once the interface is agreed. `None` means the locked query found no head. A busy or unavailable query is handled by the transaction and must never masquerade as an empty queue.
3. Build the existing `ListingSnapshot` from Listing ID, status, total capacity and `allocated_gpu_count`; build the existing `JobSnapshot` from Job ID, Listing ID, status, enqueue sequence and requested GPUs. Pass only these scalars. Do not pass a queue, ORM row, Session, signer proof, or unlocked scan hint to this policy. These are current TV4-local classes; final cross-owner Python signatures remain subject to ACK.
4. `ELIGIBLE` allows TV2 to proceed with the remaining guards; it does not imply reservation or COMMIT. TV2 owns guarded state/counter changes, the Allocation/Attempt/Outbox inserts and all authoritative outcomes. TV1 consumes the result after transaction cleanup.

## Verification split

| Case | Unit evidence here | Outstanding real-port evidence |
|---|---|---|
| Exact fit or empty Listing | Policy assessment from one authoritative snapshot or `None` | One atomic reservation for a fitting head, no writes for empty. `P2D-TX-01` **NOT_RUN** |
| Oversized head | Assessment retains the blocked head; independent Listing can still be assessed | Insert a fitting later Job on the blocked Listing and prove both remain QUEUED; other Listing may progress. `P2D-TX-02/03`, `P2D-DRT-03` **NOT_RUN** |
| PAUSED, wrong Listing, or non-QUEUED head | No eligibility from these inputs | Recheck under real locks; both PAUSE/ALLOCATE commit orders and lock-busy rollback. `P2D-RACE-01/02`, `P2D-DRT-02` **NOT_RUN** |
| Concurrent reservations and partial write failure | Outside pure policy | Prove one graph, full rollback and `allocated_gpu_count = SUM(active allocations.gpu_count)` using a disposable PostgreSQL cluster. `P2D-TX-04/07` **NOT_RUN** |

When the concrete port is available, run the pending cases using its real native Manager role, accepted Alembic head, separate sessions and deterministic barriers. Record before/after Listing, Job, Allocation, Attempt and Outbox state. A pure-policy PASS is unit evidence only.
