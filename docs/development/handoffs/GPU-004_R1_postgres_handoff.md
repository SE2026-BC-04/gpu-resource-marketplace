# GPU-004 R1 — delegated PostgreSQL Listings persistence

**Status: D7_IMPLEMENTED / VERIFICATION_IN_PROGRESS / DRAFT / HOLD.** Baseline `main@ce99293` (verified 2026-10-29). This records code availability, not accepted R1/Phase 1D completion.

## Assignment and scope

[Owner delegation](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6396462023): TV4 implements R1; TV2 remains the persistence owner and mandatory technical reviewer. This separate branch/PR must not put DB code into [PR #17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17). Author cannot approve/merge. The whole R1 contribution is treated as L2 for review; no new schema/grants policy is inferred from the assignment.

Changed paths: `backend/src/gpu_marketplace/repositories/listings.py`, the repository/D7 PostgreSQL tests, `backend/migrations/versions/0003_listing_d7.py`, migration README, this handoff and [the approved-with-conditions D7 record](../change-requests/CR-GPU-004-D7-01.md). [Separate owner approval](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31#issuecomment-6396753378) permits the Listing-only migration/trigger. No shared app, frontend, Auth/Jobs implementation, dependencies, previously accepted migrations or D1 grants are changed.

## Implemented adapter and integration usage

- Implements the ACKed reader/create/update/status/locking/UoW consumption shape from PR #17 at `b5ad0b7`. Effective updates use only allowlisted metadata/status fields and receive DB-generated updated_at. Empty/unchanged metadata and already-target status return the locked record without issuing UPDATE. Application/HTTP ownership/guard acceptance remains separate from repository implementation.
- One short synchronous Session/READ COMMITTED transaction per UoW; no commits in repositories; rollback on exit unless committed, including failures. Never return live/lazy ORM objects.
- Exact Listing row lock before fresh owner/Job constraint reads; when joining use `FOR UPDATE OF gpu_listings`, never lock nullable reputation rows or skip Jobs.
- SQL keyset order `(created_at DESC, id DESC)` with strict before/filter predicates; immutable public-safe Worker/reputation projection and no oracle read.
- INSERT only the five approved columns; rely on DB id/status/allocation/timestamp defaults. Constructor checks the effective restricted API role; Job guard reads require the exact Listing lock in the same active UoW. Metadata/status writes cannot bypass D7 or write allocation/owner/timestamps.
- Migration `0003_listing_d7` follows accepted head `0002_phase1b_grants`: immutable id/worker_id/created_at, SECURITY INVOKER with pg_catalog search path, no PUBLIC EXECUTE, DB clock on every SQL UPDATE including SQL no-ops. Exact immutable error oracle: SQLSTATE `23514`, diagnostic constraint `ck_gpu_listings_identity_immutable`; no extra table CHECK is added. Upgrade/downgrade preserves data and D1 ACLs. Re-parent/retest if main's accepted migration head changes before merge.
- The effective UPDATE statement itself checks the enabled approved trigger/function in the catalog while acquiring the target-table write lock. A missing/disabled D7 mechanism returns no changed row, raises the supplied safe dependency error and rolls back the UoW; there is no owner-connection/timestamp-write fallback.
- Because PR #17 has not merged, accept the consumer's existing record constructors and unavailable-error constructor through the UoW constructor. This preserves exact consumer record/error classes without importing unmerged Listings code or creating alternate production DTOs. Integration usage/evidence must be recorded when implemented.

Traceability: `FR-WR-01..04`, API §7 / `API-LIST-01..18`, `TX-PAUSE-EDIT`, Database Design §9.2-06/§11, ADR-002, D1 grants and GPU-004 ports. Full endpoint behavior remains the responsibility of PR #17/shared integration.

Integration example **after the relevant revisions are accepted**; this does not mount/configure a production app or bypass pending acceptance/review:

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

Use the existing `backend/tests/db_safety.py`/conftest disposable-cluster guards. Tests cover restricted-role read/create/update/status, keyset/filter/projection, forbidden writes, DB clock and immutable diagnostics, no-ops, downgrade/upgrade, real two-session Listing locks with adapter UPDATE and fresh post-wait snapshots, rollback and injected commit failure. The new test also opens a real TCP gpm_api_app engine without SET ROLE: a guarded disposable-only fixture installs a random libpq-computed SCRAM verifier and restores/verifies the original afterward; no production credential/bootstrap/ACL changes. Full consumer/HTTP/browser integration is still pending. GPU-005 TX-SUBMIT / Phase 2 allocation races remain BLOCKED/NOT_RUN until actual implementations exist; current Manager grants are not expanded to pretend allocation is available.

TV2 must review SQL/transaction/security/D7 compatibility and return an exact-HEAD technical ACK; affected-owner ACK actions and two independent human reviews are required before merge. PR #17 and this PR remain HOLD until their own gates pass.

## Historical pre-D7 local checks — 2026-10-25 (`953ceb8`)

- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_listing_repository_postgres.py -q -p no:cacheprovider -rN`: **1 passed / 34 skipped** (unreachable-store sanitization passes; PostgreSQL unavailable locally).
- `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -q -p no:cacheprovider -rN`: **301 passed / 177 skipped**, one existing Starlette/httpx warning. R1 branch excludes PR #17's unmerged application/tests; do not compare its total as though the Listings application was removed.
- Ruff 0.14.0 format and `check --select F,E9` on the two new Python files: **PASS** after removing two unused test imports. `git diff --check`: **PASS**.
- Docker Desktop startup attempted for a disposable cluster, but failed initializing its Inference manager/listener. No test container, database, migration or volume deletion was performed locally. PostgreSQL tests are **NOT_RUN locally**; exact-HEAD CI PostgreSQL evidence is recorded separately in the PR.
- D7 migration/trigger and effective metadata/status/timestamp tests: **BLOCKED on owner decision / NOT_IMPLEMENTED**. The three effective-write rejection tests assert rollback under the current missing dependency; passing them is not PATCH/pause/resume success. No real browser/HTTP/Manager/Job-submission acceptance is claimed.

## D7 implementation checks — 2026-10-29

- D7 approval and stable error profile were recorded before DDL at `b1e1008` and [the public implementation note](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31#issuecomment-6500093853). This does not close the TV2/consumer/human review gates.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_listing_repository_postgres.py backend/tests/test_listing_d7_postgres.py -q -p no:cacheprovider -rN`: **1 passed / 50 skipped** without a local cluster; no PostgreSQL PASS is claimed locally.
- Full backend command above: **301 passed / 193 skipped**, one existing Starlette/httpx warning. Prior `953ceb8` CI (478 passed) is historical pre-D7 evidence; new exact-HEAD CI must be recorded in PR #31.
- Ruff 0.14.0 format/check `--select F,E9` for the four changed Python files and offline Alembic upgrade `0002_phase1b_grants:0003_listing_d7`: **PASS**. Offline generation verifies neither PostgreSQL trigger execution nor live login; those need the real CI cluster.
- Production AuthService/engine/session/router/shell/audit/browser acceptance and actual Jobs/Manager races remain **BLOCKED/NOT_RUN**. R1 implementation and D7 conditional approval do not remove R2–R4 or permit author merge.
