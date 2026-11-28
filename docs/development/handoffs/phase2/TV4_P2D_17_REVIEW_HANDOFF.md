# TV4-P2D-17 — Phase 2D review handoff

Snapshot from the PRs on 2026-11-28. Use this index for one coordinated review round while keeping changes and follow-up commits on their task branches. The SHA identifies the evidence reviewed here. Check the current head before posting a review or counting CI and approvals. An independent review or owner ACK remains scoped to its diff and revision.

## Review queue

| Task | Draft and source | Evidence already available | Outstanding acceptance |
|---|---|---|---|
| P2D-07 | [#64](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/64) `b54480b` | 27 focused, 872 backend passed, 372 skipped. [CI PASS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/46031890531). TV1 technical findings closed. | Independent review and separate merge decision. |
| P2D-08 | [#76](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/76) `51931bb` | 36 focused tests pass. | Real TX-ALLOCATE and D-IF-01/02. Stacked on #64, final main-target CI pending. |
| P2D-09 | [#77](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/77) `2dccaf7` | 36 focused tests; 881 backend passed, 372 skipped. | Concrete TV2 outcomes and real reconciliation. Stacked on #64, final main-target CI pending. |
| P2D-10 | [#75](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/75) `fe3a780` | 56 focused tests; 901 backend passed, 372 skipped. [CI PASS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/46127418933). [TV2 scoped review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/75#pullrequestreview-6097723123) found no blocker. | D-IF-03/04, SQL scan and TV1 runtime integration. |
| P2D-11 | [#78](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/78) `ade0491` | 315 passed, 4 PostgreSQL skipped. [CI PASS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/46128554722). | [TV2 P2](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/78#pullrequestreview-6097723413): add the valid readiness fixture and separate two-key quiesce/PATCH control before running real races. |
| P2D-12 | [#79](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/79) `b175b49` | 52 passed, 35 PostgreSQL skipped. [CI PASS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/46128560679). | [TV2 P2](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/79#pullrequestreview-6097723512): bind a valid readiness fixture for the contenders so the race cannot pass without reaching the lock. |
| P2D-13 | [#80](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/80) `b55ed39` | 10 assertion fixture tests pass. | TV1/TV2 Outbox + TV5 dispatch behavior. D-19 repair still gated. |
| P2D-14 | [#81](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/81) `f65cca4` | Rotation/expiry/rollback test plan. | TV1/TV2/TV3/TV5 readiness wiring, `D-IF-07` and native-role test fixtures. |
| P2D-15 | [#82](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/82) `bc79134` | 105 focused tests pass, including 73 new FIFO properties. | Stacked on #64. Reconcile and run final main-target CI after that base lands. |
| P2D-16 | [#83](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/83) `e8eda01` | 30 setup/baseline checks passed, 1 skipped. Backend: 855 passed, 372 skipped. | Disposable native-role PostgreSQL 16, accepted migrations/grants, actual ports and Phase 2 E2E evidence. |

## Coordinated review and evidence closure

- **TV1:** review policy/runtime boundaries across #75, #80, #82 and #83, then coordinate the merges. Check #64 before retargeting #76, #77 and #82 to accepted main and obtaining fresh evidence. Check CI directly on the proposed final commits.
- **TV2:** agree the actual allocation and reconciliation ports, review the native-role/race harness and the proposed Outbox snapshots, and confirm the accepted Alembic revision and privileges once available. [R1 #70](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/70) is not the TX-ALLOCATE implementation.
- **TV3/TV5:** review #81's signer controls and the source contract for expected Worker/key/fingerprint/expiry data. After that, apply the fixture controls to #78 and #79. TV5 also reviews Job and retry behavior in #79 and #80. [TV1's isolated Scheduler #62](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/62) and [Outbox #63](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/63) still need their own integration and review.
- **TV4:** accumulate review comments by task, fix each finding on its branch, and request re-review on the new SHA. Attach the exact integration tree, native role and revision evidence, run commands, CI links and any remaining BLOCKED/NOT_RUN cases once those tests are actually executed.

Live phase 2 race, DB and E2E evidence remains **NOT_RUN** for these preparations. Unit counts and Phase 1 CI do not certify allocation, stale-lease handling, key rotation or final release. Budgets, D-19/D-20 and unresolved port decisions follow their separate owner gates.
