# VT-090 Mutation Experiment

**Target:** `frontend/src/ui/jobs/JobsPage.tsx` — retry exhaustion boundary in the selected Job status-read effect.

**Final intended predicate:** `consecutiveFailures > MAX_CONSECUTIVE_STATUS_READ_FAILURES`, where the maximum consecutive automatic retries is 3.

**Code baseline for final experiment:** `ae669194f02a56de7638472cd71b94b7483a66c0` (the same predicate is present in the final branch HEAD).

## Experiment

The boundary test `allows the fourth poll after exactly three transient failures` first passed against the intended predicate. It asserts that after three failed reads and retry delays of 1, 2 and 4 seconds, a fourth read is still attempted and can return `RUNNING`.

The operator was then mutated from `>` to `>=` in an uncommitted one-line edit. The mutation was saved in `evidence/mutation-operator-diff.txt`; it was not committed.

| Run | Command/result | Evidence |
|---|---|---|
| Original predicate | Focused boundary test: PASS, exit 0 | `evidence/mutation-original-pass.log` |
| Mutated predicate `>=` | Focused test: FAIL, exit 1; expected `getJob` 5 calls, observed 4 because polling stopped after failure 3 | `evidence/mutation-mutant-failure.log` and `evidence/mutation-operator-diff.txt` |
| Restored predicate `>` | Focused boundary test: PASS, exit 0 | `evidence/mutation-restored-pass.log` |

The deliberate mutation has been restored. A source diff check confirms no mutation remains. The mutation was killed by the exact threshold assertion, not by setup or compilation failure.

### Supplemental command-recorded replay (2026-11-11)

The historical evidence above remains unchanged. A supplemental replay on source commit `805a4e53326fc0789654242de288199cf5ff7765` records the exact command: `& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run src/ui/jobs/JobsPage.test.tsx -t 'allows the fourth poll after exactly three transient failures' --reporter=dot`. With the original predicate, 1 focused test passed (exit 0). With the temporary `>=` mutant, it failed the assertion expecting 5 GETs but observed 4 (exit 1, **KILLED**). The source was restored byte-for-byte; SHA-256 before/after was `A534A3B2B24131F27A91A2F15F6546A1F35A81F33B83867C0C54EFF0BD8A0DC8`. Full output is in `evidence/mutation-boundary-operator-rerun.log`.

## E2 review-requested mutation trials

Both temporary mutations were applied only to `frontend/src/ui/jobs/JobsPage.tsx` on source commit `6daeea368e6add6aefefe8540e637f938698cba4`, tested separately, and restored byte-for-byte after each run. No mutation is present in the final commit.

| Mutation | Focused test and assertion | Actual result | Evidence |
|---|---|---|---|
| Poll interval `2000` → `1000` | `polls a selected queued Job at the 2-second boundary and displays RUNNING`; expects one GET through 1999 ms, then exactly two at 2000 ms | **KILLED**, exit 1; at 1999 ms expected 1 call, received 2 | `evidence/mutation-poll-interval.log` |
| Remove `stopDetailPollingRef.current?.()` from `beginReconciliation` | `VT090-P1-02 aborts and ignores a late poll response during Cancel reconciliation, then resumes`; expects the resumed poll to remain single-flight (`maxActiveGets === 1`) | **KILLED**, exit 1; observed `maxActiveGets=2`, proving old and replacement GETs overlapped without the stop/abort call | `evidence/mutation-cancel-reconciliation-abort.log` |

Exact focused commands, assertion output, exit codes and restored SHA-256 are in the linked logs. Both logs report `Source restored byte-for-byte: True`; the final production source hash matches the pre-mutation hash. The original `>` → `>=` experiment and its evidence above are retained unchanged.
