# Remote CI status — stale PR head

- PR: [#52](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/52)
- Observed GitHub head: `74b5c084248cbf9cc1689f9e7cf353800da97cd1`
- Workflow run: [43469022825](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/43469022825)
- Overall result: **RED evidence**: 7 feature tests failed and 1223 passed. Frontend, Compose and local PowerShell setup jobs succeeded; Python job failed.
- Failing assertion includes `backend/tests/test_jobs_foundation.py:536`, where duplicate `listing_id` query returned HTTP 200 but the regression expected HTTP 400.
- Scope: this remote commit is the earlier RED/test-only head, before implementation commit `e90627a`. It is not exact-head CI for the local implementation and must not be described as such.
- Current local implementation/evidence commits have not been pushed because GitHub hostname resolution fails in this environment. Therefore exact-head CI is unavailable.
