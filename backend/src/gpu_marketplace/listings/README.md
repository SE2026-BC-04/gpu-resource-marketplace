# GPU-004 Listings — implementation and integration handoff

Status: **core/router/UI on `feat/gpu-004-listings`; real Auth dependency connected;
PostgreSQL/shared-app integration BLOCKED**.
Baseline: `main@028c355` (25/10/2026). The user explicitly authorized GPU-004 coding.
This does not claim that the complete Phase 1D acceptance gates have passed.
GPU-002-B now supplies ORM mappings and migration `0001_phase1b_baseline`, but
Listing repositories/UoW are not handed off. GPU-003 core and Auth routes are on
this baseline; the PostgreSQL account reader in PR #25 and session UI in PR #26
remain separate, unmerged prerequisites at this review.

## Implemented scope

- Six routes from API Contract §7, exported by `create_listing_router`.
- `create_authenticated_listing_router` connects the same routes to GPU-003's
  real `create_principal_dependency(AuthService)` without copying JWT logic.
- Strict request DTOs, unknown/managed-field rejection, duplicate-key JSON rejection,
  exact decimal-string prices, UTC timestamps, safe errors and request IDs.
- Server-side role/owner policies, ACTIVE-only marketplace, Worker `mine`, Admin
  read-only `all`, and PAUSED detail reads.
- Atomic-use-case boundaries for create/PATCH/pause/resume; Listing lock before
  fresh owner/Job reads; hardware and allocated/queued capacity guards before writes.
- No-op hardware edits and repeated pause/resume; no Job, allocation or reputation writes.
- HMAC-authenticated keyset cursors bound to scope/filter and the trusted actor for `mine`.
- React `ListingsPage`, create/edit form, detail, filters, paging, status actions,
  loading/empty/error states, duplicate-submit protection and request cancellation.

## Required owner handoffs

`ports.py` contains **GPU-004 consumption interfaces**, not an implementation of
GPU-002 persistence or a claim that GPU-002 has approved these exact signatures.
TV2/TV3 and the shared integration owner must review the adapters before integration.

| Owner | Required implementation / evidence |
|---|---|
| GPU-002 / TV2 | Use the existing migration/ORM; still need PostgreSQL-backed UoW, Worker lookup, Listing repository and Job constraint reader, with runtime-role evidence |
| GPU-003 / TV3 + TV2 | Canonical principal dependency is available and consumed; still need the reviewed PostgreSQL account adapter/provisioning and shared volatile session integration |
| Leader | Shared AuthService/engine/session/JWT-secret configuration, router registration in `api/app.py`, frontend shell mounting, cursor-key injection, request correlation and audit integration |
| TV2/TV3/leader | Resolution of the documented Auth sync/provisioning gates and applicable D1–D12 decisions/ACKs |

The production `api/app.py` and frontend `App.tsx` are intentionally not changed:
their ownership is shared and required DB adapters/configuration are absent. The foundation page
therefore remains the default application screen. Do not mount test doubles,
accept a user/role header as authentication, or use a privileged DB connection as
a substitute for the missing runtime adapters.

### Auth decision tracking

The owner confirmed `DEC-P1-03` in [PR #13](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372245355).
API Contract **v0.9** on the current baseline records the approved profile; PR #18
(core) and PR #23 (Auth endpoints/dependency) have merged. The earlier
[PR #13 ACK](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372588314)
is historical. TV4 also posted
[XPH-GPU-003-05 ACK_WITH_ACTIONS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/23#issuecomment-6382291607)
and a [session-client compatibility ACK](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#issuecomment-6387480528).
The canonical Auth dependency is now exercised with real JWTs on all six Listing
routes, but account persistence and Listing UoW in these tests are doubles.
These consumer checks do not approve unmerged adapters, constitute independent
human review, or close shared-app/PostgreSQL/E2E gates.

### Persistence adapter requirements

1. Each UoW owns one short SQLAlchemy synchronous Session / PostgreSQL
   READ COMMITTED transaction. On exit without successful commit, roll back,
   including when commit raises. Returned `ListingRecord` values must be fully
   materialized, immutable public projections, not lazy ORM instances.
2. `get_for_update` performs an actual Listing `SELECT ... FOR UPDATE` and
   returns fresh post-lock values. All submit/allocation callers must share the
   same Listing-first protocol. Unit tests cannot prove this DB behavior.
3. `page` applies status/owner predicates **in SQL**, orders
   `(created_at DESC, id DESC)`, uses a strict keyset comparison and respects the
   requested `limit` (service requests page size + 1). A Worker-less `mine` is empty.
4. `create` inserts only the supplied metadata plus the trusted resolved Worker
   ID. Omit managed columns; DB defaults produce ID, ACTIVE, allocated=0 and times.
   `update` writes only changed metadata; `set_status` writes status only.
   Use the timestamp mechanism approved by GPU-002; if D7 is accepted, the DB
   trigger supplies `updated_at` and the API does not explicitly UPDATE it.
5. `has_nonterminal_jobs` checks QUEUED/RUNNING; `max_queued_gpu_count` returns
   MAX of **QUEUED** requests, not their sum, or 0. Both are read-only and called
   only after acquiring the Listing lock in that UoW.
6. Translate temporary driver/connection failures into
   `ListingDependencyUnavailable`; do not expose DSNs or raw SQL through public
   `ListingError` messages. Map named constraints only after the TV2 contract is
   agreed. The router never returns adapter exception text.
7. DB privileges and shared fixture/cluster harness follow the upstream approved
   decisions. No grants, triggers, migrations, seed/provisioning credentials or
   additional tables are introduced by this module.

TV4's [D1 ACK on PR #27 at `ab32545`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/27#issuecomment-6387610827)
is `ACK_WITH_ACTIONS`: the column grants match these consumption requirements,
but real restricted-role/UoW/timestamp tests remain open. D1 is not activated by
this branch. A joined projection must lock only the Listing row, not every
read-only joined table. Do not broaden API timestamp/counter grants to make an
adapter pass.

### Backend wiring (integration-owner task)

After the above adapters exist, include the router with the real dependencies:

```python
from gpu_marketplace.listings.cursors import ListingCursorCodec
from gpu_marketplace.listings.router import create_authenticated_listing_router
from gpu_marketplace.listings.service import ListingService

# These three values come from the reviewed integration, not this package:
# uow_factory, shared_auth_service, cursor_signing_key_bytes.
service = ListingService(uow_factory, ListingCursorCodec(cursor_signing_key_bytes))
app.include_router(create_authenticated_listing_router(
    service=service,
    auth_service=shared_auth_service,
))
```

Use a cursor-specific key, separate from JWT/service credentials. It must contain
at least 32 random bytes and remain stable across
API instances/restarts for cursor continuity. The integrator decides secret
delivery; this slice adds no environment-variable name, and has no default key.
It is not a JWT implementation. Never hardcode a production signing key.

### Frontend wiring (GPU-003 / shared-shell task)

Import `createListingsApi` from `frontend/src/api/listings.ts` and
`ListingsPage` from `frontend/src/ui/listings/ListingsPage.tsx`.
Construct a stable API instance with the actual volatile token getter and the
existing session-clear handler. Supply `session={user ? {userId: user.id,
role: user.role} : null}` and `api={listingsApi}` to the page. No token is stored
in browser storage, cookies or URLs. An old request's 401 cannot clear a newer
session's different token.

## Verification and limits

From repository root with the locked backend environment:

```text
uv sync --project backend --locked --group dev
uv run --project backend --locked --group dev pytest backend/tests tests -q -p no:cacheprovider -rN
```

From `frontend/`:

```text
npm ci
npm test
npm run typecheck
npm run build
```

The HTTP contract tests instantiate a real FastAPI router with an explicitly
**test-only** transactional double and server-injected principal.
`test_auth_integration.py` instead uses the real GPU-003 AccessTokenCodec,
AuthService and principal dependency, with account/Listing persistence doubles.
The React tests inject a test API. These are not PostgreSQL, production
frontend-shell or cross-process E2E acceptance evidence. The normal
frontend build still builds the foundation shell; TypeScript and RTL tests
compile/render the separate Listings component.

Observed on 25/10/2026 after syncing `main@028c355`: backend **491 passed / 58
skipped**, including **201** Listings tests (**65** real-Auth/double-persistence
consumer tests); frontend **27 passed**, TypeScript and Vite build
passed. The 58 skipped tests are upstream PostgreSQL checks without a configured
disposable cluster, not successful DB tests. Python 3.12.14 and Node 24.19.0 were
used with existing lockfiles. Real-Auth cases cover valid JWTs, missing/tampered/
expired credentials, signed missing/ill-typed claims, fresh account/role changes,
safe account-store 503, and cross-Worker 404. Auth rejection never enters the
Listing UoW. Terminal Job-guard doubles now cover COMPLETED/FAILED/CANCELLED,
the existing DB enum; these are not complete persisted Job fixtures.

The UUID-path review finding is also fixed: all four ID-bearing routes require
lowercase hyphenated UUIDv4 text before conversion. **32** regression cases cover
canonical/hex/uppercase/braced/URN/wrong-version/wrong-variant/malformed IDs;
invalid forms return safe 422 without entering the Listing UoW. Before the fix,
16 of these cases failed by accepting alternate spellings with 200.

Remaining **BLOCKED / NOT_RUN**: PostgreSQL Listing/account adapters and router/shell wiring;
PostgreSQL multi-session lock/rollback/role tests; full API-LIST-13/14/15
submit/allocation/FIFO races; persistent DB audit integration where applicable;
browser-to-real-API E2E and the benchmark. Keep Phase 1D out of `IMPLEMENTED`.

[TV4 environment inventory](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/22#issuecomment-6387611172):
Docker/WSL engine stopped, no reachable local project DB verified. Old volumes,
historical/remote DB use and actual Alembic revision remain NOT_VERIFIED; no
migration/recovery action was performed. A stopped engine does not prove that
no persistent DB exists.

## When GPU-002/GPU-003 are ready

1. Fetch the reviewed upstream commits, check migration/runtime grants and agree
   the actual UoW/principal/session signatures with TV2/TV3. Adapt to their real
   interfaces rather than duplicating Identity or persistence in Listings.
2. Connect those adapters to `ListingService` and the existing router; coordinate
   shared API registration, frontend mounting and cursor-key configuration with
   the integration owner. Never wire test doubles into the production app.
3. Run real PostgreSQL transaction/ownership/capacity tests, Auth rejection/expiry
   checks on all six routes, and browser-to-API role-specific flows. Keep the
   GPU-005/Phase 2 race branches separately blocked until their owners deliver.
4. Update this evidence and the Phase 1D/handoff status in a follow-up commit on
   the same open PR (or a new PR if already integrated), then obtain the required
   cross-phase ACKs and independent human review before requesting merge.
