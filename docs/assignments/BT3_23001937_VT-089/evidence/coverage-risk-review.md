# VT-089 coverage status and risk review

**Quantitative line/branch coverage:** NOT_RUN. The locked backend development environment does not contain `coverage.py` or `pytest-cov`; no dependency or lockfile was changed to add them.

| Acceptance/risk | Evidence in source | Actual status |
|---|---|---|
| Invalid/duplicate/canonical Listing ID, safe 400 | `backend/tests/test_jobs_foundation.py::test_vt089_list_http_rejects_invalid_or_duplicate_listing_filter` | Exercised by focused suite |
| Filter and status conjunction, safe empty result | `test_vt089_list_http_combines_listing_and_status_and_returns_safe_empty_page` | Exercised by focused suite |
| Backward-compatible baseline cursor | `test_vt089_baseline_cursor_remains_usable_through_unfiltered_http_route`; `test_vt089_legacy_cursor_fixture_is_byte_compatible_without_listing_filter` | Exercised by focused suite |
| Filtered cursor context binding | `test_vt089_filtered_cursor_is_bound_to_listing_id` | Exercised by focused suite |
| SQL structure/native UUID/filter-before-LIMIT and unchanged unfiltered params | `backend/tests/test_jobs_read_adapter_postgres.py::test_vt089_unfiltered_reader_sql_and_parameters_match_baseline_contract`; `test_vt089_listing_filter_is_bound_native_uuid_before_order_and_limit` | Recording-session tests passed; no real DB claim |
| CLIENT/WORKER/ADMIN visibility, unknown/non-visible parity, tied timestamps, page boundaries 19/20/21 | `test_vt089_pg_listing_filter_status_roles_cursor_ties_and_before_limit`; `test_vt089_pg_listing_filter_page_boundaries_19_20_21` | SKIPPED without disposable PostgreSQL |
| Authorization guard mutation | `test_router_rejects_cross_role_scope` | One specified guard mutation killed: 3 failures on mutant |
| Frontend serialization, reset and stale response | `frontend/src/api/jobs.test.ts`; `frontend/src/ui/jobs/JobsPage.test.tsx` | Full frontend suite passed, 160 tests |
| Browser E2E and real workload | `backend/tests/test_phase1_runtime_http_postgres_e2e.py`; `tools/vt089_load.py` | E2E skipped; 120-VU run NOT_RUN |

The evidence supports exercised-path behavior and one mutation sensitivity check. It does not provide a percentage, exhaustive branch coverage, real PostgreSQL assurance, or performance acceptance.
