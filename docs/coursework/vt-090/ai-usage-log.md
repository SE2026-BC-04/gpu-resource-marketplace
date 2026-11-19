# VT-090 AI Usage Log

## Tool and prompts

- **Tool:** Codex desktop coding agent (GPT-6 family).
- **Primary task prompt:** the user-provided task “CODEX TASK — BT3 VT-090: Async Job Progress & Retry Safety”.
- **Implementation prompt and assumptions:** recorded in `implementation-plan.md` before production code was changed.
- **Additional prompts:** review the existing repository/contracts before coding; implement only the smallest selected-Job GET polling slice; use fake timers/controlled promises; prove the retry boundary with a temporary mutation; never claim mock load as production evidence.

## AI-generated work and human review

- **Plan:** `implementation-plan.md`; source evidence and scope limits are in `repository-audit.md`.
- **Specification/test design:** `specification.md`, `test-strategy.md`, generated `pairwise-cases.json`.
- **Tests:** VT-090 component tests in `frontend/src/ui/jobs/JobsPage.test.tsx` and generated pairwise configurations. Existing API and backend idempotency tests were reused as contract evidence rather than duplicated.
- **Patch:** safe polling and cleanup in `frontend/src/ui/jobs/JobsPage.tsx`; no backend/API/database implementation.
- **Performance harness:** `performance/run-status-load.mjs` and `performance/README.md`.

Two generated tests were not trusted as written:

1. The selected-status check passed on the original no-polling code and duplicated a pre-existing detail test. It was removed and replaced by the exact 1999/2000 ms GET-count/status-change oracle.
2. The “GET failure does not submit” assertion never attempted a submission and was vacuous. It was replaced with an accepted submit followed by GET failure/recovery, asserting exactly one POST and one success notice.

`ai-test-review.md` identifies the original cases and the actual deletion/replacement diff. The RED log showed 14 functional failures and only the two weak cases passing. The revised test passed after the patch.

## Plausible AI suggestions rejected or corrected

- Re-POST after a status GET timeout: rejected because a status-read failure does not prove submission failed, and the existing GET route plus idempotency attempt already provide the correct boundaries.
- Add a Manager/Scheduler/Simulator loop to make status appear to progress: rejected because the baseline Manager is an idle foundation and Phase 2 is explicitly outside this individual slice.
- Display a progress percentage: rejected because the approved safe Job DTO provides state/timestamps but no measured progress value.
- Initial weak test design: corrected after observing that it passed against the no-poll baseline without testing polling.
- Mutation correctness: checked manually with the required `>`→`>=` mutation and the boundary test; the mutant failed for the expected fourth-request count.
- Simulated load result: kept explicitly separate from actual API and database performance; it is not used to claim the 2.0-second NFR passes.

## Evidence paths

- `evidence/red-frontend-polling.log`
- `evidence/frontend-final-tests.log`
- `evidence/frontend-final-typecheck-build.log`
- `evidence/ai-test-review-focused.log`
- `evidence/mutation-operator-diff.txt`, `mutation-mutant-failure.log`, `mutation-restored-pass.log`
- `evidence/flaky-repeats.log`
- `evidence/backend-jobs-unit.log`
- `performance/results-local.json`
