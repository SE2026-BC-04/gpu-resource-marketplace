# VT-089 Acceptance Traceability

**Baseline:** `bee832eaf5463df20f6c6815174322871eb6685a`
**Implementation commit:** `e90627a1913550a5ea9ea224eff70b04ab99455c`
**Current report status:** local checks only; exact-head CI and owner implementation reviews pending.

| AC / risk | Test ID / test function | Source | Commit | Actual result | Evidence |
|---|---|---|---|---|---|
| Optional query preserves legacy route and cursor | VT089-01; `test_vt089_baseline_cursor_remains_usable_through_unfiltered_http_route`; `test_vt089_legacy_cursor_fixture_is_byte_compatible_without_listing_filter` | `backend/tests/test_jobs_foundation.py` | `e90627a` | PASS in focused suite; fixed baseline-signed token accepted | `evidence/pytest-green-focused.log` |
| Correct filter and listing+status AND; safe empty response | VT089-02/03/04/20; `test_vt089_list_http_filters_listing_before_returning_collection`; `test_vt089_list_http_combines_listing_and_status_and_returns_safe_empty_page` | `backend/tests/test_jobs_foundation.py` | `e90627a` | PASS in focused suite | `evidence/pytest-green-focused.log` |
| Canonical UUIDv4; invalid/duplicate values rejected | VT089-05/21; `test_vt089_list_http_rejects_invalid_or_duplicate_listing_filter` | `backend/tests/test_jobs_foundation.py` | `e90627a` | PASS in focused suite | `evidence/pytest-green-focused.log` |
| Limit bounds and sanitized dependency error | VT089-06..11/18; `test_vt089_limit_http_accepts_bva_boundaries`; `test_vt089_limit_http_rejects_bva_outside_boundaries`; `test_vt089_filtered_read_dependency_failure_maps_to_safe_503` | `backend/tests/test_jobs_foundation.py` | `e90627a` | PASS in focused suite | `evidence/pytest-green-focused.log` |
| Filtered cursor binds Listing; old context unchanged | VT089-14/15; `test_vt089_filtered_cursor_is_bound_to_listing_id`; baseline cursor tests above | `backend/tests/test_jobs_foundation.py` | `e90627a` | PASS in focused suite | `evidence/pytest-green-focused.log` |
| Unfiltered SQL and parameters exact; native UUID predicate before order/limit | VT089-02/03/22; `test_vt089_unfiltered_reader_sql_and_parameters_match_baseline_contract`; `test_vt089_listing_filter_is_bound_native_uuid_before_order_and_limit` | `backend/tests/test_jobs_read_adapter_postgres.py` | `e90627a` | PASS with recording-session tests; not a PostgreSQL execution | `evidence/pytest-green-focused.log` |
| CLIENT/WORKER/ADMIN visibility, unknown/non-visible parity, timestamp ties, filter-before-LIMIT | VT089-02/13/16/20/22; `test_vt089_pg_listing_filter_status_roles_cursor_ties_and_before_limit` | `backend/tests/test_jobs_read_adapter_postgres.py` | `e90627a` | SKIPPED / NOT_RUN; no disposable DB opt-in | `evidence/pytest-green-focused.log` |
| 19/20/21 page boundaries | VT089-12; `test_vt089_pg_listing_filter_page_boundaries_19_20_21` | `backend/tests/test_jobs_read_adapter_postgres.py` | `e90627a` | SKIPPED / NOT_RUN; no disposable DB opt-in | `evidence/pytest-green-focused.log` |
| Scope authorization detects removed guard | VT089-16; `test_router_rejects_cross_role_scope` | `backend/tests/test_jobs_foundation.py` | Correct `e90627a`; mutant `bac2ea4` | MUTANT KILLED: 3 failed assertions for CLIENT/WORKER/ADMIN forbidden scopes | `evidence/mutation-scope.md`, `evidence/pytest-mutation-scope.log` |
| UI filter serialization, cursor reset, stale response handling | VT089-19 | `frontend/src/api/jobs.test.ts`; `frontend/src/ui/jobs/JobsPage.test.tsx` | `e90627a` | PASS: full frontend suite 160 tests | command in README; CI pending exact HEAD |
| Browser runtime E2E | VT089-19 | `backend/tests/test_phase1_runtime_http_postgres_e2e.py`; `frontend/e2e/phase1-runtime.spec.ts` | `e90627a` | SKIPPED / NOT_RUN; no disposable DB | `evidence/pytest-runtime-e2e.log` |
| 120-VU p95 <= 3.5s | NFR performance | `tools/vt089_load.py` | `e90627a` | NOT_RUN; harness help only, no measured value | README evidence status |

The focused GREEN command also passed 109 tests overall with 5 PostgreSQL skips. Frontend, typecheck and production build results are in `README.md`. RED evidence is separately recorded in `evidence/red-run-01.md` through `red-run-03.md`; baseline results are not represented as feature verification.
