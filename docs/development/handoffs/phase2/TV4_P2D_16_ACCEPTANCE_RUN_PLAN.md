# TV4-P2D-16 — PostgreSQL and E2E acceptance run plan

**Status:** Preflight fixture is ready. PostgreSQL transaction races and Phase 2 E2E are BLOCKED pending the actual allocation/Outbox/finalizer ports, approved role grants and an available disposable PostgreSQL 16 environment. The R1 schema alone does not meet those prerequisites.

## Before running

1. Use the existing `test_database` / `db_safety` guard with a test-only loopback endpoint and distinct port, explicit opt-in and cluster/database markers. Use a fresh disposable instance or securely isolated fixture cluster. Leave all development and shared endpoints untouched.
2. Pin the candidate tree, expected single Alembic revision and the reviewed owner port SHAs. On open connections call `require_phase2d_acceptance_sessions` with the guarded operator connection, a native API session and two distinct native Manager sessions. It is a read-only preflight and refuses mismatches in login role, schema revision, server identity or backend PID. Keep fixture reset/DDL owned by the existing test harness.
3. Set test-only bounded barriers and a controlled trusted DB clock. Use separate actors plus an observer connection. Assert actual lock overlap, both commit orders and cleanup. Inject faults at clear boundaries and preserve the original IDs through retry/reconciliation. Keep all unknown deployment parameters pending their owner decisions.

## Batches and required evidence

| Cases | Acceptance evidence |
|---|---|
| `P2D-DRT-01..04,08,11`, `P2D-RACE-01..06,08` | Under real locks, confirm true FIFO head, PAUSE/PATCH/CANCEL orders, retained submit replay, independent progress and no duplicate reservation in two Manager sessions. Save before/after Job, Listing, Allocation, Attempt and Outbox snapshots. |
| `P2D-DRT-05,06,13` | Rollback after staged writes, known committed graph after a lost COMMIT ACK, and absence/partial/wrong-ID reconciliation. Preserve all four expected identities. Prove no second counter increment or attempts created blindly. |
| `P2D-DRT-07,15` | PAUSED retry preserves execution identity and deadline. Stale owner cannot ACK or reschedule a replacement lease. D-19 repair remains a separately gated scenario. |
| `P2D-DRT-09,10`, `P2D-SCHED-01..05` | More Listings than the test budget, scan wrap/restart, held head, bounded resources and unrelated due work under saturation. Record observed measurements without applying a production SLA. |
| `P2D-DRT-12`, `P2D-RACE-07` | Real Worker advisory lock contention, K1→K2 quiesce/restore and stale proof handling with owner-approved signer wiring. |
| `P2D-DRT-14` and Phase 2 E2E | Native API role cannot write allocation. Real Manager emits one execution graph, Simulator stays isolated, and callback/finalization release capacity exactly once. |

For each row record commit SHA, Alembic revision, native roles, branch/port pins, test command, actual status, bounds and observed outcomes. The phase 1 E2E and constraint suite are controls. The new unit suite validates setup checks, and does not execute Phase 2 PostgreSQL. Reuse the established suites and harnesses when wiring the real cases.
