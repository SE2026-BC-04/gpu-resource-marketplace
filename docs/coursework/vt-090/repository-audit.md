# VT-090 Repository Audit

**Student:** Vương Sỹ Thắng (`23001940`)

**Variant:** VT-090

**Audit date:** 2026-11-09

**Baseline:** `origin/main` at `bee832eaf5463df20f6c6815174322871eb6685a`

**Work branch:** `bt3/vt-090-async-job-progress`

## Repository and Git state

- Repository: `SE2026-BC-04/gpu-resource-marketplace`; remote `origin` points to the expected GitHub repository.
- Before the coursework branch was created, the existing branch `docs/p2a-manager-runtime-review` was clean at `81ef6084d52a87e60710ee4d27de93c551d35f6b`. It was preserved.
- `git fetch origin` completed; `origin/main` was `bee832eaf5463df20f6c6815174322871eb6685a`.
- The coursework branch was created from that `origin/main`; its initial HEAD equals the baseline and its working tree was clean.
- No application files, database, or local Docker stack were changed during this audit.

## Source findings

| Question | Finding and source evidence |
|---|---|
| What does submit do? | `JobSubmitService` validates the logical request and idempotency key, fingerprints the normalized fields, checks retained submissions, and delegates the transaction that inserts the Job/reference. `backend/src/gpu_marketplace/jobs/submit.py` lines 86–158. The API Contract §8.1 says submit is accepted as `QUEUED`; a same-key/same-body replay returns the original Job, while changed-body reuse is `409 IDEMPOTENCY_KEY_REUSED`. |
| What states exist? | `JobStatus` in `backend/src/gpu_marketplace/jobs/models.py` defines `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`. `backend/src/gpu_marketplace/domain/jobs.py` constrains persisted status and terminal timestamp consistency. |
| Where is idempotency enforced? | The API contract binds `(client_id, Idempotency-Key)` to the retained Job. The domain defines a partial unique index `uq_jobs_client_idempotency`; `JobSubmitService` compares the request fingerprint and reports key reuse conflicts. Existing frontend submit tests verify the same frozen key/body for uncertain retry and changed-body key replacement. |
| Which retry/concurrency tests exist? | Backend has Job submit service and PostgreSQL adapter/concurrency tests, including `backend/tests/test_jobs_submit_service.py`, `test_jobs_submit_adapter_postgres.py`, and `test_listing_submit_concurrency_postgres.py`. Frontend has uncertain-submit retry, changed-key, selection, stale-detail, and cancel reconciliation tests in `frontend/src/ui/jobs/JobsPage.test.tsx`, plus Jobs API tests in `frontend/src/api/jobs.test.ts`. The PostgreSQL integration files require their configured disposable database and were not run during this read-only audit. |
| What does the UI do today? | `JobsPage.tsx` fetches the list and selected detail in effects. Selecting a Job, submit completion, explicit reload, or cancellation triggers another read. There is no scheduled automatic polling. The detail effect uses `AbortController`, selected identity/Job keys, and a generation check to reject stale responses. |
| What does the public API expose? | API Contract §8.1–8.2 defines `GET /api/v1/jobs/{job_id}` as a role/ownership-filtered safe status projection. `JobResponse` has status and timestamps, but no progress percentage. Existing `JobsApi.getJob(jobId, signal)` already supplies the read needed by the UI. |
| Does Manager/Simulator execute Jobs now? | `backend/src/gpu_marketplace/manager/service.py` probes PostgreSQL then runs `_foundation_idle_runner`; it performs no scheduling or Job state transition. Phase 2A is explicitly a design document and says its gate is documentation-only. A working execution loop was not found in the inspected Manager runtime. Thus polling can be tested against controlled API responses, but a local demo Job will not naturally progress through execution states on this baseline. |
| Which Phase 2 parts are excluded? | Manager scheduling/allocation, outbox dispatch/recovery, Simulator execution, callbacks, signed results and terminal finalization. This VT-090 slice is a UI read/polling behavior only. It does not enable Phase 2 or claim that a GPU task executes. |
| Can 60 real users be measured safely now? | No authorized disposable PostgreSQL/API test environment or prepared authenticated fixture set was available in the audit. The local stack contains user data and is not to be used for destructive/performance testing. The coursework will run a local mock HTTP harness and label it `SIMULATED_ONLY`; it cannot establish production/API p95. |

## Environment observed

- `backend/.venv/Scripts/python.exe --version`: Python 3.12.15.
- `D:\Application\node.exe --version`: Node.js 22.13.0; the repository documents Node 24 for the approved stack.
- `frontend/node_modules` and the Vitest/TypeScript package entrypoints exist, so direct package binaries may be usable without npm.
- `npm --version` fails because its shim resolves a missing `%APPDATA%\npm\node_modules\npm\bin\npm-cli.js`.
- `uv` and `docker` were not resolvable from this PowerShell session. Do not infer tests passed from dependencies merely being present.
- Coverage provider `@vitest/coverage-v8` is not installed.

## Change boundary

The smallest useful production slice is a sequential polling loop inside the existing selected-detail lifecycle in `JobsPage.tsx`, using the existing `getJob` API. It will poll only while the selected Job is `QUEUED` or `RUNNING`; stop after terminal status, unmount, selection/identity change, or the bounded failure policy. Poll failures must never call `submitJob`. No route, DTO, database, service, Manager or Simulator change is needed.

## Baseline commands and evidence

Commands executed before implementation:

```text
git status --short --branch                 PASS: clean coursework branch tracking origin/main
git rev-parse HEAD                           PASS: bee832eaf5463df20f6c6815174322871eb6685a
git fetch origin                             PASS: origin/main fetched
python via backend/.venv                     PASS: Python 3.12.15
node --version                               PASS: v22.13.0
npm --version                                ERROR: broken npm shim; missing npm-cli.js
uv --version                                 NOT_RUN: uv executable not found
docker version                               NOT_RUN: Docker CLI not found on PATH
```

This audit is source inspection, not test evidence. Runtime checks will be recorded separately with their actual exit codes.
