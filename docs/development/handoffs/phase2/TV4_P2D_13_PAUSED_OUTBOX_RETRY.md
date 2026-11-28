# TV4-P2D-13 — PAUSED dispatch retry acceptance

Status: test assertions prepared. Runtime uses the TV1 dispatcher and TV2 Outbox under ADR-005. The conditional repair path D-19/B-IF-06R stays separate. No port signature or new repair rule is introduced.

| Case | Required observation |
|---|---|
| Normal retry after lost dispatch ACK (`P2D-DRT-07`) | Start with one committed RUNNING Attempt and lose the dispatch response. Commit PAUSE before the due retry. Retry the original event/Attempt and immutable payload. Compare the committed execution snapshots before retry and before finalization: same Job, one Allocation, same counter and unchanged deadlines. A dispatch ACK is transport evidence only. |
| Stale settlement (`P2D-DRT-15`, `DBTX-07-OUTBOX-FENCE`) | Dispatcher A claims v, the trusted clock passes lease expiry, and B takes v+1. Gate A's settlement until B commits. A's ACK and retry settlement affect zero rows. B's version, owner, deadlines, state and counters remain intact. Also test wrong-owner-only and stale-version-only inputs independently. |
| PAUSED and QUEUED, no committed Attempt (`P2D-TX-11`) | Dispatcher has no committed event to send. No allocation, Attempt, Outbox or counter change. |
| After terminalization or at hard deadline (`P2D-TX-12`) | No resend or attempt revival when terminal or at/after the dispatch hard deadline. Verify no change to the terminal result and no second release or reservation. |
| ACKED missing-receipt repair (`P2D-TX-10`) | Use the separate repair claim/fence only after D-19 authorization and implementation. Its probe is `finish_due_at + 10s`. Keep the original attempt, event, payload and hard deadline (`finish_due_at + 120s`); ordinary claims never take ACKED. This case remains BLOCKED. |

Capture snapshots from fresh reads across real commits. The assertion fixture compares exact payload identity via untouched wire bytes when available or a consistent encoding of the stored immutable payload. Keep the lease snapshot separate from execution identity. Read all rows for the Job, not just the expected allocation. Use a controlled DB clock and barriers, and verify the HTTP call is outside all UoWs. Real native-role DB and transport acceptance is NOT_RUN. Unit checks cover the assertion fixture.
