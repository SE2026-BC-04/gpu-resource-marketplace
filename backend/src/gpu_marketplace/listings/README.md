# GPU-004 Listings — implementation and integration handoff

Status: **core/router/UI on `feat/gpu-004-listings`; PostgreSQL/Auth integration BLOCKED**.
Baseline: `main@f9124f7` (24/10/2026, PR #12 merged). The user explicitly authorized GPU-004 coding.
This does not claim that the complete Phase 1D acceptance gates have passed.
GPU-002-B now supplies ORM mappings and migration `0001_phase1b_baseline`, but
`repositories/` and `identity/` still contain placeholders on this baseline.

## Implemented scope

- Six routes from API Contract §7, exported by `create_listing_router`.
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
| GPU-003 / TV3 | Real verified JWT + fresh ACTIVE DB account/role dependency; Auth session and token getter; approved provisioning |
| Leader | Router registration in `api/app.py`, shared frontend shell mounting and cursor-key injection/configuration |
| TV2/TV3/leader | Resolution of the documented Auth sync/provisioning gates and applicable D1–D12 decisions/ACKs |

The production `api/app.py` and frontend `App.tsx` are intentionally not changed:
their ownership is shared and the real adapters are absent. The foundation page
therefore remains the default application screen. Do not mount test doubles,
accept a user/role header as authentication, or use a privileged DB connection as
a substitute for the missing runtime adapters.

### Auth decision tracking

The owner confirmed `DEC-P1-03` in [PR #13](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372245355).
Its documentation-sync revision `c61b8f2` is not merged into this baseline.
TV4 posted [ACK_WITH_ACTIONS](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372588314):
consume GPU-003's trusted principal/session, update the remaining GPU-004 Auth
labels in the separately coordinated documentation PR after #13 merges, and
verify invalid/expired credentials against the real integration. This ACK does
not approve GPU-003-B implementation choices or confirm our proposed adapter
signatures. Do not infer a human review approval or a closed cross-phase gate.

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

### Backend wiring (integration-owner task)

After the above adapters exist, include the router with the real dependencies:

```python
from gpu_marketplace.listings.cursors import ListingCursorCodec
from gpu_marketplace.listings.router import create_listing_router
from gpu_marketplace.listings.service import ListingService

# These three values come from the reviewed integration, not this package:
# uow_factory, trusted_principal_dependency, cursor_signing_key_bytes.
service = ListingService(uow_factory, ListingCursorCodec(cursor_signing_key_bytes))
app.include_router(create_listing_router(
    service=service,
    principal_dependency=trusted_principal_dependency,
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

The HTTP tests instantiate a real FastAPI router with an explicitly **test-only**
transactional double and server-injected principal. The React tests inject a
test API. They cover policies/contracts but are not PostgreSQL, cryptographic JWT,
production frontend-shell, or cross-process E2E acceptance evidence. The normal
frontend build still builds the foundation shell; TypeScript and RTL tests
compile/render the separate Listings component.

Observed on 24/10/2026: backend **154 passed / 58 skipped**, including **102**
Listings double-backed tests; frontend **27 passed**, TypeScript and Vite build
passed. The 58 skipped tests are upstream PostgreSQL checks without a configured
disposable cluster, not successful DB tests. Python 3.12.14 and Node 24.19.0 were
used with existing lockfiles. The added Auth-boundary cases inject an upstream
401 and prove no Listing UoW is entered; they do not decode or validate JWTs.

Remaining **BLOCKED / NOT_RUN**: real GPU-002/003 adapters and router/shell wiring;
PostgreSQL multi-session lock/rollback/role tests; full API-LIST-13/14/15
submit/allocation/FIFO races; persistent DB audit integration where applicable;
browser-to-real-API E2E and the benchmark. Keep Phase 1D out of `IMPLEMENTED`.

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
