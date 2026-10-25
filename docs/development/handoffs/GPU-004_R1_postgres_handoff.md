# GPU-004 R1 — delegated PostgreSQL Listings persistence

**Status: IN_PROGRESS / DRAFT / HOLD.** Baseline `main@ce99293` (2026-10-25).

## Assignment and scope

[Owner delegation](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6396462023): TV4 implements R1; TV2 remains the persistence owner and mandatory technical reviewer. This separate branch/PR must not put DB code into [PR #17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17). Author cannot approve/merge. The whole R1 contribution is treated as L2 for review; no new schema/grants policy is inferred from the assignment.

Changed paths: `backend/src/gpu_marketplace/repositories/listings.py`, `backend/tests/test_listing_repository_postgres.py`, this handoff and [the separate proposed D7 decision](../change-requests/CR-GPU-004-D7-01.md). No shared app, frontend, Auth, Jobs implementation, dependencies, migrations or grants are changed.

## Implemented subset and integration usage

- Implements the already ACKed reader/create/locking/UoW consumption shape from PR #17 at `b5ad0b7`. **Effective metadata/status writes are deliberately unavailable pending D7**; this is a partial R1 delivery, not full CRUD acceptance. Empty metadata updates and already-target status return the locked record without issuing UPDATE.
- One short synchronous Session/READ COMMITTED transaction per UoW; no commits in repositories; rollback on exit unless committed, including failures. Never return live/lazy ORM objects.
- Exact Listing row lock before fresh owner/Job constraint reads; when joining use `FOR UPDATE OF gpu_listings`, never lock nullable reputation rows or skip Jobs.
- SQL keyset order `(created_at DESC, id DESC)` with strict before/filter predicates; immutable public-safe Worker/reputation projection and no oracle read.
- INSERT only the five approved columns; rely on DB id/status/allocation/timestamp defaults. Constructor checks the effective restricted API role; Job guard reads require the exact Listing lock in the same active UoW. Metadata/status writes cannot bypass D7 or write allocation/owner/timestamps.
- Because PR #17 has not merged, accept the consumer's existing record constructors and unavailable-error constructor through the UoW constructor. This preserves exact consumer record/error classes without importing unmerged Listings code or creating alternate production DTOs. Integration usage/evidence must be recorded when implemented.

Traceability: `FR-WR-01..04`, API §7 / `API-LIST-01..18`, `TX-PAUSE-EDIT`, Database Design §9.2-06/§11, ADR-002, D1 grants and GPU-004 ports. Full endpoint behavior remains the responsibility of PR #17/shared integration.

Integration example **after the relevant revisions are accepted**; this is not shared app wiring or an instruction to enable the incomplete adapter in production:

```python
from functools import partial

from gpu_marketplace.listings.errors import ListingDependencyUnavailable
from gpu_marketplace.listings.models import ListingRecord, WorkerProfile
from gpu_marketplace.repositories.listings import PostgresListingUnitOfWork

unit_of_work = partial(
    PostgresListingUnitOfWork,
    api_sessions,  # fresh sync Session factory using gpm_api_app, never owner DSN
    worker_record=WorkerProfile,
    listing_record=ListingRecord,
    unavailable_error=ListingDependencyUnavailable,
)
```

Repositories return those exact supplied immutable record classes. There is no dependency on the unmerged Listings package in R1 production code; tests use frozen record fixtures with the same constructor shape. SQL failures and missing D7 produce the supplied safe exception without SQL/DSN context. An uncommitted/failed UoW rolls back all prior writes and closes its Session; objects cannot be used after commit/exit or re-entered.

## Verification plan and open gates

Use the existing `backend/tests/db_safety.py`/conftest disposable-cluster guards. Exercise restricted-role reads/create/defaults, keyset/filter/projection, forbidden writes, real two-session Listing locks and post-wait snapshots, rollback and commit-failure cleanup. CRUD/PATCH/status/timestamp acceptance depends on the D7 decision and real consumer integration. GPU-005 TX-SUBMIT / Phase 2 allocation races remain BLOCKED/NOT_RUN until actual implementations exist.

TV2 must review SQL/transaction/security/D7 compatibility and return an exact-HEAD technical ACK; affected-owner ACK actions and two independent human reviews are required before merge. PR #17 and this PR remain HOLD until their own gates pass.

## Actual local checks — 2026-10-25

- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_listing_repository_postgres.py -q -p no:cacheprovider -rN`: **1 passed / 34 skipped** (unreachable-store sanitization passes; PostgreSQL unavailable locally).
- `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -q -p no:cacheprovider -rN`: **301 passed / 177 skipped**, one existing Starlette/httpx warning. R1 branch excludes PR #17's unmerged application/tests; do not compare its total as though the Listings application was removed.
- Ruff 0.14.0 format and `check --select F,E9` on the two new Python files: **PASS** after removing two unused test imports. `git diff --check`: **PASS**.
- Docker Desktop startup attempted for a disposable cluster, but failed initializing its Inference manager/listener. No test container, database, migration or volume deletion was performed locally. PostgreSQL tests are **NOT_RUN locally**; exact-HEAD CI PostgreSQL evidence is recorded separately in the PR.
- D7 migration/trigger and effective metadata/status/timestamp tests: **BLOCKED on owner decision / NOT_IMPLEMENTED**. The three effective-write rejection tests assert rollback under the current missing dependency; passing them is not PATCH/pause/resume success. No real browser/HTTP/Manager/Job-submission acceptance is claimed.
