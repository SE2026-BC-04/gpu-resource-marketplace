# BT3 — VT-090: Async Job Progress & Retry Safety

- **Student ID:** 23001940
- **Student:** Vương Sỹ Thắng (reflection draft requires confirmation)
- **Variant:** VT-090
- **Baseline full SHA:** `bee832eaf5463df20f6c6815174322871eb6685a`
- **Branch:** `bt3/vt-090-async-job-progress`
- **Branch URL:** [bt3/vt-090-async-job-progress](https://github.com/SE2026-BC-04/gpu-resource-marketplace/tree/bt3/vt-090-async-job-progress)
- **Draft PR:** [#51](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/51) — draft; no merge or self-approval.
- To identify the checked-out revision at any time, run `git rev-parse HEAD`; this document records the immutable baseline and evidence-stage commits, not a moving branch HEAD.

## Scope

Adds selected-Job status polling through the existing GET endpoint, bounded timeout/transient-error retries, and lifecycle cleanup. Job submission, API contract, database and Phase 2 execution remain unchanged. The current Manager is idle foundation code, so this work does not make a Job execute on a GPU or promise a real state transition.

## Prerequisites and commands

The repository expects Node 24, Python 3.12 and the locked dependencies. This machine has Python 3.12.15 and Node 22.13.0; the npm shim is broken and `uv`/Docker are not on PATH. `frontend/node_modules` and `backend/.venv` already exist. Commands below use the installed direct entrypoints; npm/uv installation was not performed.

From the repository root in PowerShell:

```powershell
# Dependency installation when npm/uv are available
Set-Location frontend
npm ci
Set-Location ..\backend
uv sync --locked --group dev
Set-Location ..\frontend

# Focused polling tests
& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run src/ui/jobs/JobsPage.test.tsx -t VT-090

# Generated pairwise rows (28 polling component cases + 8 API-client cases)
& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run src/ui/jobs/JobsPage.pairwise.test.tsx src/api/jobs.pairwise.test.ts --reporter=dot

# Pairwise generation and p95/DTO harness unit checks
Set-Location ..
& 'D:\Application\node.exe' docs/coursework/vt-090/generate-pairwise.mjs
& 'D:\Application\node.exe' --test docs/coursework/vt-090/performance/run-status-load.test.mjs
Set-Location frontend

# All frontend Vitest tests
& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run

# Frontend typecheck and production build
& 'D:\Application\node.exe' node_modules/typescript/bin/tsc -b --pretty false
& 'D:\Application\node.exe' node_modules/typescript/bin/tsc --noEmit --pretty false -p tsconfig.e2e.json
& 'D:\Application\node.exe' node_modules/vite/bin/vite.js build

# Coverage (requires the Vitest coverage provider; NOT_RUN in the recorded environment)
& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run --coverage

# Backend Job submit/foundation regression; this selected group uses no live DB
Set-Location ..
& backend/.venv/Scripts/python.exe -m pytest backend/tests/test_jobs_submit_service.py backend/tests/test_jobs_foundation.py -q

# Deterministic pairwise matrix regeneration
& 'D:\Application\node.exe' docs/coursework/vt-090/generate-pairwise.mjs

# 60 concurrent status GET mock; output goes to performance/results-local.json
& 'D:\Application\node.exe' docs/coursework/vt-090/performance/run-status-load.mjs
```

**Coverage:** line/branch coverage is `NOT_RUN`; `@vitest/coverage-v8` is absent. `npm --version` fails because the shim points at a missing `npm-cli.js`. Do not interpret coverage as zero or PASS.

## Evidence guide

- Audit, assumptions and rejected proposals: `repository-audit.md`, `implementation-plan.md`.
- Requirements and test design: `specification.md`, `test-strategy.md`, `pairwise-cases.json`.
- Review remediation evidence: `evidence/review-p1-red.log`, `review-p1-green.log`, `review-p2-pairwise.log`, `review-final-frontend.log`, `review-p3-backend.log`, `review-p3-mutation-final.log`, `review-p3-coverage.log`, `review-p3-audit.log`, and `review-p3-performance-run.log`.
- Earlier RED/GREEN, build, backend, performance, mutation and repeated-run evidence remains in `evidence/`.
- Two AI test reviews: `ai-test-review.md`.
- Mutation `>`→`>=`: `mutation-report.md` and `evidence/mutation-*.log`.
- 60-task experiment and limitations: `performance-report.md`, `performance/results-local.json`.
- AC-to-test links: `traceability.md`.
- AI use: `ai-usage-log.md`.
- Reflection: `reflection.md` (draft for student confirmation).

## Known limitations

- No Manager/Scheduler/Simulator execution is implemented; live local state transition remains `NOT_RUN`.
- 60-task run is `SIMULATED_ONLY`, not real API/DB performance evidence.
- Line/branch coverage is `NOT_RUN`.
- Human review is still required on the Draft PR; Codex is not a reviewer approval. Do not merge this coursework PR without the independent review gate.
