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

The repository expects Node 24, Python 3.12 and locked dependencies. This machine has Python 3.12.15 and Node 22.13.0; the npm shim is broken, so npm was invoked through the installed Node CLI. `uv`/Docker are not on PATH. `frontend/node_modules` and `backend/.venv` already exist. `@vitest/coverage-v8@5.0.5` is now pinned to match Vitest `5.0.5` in `package.json`/`package-lock.json`; the coverage results below are local evidence under Node 22, not Node 24.

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

# Jobs-focused line/branch coverage (measured 2026-11-11; outputs under docs/coursework/vt-090/evidence)
& 'D:\Application\node.exe' node_modules/vitest/vitest.mjs run src/ui/jobs/JobsPage.test.tsx src/ui/jobs/JobsPage.pairwise.test.tsx src/api/jobs.test.ts src/api/jobs.pairwise.test.ts --coverage.enabled --coverage.provider=v8 --coverage.include=src/ui/jobs/JobsPage.tsx --coverage.include=src/api/jobs.ts --coverage.include=src/api/authorizedFetch.ts --coverage.include=src/api/auth.ts --coverage.reporter=text --coverage.reporter=json --coverage.reporter=json-summary --coverage.reportsDirectory=../docs/coursework/vt-090/evidence/coverage-review-20261111

# Backend Job submit/foundation regression; this selected group uses no live DB
Set-Location ..
& backend/.venv/Scripts/python.exe -m pytest backend/tests/test_jobs_submit_service.py backend/tests/test_jobs_foundation.py -q

# Deterministic pairwise matrix regeneration
& 'D:\Application\node.exe' docs/coursework/vt-090/generate-pairwise.mjs

# 60 concurrent status GET mock; output goes to performance/results-local.json
& 'D:\Application\node.exe' docs/coursework/vt-090/performance/run-status-load.mjs
```

**Coverage:** Jobs-focused line/branch coverage has been measured; see `coverage-flaky-review.md` and `evidence/coverage-review-20261111/`. Full frontend coverage remains `NOT_RUN`. The local npm shim still fails, but the direct Node/npm CLI installed the exact provider version.

**Latest frontend verification (2026-11-11, source HEAD `6daeea368e6add6aefefe8540e637f938698cba4`):** full Vitest passed 12 files / 215 tests; both TypeScript checks and the Vite production build exited 0. Raw outputs are in `evidence/frontend-vitest-full-20261111.log`, `frontend-tsc-project-20261111.log`, `frontend-tsc-e2e-20261111.log`, and `frontend-vite-build-20261111.log`. These are local runs on Node 22.13.0, while the project expects Node 24.

## Evidence guide

- Audit, assumptions and rejected proposals: `repository-audit.md`, `implementation-plan.md`.
- Requirements and test design: `specification.md`, `test-strategy.md`, `pairwise-cases.json`.
- Review remediation evidence: `evidence/review-p1-red.log`, `review-p1-green.log`, `review-p2-pairwise.log`, `review-final-frontend.log`, `review-p3-backend.log`, `review-p3-mutation-final.log`, `review-p3-coverage.log`, `review-p3-audit.log`, `review-p3-performance-run.log`, and the new E1/E2 evidence under `evidence/coverage-review-20261111/` and `evidence/mutation-*.log`.
- Latest full frontend verification logs: `evidence/frontend-vitest-full-20261111.log`, `frontend-tsc-project-20261111.log`, `frontend-tsc-e2e-20261111.log`, `frontend-vite-build-20261111.log`; exact installed provider verification: `evidence/dependency-provider-verification.log`.
- Earlier RED/GREEN, build, backend, performance, mutation and repeated-run evidence remains in `evidence/`.
- Two AI test reviews: `ai-test-review.md`.
- Mutation `>`→`>=`: historical evidence remains in `mutation-report.md` and `evidence/mutation-*.log`; exact command and supplemental replay are in `evidence/mutation-boundary-operator-rerun.log`.
- Additional E2 mutations (`2000→1000`, remove reconciliation poll stop/abort): `mutation-report.md` and `evidence/mutation-*.log`; each source mutation was restored before continuing.
- 60-task experiment and limitations: `performance-report.md`, `performance/results-local.json`.
- AC-to-test links: `traceability.md`.
- AI use: `ai-usage-log.md`.
- Reflection: `reflection.md` (draft for student confirmation).

## Known limitations

- No Manager/Scheduler/Simulator execution is implemented; live local state transition remains `NOT_RUN`.
- 60-task run is `SIMULATED_ONLY`, not real API/DB performance evidence.
- Full-frontend line/branch coverage is `NOT_RUN`; Jobs-focused modules have measured line/branch results and documented uncovered-branch risks.
- Human review is still required on the Draft PR; Codex is not a reviewer approval. Do not merge this coursework PR without the independent review gate.
