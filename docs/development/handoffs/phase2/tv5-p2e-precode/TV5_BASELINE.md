# TV5-P2E-01 — Phase 1 Baseline and Phase 2 Intake

**Review snapshot:** 2026-11-08 (UTC)
**Baseline:** `main@bee832eaf5463df20f6c6815174322871eb6685a`
**Status:** `DOCUMENTATION REVIEW — proposed status sync; not implementation approval`

## Repository and GitHub evidence

| Item | Verified state | Evidence |
|---|---|---|
| Local checkout | `main`, clean before this docs branch; HEAD equals `origin/main` | Local `git status --short --branch`, `git rev-parse HEAD` |
| PR #39 Phase 1 integration | CLOSED, merged 2026-11-08; head `3482bce3cc9726543b9345a5224d8db1b9fc6454`; merge commit `aff538f79997c6e2bfcf359b176a82f2cd9ecc53` | [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) |
| PR #39 CI | Run `42385995533`, completed SUCCESS on the exact head SHA above | [GitHub Actions run](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533) |
| PR #44 Phase 2 doc intake | CLOSED, merged; merge commit is current baseline `bee832e...` | [PR #44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44) |
| PR #45 Phase 2D | OPEN, Draft, not merged; head `5768d70c25a8d63a5c9286ae454e829d42266438` | [PR #45](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/45) |
| PR #46 Phase 2B docs | OPEN, Ready, not merged; head `517942f9f34e779b9a2e07e80c3088e9cf7e8f3f` | [PR #46](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) |
| PR #47 Phase 2A docs | OPEN, Draft, not merged; head `81ef6084d52a87e60710ee4d27de93c551d35f6b` | [PR #47](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/47) |
| Migration graph | `alembic -c backend/alembic.ini heads` reports one head: `0005_listing_d7` | Alembic source-only CLI PASS; live DB verification NOT_RUN. `uv`-managed command was blocked on pinned build dependency DNS, so system Alembic 1.13.1 was used without DB access. |
| Phase 2 runtime | No Phase 2 runtime implementation is established by this baseline. #45 contains unmerged prototype work; #46/#47 contain unmerged docs. | Local tracked source paths and PR state above |

The CI run is evidence for PR #39's exact merged head, not for Phase 2, not for the merge commit's post-merge workflows, and not for any current local database. The connector returned no PR-triggered runs for the merge commit; the direct `gh run list` query for the exact PR head found the run above.

## Phase 1 contracts retained

- Submit creates a `QUEUED` Job with immutable request identity/idempotency and `enqueue_seq`; cancel is allowed only for the owning Client's `QUEUED` Job. The Listing-before-Job lock order governs state-changing operations. A paused Listing blocks new submissions/allocations, not recovery of an already `RUNNING` attempt.
- `backend/src/gpu_marketplace/jobs/reference.py` implements the approved `demo-v1-public1` generator in the merged baseline. It uses the fixed public deterministic algorithm and V1–V4 vectors; this generator's output is a protected expected reference, not real GPU evidence.
- The reference boundary is logical and role-scoped in approved design. The Simulator must never receive `simulation_references`, reference seed/digest, DB credentials, or a private key. Public determinism means outcomes are recomputable from public inputs; it does not provide anti-cheat secrecy.
- API Contract §13 fixes dispatch to ten properties and `simulation_input={"workload_profile":"demo-v1"}`. The approved mock output has nine fields; ADR-004 Signed Result V1 has eleven signed fields. They are different wire objects.
- API Contract §§8–13 and ADR-004/005 remain authoritative. Callback `202` confirms durable Inbox ingestion/duplicate only, not verification or Job completion.

## Reusable Phase 1 code and evidence

| Existing code | Reuse boundary |
|---|---|
| `jobs/reference.py` | Pure deterministic reference helper; no Simulator DB usage |
| `jobs/submit.py`, `jobs/cancel.py` | Phase 1 submit/cancel policy and typed ports; do not turn them into Phase 2 allocation/finalization paths |
| `repositories/job_submit.py`, `repositories/jobs.py` | Phase 1 persistence patterns and lock/transaction behavior; TV2 owns new Phase 2 tables/UoW |
| `manager/service.py` | Existing Manager lifecycle foundation; Phase 2 loop wiring remains TV1-owned |
| `simulator/src/gpu_marketplace_simulator/app.py`, `config.py` | Existing Simulator process/config; `create_app()` exposes only `/health/live` and `/health/ready`, no execution/callback route; no DB configuration |
| `backend/tests/`, `simulator/tests/` | Phase 1 tests may provide fixtures; Phase 2 acceptance requires new executable evidence |

Direct code evidence: `backend/src/gpu_marketplace/manager/service.py` currently starts `_foundation_idle_runner` after a database readiness probe; it does not schedule, dispatch, verify or finalize Jobs. `simulator/src/gpu_marketplace_simulator/app.py` defines only health routes. `simulator/tests/test_health.py` asserts the health-only surface. The presence of Phase 2 design files or open PR branches is not evidence that these runtimes exist on main.

The local review did not run application or PostgreSQL tests. The exact Phase 1 CI run linked above is the available CI evidence. **Live PostgreSQL verification: NOT_RUN**; no disposable-cluster safety evidence was provided. The Alembic head command reads repository revisions only and is not a live schema assertion.

## Open baseline dependencies

- E-IF-12 remains pending until all phase owners record exact Phase 1 acceptance and compatibility ACK against this SHA.
- #45's PR text reports the `reserved_gpu_count` reference as an erratum and asks TV2/lead to confirm `gpu_listings.allocated_gpu_count`; do not import unmerged edits or claim owner ACK from its Draft state.
- The latest #46 comment requests TV5 decisions about `dispatch_payload`, signed-results evidence copy, aggregate creation/update fields, and whether finalization needs references. These are open requests, not ACKs.
- Handoff v1.1's PR #39 status and CI details are a historical snapshot and must not be reused as current state.
