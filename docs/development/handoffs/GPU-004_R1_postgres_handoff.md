# GPU-004 R1 — delegated PostgreSQL Listings persistence

**Status: D7_IMPLEMENTED / RE_REVIEW_IN_PROGRESS / DRAFT / HOLD.** Baseline `main@ef9ddcb` (verified 2026-11-03). This records code availability, not accepted R1/Phase 1D completion. [Owner review on `99aa023`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31#pullrequestreview-5750511656) requests P1 migration and P2 commit-outcome repairs; earlier ACKs do not approve a new HEAD.

## Assignment and scope

[Owner delegation](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6396462023): TV4 implements R1; TV2 remains the persistence owner and mandatory technical reviewer. This separate branch/PR must not put DB code into [PR #17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17). Author cannot approve/merge. The whole R1 contribution is treated as L2 for review; no new schema/grants policy is inferred from the assignment.

Changed paths: `backend/src/gpu_marketplace/repositories/listings.py`, the repository/D7 PostgreSQL tests, `backend/migrations/versions/0004_listing_d7.py`, migration README, this handoff and [the approved-with-conditions D7 record](../change-requests/CR-GPU-004-D7-01.md). [Separate owner approval](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31#issuecomment-6396753378) permits the Listing-only migration/trigger. Current main is merged normally, preserving its D2/Jobs/Auth work. No shared app, frontend, Auth/Jobs implementation, dependencies, previously accepted migrations or D1 grants are edited by R1.

## Implemented adapter and integration usage

- Implements the ACKed reader/create/update/status/locking/UoW consumption shape from PR #17 at `b5ad0b7`. Effective updates use only allowlisted metadata/status fields and receive DB-generated updated_at. Empty/unchanged metadata and already-target status return the locked record without issuing UPDATE. Application/HTTP ownership/guard acceptance remains separate from repository implementation.
- One short synchronous Session/READ COMMITTED transaction per UoW; no commits in repositories. Uncommitted work is rolled back on exit; after an indeterminate COMMIT, rollback is cleanup and cannot prove the writes were undone (see the outcome contract below). Never return live/lazy ORM objects.
- Exact Listing row lock before fresh owner/Job constraint reads; when joining use `FOR UPDATE OF gpu_listings`, never lock nullable reputation rows or skip Jobs.
- SQL keyset order `(created_at DESC, id DESC)` with strict before/filter predicates; immutable public-safe Worker/reputation projection and no oracle read.
- INSERT only the five approved columns; rely on DB id/status/allocation/timestamp defaults. Constructor checks the effective restricted API role; Job guard reads require the exact Listing lock in the same active UoW. Metadata/status writes cannot bypass D7 or write allocation/owner/timestamps.
- Migration `0004_listing_d7` follows accepted D2 `0003_phase1b_jobs_guard_update`: immutable id/worker_id/created_at, SECURITY INVOKER with pg_catalog search path, no PUBLIC EXECUTE, DB clock on every SQL UPDATE including SQL no-ops. Exact immutable error oracle: SQLSTATE `23514`, diagnostic constraint `ck_gpu_listings_identity_immutable`; no extra table CHECK is added. This differs from D2's `23000 / trigger-name` rejection; error mappers must not conflate them. D7 downgrade stops at D2 and preserves its trigger/function, rows and D1 ACLs. D3 (#29) is pending: whichever PR merges second must re-parent/renumber its unmerged revision and retest; do not rewrite accepted revisions or stamp a persistent DB.
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

Repositories return those exact supplied immutable record classes. There is no dependency on the unmerged Listings package in R1 production code; tests use frozen record fixtures with the same constructor shape. SQL failures and missing D7 produce the supplied safe exception without SQL/DSN context. The consumer must keep `mock_price_per_hour` as `Decimal | None`, matching the DB record; equivalent `Decimal("1.20")` / `Decimal("1.200")` values are no-ops, with no UPDATE/timestamp touch. Objects cannot be used after commit/exit or re-entered, including after an unknown commit outcome.

## Transaction outcomes and consumer handoff — 2026-11-03 (P2)

`uow.outcome` is a read-only internal `TransactionOutcome`, retained after context exit. The supplied exception type/constructor and existing HTTP `503 DEPENDENCY_UNAVAILABLE` remain unchanged. Sanitized store logs include only exception type and this outcome; no SQL/credentials or private record values. These are diagnostic states, not public error codes or automatic retry instructions:

| Internal state | Evidence and handling |
|---|---|
| `NOT_COMMITTED` | No COMMIT has been attempted and no successful rollback has yet been observed. This alone is not a completed rollback guarantee. |
| `ROLLED_BACK` | No COMMIT was attempted and Session rollback returned successfully. Statement/body failures before commit are in this category; independent DB reads must establish the tested non-persistence. A rollback failure is not relabeled confirmed rollback. |
| `COMMITTED` | Session commit returned successfully. Later cleanup errors do not turn this into an abort. |
| `COMMIT_OUTCOME_UNKNOWN` | COMMIT was attempted but did not return successfully. Conservatively includes any commit exception, even if the test knows it injected an error before forwarding to the real commit. Cleanup rollback/close never changes this state to `ROLLED_BACK`; the DB may already have committed. |

This addresses [TV5's review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31#pullrequestreview-5748868101) and the owner P2 without inventing an idempotency key or changing API policy. The adapter never retries commit or replays writes. The consumer service/router must retain the safe dependency response and never assert that a 503 implies zero persisted Listings. Integration logging may inspect the retained UoW outcome with the trusted request ID; the internal state is not added to public DTOs.

For non-idempotent `POST /gpu-listings`, **do not automatically retry** after an unknown outcome. After connectivity/authentication recovery, the owner should refresh the existing `scope=mine` catalogue and inspect it before deciding on a new creation. Identical metadata does not uniquely identify an operation; this is manual reconciliation, not proof of exactly-once creation. PATCH/pause/resume callers should also refresh authoritative state instead of assuming rollback. Mounted UI guidance/request correlation remains an explicit TV4/TV1 integrator handoff on #17; no shared application/UI wiring is implemented by this persistence PR.

Tests distinguish failures before a commit attempt (confirmed rollback and no row), an injected exception before forwarding real commit (no row, conservatively unknown), and a real successful commit followed by simulated acknowledgement loss for create/metadata/pause/resume. The last case observes the durable row/timestamp using a distinct engine/physical connection after cleanup, while the caller receives the same sanitized exception and the UoW stays unknown. This is controlled fault injection, not a measured network-outage or mounted HTTP test.

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

## Current-main P1/P2 repair checks — 2026-11-03

- Normal merge of `main@ef9ddcb` preserves accepted D2, Jobs and Auth tests; migration README keeps both D2 and D7. Only the unmerged D7 is renamed/re-parented to `0004_listing_d7 → 0003_phase1b_jobs_guard_update`. No accepted migration, D1 grant, shared app or workflow is edited.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_listing_repository_postgres.py backend/tests/test_listing_d7_postgres.py -q -p no:cacheprovider -rN`: **2 passed / 54 skipped**, one existing Alembic configuration deprecation. The single-head graph assertion and unavailable-store test run without PostgreSQL; no local DB PASS claim.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests tests -q -p no:cacheprovider -rN`: **393 passed / 280 skipped**, existing Starlette and Alembic warnings. Additional skips include current-main PostgreSQL tests and the four new lost-ack cases.
- Ruff 0.14.0 format/check `--select F,E9` on the four changed Python files: **PASS**. Offline Alembic `0003_phase1b_jobs_guard_update:0004_listing_d7` emits D7 SQL with the stable profile and no grant/role changes: **PASS**, not a live DB upgrade.
- New-head CI must rerun all disposable PostgreSQL tests, including fresh upgrade, D2 regression, D7 round trip preserving D2/ACL/data, confirmed rollback, actual-commit/lost-ack independent reads, restricted login, locks and safe errors. The 2026-10-29 green run cannot close the current P1/P2 review. Exact-head CI results belong in PR #31 after completion; TV2/TV5/integrator re-review and independent human L2 gates remain open.
