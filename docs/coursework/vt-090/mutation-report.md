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
