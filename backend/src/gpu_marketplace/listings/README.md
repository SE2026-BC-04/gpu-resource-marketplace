# GPU-004 Listings — implementation and integration handoff

Status: **core/router/UI on `feat/gpu-004-listings`; real Auth dependency connected;
PostgreSQL/shared-app integration BLOCKED**.
Baseline: `main@7fa6afc` (25/10/2026). Application dependencies come from
`6434ee3` (PR #27 D1 / #26 session UI); the later #19 merge adds GPU-005 docs only.
The user explicitly authorized GPU-004 coding.
This does not claim that the complete Phase 1D acceptance gates have passed.
GPU-002-B now supplies ORM mappings and migration `0001_phase1b_baseline`, but
Listing repositories/UoW are not handed off. GPU-003 core and Auth routes are on
this baseline, including the volatile session store. The PostgreSQL account
reader in PR #25 is still Draft/unmerged at this review; Listing UoW/D7 are not delivered.

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
- `createSessionListingsApi` and `SessionListingsPage` consume GPU-003's real
  SessionStore, preserving the sent-token guard and stable API instance.
- Trusted middleware request IDs are reused; absent/invalid state gets a fresh
  server UUIDv4. Incoming client request-ID headers are never trusted.

## Required owner handoffs

`ports.py` contains **GPU-004 consumption interfaces**, not an implementation of
GPU-002 persistence. [TV2 ACK_WITH_ACTIONS on `f7d3c0d`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6388130749)
confirmed these ports and service usage; they remain unchanged. This is not a
delivered adapter or PostgreSQL Listing test PASS. TV3 also
[confirmed the Auth connection](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6389075737).

| Owner | Required implementation / evidence |
|---|---|
| GPU-002 / TV2 | Use the existing migration/ORM; still need PostgreSQL-backed UoW, Worker lookup, Listing repository and Job constraint reader, with runtime-role evidence |
| GPU-003 / TV3 + TV2 | Canonical principal dependency is available and consumed; still need the reviewed PostgreSQL account adapter/provisioning and shared volatile session integration |
| Leader | Shared AuthService/engine/session/JWT-secret configuration, router registration in `api/app.py`, frontend shell mounting, cursor-key injection, request correlation and audit integration |
| TV2/TV3/leader | Resolution of the documented Auth sync/provisioning gates and applicable D1–D12 decisions/ACKs |

The production `api/app.py` and frontend `App.tsx` are intentionally not changed:
their ownership is shared and required DB adapters/configuration are absent. The
merged GPU-003 Login-first shell remains the default screen, without Listings.
Do not mount test doubles,
accept a user/role header as authentication, or use a privileged DB connection as
a substitute for the missing runtime adapters.

### Auth decision tracking

The owner confirmed `DEC-P1-03` in [PR #13](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372245355).
API Contract **v0.9** on the upstream baseline records the approved Auth profile;
this branch adds the approved Listings body change at **v0.10**. PR #18
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
but real restricted-role/UoW/timestamp tests remain open. D1 revision `0002` is
now on the merged baseline (`2b9a4c7` hardens membership options without changing
Listing column grants); no local migration or runtime-DSN activation was done.
A joined projection must lock only the Listing row, not every
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

Mount `SessionListingsPage` from
`frontend/src/ui/listings/SessionListingsPage.tsx` with the **same** SessionStore
instance already passed to `App`: `<SessionListingsPage session={session} />`.
The component subscribes to the real store, creates a stable auth-aware API, maps
`state.user.id/role`, and supplies null when signed out. Logout/expiry unmounts
the protected workspace. The generic `ListingsPage`/`createListingsApi` remain
available; `createSessionListingsApi(session)` implements the bridge agreed in
GPU-003 handoff §9. No token is persisted; current 401 clears the store, old 401
does not clear a newer token, and 403 keeps the session. This leaf component is
ready for integrator review, **not mounted into the shared shell by this change**.

### Approved Listings body bounds — CR-GPU-004-BODY-01

Pause/resume reuse GPU-003's `require_empty_body`: nonzero declared length or the
first nonempty chunk is rejected without buffering the rest. Parser
`RecursionError` maps to safe 400 INVALID_JSON. These preserve existing contracts.

[The owner decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6395344255)
marks **APPROVED_FOR_IMPLEMENTATION**, change path A: atomic L2 design + code in
PR #17. API Contract v0.10 §§3.3/7/14.6 and this branch now enforce **16,384 raw
bytes inclusive / 8 JSON levels counting root** on POST/PATCH. Auth then WORKER
role precede body checks; invalid input enters no Listing UoW. Declared length is
checked before reading and each actual chunk before copying, even with missing
or misleading length. Oversize -> 413 PAYLOAD_TOO_LARGE; malformed framing/UTF-8/
strict JSON, excess depth or parser exhaustion -> safe 400 INVALID_JSON. Typed
and unknown-field behavior is preserved. The existing reviewed reader/parser
is reused without modifying Auth policy or adding a parallel parser; the Listing
byte constant is independent of Login. Frontend handles 413 without logout/retry.

This is **P1 remediation ready for re-review**, not a self-closed finding or merge
approval. Required two independent human reviews and R1–R4 integration gates
remain open; no shared app/config, DB/schema/grant or Jobs change is authorized.

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
The new session consumer tests use the real store/client/component with fake
Auth HTTP/fetch/clock; other React tests inject a test API. These are not
PostgreSQL, production-shell or cross-process E2E evidence. The normal build
builds the merged Login-first shell; RTL also renders the separate Listings component.

Observed on 25/10/2026 after implementing the approved change on the
`main@7fa6afc` baseline: backend **607 passed / 132 skipped**, including **308**
Listings tests (**65** real-Auth/double-persistence, **37** ASGI correlation/body,
and **70** body-bound cases); frontend **104 passed**,
including **9** real-session Listings consumer cases. TypeScript and Vite build
passed. The 132 skipped tests are upstream PostgreSQL checks without a configured
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
Docker engine still stopped; no test-cluster configuration or local DB testing.
TV4 explicitly confirmed never using DB/Alembic for this project: D1 recovery is
not required based on that reported history. No physical old-volume inspection,
live revision query or migration/recovery action was performed.

The 70 body-bound cases reproduced **32 failures / 38 passes** on `1800379`
before the fix, then passed with the reviewed helper integration. Coverage
includes exact 16,384/16,385 bytes, no/false/malformed/extreme/leading-zero length,
single/multiple chunks (including rejection before copying a 4 MiB chunk), depth
8/9, bracket/quote escapes, invalid UTF-8/strict JSON/parser exhaustion, zero UoW,
safe errors and 401/403 precedence. This HTTP evidence still uses persistence
doubles and does not satisfy PostgreSQL or mounted-application acceptance.

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
