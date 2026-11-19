# VT-089 RED run 01

- **Feature baseline under test:** `6eba257` (`docs(api): record approved VT-089 Jobs filter`), whose application code is still the pre-feature baseline from `bee832eaf5463df20f6c6815174322871eb6685a`.
- **Test source:** `backend/tests/test_jobs_foundation.py`.
- **Command:** `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -k vt089_list_http -q`
- **Exit code:** `1` (expected RED).
- **Result:** `7 failed, 88 deselected in 0.45s`.

## Observed feature-specific failures

1. `test_vt089_list_http_filters_listing_before_returning_collection_red`: HTTP request returned `200`, but its collection contained both the nonmatching Listing Job `33333333-3333-4333-8333-333333333334` and the matching Job `33333333-3333-4333-8333-333333333333`. The assertion expected only the matching fixture ID. This proves the current route accepts but ignores the new query key.
2. `test_vt089_list_http_rejects_invalid_or_duplicate_listing_filter_red`: all six invalid cases (empty, malformed, UUIDv1, uppercase, unhyphenated and duplicate identical keys) returned `200` instead of `400 INVALID_FILTER`.

The ASGI route executed, fixtures were constructed, and assertions failed on actual HTTP status/body results. No import, fixture, environment, or database error occurred. The behavior is the missing feature, not an unrelated test failure.

The full pytest output is saved in [`pytest-red-01.log`](pytest-red-01.log). This record preserves the command, return code, failing test IDs, assertion outcomes and pre-patch commit; no application code was changed before the RED run.
