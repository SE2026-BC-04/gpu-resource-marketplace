# VT-090 Review of AI-Generated Tests

**Review scope:** test cases introduced in commit `b9d2d9d3391a813966ef9c3be26d8d89d0c6e8bb` before the polling production patch.

**Review date:** 2026-11-09

## Finding 1 — removed a duplicate, non-polling oracle

- **Original case:** `keeps a lightweight selected-status assertion (AI review: weak duplicate)` in `frontend/src/ui/jobs/JobsPage.test.tsx` at the test-first commit.
- **Why it was weak:** it asserted that an initially selected `QUEUED` status was rendered and that the list was fetched once. It never advanced the clock or asserted a second `getJob` call, so it passed when automatic polling was completely absent. The existing foundation case `loads a safe detail projection and shows Cancel only for a Client's QUEUED Job` already checked the initial safe detail/status behavior.
- **Decision:** deleted the duplicate. The behavior this coursework needs is tested by `polls a selected queued Job at the 2-second boundary and displays RUNNING`, which asserts no early request at 1999 ms, exactly one GET at 2000 ms, and a visible server-returned status change.

## Finding 2 — replaced a vacuous “no POST” assertion

- **Original case:** `does not submit when a status GET fails (AI review: weak oracle)` in `frontend/src/ui/jobs/JobsPage.test.tsx` at the test-first commit.
- **Why it was weak:** the test never submitted a Job, so `expect(api.submitJob).not.toHaveBeenCalled()` was true before and after any polling implementation. It did not establish retry safety.
- **Decision:** replaced it with `does not create a second Job or duplicate success notice when polling fails then recovers`. The revised test submits a real logical attempt once, reads the accepted Job, injects a transient GET failure, allows a GET recovery to `COMPLETED`, and asserts `submitJob` remains at exactly one call and the success message appears once.

## Execution evidence

| Evidence | Result |
|---|---|
| RED run on test-first commit `b9d2d9d` (`evidence/red-frontend-polling.log`) | Exit 1; 14 failed, 2 passed, 22 skipped. Polling, terminal update, timeout retry schedule and scheduled cleanup assertions failed because the baseline had no polling effect. The two weak cases were among the passing cases, confirming their lack of sensitivity. |
| Initial GREEN run after polling patch (`evidence/frontend-final-tests-pre-review.log`) | Exit 0; 10 files and 175 tests passed before this review strengthened the real-submit failure/recovery oracle. |
| Focused run after replacing the weak no-POST case (`evidence/ai-test-review-focused.log`) | Exit 0; 1 revised test passed, 37 skipped. |
| Final full-suite rerun | Recorded after review in `evidence/frontend-final-tests.log`. |

The source diff removes one weak duplicate and replaces the vacuous assertion with an exercised submit→poll failure→poll recovery flow. These edits are visible in the test-review commit after `b9d2d9d`; they are not only described in this report.
