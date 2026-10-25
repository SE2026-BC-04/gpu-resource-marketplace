# GPU-004 R1 — delegated PostgreSQL Listings persistence

**Status: IN_PROGRESS / DRAFT / HOLD.** Baseline `main@ce99293` (2026-10-25).

## Assignment and scope

[Owner delegation](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6396462023): TV4 implements R1; TV2 remains the persistence owner and mandatory technical reviewer. This separate branch/PR must not put DB code into [PR #17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17). Author cannot approve/merge. The whole R1 contribution is treated as L2 for review; no new schema/grants policy is inferred from the assignment.

Planned paths: `backend/src/gpu_marketplace/repositories/listings.py`, focused repository tests, this handoff and [the separate proposed D7 decision](../change-requests/CR-GPU-004-D7-01.md). No shared app, frontend, Auth, Jobs implementation, dependencies, migrations or grants are changed before their own approvals.

## Contracts and implementation plan

- Implement the already ACKed `WorkerReader`, `ListingRepository`, `JobConstraintReader` and `ListingUnitOfWork` consumption shape from PR #17 at `b5ad0b7`.
- One short synchronous Session/READ COMMITTED transaction per UoW; no commits in repositories; rollback on exit unless committed, including failures. Never return live/lazy ORM objects.
- Exact Listing row lock before fresh owner/Job constraint reads; when joining use `FOR UPDATE OF gpu_listings`, never lock nullable reputation rows or skip Jobs.
- SQL keyset order `(created_at DESC, id DESC)` with strict before/filter predicates; immutable public-safe Worker/reputation projection and no oracle read.
- INSERT only the five approved columns; rely on DB id/status/allocation/timestamp defaults. Metadata/status writes cannot bypass D7 or write allocation/owner/timestamps.
- Because PR #17 has not merged, accept the consumer's existing record constructors and unavailable-error constructor through the UoW constructor. This preserves exact consumer record/error classes without importing unmerged Listings code or creating alternate production DTOs. Integration usage/evidence must be recorded when implemented.

Traceability: `FR-WR-01..04`, API §7 / `API-LIST-01..18`, `TX-PAUSE-EDIT`, Database Design §9.2-06/§11, ADR-002, D1 grants and GPU-004 ports. Full endpoint behavior remains the responsibility of PR #17/shared integration.

## Verification plan and open gates

Use the existing `backend/tests/db_safety.py`/conftest disposable-cluster guards. Exercise restricted-role reads/create/defaults, keyset/filter/projection, forbidden writes, real two-session Listing locks and post-wait snapshots, rollback and commit-failure cleanup. CRUD/PATCH/status/timestamp acceptance depends on the D7 decision and real consumer integration. GPU-005 TX-SUBMIT / Phase 2 allocation races remain BLOCKED/NOT_RUN until actual implementations exist.

TV2 must review SQL/transaction/security/D7 compatibility and return an exact-HEAD technical ACK; affected-owner ACK actions and two independent human reviews are required before merge. PR #17 and this PR remain HOLD until their own gates pass. Actual commands/results will be added after execution; this plan is not test evidence.
