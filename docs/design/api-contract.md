# GPU Resource Marketplace - API Contract Design

**Document version:** v0.10 — owner-approved Listings request-body bounds (`CR-GPU-004-BODY-01`, §14.6), added on top of v0.9 Auth bounds; Markdown design record<br>
**Date:** 2026-10-25<br>
**Status:** **APPROVED_DESIGN** for the described API routes/DTOs, the 100 API contract-test IDs, and the owner-approved scope of `API-OPEN-01`, `API-OPEN-02`, and `API-OPEN-06` (2026-10-18). The additional JWT claim/header profile, fractional NumericDate representation and login-normalization repertoire were **owner-approved as `DEC-P1-03` on 2026-10-21** (recorded in [Phase 1 §6](../architecture/phases/phase1_project_foundation.md)) and are synchronized in §§4.5 and 14.3. The L2 change `CR-GPU-003-UNICODE-01` (rejection of U+0000 and surrogate code points in `login_name`, safe Unicode password handling) was **owner-approved on 2026-10-24** ([#16](https://github.com/SE2026-BC-04/gpu-resource-marketplace/issues/16)) and is recorded in §§4.2, 4.5, 6 and 14.4. The Auth request-body bounds and the `D-C1`/`D-C2` error decisions directed by the team lead in the PR #23 review (2026-10-24) are recorded in §§3.3, 4.2–4.4, 6 and 14.5; they become approved with the L2 review of PR #23. ADR-008 Option B is **ACCEPTED** (2026-10-18). All implementation/API/database tests remain `NOT_RUN`; this document makes no claim that application code or migrations exist.
**Target repository path:** `docs/design/api-contract.md`  
**Output scope:** Markdown documentation only; no source code, SQL migration, OpenAPI generator, Docker file, or CI workflow.  
**Product scope:** Real GPU Marketplace simulation-only MVP. NOT the separate AD-090 assignment variant.

**v0.10 scoped approval:** [OWNER DECISION — CR-GPU-004-BODY-01, 2026-10-25](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6395344255) marks the Listings body-bound design **APPROVED_FOR_IMPLEMENTATION**, allowing atomic L2 design + implementation in PR #17. This is not approval to merge/deploy or full Listing/database acceptance; two independent human reviews and the other PR gates remain required. Actual scoped test evidence belongs in PR #17/Phase 1D, not an inferred PASS for this design catalogue. Auth/Jobs policy is unchanged.

## 1. Goal, workflow, and source of truth

### 1.1 Goal for this iteration

Define a reviewable API interface against the **approved 18-table Database Design** without silently changing business rules or runtime responsibilities. v0.1 specified common conventions and Authentication/RBAC; v0.2 recorded the **approved 15-minute stateless access-token decision** and designed **Worker GPU Listings** contracts. v0.3 drafted the remaining API groups; v0.4 records their acceptance as a design baseline. v0.5 synchronized the owner's approval of the broad JWT policy, trimmed case-sensitive login matching, and exact `simulation_input` allowlist. v0.6 separates those approved decisions from extra Authentication details that still need owner review. v0.7 records the owner's later approval of those extra details (`DEC-P1-03`, 2026-10-21) without changing their technical content. v0.8 adds the owner-approved change `CR-GPU-003-UNICODE-01` (2026-10-24): login names containing U+0000 or a surrogate code point are rejected before any database access, and passwords are handled without Unicode-encoding failures or truncation; `DEC-P1-03` semantics are unchanged. No endpoint or test is claimed implemented or verified.

### 1.2 Design and review workflow

1. Read approved product requirements, the physical/transactional data model and accepted ADRs.
2. Define consistent public HTTP/JSON semantics, authorization error categories and audit/correlation practices.
3. Specify Login, Logout and Current-User contract candidates, including data ownership and security boundaries.
4. Define reproducible API contract test cases with binary PASS/FAIL oracles.
5. Record the 2026-10-18 approval of the documented API contracts and the owner-approved scope of `API-OPEN-01/02/06`; keep additional implementation choices explicit and never claim executable verification without a code commit and test evidence.

**Review record:** The user approved the v0.4 API design baseline on 2026-10-18. The owner separately approved the broad `API-OPEN-01` policy (HS256 JWT, dedicated API secret of at least 256 bits, 900-second lifetime, volatile-memory-only browser storage, no refresh token and no immediate server-side Logout revocation), `API-OPEN-02` (trim surrounding login whitespace, case-sensitive matching, and the same rule for seeding/provisioning and login), and `API-OPEN-06` (the exact `simulation_input` allowlist). Those approvals did not specify every JWT claim/header or every Unicode normalization detail; the owner approved those details separately as `DEC-P1-03` on 2026-10-21 (see §§4.5 and 14.3). ADR-008 was accepted separately and does not itself approve these API details. This documentation records design decisions only; implementation and test status remain separate.

### 1.3 Normative references

- [SRS](../requirements.md): seeded single-role accounts, Login/Logout UC-G01, roles and ownership rules, 736 VUs, 23-day Job history, 7-day Dispute filing, 18-hour first Change Request response.
- [Functional Requirements](../functional-requirements.md): 21 P0 FRs across six business modules; authentication is cross-cutting.
- [Non-functional Requirements](../non-functional-requirements.md): NFR-S01/S02/S07 and performance/reliability goals.
- [Database Design](database-design.md): 18 approved tables, physical schemas and transactional ownership/locking design (no migrations have been run).
- [System Architecture](../architecture/system-architecture.md), [Quality Attributes](../architecture/quality-attributes.md).
- [ADR-001](../architecture/decisions/ADR-001-modular-monolith.md), [ADR-002](../architecture/decisions/ADR-002-postgresql-access-boundaries.md), [ADR-003](../architecture/decisions/ADR-003-internal-communication.md), [ADR-004](../architecture/decisions/ADR-004-signed-result.md), [ADR-005](../architecture/decisions/ADR-005-retry-timeout-internal-auth.md), [ADR-006](../architecture/decisions/ADR-006-dispute-retention.md) and [ADR-007](../architecture/decisions/ADR-007-load-test-configuration.md).
- [ADR-008](../architecture/decisions/ADR-008-technology-stack.md) is ACCEPTED for technology reference choices; this does not settle any API Auth/simulation-input details.

**Non-goals:** No personal-data-erasure feature/third-party adapter from AD-090; no public self-registration, real payments, real GPUs, multi-role account behavior, new database tables, or Admin manual adjudication. Do not substitute 99 VUs / 28 days / 22 hours from AD-090 for the product baseline.

## 2. API surfaces and design status

| Surface / planned group | Access path | Owning component | v0.6 design status |
|---|---|---|---|
| Authentication / current account | Public HTTPS-facing API | Backend API / Identity | **APPROVED_DESIGN** for owner-approved HS256/900-second/volatile-memory policy and trimmed case-sensitive login rule; additional profile details need owner decision (§4.5) |
| Worker GPU Listings | Public API | Backend API / Registry | **APPROVED_DESIGN**: six endpoints and 18 tests (Section 7) |
| Client Jobs and cancellation | Public API | Backend API / Jobs | **APPROVED_DESIGN** in Section 8 |
| Signed Result viewing | Public read-only API | Backend API / Results | **APPROVED_DESIGN** in Section 9 |
| Disputes and decisions | Public API and Manager-internal work | Backend API / Disputes; Manager adjudicates | **APPROVED_DESIGN** in Section 10 |
| Worker Reputation / dashboards | Public read-only API | Backend API / Reporting | **APPROVED_DESIGN** in Sections 11-12 |
| Manager -> Simulator dispatch | Internal HTTP | Manager sends; Simulator receives | ADR-003/005 accepted; **APPROVED_DESIGN** wire DTO and exact `simulation_input` allowlist in Section 13 |
| Simulator -> API signed callback | Internal HTTP | Simulator sends; API durably stores Inbox | ADR-003/004/005 accepted; **APPROVED_DESIGN** wire DTO in Section 13 |

**No front-end or user request directly mutates** GPU allocation, Job terminal state, accepted Signed Result, simulation oracle, Reputation or Manager scheduling state. Internal service identity is NOT a fourth end-user role.

## 3. Shared HTTP and JSON conventions (APPROVED_DESIGN)

### 3.1 Versioning and media type

| Item | Candidate rule / reason |
|---|---|
| Public base path | `/api/v1` for all public endpoints; future breaking contracts require a new version or approved compatibility policy. |
| Transport | HTTPS when accessed outside a trusted localhost/development context; no exposed direct DB/Simulator endpoint. |
| Request / response body | JSON over UTF-8; `Content-Type: application/json` for JSON bodies; `Accept: application/json`. |
| ID syntax | UUIDv4 lowercase with hyphens for public resource IDs, consistent with Database Design and ADR-004. |
| Time representation | Public timestamps, when an endpoint includes them, use normalized UTC ISO-8601 strings with six fractional digits and trailing `Z`; this is a public convention, NOT authority for retention/dispute decisions. |
| Server-trusted times | Database/server clock only. Client-provided `created_at`, `finished_at`, role or owner claims never govern admission, scheduling, dispute cutoff or cleanup. |
| Cache control | Auth responses and any private account/job/evidence views: `Cache-Control: no-store`. Do not cache authorization-sensitive cross-user responses. |
| Request correlation | Server emits `X-Request-ID` (server-generated UUIDv4) on success and failure and stores a redacted correlation value in operational audit. Clients must not force trusted actor identity by supplying this header. |
| Pagination | Details deferred to the Listings/Jobs groups; do not assume all collections return unlimited rows. |
| Idempotency | Per-command, not universally enabled. Job submit and service callback rules will be specified in their own sections in line with approved database/ADR constraints. Login is not a Job-creation idempotency operation. |

**Public JSON field casing:** `snake_case`, using stable lowercase enum strings only when a particular group explicitly defines lowercase; for approved business domain enums, preserve exact uppercase names (`CLIENT`, `WORKER`, `ADMIN`, `QUEUED`, etc.). Do not silently remap state-machine values.

### 3.2 Standard success behavior

- `200 OK`: successful read or synchronous login returning a JSON representation.
- `201 Created`: durable synchronous creation of a new resource (future Listing/Job/Dispute review decides whether a specific create operation instead uses `202`).
- `202 Accepted`: request durably accepted for asynchronous processing; NEVER means Worker execution completed or Signed Result verified. ADR-003/005 already require `202` for successful internal dispatch acknowledgment and durable callback ingress.
- `204 No Content`: a completed command with no response body, such as the proposed Logout candidate. Do not include a JSON body with `204`.

These are conventions, **not premature acceptance of endpoints still awaiting design**. In particular Job submit may be `201` for a committed `QUEUED` Job even though execution itself is asynchronous; the future Job section must lock its actual response semantics explicitly.

### 3.3 Standard error representation

All controlled public HTTP errors return this **candidate** structure (fields not listed here must not leak password hashes, tokens, private keys, simulation reference/oracle or raw DB errors):

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Authentication failed.",
    "request_id": "a3f70e25-559a-444f-8226-a667aa401e6c"
  }
}
```

| HTTP status | Meaning / examples | Security and state rule |
|---|---|---|
| `400` | Malformed JSON, unsupported field structure, syntactically invalid API request | No durable business mutation |
| `401` | Missing/invalid/expired user credential; unsuccessful login | No privileged data disclosed; do not enumerate users |
| `403` | Validly authenticated account but wrong role/permission | No mutation, log redacted denial |
| `404` | Resource absent, or private resource owned by another account when existence should be concealed | No cross-owner data disclosure; do not rely on client-side filtering |
| `409` | Legal request shape but conflicting immutable or current state (future cancel/pause/duplicate dispute, etc.) | Do not commit a partial business effect |
| `413` | Request body larger than the endpoint's limit: Login 16 KiB (§14.5); Listings POST/PATCH 16 KiB (§14.6), checked while received | Login: before account reads. Listings: after Auth/WORKER role, before JSON parsing and Listing UoW/SQL/mutation. Body never echoed |
| `422` | Well-formed JSON, but typed/field validation failed | Stable field validation details may be added in next group; no internal schema dump |
| `429` | Only if a rate-limit control is later explicitly adopted | Do not claim a rate limiter already exists |
| `500` / `503` | Internal failure / temporary dependency unavailable | Generic public message and request ID; no stack trace or secret |

**Ownership convention proposed:** For authenticated access to another Client's private Job/receipt/dispute, respond `404` rather than leak existence; for known cross-role commands the v0.2 Listing review proposes `403`, while a Worker mutating another Worker's Listing returns uniform `404` to conceal ownership/existence; other endpoint groups choose their own explicit policy when reviewed. Never authorize purely through visibility of an UI button.

### 3.4 Boundary and secret separation

- Public authenticated user credentials are **not** `MANAGER_DISPATCH_TOKEN` or `SIMULATOR_CALLBACK_TOKEN`. These two 256-bit direction-specific service Bearer tokens are already approved by ADR-005 and work **only** for their own internal route.
- A Manager is a service, not an `ADMIN` account. Admin end users are read-only monitors and cannot acquire Manager permissions via a role claim.
- API/Manager can use PostgreSQL under approved logical ownership rules; Worker Simulator cannot connect to PostgreSQL. Public clients never access `simulation_references` or Ed25519 private keys.
- Every state-changing request evaluates actual server-side account role and object ownership; client-sent user ID/role must not override the authenticated principal.
- Secrets are never returned in error bodies, audit metadata, frontend bundles or documentation fixtures. Redacted request IDs and error classes are safe to record.

## 4. Authentication / RBAC endpoint group (APPROVED_DESIGN; extra profile details pending)

### 4.1 Scope and required accounts

**Use case:** UC-G01 Login / Logout; NFR-S01/S02/S07. The MVP provisions accounts **before** use. Each `users` row is `ACTIVE` or `DISABLED`, and each account has **exactly one** role from `user_roles` (`CLIENT`, `WORKER`, `ADMIN`). These facts come from the approved Database Design. There is NO public `register`, `signup`, `change-role`, `reset-password` or `create-admin` endpoint in this review.

**Owner:** Backend API Identity boundary. Authentication reads `users`, `user_roles` and `roles`; login/logout may write redacted `audit_events`. Neither caller nor frontend may write `user_roles` or change authorization identity.

**Owner-approved authentication policy (2026-10-18):** use a signed **JWT with HS256** and a dedicated API secret of at least 256 bits, valid for exactly **900 seconds**. There is no refresh token or user-session table. The browser keeps the token in volatile memory only; it must not persist it to Web Storage, IndexedDB, cookies, URLs, or service-worker caches. Logout causes the client to discard the token but **does not revoke an issued token on the server**; an unexpired token can still authenticate until expiry unless the account is disabled or rejected by fresh server-side checks. Login trims surrounding whitespace and matches case-sensitively; seeding/provisioning and Login use the same rule. The exact JWT claim/header profile and login normalization repertoire are not included in that approval (§4.5). Do not conflate end-user access tokens with ADR-005 service tokens.

### 4.2 `POST /api/v1/auth/login` - sign in to a preseeded account

| Contract property | Proposed value |
|---|---|
| Access | Public (unauthenticated request allowed) |
| Owner / reads | API Identity; `users` + `user_roles` (`roles` catalog) |
| Body | Required `login_name` and `password` strings; no `role` or `user_id` accepted |
| Request body bounds | `Content-Type: application/json` required (an optional `charset` must be `utf-8`), otherwise `400 INVALID_JSON`; raw body at most **16 KiB** (16,384 bytes), enforced from `Content-Length` and while the stream is received (also without or with a misleading `Content-Length`), otherwise `413 PAYLOAD_TOO_LARGE`; strict UTF-8 JSON with no duplicate keys, no `NaN`/`Infinity` and at most 8 nested arrays/objects, otherwise `400 INVALID_JSON`, never `500`. All of these are decided before any database query (§14.5) |
| Input validation | `login_name` length 1..128 after applying the owner-approved surrounding-whitespace trim rule; `password` nonempty; malformed JSON or unexpected fields -> `400`; missing/empty/wrong-type required fields -> `422`; the trim set is exactly ASCII SP/HT/LF/CR (`DEC-P1-03`, §4.5); a `login_name` containing U+0000 or any surrogate code point U+D800..U+DFFF -> `422`, decided **before any database query** (`CR-GPU-003-UNICODE-01` R1) |
| Login name matching | Trim only ASCII SP/HT/LF/CR at both ends and match case-sensitively; keep U+00A0 and other Unicode whitespace; apply no NFC/NFD normalization or case folding; accept otherwise-valid Unicode, including supplementary (non-BMP) code points; seeding/provisioning and Login use the **same** pure validation/normalization implementation in `identity/`, never a duplicate (`API-OPEN-02` + `DEC-P1-03`, §4.5; `CR-GPU-003-UNICODE-01` R2, R6) |
| Authentication | Verify password against stored **hash**, require `users.status='ACTIVE'` and exactly one valid assigned role; never compare/store plaintext password. The password is never trimmed or normalized; U+0000 in a password is **not** rejected or truncated, and the exact password bytes are hashed and compared (R4). A password containing an unencodable surrogate code point returns the same generic `401 INVALID_CREDENTIALS` as a wrong password, never `500` (R3) |
| Success | `200 OK`, `Cache-Control: no-store`, response JSON containing authenticated `user` and credential info (shape below) |
| Wrong name/password/disabled account | `401 INVALID_CREDENTIALS` with the same generic message; do not reveal which condition failed |
| Corrupt or missing role mapping | Refuse login with the same generic `401 INVALID_CREDENTIALS` as other login failures (`D-C2`, §14.5); log redacted server-side failure and fail closed; never guess role, default to Admin or reveal account existence |
| Side effects | No GPU/Job/Worker/Reputation effect; optionally one sanitized audit event |
| Error redaction | No raw `login_name`, password, password hash, token or driver/Unicode exception text in any public response or log (`CR-GPU-003-UNICODE-01` R5) |

**Proposed request:**

```json
{
  "login_name": "demo_client",
  "password": "<password-entered-by-user>"
}
```

**Proposed success shape under APPROVED Option A token policy:**

```json
{
  "access_token": "<issued-short-lived-user-token>",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "e98d4b53-dca0-4a50-8ea0-51647b60b254",
    "login_name": "demo_client",
    "role": "CLIENT"
  }
}
```

**Security notes:** Example token/password are placeholders, not usable credentials. `expires_in=900` seconds and the HS256 JWT profile are **APPROVED**; calculate expiry from a server-trusted issue instant and reject at the exact expiry boundary (`now >= exp`). Do not send `password_hash`, any Worker private key, or internal service tokens in this response.

### 4.3 `GET /api/v1/auth/me` - current identity

| Contract property | Proposed value |
|---|---|
| Access | End-user JWT signed with approved HS256 policy using `Authorization: Bearer <user-token>` and within the approved 900-second lifetime; the approved claim/header profile is listed in §4.5 |
| Owner / reads | API Identity; current account/role record |
| Success | `200 OK`, `Cache-Control: no-store` |
| Success body | `id` UUIDv4, `login_name`, `role`; only the account identified by the validated credential |
| Missing/invalid/expired authentication | `401 UNAUTHORIZED` with `WWW-Authenticate: Bearer` (`D-C1`, §14.5); no identity body |
| Disabled account or missing role mapping | Fail closed as `401 UNAUTHORIZED` / invalid current session; never infer `ADMIN` |
| Service-token attempt | `401`; internal service tokens are not user identities |

**Proposed success response:**

```json
{
  "id": "e98d4b53-dca0-4a50-8ea0-51647b60b254",
  "login_name": "demo_client",
  "role": "CLIENT"
}
```

An end-user token's role claim, if one exists, is not permission to ignore the authoritative account/role status. Protected operations must use the trusted server-side principal and enforce ownership, independently of front-end route guards.

### 4.4 `POST /api/v1/auth/logout` - end the current client session

| Contract property | Proposed value |
|---|---|
| Access | Valid end-user authentication; no request body: any nonempty body -> `400 INVALID_JSON`, checked before authentication (§14.5) |
| Success | Proposed `204 No Content` (no response body), `Cache-Control: no-store` |
| Side effects | Does not cancel jobs, release GPU, revoke Worker signing keys or delete account data |
| Idempotent visible behavior | Repeating logout with a still-valid credential yields a harmless `204`, with no domain business effect |
| Missing/invalid user authentication | `401 UNAUTHORIZED` with `WWW-Authenticate: Bearer` (`D-C1`, §14.5) |
| Precise security semantics | **APPROVED LIMITATION:** Logout does not revoke an issued token on the server. The client discards it; a copied/stolen unexpired token could remain usable until expiry if the account is still ACTIVE. Do not misstate a `204` response as invalidating previously issued Bearer credentials. |

**Do not label a stateless logout response as proof of immediate token invalidation.** The UI must disclose this approved limitation. The API cannot force a client to delete a copied credential. No automatic account deletion or personal-data-erasure behavior is implied by Logout.

### 4.5 Approved end-user credential policy and pending profile details

| Candidate | Fits approved 18-table data model? | Login/Logout properties | Main drawback |
|---|---|---|---|
| **A. Short-lived HS256 JWT, no refresh token for MVP (APPROVED)** | Yes, if a dedicated signing secret is injected outside DB and account/role/status are validated server-side | Login returns a 15-minute Bearer token; `/me` uses it; the browser keeps it in volatile memory only; Logout clears client-held token and may record a redacted event | Already issued tokens remain usable until expiry unless account disabled; no immediate logout revocation |
| **B. Revocable server-side session** | **No, not without a separately approved physical-model change or existing sanctioned external session store** | Immediate session invalidation on Logout is possible with session state | Requires additional storage/session model and tests, modifying the approved 18-table scope or introducing a new approved component |

**Owner-approved policy (2026-10-18):** the credential is an HS256-signed JWT with a dedicated API secret of at least 256 bits. The trusted issue instant is authoritative, `exp = iat + 900 seconds`, a token is valid only before `exp`, and the API rejects when `now >= exp`; no expiry tolerance is part of this contract. Protected requests revalidate the account's ACTIVE status and authoritative role mapping; a signed role claim does not supersede database permissions. There is no refresh token, user-session table, or immediate server-side Logout revocation. The browser holds the token only in volatile memory. The signing key remains distinct from the two internal service Bearer tokens and Worker Ed25519 signing keys. These are the approved scopes of `API-OPEN-01` and `API-OPEN-02`; the claim/header and Unicode details below were approved separately as `DEC-P1-03`.

**Additional JWT profile — APPROVED (`DEC-P1-03`, 2026-10-21):** header `typ=JWT`; `iss=gpu-marketplace-api`; `aud=gpu-marketplace-web`; `sub` is the user's UUID. These technical hardening/representation choices were added in earlier draft text and later approved by the owner; token issuance and validation must enforce them exactly.

**NumericDate precision — APPROVED (`DEC-P1-03`, 2026-10-21):** JWT NumericDate is a JSON number of seconds since the Unix epoch, and its definition permits non-integer values ([RFC 7519 §2](https://www.rfc-editor.org/rfc/rfc7519.html#section-2)); the `exp` rule requires current time to be before expiration and permits optional leeway, which this project does not approve ([RFC 7519 §4.1.4](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.4)). To preserve the approved exact 900-second lifetime, the approved representation retains six fractional decimal places for trusted `iat`/`exp`, sets `exp = iat + 900.000000`, and compares using equivalent exact microsecond/decimal precision without truncation, rounding, or tolerance. `T0+899.999999s` is valid and `T0+900.000000s` is expired. Integer-second truncation or rounding can change the actual elapsed lifetime from the issuance instant, which is why the representation is fixed explicitly.

**Login normalization repertoire — APPROVED (`DEC-P1-03`, 2026-10-21):** the owner first approved trimming surrounding whitespace, case-sensitive matching, and applying one consistent rule to seeded/provisioned names and Login (`API-OPEN-02`), then approved the exact repertoire: trim ASCII space, tab, line feed, and carriage return only; preserve other Unicode whitespace (including U+00A0) as part of the name; do not apply NFC/NFD or case folding. This avoids silently treating all Unicode whitespace as trim characters.

**Unstorable code points — APPROVED (`CR-GPU-003-UNICODE-01`, 2026-10-24, [#16](https://github.com/SE2026-BC-04/gpu-resource-marketplace/issues/16)):** PostgreSQL `text`/`varchar` cannot store U+0000, and surrogate code points U+D800..U+DFFF (which a JSON `\u` escape can produce) cannot be encoded as UTF-8. A `login_name` containing either is therefore rejected with `422` at the application boundary, before any database query, by the same `identity/` function used for provisioning. This adds a rejection only; the `DEC-P1-03` trim, case and no-normalization rules above are unchanged, and every other valid Unicode character, including supplementary code points, remains part of the name.

## 5. Authorization and error decision matrix (APPROVED_DESIGN)

| Caller / action | Login | `/auth/me` | Worker-only mutation | Client-only mutation | Admin dashboard read | Internal dispatch/callback |
|---|---|---|---|---|---|---|
| Anonymous | Allowed request; invalid credentials -> 401 | 401 | 401 | 401 | 401 | 401 |
| `CLIENT` | Allowed credentials | 200 own identity | 403 | Role + owner/state validation | 403 | 401 |
| `WORKER` | Allowed credentials | 200 own identity | Role + owner/state validation | 403 | 403 | 401 |
| `ADMIN` | Allowed credentials | 200 own identity | 403 (read-only in MVP) | 403 | Allowed read | 401 |
| Internal Manager dispatch token | Not an end-user password | 401 | 401 | 401 | 401 | Only Manager -> Simulator endpoint |
| Internal Simulator callback token | Not an end-user password | 401 | 401 | 401 | 401 | Only Simulator -> API callback endpoint |

The planned resource mutations in this table are **authorization requirements**, not finalized route names or business response schemas. Worker/Client object ownership is ALWAYS checked server-side against the real persisted owner. Admin reads are limited to approved dashboard scope. A private object belonging to another Client must not become accessible by editing its URL.

## 6. Authentication contract test design (APPROVED_DESIGN; ALL `NOT_RUN`)

### 6.1 Fixed fixtures and evidence

- Three seeded active accounts `C1/CLIENT`, `W1/WORKER`, `A1/ADMIN`; each uses a different known test password hash and a single role mapping.
- One `DISABLED` account `D1`; one nonexistent `login_name`; wrong-password fixture; a deliberately corrupted account missing its role association in a controlled negative test database.
- Distinct service-only tokens for Manager dispatch and Simulator callback; neither is an end-user credential.
- Separate Worker Listing owned by `W1`, private Job owned by `C1`, and a second Client `C2` (future resource-group fixtures).
- Fixed fake clock `T0` for JWT expiry checks; capture API status, redacted JSON, DB before/after snapshots and structured audit with no secrets. Use canonical and whitespace-wrapped login fixtures, a space-only value, a case variant, U+00A0-wrapped input, and precomposed/decomposed Unicode fixtures; the last two use the `DEC-P1-03` oracles in §4.5.
- For every case: set implementation version, test fixture ID, command, elapsed time, observed HTTP status/body, and PASS/FAIL/NOT_RUN. No behavior is asserted to have executed here.

| ID | Action | Binary PASS oracle | Prerequisite |
|---|---|---|---|
| `API-AUTH-01-ROLES` | Login separately with valid C1/W1/A1 canonical credentials; repeat C1 with the same login surrounded by U+0020 spaces; seed/provision a whitespace-wrapped C1 name and login with its canonical form; try a U+0020-only login and a mixed-case variant | Canonical and U+0020-wrapped C1 requests return `200` with the same C1 identity; provisioning and Login resolve the same canonical name; U+0020-only input returns `422` after trim; mixed-case variant returns generic `401`; three role identities match DB; 0 secret fields in replies | Owner-approved trim/case/seed consistency rules; Unicode-specific subcases below follow `DEC-P1-03` |
| `API-AUTH-02-GENERIC-FAIL` | Unknown login, wrong password and disabled D1 with otherwise valid password; valid C1 `login_name` with a password containing a lone surrogate code point; an account provisioned with a password containing U+0000 (for example `ab` U+0000 `cd`), logging in with the exact password and with the prefix `ab` | All failures return `401 INVALID_CREDENTIALS` with equivalent public message, including the surrogate password (never `500`); 0 role or account existence disclosure; the exact NUL-containing password returns `200` and the prefix `ab` returns `401`, proving no truncation (`CR-GPU-003-UNICODE-01` R3, R4) | Auth decision accepted; CR approved 2026-10-24 |
| `API-AUTH-03-BAD-BODY` | Missing `login_name`, empty password, malformed JSON and injected `role='ADMIN'` in login body; `login_name` containing U+0000 at the start, middle and end; `login_name` containing a lone high surrogate, a lone low surrogate, or two surrogate code points | Malformed JSON and injected unknown `role` -> `400`; missing `login_name` or empty `password` -> `422`; missing or non-JSON `Content-Type`, invalid UTF-8, more than 8 nested arrays/objects and an over-limit integer -> `400 INVALID_JSON` (never `500`); a body over 16 KiB -> `413 PAYLOAD_TOO_LARGE` whether `Content-Length` is accurate, absent (chunked) or misleading; each body-bound case with **0 account reads** and no echo (§14.5); every U+0000 or surrogate `login_name` -> `422` with **0 database queries**, no echo of the input in body or logs, and no `500`/encoding exception; no account/role mutation (`CR-GPU-003-UNICODE-01` R1, R5) | Validation contract approved; CR approved 2026-10-24 |
| `API-AUTH-04-ME-OWN` | GET `/auth/me` with valid C1 credential | `200` and C1 identity only; no password hash/token contents, other users or secrets | Auth decision accepted |
| `API-AUTH-05-NO-AUTH` | GET `/auth/me` without a credential; with malformed/tampered JWT; with `exp` changed to a future value while keeping the original signature; with an unsupported signing algorithm such as `none` or `HS384`; or with a correctly signed token whose `typ`, `iss` or `aud` differs from §4.5 or whose `sub` is not a UUID; or with a correctly signed token that omits `typ`, `iss`, `aud` or `sub`, or carries a header/claim with the wrong JSON type (for example a numeric `sub`, a non-string `iss`/`aud`/`typ`, or a string `iat`/`exp`) | `401` for every invalid credential, including the modified-`exp` token, any `alg` other than HS256 and every `DEC-P1-03` header/claim mismatch, omission or type error; no identity body | Owner-approved HS256, expiry policy and `DEC-P1-03` profile |
| `API-AUTH-06-EXPIRED` | Issue token at trusted fake `T0`; call `/auth/me` at `T0+899.999999s` and `T0+900.000000s` | Approved oracle: reject at exactly `now >= exp` with no tolerance; with the approved microsecond NumericDate representation in §4.5, `+899.999999s` returns `200` and `+900.000000s` returns `401` | Exact 900-second policy and `DEC-P1-03` NumericDate representation APPROVED; test `NOT_RUN` |
| `API-AUTH-07-DISABLED-AFTER-ISSUE` | Disable C1 after issuing an access credential; call `/auth/me` | Request rejected at 401; server-side account status not bypassed by a still-well-signed token | Auth decision accepted |
| `API-AUTH-08-MISSING-ROLE` | Try login for account with no valid unique role mapping | Login rejected; 0 default role and 0 Admin escalation | Controlled negative DB fixture |
| `API-AUTH-09-CROSS-ROLE` | C1 requests Worker write; W1 requests Client write; A1 requests any business write | `403` for each wrong-role request; no domain mutation | Related routes subsequently defined |
| `API-AUTH-10-OBJECT-OWNER` | C2 requests C1's private Job/receipt/dispute | Uniform `404` for private resource, no C1 data disclosed | Related resource routes subsequently defined |
| `API-AUTH-11-TOKEN-BOUNDARY` | Call `/auth/me` with Manager and Simulator service-only tokens; use a Client token for either internal route | Every call denied 401 with zero Inbox/dispatch/domain mutations | Internal API routes defined |
| `API-AUTH-12-LOGOUT` | Call Logout twice with C1 token; try same token against `/auth/me` before expiry, then at expiry; call Logout with a JSON or non-JSON body, including a chunked one | Design expects `204` twice, 0 domain changes; any nonempty Logout body returns `400 INVALID_JSON` before the account is read; same token can authenticate before expiry while account ACTIVE, must be `401` at expiry; client deletes its token locally | Logout non-revocation policy and route APPROVED_DESIGN; test `NOT_RUN` |
| `API-AUTH-13-NO-SECRETS` | Search public JSON replies, request traces, audit metadata, redacted errors, and browser persistent stores for injected passwords, password hashes, user token, service tokens, signing keys | 0 raw secrets exposed in artifacts/logs; user token appears only in volatile browser memory; correlation IDs present | Sanitized test environment |
| `API-AUTH-14-NO-SIGNUP` | Probe public account-registration/role-assignment routes | No route allows creating user or changing role; unimplemented `/api/v1/auth/register` and role-assignment paths respond `404`; no account or role mutation | Public API routing implemented |

**Approval vs execution:** All rows are proposed test *designs*, currently `NOT_RUN`. An auth group cannot be called `VERIFIED` until every applicable approved mandatory check actually runs with evidence. A deferred test is not silently assumed to PASS.

**Additional normalization subcases under existing `API-AUTH-01-ROLES` (no new test ID):**

- **Unicode whitespace (`U+00A0` NO-BREAK SPACE):** fixture uses `\u00A0demo_client\u00A0` against a seeded canonical ASCII `demo_client`. Approved oracle (`DEC-P1-03` ASCII-only trim, §4.5): U+00A0 is part of the login name, so the request returns generic `401`, not `200`.
- **Unicode normalization-sensitive name:** seed the exact precomposed `caf\u00E9` login and verify that exact sequence succeeds. Approved oracle (`DEC-P1-03` no-normalization rule): decomposed `cafe\u0301` is a distinct name and returns generic `401`; no NFC/NFD equivalence is assumed.
- **Provisioning/Login consistency:** apply the same normalization function once when writing the seeded `users.login_name` and when parsing Login input. A seed input of `  demo_client  ` and login input `demo_client` must resolve to the same account; the same oracle applies to HT, LF and CR at either end, and not to any other character.
- **Supplementary and precomposed names (`CR-GPU-003-UNICODE-01` R6):** seed a login containing a non-BMP character (for example U+1F600) and a precomposed Vietnamese name; the exact sequences succeed, length is counted in code points (128 non-BMP characters are accepted, 129 are rejected with `422`).
- **Provisioning rejects unstorable names (R2):** the provisioning path, using the same `identity/` function, refuses a seed `login_name` containing U+0000 or a surrogate code point and writes nothing to the database.

## 7. Worker GPU Listings contract (v0.2 design baseline; tests `NOT_RUN`)

### 7.1. Goal, workflow, ownership and scope

**Goal:** support FR-WR-02/03/04 and UC-W01/W02 plus Client marketplace browsing (UC-C01/C02) using exactly the approved `workers`, `gpu_listings`, `jobs` and optional `worker_reputation_aggregates` read model. This section **does not** add tables, public Worker onboarding, payments, auto-matching, real GPU allocation, or Manager scheduling endpoints.

**Review workflow:** (1) lock the public Listing representation; (2) design browse/detail/create/edit/pause/resume; (3) specify server-enforced roles and Listing ownership; (4) bind edits to the approved Listing-row-first transaction protocol; (5) freeze error oracles and contract tests; (6) request stakeholder approval **before proceeding to the Jobs group**.

- **Registry / Backend API owns** Listing creation, metadata edits and `ACTIVE ↔ PAUSED` transitions; the authenticated `WORKER` maps through `workers.user_id` to immutable `gpu_listings.worker_id`.
- **Manager owns** allocation/release and is the *only* legitimate writer of `allocated_gpu_count`. API Listing endpoints NEVER set/recompute it outside the shared domain transaction.
- **No caller** may supply or overwrite `worker_id`, `allocated_gpu_count`, `created_at`, `updated_at`, Listing ID, or another user's identity in a create/update body. No private Worker signing keys, simulation truth, or internal service tokens are Listing data.
- **Authenticated marketplace view:** `CLIENT`, `WORKER`, `ADMIN` may read public Listing metadata, but the `marketplace` collection returns **ACTIVE only**. A direct detail view can show PAUSED metadata and `accepting_jobs=false` (to make Job-linked listings readable); **PAUSED never admits new submissions or allocations**.
- **Worker management view:** `scope=mine` reveals the current Worker's own ACTIVE and PAUSED Listings; never infer Worker ownership from a query/body-supplied identifier. `scope=all` is a read-only Admin view. Admin is not authorized to create/edit/pause/resume for a Worker.

### 7.2. Endpoint register

| Method | Path | Allowed caller | Proposal / result | DB owner and effects |
|---|---|---|---|---|
| `GET` | `/api/v1/gpu-listings` | Authenticated `CLIENT`, `WORKER`, `ADMIN`, scope constrained by role | `200` paginated Listings | Read `gpu_listings` joined to `workers` and Reputation; no writes |
| `GET` | `/api/v1/gpu-listings/{listing_id}` | Authenticated `CLIENT`, `WORKER`, `ADMIN` | `200` Listing detail, including PAUSED status | Read-only; no evidence/oracle/key exposure |
| `POST` | `/api/v1/gpu-listings` | `WORKER` | `201 Created` plus `Location` header | Insert own Listing, default ACTIVE and allocated=0 |
| `PATCH` | `/api/v1/gpu-listings/{listing_id}` | Owner `WORKER` | `200` with updated Listing | Metadata/capacity transaction with Listing lock |
| `POST` | `/api/v1/gpu-listings/{listing_id}/pause` | Owner `WORKER` | `200` with PAUSED Listing | Atomic state transition; running Jobs preserved |
| `POST` | `/api/v1/gpu-listings/{listing_id}/resume` | Owner `WORKER` | `200` with ACTIVE Listing | Atomic state transition; Manager resumes FIFO asynchronously |

Use `Authorization: Bearer <user-access-token>` for protected endpoints per Section 4.5: validate the owner-approved HS256 signature and 900-second lifetime; apply additional claim/header checks only after the decisions in §4.5 are approved. No Listing mutation authorizes users by trusting a `worker_id` in the JSON.

### 7.3. Read DTO, price precision and computed availability

**Proposed canonical Listing DTO (public-safe fields):**

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "worker": {
    "id": "11111111-1111-4111-8111-111111111111",
    "display_name": "Demo Worker",
    "reputation": {
      "successful_jobs": 7,
      "worker_fault_jobs": 3,
      "success_rate": "0.7000"
    }
  },
  "gpu_model": "NVIDIA A100 (simulated)",
  "vram_gb": 80,
  "total_gpu_count": 8,
  "allocated_gpu_count": 3,
  "available_gpu_count": 5,
  "status": "ACTIVE",
  "accepting_jobs": true,
  "mock_price_per_hour": "12.50",
  "created_at": "2026-10-18T08:00:00.000000Z",
  "updated_at": "2026-10-18T08:00:00.000000Z"
}
```

- `available_gpu_count = total_gpu_count - allocated_gpu_count` is a **read snapshot of unallocated capacity**, not a reservation guarantee: FIFO head-of-line blocking and other Clients' requests can still prevent immediate scheduling.
- `accepting_jobs` is derived solely from `status == 'ACTIVE'` and represents admission policy; actual admission MUST recheck status/capacity in `TX-SUBMIT` with the Listing lock. A PAUSED Listing can still have allocated, RUNNING Jobs.
- `mock_price_per_hour` is a decimal **string** with exactly two digits after `.` (or JSON `null` if unset); no float rounding and **no real payment**. Proposed input is also a decimal string, e.g. `"0.00"` or `"12.50"`, with precision compatible with `numeric(12,2)` and value `>= 0`; values with more than two fractional places fail validation rather than silently rounding.
- Reputation is a projection of `worker_reputation_aggregates`; if eligible `SUCCESS + WORKER_FAULT == 0`, use `successful_jobs=0`, `worker_fault_jobs=0`, `success_rate=null` (**N/A** in UI). The string ratio is fixed to four fractional places for display, derived from lifetime counters; no per-Job evidence is exposed.
- `status` is exactly `ACTIVE` or `PAUSED`; only these two are in MVP. `created_at`/`updated_at` are server-trusted timestamps in the public convention of Section 3.1. Do not expose `password_hash`, `public_key_raw`, `private_key`, session/service token, simulation reference or raw execution data.

### 7.4. `GET /api/v1/gpu-listings` — browse/list management

**Proposed query parameters:**

| Name | Type/default | Interpretation |
|---|---|---|
| `scope` | Enum `marketplace` / `mine` / `all`; default `marketplace` | `marketplace`: all and only ACTIVE Listings, any authenticated role. `mine`: only current WORKER's Listings, including PAUSED. `all`: Admin-only read, including PAUSED |
| `status` | Optional `ACTIVE` or `PAUSED` | With `mine`/`all`, optional filter; omitted means both states. With `marketplace`, only omitted or redundant `status=ACTIVE` is valid; `status=PAUSED` returns `400 INVALID_FILTER` |
| `limit` | Integer, default 20, min 1, max 100 | Bound response size |
| `cursor` | Optional opaque, server-generated string | Keyset pagination; cursor bound to selected scope, status/filter and trusted caller identity for `mine` |

**Sorting:** `created_at DESC, id DESC` (stable tie-breaker, no duplicate on page transitions). An invalid, tampered or mismatched cursor is `400 INVALID_CURSOR`. A scope not permitted for the caller returns `403 FORBIDDEN` (e.g. Client with `mine`, non-Admin with `all`). If no more results, `next_cursor=null`. Ordinary inserts during paging may affect the overall set; keyset semantics prevent repetition of existing rows, but do not promise a cross-request snapshot.

**Proposed response `200`:**

```json
{
  "items": [
    {
      "id": "22222222-2222-4222-8222-222222222222",
      "worker": {
        "id": "11111111-1111-4111-8111-111111111111",
        "display_name": "Demo Worker",
        "reputation": {
          "successful_jobs": 7,
          "worker_fault_jobs": 3,
          "success_rate": "0.7000"
        }
      },
      "gpu_model": "NVIDIA A100 (simulated)",
      "vram_gb": 80,
      "total_gpu_count": 8,
      "allocated_gpu_count": 3,
      "available_gpu_count": 5,
      "status": "ACTIVE",
      "accepting_jobs": true,
      "mock_price_per_hour": "12.50",
      "created_at": "2026-10-18T08:00:00.000000Z",
      "updated_at": "2026-10-18T08:00:00.000000Z"
    }
  ],
  "next_cursor": null
}
```

`items` uses the exact DTO of Section 7.3. Empty collections return `200` with `items=[]` and `next_cursor=null`. Never trust `worker_id` query values to implement `mine`; resolve owner from authenticated account.

### 7.5. `GET /api/v1/gpu-listings/{listing_id}` — inspect metadata

- Valid Listing UUIDv4 -> `200` and Section 7.3 DTO; a PAUSED Listing remains readable, but `accepting_jobs=false`.
- Unknown ID -> `404 LISTING_NOT_FOUND`; wrong UUID format -> `422 VALIDATION_ERROR` (following Section 3.3).
- All three valid user roles may read **public-safe metadata**; they cannot view private signing data or another Worker's private Job/result through this route.
- This route is **not** an availability hold: Client Job submission must independently validate current Listing status and capacity under `TX-SUBMIT`.

### 7.6. `POST /api/v1/gpu-listings` — Worker creates own Listing

**Proposed request:**

```json
{
  "gpu_model": "NVIDIA A100 (simulated)",
  "vram_gb": 80,
  "total_gpu_count": 8,
  "mock_price_per_hour": "12.50"
}
```

| Field | Validation |
|---|---|
| `gpu_model` | Required nonblank string after trimming outer whitespace, length 1..160; casing preserved |
| `vram_gb` | Required JSON integer `>0` (`true`, floats and numeric strings are invalid) |
| `total_gpu_count` | Required JSON integer `>0`, bounded by PostgreSQL signed-32-bit `integer` |
| `mock_price_per_hour` | Optional `null` or decimal string, exactly 2 decimal places, value `0..9999999999.99`; omitting it stores `null` |

The API resolves the `WORKER` profile from the authenticated account, persists `gpu_listings.worker_id` itself, defaults `status='ACTIVE'`, `allocated_gpu_count=0` and uses database-generated timestamps and Listing ID. `worker_id`, `id`, `status`, `allocated_gpu_count`, timestamps and unknown fields are **not writable by the user** (`400 UNKNOWN_FIELD`). `CLIENT`/`ADMIN` creation -> `403 FORBIDDEN`; missing Worker profile -> `409 WORKER_PROFILE_MISSING` without creating a Listing. Required-field/type violations -> `422 VALIDATION_ERROR`.

**Success:** `201 Created`, `Location: /api/v1/gpu-listings/{id}`, body = Section 7.3 DTO. Same body submitted again **creates another Listing**; creation idempotency is **not** silently implied (no Listing idempotency key/column in the approved schema). This is distinct from Job submission idempotency.

### 7.7. `PATCH /api/v1/gpu-listings/{listing_id}` — Worker edits owned Listing

**Allowed PATCH fields:** `gpu_model`, `vram_gb`, `total_gpu_count`, `mock_price_per_hour` only; at least one must be present. Omitted fields remain unchanged. An explicit `mock_price_per_hour: null` clears the optional price. `status` is **not** PATCH-writable; use Pause/Resume endpoints. Empty objects and invalid value/types -> `422`; unknown or server-owned keys -> `400 UNKNOWN_FIELD`.

**POST/PATCH body boundary — APPROVED (`CR-GPU-004-BODY-01`):** both create (§7.6) and update (§7.7) accept at most **16,384 raw bytes, inclusive**, and at most **8 object/array levels counting the root**, ignoring brackets inside strings. Validate the authenticated WORKER first; check declared `Content-Length` before reading and count actual streamed bytes **before copying**, even with no length, an understated length or one oversized chunk. A numeric length above the bound, including excessive significant digits, or actual size above it -> **413 PAYLOAD_TOO_LARGE**; leading zeros do not change the value. Malformed length/framing, UTF-8/JSON, duplicate keys, NaN/Infinity, excessive depth or parser exhaustion -> **400 INVALID_JSON**. These checks finish **before any Listing UoW/SQL/mutation**. Existing application/json handling, typed/unknown-field semantics and pause/resume contracts remain unchanged. Exact size/depth does not bypass field validation; an array-valued metadata field at depth 8 is still `422`. Full decision and order are in §14.6.

**Example request:**

```json
{
  "total_gpu_count": 6,
  "mock_price_per_hour": "10.00"
}
```

**Server MUST execute a guarded Listing transaction (`TX-PAUSE-EDIT` in approved Database Design):**

1. Authenticate as `WORKER`; resolve `workers.id` from trusted account. Locate Listing; for nonexistent or non-owned Listing return **uniform `404 LISTING_NOT_FOUND`** with no data mutation.
2. Lock `gpu_listings[listing_id] FOR UPDATE` **before** inspecting/changing Listing capacity or reading its current queued/running Job constraints. Revalidate identity/state after acquiring the lock; do not accept stale pre-lock reads. Concurrent Manager `TX-ALLOCATE`, Client `TX-SUBMIT`, pause and edit must use this same Listing lock.
3. If actually changing `gpu_model` or `vram_gb`, refuse while **any** Job under Listing is `QUEUED` or `RUNNING`: `409 LISTING_HARDWARE_LOCKED`. A no-op value equal to the current value does not count as hardware change.
4. On reducing `total_gpu_count`, require new total `>= allocated_gpu_count` **and** `>= MAX(requested_gpu_count)` among current `QUEUED` Jobs; reject with `409 LISTING_CAPACITY_BELOW_ALLOCATED` first if both fail, else `409 LISTING_CAPACITY_BELOW_QUEUED_MAX`. It must also remain `>0`.
5. `mock_price_per_hour` may be changed without changing existing Jobs' submitted parameters or starting real billing. One short DB transaction commits all accepted fields together; on failure, **zero partial updates**. Return `200` with the resulting DTO and `updated_at`.

**Concurrent metadata PATCH limitation:** No optimistic version/ETag column is present among the approved 18-table design. Two otherwise valid metadata edits serialize under the Listing lock, and the last committed value for an overlapping field wins. No promise of lost-update detection is made in this v0.2 contract; introducing one would require a separate reviewed design change. This does **not** relax GPU-capacity or ownership correctness.

### 7.8. `POST /api/v1/gpu-listings/{listing_id}/pause` and `/resume`

**Request:** no JSON body. **Success:** `200 OK` returning the Section 7.3 DTO with target state. Both commands are role- and owner-guarded, acquire the Listing row lock and are idempotent for repeated requests while Listing is already in that target state; a no-op need not advance `updated_at`.

| Command | Atomic DB effect | Required downstream behavior |
|---|---|---|
| `pause` | `ACTIVE → PAUSED` (or no-op if PAUSED) | Any Client submit/scheduler allocation that locks Listing **after the pause commits** must not be admitted/allocated; existing `QUEUED` stay queued; existing `RUNNING` are allowed to finish/release |
| `resume` | `PAUSED → ACTIVE` (or no-op if ACTIVE) | New submissions become eligible; Manager may asynchronously resume **strict FIFO** scheduling; API response does not claim GPU allocation or Job completion |

A racing submit/allocation committed **before** pause acquired its Listing lock is valid and may remain RUNNING; this is not a Pause violation. `CLIENT`/`ADMIN` mutation -> `403 FORBIDDEN`; missing/non-owned Listing -> `404 LISTING_NOT_FOUND`; invalid/missing user credential -> `401`. Neither operation performs billing, cancels Jobs, manually assigns work or updates Reputation.

### 7.9. Error mapping and enforcement summary

All errors use the Section 3.3 shape `{ "error": { "code", "message", "request_id" } }` and `X-Request-ID`; never return SQL details or signing secrets.

| HTTP | Business error code | Trigger / guaranteed state |
|---|---|---|
| `400` | `INVALID_JSON`, `UNKNOWN_FIELD`, `INVALID_FILTER`, `INVALID_CURSOR` | Malformed body, attempt to write managed column, incompatible scope/status filter or bad pagination cursor; no mutation |
| `401` | `UNAUTHORIZED` | No valid user access token, token expired/disabled account; no privileged data |
| `403` | `FORBIDDEN` | Wrong user role for `create/edit/pause/resume` or forbidden `mine/all` list scope; no mutation |
| `404` | `LISTING_NOT_FOUND` | Nonexistent or non-owned Listing on Worker mutation; hide owner resource existence |
| `409` | `WORKER_PROFILE_MISSING`, `LISTING_HARDWARE_LOCKED`, `LISTING_CAPACITY_BELOW_ALLOCATED`, `LISTING_CAPACITY_BELOW_QUEUED_MAX` | Business invariant rejects entire mutation; no partial state change |
| `413` | `PAYLOAD_TOO_LARGE` | POST/PATCH declared or actual raw body exceeds 16,384 bytes (§14.6); rejected before Listing UoW/SQL/mutation |
| `422` | `VALIDATION_ERROR` | Wrong/missing typed field, malformed UUID path, empty PATCH or out-of-range values; no mutation |
| `500`/`503` | `INTERNAL_ERROR`/`DEPENDENCY_UNAVAILABLE` | Unexpected failure or DB unavailable; no false success claim |

`400 INVALID_JSON` includes malformed framing/UTF-8/JSON, duplicate keys, nonstandard constants, excessive nesting and parser exhaustion before field validation (§14.6). For create/PATCH, precedence is **Auth → WORKER role → body validation → Listing UoW/SQL/mutation**: absent/invalid credential remains 401 and CLIENT/ADMIN remains 403 even with an oversized/malformed body. Never echo raw body or exception detail. A pause/submit or edit/allocate race is not resolved by UI checks; it must be resolved by the DB lock and the rechecked state under a single authorized transaction.

### 7.10. Reproducible Listing API contract tests (reviewed design; all `NOT_RUN`)

**Fixture:** `W1` is an ACTIVE seeded WORKER with one Worker profile; `W2` is another WORKER; `C1` is a CLIENT; `A1` is an ADMIN; all have valid single roles and 900s test access tokens. `L1` belongs to `W1`, initially ACTIVE, `total_gpu_count=8`, `allocated_gpu_count=3`, with `J_RUN` RUNNING (3 GPUs) and `J_Q` QUEUED (6 GPUs), and `L2` belongs to `W2`, PAUSED, with no active Jobs. A test fixture Worker reputation is `7/3`; use fixed UTC server clock, reset DB state between independent cases, barriers for contested DB-transaction tests and capture redacted request/response/audit and DB snapshots. Listing fixtures reference the approved 18 logical tables; they are **not** a claim of existing DB data.

| Test ID | Fixed action / stimulus | Exact PASS oracle |
|---|---|---|
| `API-LIST-01-MARKETPLACE` | As C1, `GET /gpu-listings?scope=marketplace` on L1 ACTIVE, L2 PAUSED | `200`; L1 included, L2 excluded; every item ACTIVE; no secret/internal fields |
| `API-LIST-02-MINE` | As W1 then W2, `GET /gpu-listings?scope=mine` | W1 sees exactly its Listings, W2 sees exactly its Listings (including PAUSED); 0 cross-owner rows |
| `API-LIST-03-ADMIN` | As A1, `GET /gpu-listings?scope=all` | `200`, both L1 and L2 visible; A1 still cannot invoke Worker mutation (403) |
| `API-LIST-04-SCOPE-RBAC` | C1 requests `scope=mine/all`; W1 requests `scope=all` | Every forbidden scope returns `403`, 0 private worker-management rows leaked |
| `API-LIST-05-DETAIL` | As C1, `GET` detail of paused L2 and nonexistent UUID | L2 `200 status=PAUSED accepting_jobs=false`; missing ID `404`; no oracle/key/user secrets |
| `API-LIST-06-CREATE` | W1 POST valid body with 8 GPUs and price `"12.50"` | `201`, Location includes new UUIDv4, `worker_id=W1` via owner join, `status=ACTIVE`, allocated=0, exactly one persisted row |
| `API-LIST-07-CREATE-INVALID` | Create with `vram_gb=0`, `total_gpu_count=0`, `price="-1.00"`, `price="1.001"`, injected `worker_id`, missing model; additionally POST size 16,384/16,385, absent/false/extreme/malformed length, oversized single/multiple chunks, depth 8/9, brackets/escapes in strings, invalid UTF-8/JSON/duplicates/constants/parser exhaustion (§14.6) | Invalid numbers/missing model 422; injected `worker_id` 400 UNKNOWN_FIELD. Valid exact-size body can create, over-size 413; malformed/deep/parser failure 400; depth 8 reaches typed validation. All body rejections have safe envelopes, zero Listing UoW/SQL/mutation and 401/403 precedence; 0 inserts for rejected cases |
| `API-LIST-08-CREATE-RBAC` | C1 and A1 POST valid Listing body | `403` each, 0 Listing inserts |
| `API-LIST-09-PATCH-METADATA` | W1 PATCH L1 price from `"12.50"` to `"10.00"` | `200`, price updated, model/VRAM/capacity/status/allocated unchanged; no Job mutation |
| `API-LIST-10-HARDWARE-BLOCK` | W1 PATCH model or VRAM of L1 while J_RUN and/or J_Q nonterminal | `409 LISTING_HARDWARE_LOCKED`, zero field changes; same-value no-op accepted |
| `API-LIST-11-ALLOCATED-BOUND` | Original W1 PATCH total to 2 with 3 allocated; additionally run §14.6 byte/depth/framing/strict-JSON boundary cases on PATCH | Valid parsed capacity violation remains `409 LISTING_CAPACITY_BELOW_ALLOCATED`, total 8. Valid exact-size metadata PATCH can succeed; oversized 413, malformed/deep/parser failure 400 before UoW/SQL/guard/mutation. Preserve field errors and 401/403 precedence |
| `API-LIST-12-QUEUED-BOUND` | W1 PATCH L1 capacity to 5 while 3 allocated and largest QUEUED request=6 | `409 LISTING_CAPACITY_BELOW_QUEUED_MAX`; total remains 8 |
| `API-LIST-13-PAUSE-RACE` | Barrier: pause L1 commits before competing C1 submit/Manager allocate get Listing lock | Listing PAUSED; new submit rejected (`409 LISTING_PAUSED` by future Job contract), 0 new allocation; J_RUN remains runnable to terminal |
| `API-LIST-14-RESUME-FIFO` | Pause L1 with J_Q waiting, then resume and run Manager | L1 ACTIVE; subsequent allocation follows `enqueue_seq` FIFO, 0 over-capacity, no automatic Job terminalization by API resume |
| `API-LIST-15-LOCK-RACE` | Barrier: W1 capacity PATCH races Manager allocation or Client submit on L1 | Committed order obeys Listing lock: either accepted update with guards rechecked or `409`; 0 capacity violations, 0 half-updated metadata |
| `API-LIST-16-OWNER-GUARD` | W2 PATCH/pause/resume L1 and W1 PATCH L2 | Each returns `404 LISTING_NOT_FOUND`; 0 cross-owner mutations |
| `API-LIST-17-RETRY-NOOP` | W1 pauses already PAUSED L1, then resumes twice | Each valid call `200`; exactly one state transition per target state, no Job cancellation/allocation by API command |
| `API-LIST-18-PAGINATION-SAFETY` | Seed 120 Listings with duplicate timestamps and stable UUIDs; page at `limit=20`, then mutate cursor/scope | All pages ordered `(created_at DESC,id DESC)` with no duplicate IDs, limit enforced, tampered/mismatched cursor `400 INVALID_CURSOR`; no cross-role data |

**Test rule:** A test design is approved only after stakeholder review; `NOT_RUN` until executed against a code commit and database fixture. No number here is a measured p95; ADR-007 remains the sole owner of the 736-VU benchmark protocol. Tests for `TX-PAUSE-EDIT`, `TX-SUBMIT`, `TX-ALLOCATE` and `DBTX` remain separate DB transaction verification, even if an API contract test references the same invariant.

### 7.11. Listing-group traceability and review gate

| Requirement / approved architectural rule | Proposed API or boundary | Evidence to collect when implemented |
|---|---|---|
| FR-WR-02; UC-W01 | `POST /gpu-listings`, owner assignment + field validation | API-LIST-06..08; database ownership FK |
| FR-WR-03; UC-W02 | `PATCH /{id}`, `/pause`, `/resume`; Listing-row-first TX | API-LIST-09..17; DBTX concurrency snapshots |
| FR-WR-04; UC-C01/C02 | Read catalogue and detail, ACTIVE filtering + lifetime reputation read | API-LIST-01..05, 18 |
| FR-JL-01..03; BR-03..08 | Admission and scheduling guarded by server Listing lock, NOT by response flags/UI | API-LIST-13..15; later Job and Manager tests |
| ADR-001/002/003/005; NFR-S02 | API Registry owns Listings; Manager alone allocates; service tokens distinct | API-LIST-04, 08, 16 plus API-AUTH-11 |
| Approved Database Design (18 tables) | `gpu_listings`, `workers`, `jobs`, `worker_reputation_aggregates` | DB constraints and transaction test design (`NOT_RUN`) |

**Review outcome (2026-10-18):** the Listings group was first reviewed in v0.2; the user subsequently approved the consolidated v0.4 Markdown design baseline. The six Listing endpoints and 18 `API-LIST` tests are **APPROVED_DESIGN** and `NOT_RUN`. The same design-level approval applies to the other documented API groups. The owner-approved API decisions `API-OPEN-01/02/06` are synchronized at their approved scope; the additional Auth profile details listed in §§4.5 and 14.3 remain pending. ADR-008 is already ACCEPTED. Future code evidence may require an explicit contract revision.


## 8. Client Jobs API (APPROVED_DESIGN; implementation `NOT_RUN`)

### 8.1. Scope, roles and transaction ownership

**Source:** FR-JL-01..06, ADR-001/002/003/005 and [Database Design](database-design.md) §9/§11. The Client chooses **one** existing `gpu_listings.id`; there is no automatic Worker selection, payment or real GPU execution. The **API owns** Job submission and QUEUED cancellation; the **Manager alone owns** FIFO allocation, `RUNNING`/terminal transitions, timeout fallback, GPU release and reputation. Neither a Client nor a Worker can send an API command to force execution/finalization.

| Method and route | Caller | Proposed success | Authoritative operation |
|---|---|---|---|
| `POST /api/v1/jobs` | `CLIENT` only | `201 Created`; identical idempotent retry `200` | `TX-SUBMIT`: Listing lock, Job `QUEUED` + immutable `simulation_references` same commit |
| `GET /api/v1/jobs` | `CLIENT`, `WORKER`, `ADMIN` with role-filtered scope | `200 OK` | Read only; visibility enforced in SQL/query layer |
| `GET /api/v1/jobs/{job_id}` | Owning Client, selected Worker, Admin | `200 OK` | Safe Job state projection only |
| `POST /api/v1/jobs/{job_id}/cancel` | Owning `CLIENT` only | `200 OK` | `TX-CANCEL`: only `QUEUED -> CANCELLED`; Listing lock before Job |

**Job-submission request (PROPOSED):**

```json
{
  "listing_id": "22222222-2222-4222-8222-222222222222",
  "gpu_count": 2,
  "duration_seconds": 60
}
```

Required header: `Idempotency-Key: client-generated-logical-submit-key` (printable ASCII 8..128 characters; **proposed** HTTP rule). Allowed JSON fields are **exactly** `listing_id`, `gpu_count`, `duration_seconds`. `gpu_count` is mapped to immutable DB field `jobs.requested_gpu_count`; positive JSON integer, not bool/float/string, and must be `<= gpu_listings.total_gpu_count` when locked. `duration_seconds`: positive JSON integer (DB signed 32-bit); **the maximum operational duration is not yet approved as a separate product restriction**. Unknown/server-owned fields such as `client_id`, `worker_id`, `status`, `failure_reason`, `terminal_at`, `enqueue_seq`, `simulation_reference` are rejected with `400 UNKNOWN_FIELD`. Wrong/missing typed required fields -> `422 VALIDATION_ERROR`. Authorization and Worker identity come from the authenticated account and locked Listing.

A temporarily insufficient **free** GPU count does **not** reject a valid Job: it remains `QUEUED` and obeys head-of-line FIFO. A PAUSED Listing returns `409 LISTING_PAUSED`; requested GPU count exceeding **total** capacity returns `422 JOB_GPU_EXCEEDS_LISTING_TOTAL`. Rejecting an invalid submit inserts **neither** Job nor simulation reference. Job and reference creation is one transaction; do not disclose oracle seed/expected outcome/digest to the Client, Worker or Simulator.

**Proposed `201` response** with `Location: /api/v1/jobs/{id}`:

```json
{
  "id": "33333333-3333-4333-8333-333333333333",
  "listing_id": "22222222-2222-4222-8222-222222222222",
  "worker_id": "11111111-1111-4111-8111-111111111111",
  "gpu_count": 2,
  "duration_seconds": 60,
  "status": "QUEUED",
  "failure_reason": null,
  "submitted_at": "2026-10-18T08:00:00.000000Z",
  "started_at": null,
  "terminal_at": null
}
```

`gpu_count` is the API alias of stored `requested_gpu_count`, and **not** current reserved capacity. `submitted_at` and `enqueue_seq` come from the DB **after the Listing lock**; `enqueue_seq` is immutable and used by Manager, not required in public output. `started_at`/`terminal_at` are trusted, never client-writable. Terminal `failure_reason` is `WORKER_FAULT`, `JOB_FAULT` or `SYSTEM_FAULT` only for `FAILED` Jobs; `COMPLETED`/`CANCELLED` have `null`.

**Submission idempotency:** `(authenticated client_id, Idempotency-Key)` is unique **while the corresponding Job remains retained**. Fingerprint a canonical, validated and normalized representation of the three logical fields; the same key + same normalized request returns **`200` with the original existing Job and `Location`**, with no second Job/reference/enqueue entry. Same key + changed request -> `409 IDEMPOTENCY_KEY_REUSED`. Duplicate concurrent POSTs must serialize into one stored Job. **After legitimate 23-day Job history purge, this key is no longer remembered:** never promise indefinite deduplication or add a new tombstone table without separate review. Missing mandatory header -> `400 IDEMPOTENCY_KEY_REQUIRED` (proposed strict API choice; nullable DB column is compatible with this stronger API validation).

### 8.2. Job reads and role-safe views

`GET /api/v1/jobs?scope=<mine|assigned|all>&status=<status>&limit=20&cursor=...` uses the shared keyset pagination (`submitted_at DESC, id DESC`; `limit` 1..100; opaque tamper-evident cursor bound to role/identity and filters). Default scope is inferred from the caller: `mine` for Client, `assigned` for Worker, `all` for Admin. Other scope values or cross-role scope attempts -> `403 FORBIDDEN`; unsupported status -> `400 INVALID_FILTER`.

- `CLIENT`: only its `jobs.client_id`; sees its own Job fields and Worker ID, but no seed/oracle, Manager internals or another Client's Job.
- `WORKER`: only Jobs assigned to Listings belonging to its Worker profile; see job ID, Listing, requested GPU count, duration, public state/times. **Do not expose another Client's private account identifiers, dispute text, tokens or oracle** through the Worker projection.
- `ADMIN`: read-only all Jobs; no manual scheduling, cancellation on another Client's behalf, or dispute ruling.

A Client guessing another Client's Job UUID, or a Worker guessing an unassigned Job, receives uniform `404 JOB_NOT_FOUND`; role-route mismatch returns `403`. `GET /jobs/{job_id}` returns the applicable read projection and not live allocation control. Polling is adequate; no WebSocket contract or permanent retention promise. Expired/purged Job -> `404 JOB_NOT_FOUND`.

### 8.3. QUEUED-only cancellation

`POST /api/v1/jobs/{job_id}/cancel` has **no JSON body**, accepts only owning Client. Under `TX-CANCEL`, lock Listing **before** Job and recheck owner/status **after** locking; `QUEUED` -> `CANCELLED` with server `terminal_at`, no allocation and no signed receipt/reputation. Return `200` with the resulting Job DTO. `RUNNING`, `COMPLETED`, `FAILED`, already `CANCELLED` -> `409 JOB_NOT_CANCELLABLE`, with **zero further mutations**; repeated cancellation is effect-idempotent but not a second success response. When Manager allocation commits first, cancel loses; when cancel commits first, Manager cannot allocate the Job. Listing PAUSE does not cancel already queued Jobs.

### 8.4. Job-specific error taxonomy and test oracles

| HTTP | Stable proposed error code | Exact trigger |
|---|---|---|
| `400` | `IDEMPOTENCY_KEY_REQUIRED`, `INVALID_JSON`, `UNKNOWN_FIELD`, `INVALID_CURSOR` | Missing submit key, malformed/extra fields, invalid cursor |
| `401` | `UNAUTHENTICATED` | Invalid/missing/expired user credential |
| `403` | `FORBIDDEN` | Non-Client submit/cancel, forbidden list scope |
| `404` | `LISTING_NOT_FOUND`, `JOB_NOT_FOUND` | Unknown resource or resource not visible to caller |
| `409` | `LISTING_PAUSED`, `JOB_NOT_CANCELLABLE`, `IDEMPOTENCY_KEY_REUSED` | Current state prevents requested transition |
| `422` | `VALIDATION_ERROR`, `JOB_GPU_EXCEEDS_LISTING_TOTAL` | Bad typed field, out-of-total requested GPU |
| `503` | `DEPENDENCY_UNAVAILABLE` | Database unable to establish committed success; never fabricate job ID |

**PROPOSED deterministic API contract tests (all `NOT_RUN`):**

| ID | Fixture/action | PASS oracle |
|---|---|---|
| `API-JOB-01` | C1 POST valid on ACTIVE L1 with Key K1 | `201`, exactly 1 QUEUED Job + 1 oracle record, correct Client/Worker binding, no allocation |
| `API-JOB-02` | Replay K1 and same normalized body; concurrent duplicate POST | One original Job, replay `200`, identical ID, zero additional references |
| `API-JOB-03` | K1 reused with different `duration_seconds` | `409`, original immutable Job unchanged |
| `API-JOB-04` | Missing key; injected status/owner/oracle fields; bad GPU/duration types | Each expected `400` or `422`; 0 inserted Job/reference rows |
| `API-JOB-05` | Submit on PAUSED Listing / unknown Listing | `409` or `404`; 0 inserts |
| `API-JOB-06` | Listing total 4, allocated 4, request 2 vs request 5 | Request 2 accepted QUEUED; request 5 rejected `422` |
| `API-JOB-07` | W1/A1 POST Job or cancel | Each `403`, 0 write effects |
| `API-JOB-08` | C1/C2/W1/A1 read owned/unowned Jobs by list/detail | Only approved role projections; unauthorized resource `404`; 0 cross-owner rows |
| `API-JOB-09` | C1 cancels its QUEUED J1 then repeats cancel | First `200` and CANCELLED; second `409`; no allocation or reputation |
| `API-JOB-10` | C1 cancels RUNNING / COMPLETED / FAILED / CANCELLED fixture | All `409`, terminal and RUNNING facts unchanged |
| `API-JOB-11` | Concurrency barrier: cancel commits before allocation | J1 `CANCELLED`, 0 allocations, Manager cannot dispatch |
| `API-JOB-12` | Concurrency barrier: allocation commits before cancel | J1 `RUNNING`, cancel `409`, one allocation, 0 overcapacity |
| `API-JOB-13` | A3=3 then B2=2 then C1=1 on L=4 | After first scheduling pass only A RUNNING; B/C QUEUED; no leapfrog |
| `API-JOB-14` | Job reaches expiry and is purged; reuse former submit key | Old GET `404`; no claim of cross-expiry dedup; new submit follows current rules |
| `API-JOB-15` | 150 Jobs tie on `submitted_at`, paginate and alter cursor | No repeated item within stable snapshot; invalid cursor `400`; strict role isolation |
| `API-JOB-16` | Worker reads Job and Client reads own Job | Worker sees no Client private identity or oracle; Client sees own safe fields |

## 9. Accepted Signed Result read API (APPROVED_DESIGN)

| Route | Caller | Proposed result | Data boundary |
|---|---|---|---|
| `GET /api/v1/jobs/{job_id}/signed-result` | Owning Client, assigned Worker or Admin | `200`; `404 SIGNED_RESULT_NOT_FOUND` if none | Reads **accepted** immutable `signed_results`, never `result_inbox` or oracle |

Response (illustrative valid format, not a new receipt variant):

```json
{
  "verified": true,
  "accepted_at": "2026-10-18T08:02:00.000000Z",
  "payload": {
    "schema_version": "1",
    "result_id": "77777777-7777-4777-8777-777777777777",
    "job_id": "33333333-3333-4333-8333-333333333333",
    "attempt_id": "44444444-4444-4444-8444-444444444444",
    "worker_id": "11111111-1111-4111-8111-111111111111",
    "listing_id": "22222222-2222-4222-8222-222222222222",
    "outcome": "SUCCESS",
    "failure_reason": null,
    "result_digest": "sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38",
    "finished_at": "2026-10-18T08:01:59.000000Z",
    "key_id": "66666666-6666-4666-8666-666666666666"
  },
  "signature": "<base64url-unpadded-86-character-signature>",
  "signature_encoding": "base64url-no-padding"
}
```

The **exact** accepted `payload` and `signature` validation is in **ADR-004**, not to be redefined here. `verified=true` means the **Manager** has already accepted the mathematical signature and contextual binding. It is **not** a statement that the reported simulated outcome matches protected ground truth. A resulting Dispute can be `UPHELD` without changing this response's original bytes. `SYSTEM_FAULT` and `CANCELLED` Jobs lack Worker accepted receipts and correctly return `404` for this endpoint (while the Job detail can remain readable). Do not expose signed evidence to unrelated Client or unassigned Worker; never reveal Worker private key or `simulation_references`.

**Proposed tests (all `NOT_RUN`):**

| ID | Action | PASS oracle |
|---|---|---|
| `API-RES-01` | Read accepted receipt as owner, assigned Worker and Admin | Safe evidence consistent with ADR-004 V1; no oracle/private key |
| `API-RES-02` | Read another Client's private receipt as C2; unassigned Worker | `404` and 0 evidence bytes leaked |
| `API-RES-03` | Read Job without accepted receipt / SYSTEM_FAULT Job | `404 SIGNED_RESULT_NOT_FOUND`, Job state unchanged |
| `API-RES-04` | Accepted receipt later receives UPHELD Dispute | Byte-identical original signed payload/signature remain; no mutable replacement |
| `API-RES-05` | Replay malformed token/service token via public route | `401`, no evidence leaked |
| `API-RES-06` | Attempt PATCH/POST on read-only signed-result route | No mutating route exists; `404`/`405`, no DB mutation |

## 10. Dispute API (APPROVED_DESIGN)

### 10.1. Public routes and strict eligibility

| Route | Caller | Proposed status | Ownership |
|---|---|---|---|
| `POST /api/v1/jobs/{job_id}/dispute` | Owning `CLIENT` only | `201 Created`; `OPEN` decision pending | API `TX-DISPUTE-FILE` transaction |
| `GET /api/v1/jobs/{job_id}/dispute` | Owning Client, selected Worker, Admin | `200`, otherwise `404` | API read-only role-safe projection |

**Submit body:** `{ "reason": "The signed outcome differs from the simulation." }`. Proposed validation: trim outer whitespace, nonempty, max **1000 Unicode characters** (reviewable input limit; no new table). Reject extra fields, forged `filed_at`, `decision`, `status` and `result_id` user claims. The Client identity comes from end-user auth and stored `jobs.client_id`; Worker/Admin **cannot file** or manually resolve a Dispute. No `PUT /disputes/{id}/resolve`, no manual Admin arbitration. The API **never** receives a caller-chosen `UPHELD`/`REJECTED` decision.

**Strict eligibility gate, enforced in trusted locked transaction:**

1. Job exists and belongs to Client; otherwise `404 JOB_NOT_FOUND`. Acquire Listing lock, then Job lock (per approved DB transaction plan). Job must be `COMPLETED` or `FAILED` **with an accepted verified `signed_results` record**; `CANCELLED`, `RUNNING`, no accepted receipt or Manager `FAILED/SYSTEM_FAULT` are ineligible (`409 DISPUTE_NOT_ELIGIBLE`).
2. Capture trusted `decision_at`/`filed_at` **after acquiring locks**, using database clock. Allow iff `terminal_at <= filed_at < terminal_at + 604800 seconds`. Exact cutoff is **rejected**, including a request that waited for lock acquisition. Client `finished_at`, receipt `finished_at` and HTTP `Date` never extend the window.
3. At most **one Dispute per Job**. `UNIQUE(disputes.job_id)` enforces concurrent duplicates; second create -> `409 DISPUTE_ALREADY_EXISTS`. Persist status `OPEN`, decision `null`, `filed_at` and an adjudication retry time, then `201` with resource Location. A Dispute filed validly before day 7 **may resolve after day 7**.
4. Manager privately loads `simulation_references`, compares against immutable signed claim and applies `UPHELD`/`REJECTED` with exactly one effective Reputation correction; it does **not** overwrite original Worker receipt. API just reports persisted status/decision, without exposing hidden oracle reference data.

**Proposed submit response:**

```json
{
  "id": "88888888-8888-4888-8888-888888888888",
  "job_id": "33333333-3333-4333-8333-333333333333",
  "status": "OPEN",
  "decision": null,
  "reason": "The signed outcome differs from the simulation.",
  "filed_at": "2026-10-18T08:05:00.000000Z",
  "resolved_at": null,
  "decision_reason": null
}
```

Proposed Worker read projection omits Client's free-text `reason` and detailed private narrative; Admin/owning Client may see redacted-safe reason and decision explanation. Operational failure states must not be rewritten as resolved merely to reclaim storage. **Day-23 evidence exception** (ADR-006): if a timely filed Dispute is still `OPEN` when Job detail expires, hold all necessary evidence, notify by 1 hour, escalate CRITICAL after 24 hours, retry adjudication every 15 minutes while healthy; after resolution, purge already-expired evidence within 1 hour. A Dispute must **not** receive a hard-delete limit while still OPEN. `GET` may return historical dispute only while its Job evidence is retained or held; after authorized cleanup return `404`.

**Proposed error taxonomy:** `409 DISPUTE_NOT_ELIGIBLE`, `409 DISPUTE_ALREADY_EXISTS`, `409 DISPUTE_WINDOW_CLOSED`, `404 JOB_NOT_FOUND`, `404 DISPUTE_NOT_FOUND`, plus common `401/403/400/422` without secrets. The deadline check is atomic with filing, not a preflight that later commits based on stale time.

### 10.2. Approved-design dispute contract tests (`NOT_RUN`)

| ID | Fixture/action | PASS oracle |
|---|---|---|
| `API-DSP-01` | C1 files for its COMPLETED Job with verified signed result at `T+7d-1us` | `201 OPEN`, 1 persisted Dispute, DB trusted timestamp |
| `API-DSP-02` | File at exact `T+7d` / `T+7d+1us` | Both `409 DISPUTE_WINDOW_CLOSED`, 0 Dispute inserts |
| `API-DSP-03` | Fake user timestamp and wait for Listing/Job lock past cutoff | Rejected; client timestamp cannot backdate |
| `API-DSP-04` | Non-owner C2, Worker W1, Admin A1 attempt filing | Nonowner `404`, wrong roles `403`; zero writes |
| `API-DSP-05` | Queued/Running/Cancelled/System-fault/no-accepted-result Job | `409 DISPUTE_NOT_ELIGIBLE` with zero dispute rows |
| `API-DSP-06` | Two simultaneous creates on eligible Job | One `201`, one `409 DISPUTE_ALREADY_EXISTS`; 1 row |
| `API-DSP-07` | Client reads own, Worker reads assigned, Admin reads any | Correct role-safe read projection; no cross-client reason leak |
| `API-DSP-08` | Filed `T+7d-1us`, Manager resolves day 8 | Valid OPEN -> RESOLVED, no second filing required |
| `API-DSP-09` | Signed SUCCESS provably false vs oracle, dispute upheld | Receipt immutable; success aggregate -1, Worker fault +1 **when corrected oracle is WORKER_FAULT**, once |
| `API-DSP-10` | Signed result exactly matches protected oracle | Decision REJECTED; aggregate remains unchanged |
| `API-DSP-11` | At day 23 dispute still OPEN; observe late ACK and warning/retry | Evidence retained; no hard delete; warning/critical/retry use ADR-006 policy |
| `API-DSP-12` | Resolve held dispute at day 24, then cleanup | Corrected reputation remains; eligible detail purged within 1h; no orphaned evidence |

## 11. Worker Reputation read API (APPROVED_DESIGN)

`GET /api/v1/workers/{worker_id}/reputation` is a read-only projection of `worker_reputation_aggregates` for the given Worker, accessible to authenticated Client/Worker/Admin. Unknown/nonexistent Worker -> `404 WORKER_NOT_FOUND`. Worker profile and key provisioning remain seeded/internal: no public key-rotation or manual-reputation-edit endpoint.

**Proposed `200` body:**

```json
{
  "worker_id": "11111111-1111-4111-8111-111111111111",
  "successful_jobs": 7,
  "worker_fault_jobs": 3,
  "success_rate": "0.7000",
  "updated_at": "2026-10-18T08:00:00.000000Z"
}
```

Formula: `successful_jobs / (successful_jobs + worker_fault_jobs)`, fixed 4 decimal places as a **presentation contract**; if denominator zero, return JSON `null` (UI displays `N/A`). Aggregates are **lifetime**, not recomputed from expired Job rows. They change only for accepted eligible results and one-time UPHELD correction: no contribution for `CANCELLED`, `SYSTEM_FAULT`, invalid receipts or verified `FAILED/JOB_FAULT`. Do not make reputation writable over public API or treat a historical deleted Job as available evidence to reconstruct every count.

| Test ID | Action | PASS oracle |
|---|---|---|
| `API-REP-01` | W1 stored `(7,3)` | `200`, ratio exactly string `"0.7000"` |
| `API-REP-02` | New W2 stored `(0,0)` | `success_rate=null`, counters zero |
| `API-REP-03` | Receipt replay and Dispute correction repeated | At most one original contribution/correction reflected in counters |
| `API-REP-04` | Purge W1 Job history after 23d | `(7,3)` still persisted unless legitimate dispute correction occurred |
| `API-REP-05` | Unknown Worker or attempted HTTP mutation | `404` or unsupported method; no writes to aggregate |

## 12. Role-specific Dashboard read APIs (APPROVED_DESIGN)

| Route | Allowed end-user role | Proposed JSON projection | Explicitly excluded |
|---|---|---|---|
| `GET /api/v1/dashboard/client` | `CLIENT` | `{ "queued_jobs": 2, "running_jobs": 1, "completed_jobs": 4, "failed_jobs": 1, "cancelled_jobs": 0, "open_disputes": 1 }` | Other Clients' Jobs; oracle/key data |
| `GET /api/v1/dashboard/worker` | `WORKER` | `{ "active_listings": 2, "paused_listings": 1, "assigned_queued_jobs": 3, "assigned_running_jobs": 1, "reputation": { "successful_jobs": 7, "worker_fault_jobs": 3, "success_rate": "0.7000" } }` | Client private profile; Manager adjudication internals |
| `GET /api/v1/dashboard/admin` | `ADMIN` | `{ "worker_count": 200, "listing_count": 600, "queued_jobs": 30, "running_jobs": 8, "completed_jobs": 12000, "failed_jobs": 0, "accepted_signed_results": 11900, "rejected_inbox_results": 2, "open_disputes": 1 }` | Manual approve/reject actions; secrets and oracle bytes |

Counts are **snapshots of retained current domain rows**, except Reputation lifetime counters. Since terminal detail expires after 23 days, `completed_jobs`/`failed_jobs` are **NOT lifetime counts**; explain that in UI. Admin may see sanitized operational alerts for held Disputes through its dashboard but cannot adjudicate them manually. `GET` routes must scope data in **server query**, not filter all rows in the browser. Polling/manual refresh only; no WebSocket in MVP. All responses are JSON and `Cache-Control: no-store`. No server guarantees real-time consistency across multiple concurrent DB transactions; one read snapshot per request is acceptable.

| Test ID | Action | PASS oracle |
|---|---|---|
| `API-DASH-01` | C1, C2 see Client dashboard | Each sees own counts only, no mixing |
| `API-DASH-02` | W1, W2 see Worker dashboard | Each sees assigned Listing/Job counts and own Reputation only |
| `API-DASH-03` | Admin requests global dashboard | Sees safe total counts and no cross-user private payload |
| `API-DASH-04` | Wrong role calls each dashboard route | `403` and no role-confidential metrics |
| `API-DASH-05` | Anonymous/expired token | `401`; no data leaked |
| `API-DASH-06` | Job state changes in DB, then dashboard refresh | Updated count reflects durable state; no frontend authority |
| `API-DASH-07` | Expire terminal Job history after 23d | Retained-row counts drop; Worker lifetime counters unaffected |
| `API-DASH-08` | Dispute held beyond day 23 | Open dispute indicator persists until RESOLVED; no evidence purged |
| `API-DASH-09` | Attempt POST/PUT/PATCH to dashboard | Unsupported method; zero business mutations |

## 13. Internal HTTP execution and callback contract (APPROVED_DESIGN; exact `simulation_input` allowlist approved)

**Authoritative behavior already ACCEPTED** in ADR-003/004/005: separate API, Manager and Simulator processes; PostgreSQL Outbox/Inbox; two independent 256-bit-or-stronger service Bearer tokens; Manager dispatch `202` means *execution request accepted*, callback `202` means *durable Inbox ingress*, **neither means verified outcome or Job terminalization**. Worker Ed25519 signature is independently verified later by Manager. Simulator **never** connects directly to the application PostgreSQL or receives protected `simulation_references` data. This section proposes route names and the non-cryptographic dispatch DTO; it **does not replace ADR-004's immutable V1 signed bytes**.

### 13.1. Manager → Simulator dispatch

**Proposed route:** `POST /internal/v1/executions` hosted **only** on the internal Worker Simulator service. Required `Authorization: Bearer <MANAGER_DISPATCH_TOKEN>`, `Content-Type: application/json`. Ordinary user tokens and Simulator callback token do not authorize this route. Example proposed body:

```json
{
  "outbox_event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "job_id": "33333333-3333-4333-8333-333333333333",
  "attempt_id": "44444444-4444-4444-8444-444444444444",
  "worker_id": "11111111-1111-4111-8111-111111111111",
  "listing_id": "22222222-2222-4222-8222-222222222222",
  "gpu_count": 2,
  "duration_seconds": 60,
  "simulation_input": { "workload_profile": "demo-v1" },
  "finish_due_at": "2026-10-18T08:01:00.000000Z",
  "hard_deadline_at": "2026-10-18T08:03:00.000000Z"
}
```

IDs are UUIDv4. `simulation_input` must be exactly the object `{ "workload_profile": "demo-v1" }`: the single required key is `workload_profile`, and its only accepted value is `demo-v1`. Reject a missing key, extra key, or any other value before accepting dispatch. The object is generated by the trusted creation path; it is **not** a `seed_value`, expected outcome/digest, ground-truth fixture, or DB record. No user-provided commands or code are permitted. The Simulator treats `finish_due_at` and `hard_deadline_at` as delivery hints, not authoritative Job or Dispute times; Manager/API read persisted DB deadlines. `gpu_count`/duration must equal the persisted chosen Job. Do not include user credentials, signing private key or service tokens in the JSON body. This closes `API-OPEN-06` without changing ADR-004.

**Proposed response:** `202 Accepted`, body `{ "attempt_id": "44444444-4444-4444-8444-444444444444", "accepted": true }`. For the **same logical `attempt_id` and identical immutable request**, retried delivery may acknowledge `202` again. Reusing that ID with a different identity/request fingerprint -> `409 EXECUTION_CONFLICT`; Simulator must not run a different Job in its place. Only the Manager's transactional Outbox controls dispatch retries. Transport timeout/5xx/408/429 follows ADR-005's `2,4,8,16,30,...` seconds capped schedule and hard deadline; authorization faults follow ADR-005's no-unauthorized-acceptance rule and 30-second bounded retry. **Do not hold a Listing/Job DB lock during HTTP**. If the Simulator's in-memory acknowledgment is lost on restart, the Manager can resend; this transport never promises exactly-once physical mock execution.

### 13.2. Simulator → API signed-result callback

**Proposed route:** `POST /internal/v1/results/callback` hosted **only** on Backend API's protected internal ingress surface. Required `Authorization: Bearer <SIMULATOR_CALLBACK_TOKEN>`; the opposite-direction Manager token and every end-user access token are rejected (`401`). Exact body is the **unmodified ADR-004 V1 HTTP envelope**:

```json
{
  "payload": {
    "schema_version": "1",
    "result_id": "77777777-7777-4777-8777-777777777777",
    "job_id": "33333333-3333-4333-8333-333333333333",
    "attempt_id": "44444444-4444-4444-8444-444444444444",
    "worker_id": "11111111-1111-4111-8111-111111111111",
    "listing_id": "22222222-2222-4222-8222-222222222222",
    "outcome": "SUCCESS",
    "failure_reason": null,
    "result_digest": "sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38",
    "finished_at": "2026-10-18T08:00:59.000000Z",
    "key_id": "66666666-6666-4666-8666-666666666666"
  },
  "signature": "<canonical-86-character-base64url-signature>",
  "signature_encoding": "base64url-no-padding"
}
```

The example `signature` is a documentation placeholder **not a valid signed fixture**. The **frozen byte-exact test vector** is in ADR-004; this document does not assert that the example callback would pass cryptographic verification.

**Ingress transaction:** verify service token **before** any Inbox insertion; strictly parse envelope and candidate IDs. If an **already retained** `result_id` has the **identical raw envelope** from the same bound authenticated context, acknowledge a safe duplicate `202` with **no new Inbox write or `received_at` change**, even if that Job has since terminalized (ADR-005 lost-ACK repair). Reuse of the same ID with different raw bytes is a conflict. For a **new** result candidate, bind claimed Job/Attempt/Worker/Listing to the persisted active attempt; acquire Listing lock then Job lock; capture DB-trusted `received_at` **after the Job lock**; accept as new only when `received_at < persisted hard_deadline_at` and Job is eligible `RUNNING`; insert immutable raw envelope + SHA-256 into `result_inbox` and **commit before sending `202`**. Manager later verifies signature and updates terminal Job/Allocation/Reputation in one separate atomic transaction. A mathematical signature may be invalid/false even though HTTP ingress returned `202`. Do **not** expose `simulation_references` in ingress or API response.

**Proposed response:** `202 Accepted`, body `{ "receipt_status": "STORED", "result_id": "77777777-7777-4777-8777-777777777777" }`; exact byte-identical callback replay **while its original Inbox row is retained** returns `202` with `receipt_status: "DUPLICATE"` but no new stored row/effect (including after terminalization). After authorized Job-history purge, no cross-expiry duplicate acknowledgment is promised. Existing `result_id` with **different raw envelope bytes** -> `409 RESULT_ID_COLLISION` even if both parse correctly. Invalid schema -> `422 INVALID_SIGNED_ENVELOPE`; bad token -> `401`; non-RUNNING/stale attempt/after deadline (including equality boundary) -> `409 RESULT_NOT_ACCEPTABLE`; unknown/unbindable Job -> `404 RESULT_CONTEXT_NOT_FOUND`. Rejected input never becomes eligible for Manager finalization. For malformed data that cannot bind a trusted Job, log only redacted operational error; **do not create an unbound PENDING Inbox row**.

**Critical race:** a correctly bound callback with `received_at=hard_deadline_at-1µs` must be processed even after the deadline if Manager restart is delayed. Manager's timeout fallback **first** checks previously committed on-time Inbox candidates under the same Listing→Job synchronization. A new callback that obtains the lock **at** `hard_deadline_at` fails. Worker-supplied `finished_at` can neither grant extra time nor backdate the ingress decision. Finalized Job never reopens because of a callback retry.

### 13.3. Internal transport error/retry/secret guardrails

| HTTP / condition | Sender behavior | Persistent effect |
|---|---|---|
| `202` dispatch | ACK stored in outbox; wait for callback and repair if missing | No Job finalization from dispatch ACK |
| `202` callback | Durable Inbox candidate (or exact duplicate) | Manager may later reject signature/claim |
| `408`, `429`, HTTP 5xx, network timeout | Retry with persisted due instants & capped ADR-005 backoff | No duplicate accepted result/lease overwrite |
| `401`, `403` | Reject service identity; bounded 30-second auth/config recovery retry per ADR-005 | Zero unauthorized execution/Inbox insert |
| `400`, `422` invalid immutable payload; `409` collision/stale | Do not repeat unchanged bad payload indefinitely | Zero Job/Result/Reputation mutation from bad input |
| Server/DB temporarily unavailable | `503` or no committed response; sender safely retries | Never return false durable success |

**Security:** internal routes must not be exposed in Frontend routing/public API documentation as available Browser calls; service tokens are 256-bit+ random, purpose-separated and never logged; constant-time comparison where practical. The single-host isolated-network trust assumption from ADR-005 applies. End-user stateless token signing credentials, the two service Bearers and Worker Ed25519 signing keys are **three separate secret purposes**, never interchangeable.

**PROPOSED `API-INT` contract tests (`NOT_RUN`):**

| ID | Stimulus | PASS oracle |
|---|---|---|
| `API-INT-01` | Dispatch with correct Manager token and stored attempt using the exact approved `simulation_input`; also try a missing, extra-key, or unsupported profile | Exact object: `202`; invalid object: `422` with 0 execution; same attempt, 0 premature terminal effects |
| `API-INT-02` | Missing/wrong/opposite-direction service credential | `401`, 0 dispatch or Inbox accepted |
| `API-INT-03` | Same attempt replay after ACK loss | `202` idempotent; 1 stable logical attempt |
| `API-INT-04` | Same attempt ID with modified Job/request | `409 EXECUTION_CONFLICT`; no different execution accepted |
| `API-INT-05` | Correct service token + valid raw V1 envelope | `202 STORED` **only after** Inbox commit; Job still RUNNING pending Manager |
| `API-INT-06` | Identical receipt replay after lost callback ACK | `202 DUPLICATE`, original bytes unchanged, 1 Inbox row |
| `API-INT-07` | Same result_id with changed envelope bytes | `409 RESULT_ID_COLLISION`; original unchanged |
| `API-INT-08` | Modified/malformed/extra-field signature envelope | `422`; 0 eligible Inbox rows; no terminal effect |
| `API-INT-09` | Callback received strictly before deadline, Manager processes after | Callback can be verified/accepted; no false SYSTEM_FAULT fallback |
| `API-INT-10` | Callback acquires Job lock at exact deadline or after | `409 RESULT_NOT_ACCEPTABLE`; no accepted result/correction |
| `API-INT-11` | Valid service-token callback with cryptographically invalid (but schema-valid) receipt | `202` eligible Inbox ingress; **Manager later REJECTS**, 0 accepted signed_results and reputation effects |
| `API-INT-12` | Manager crash before/after finalize commit and replay | 1 accepted result, terminalization, release and contribution total; no duplicate effect |

## 14. Cross-cutting API consistency and unresolved design choices

### 14.1. Common approved-design contract test checks (`NOT_RUN`)

| ID | Request / condition | PASS oracle |
|---|---|---|
| `API-COM-01` | Controlled success and error routes | JSON and correct `X-Request-ID`; `204` has no body |
| `API-COM-02` | Private or auth response | `Cache-Control: no-store`, no token/hash/oracle/secret leakage |
| `API-COM-03` | Unauthorized vs forbidden vs other-owner access | Exact `401/403/404` semantics; 0 cross-owner data |
| `API-COM-04` | Missing/duplicate/unexpected JSON keys and wrong number primitives | Predictable `400/422`, 0 persistent mutation |
| `API-COM-05` | Seeded fixed-clock request timestamps vs forged client dates | Trusted DB timestamps govern acceptance, cutoff and cleanup |
| `API-COM-06` | Malformed/tampered/role-mismatched collection cursor | `400 INVALID_CURSOR`, 0 cross-owner rows |
| `API-COM-07` | Repeat resource commands with retry and concurrency | Only intended idempotent effects, no bypass of DBTX/ADR invariants |
| `API-COM-08` | API error path under DB disconnect | `503` or safe failure, no fabricated success or sensitive stack trace |

### 14.2. Owner-approved API decisions

The user approved the documented contract baseline. `API-OPEN-01/02/06` are retained as traceable decision identifiers and were resolved by the owner on 2026-10-18 at the scope stated below. No row authorizes changes to approved MVP behavior. Additional Auth details are listed separately in §14.3 and must not be inferred from these approvals:

| ID | Owner-approved policy scope | Approval status / effect |
|---|---|---|
| `API-OPEN-01` | End-user token policy and browser storage | **APPROVED 2026-10-18**: HS256 JWT; dedicated API-side secret of at least 256 bits; 900-second lifetime; volatile-memory-only browser storage; no refresh token, user-session table, or immediate server-side Logout revocation. Extra claims/header and fractional NumericDate details remain under §14.3. |
| `API-OPEN-02` | Login-name normalization rule | **APPROVED 2026-10-18**: trim surrounding whitespace; match case-sensitively; use the same rule for seeding/provisioning and Login. The exact Unicode whitespace repertoire and Unicode normalization were approved later as `DEC-P1-03` (§14.3). |
| `API-OPEN-03` | Shared REST conventions/errors and Auth endpoint request/response structures (§3-6) | **APPROVED_DESIGN** as documented, together with the `DEC-P1-03` Auth profile in §§4.5 and 14.3. |
| `API-OPEN-04` | Jobs read/submit/cancel request DTO, required Idempotency-Key policy, read scoping (§8) | **APPROVED_DESIGN** as documented; existing DB FIFO and retention remain binding. |
| `API-OPEN-05` | Exact reason length and redacted Worker projection for Disputes (§10) | **APPROVED_DESIGN**: 1000 Unicode characters, redacted Worker projection, no manual adjudication. |
| `API-OPEN-06` | Internal dispatch `simulation_input` allowlist schema and concrete route bodies (§13) | **APPROVED 2026-10-18**: exactly `{ "workload_profile": "demo-v1" }`; no extra keys, alternate values, seed/expected result, or protected oracle data may reach Simulator. ADR-004 unchanged. |
| `API-OPEN-07` | Exact dashboards/read projections and ratio/price string rendering (§7,11,12) | **APPROVED_DESIGN** as documented; future implementation tests `NOT_RUN`. |

**Out-of-scope:** refresh tokens, DB login sessions, immediate user-token revocation, payment/billing, third-party adapter, PII erasure, real GPU execution, websocket/subscription protocol, automatic Worker selection, Admin manual dispute resolution, arbitrary code execution or a 19th database table.

### 14.3. Additional Authentication details — APPROVED as `DEC-P1-03` (2026-10-21)

These choices were not covered by the 2026-10-18 decisions or by ADR-008. The owner approved them as `DEC-P1-03` on 2026-10-21 (recorded in [Phase 1 §6](../architecture/phases/phase1_project_foundation.md)); v0.7 synchronizes that approval here without changing the values. They govern the Authentication implementation and the corresponding `API-AUTH` oracles.

| Detail | Approved value | Effect |
|---|---|---|
| JWT header/claims | **APPROVED (`DEC-P1-03`)**: strict profile `typ=JWT`, `iss=gpu-marketplace-api`, `aud=gpu-marketplace-web`, UUID-form `sub`; mismatches are validated within the existing `API-AUTH-05` ID. | Authentication implementation and `API-AUTH-05` |
| Fractional NumericDate representation | **APPROVED (`DEC-P1-03`)**: trusted UTC `iat`/`exp` as JSON NumericDate numbers with six decimal places, exact microsecond comparison, `exp=iat+900.000000`, and no truncation, rounding, or expiry tolerance. RFC 7519 permits non-integer NumericDate values; see §4.5. | Authentication implementation and `API-AUTH-06` |
| Login whitespace and Unicode normalization | **APPROVED (`DEC-P1-03`)**: trim ASCII SP/HT/LF/CR only, preserve other Unicode whitespace, apply no NFC/NFD normalization, and keep case-sensitive matching. U+00A0 and composed/decomposed fixture oracles are documented under the existing `API-AUTH-01-ROLES` ID. | Authentication implementation, provisioning and `API-AUTH-01` |

### 14.4. `CR-GPU-003-UNICODE-01` — APPROVED (2026-10-24)

L2 change requested by TV2 during cross-phase ACK `XPH-GPU-003-02`, recorded in [#16](https://github.com/SE2026-BC-04/gpu-resource-marketplace/issues/16) and approved by the team lead ([decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/issues/16#issuecomment-6373492816)). The approval covers R1–R6 below only; it does not approve the password-hash parameters, JWT implementation, issuance clock or token-size limit, which are reviewed separately.

| Rule | Approved behavior | Oracle |
|---|---|---|
| R1 | `login_name` containing U+0000 or any surrogate code point U+D800..U+DFFF -> `422`, before any database query | `API-AUTH-03` |
| R2 | Login and account provisioning use the same pure validation/normalization implementation in `identity/`; no duplicate logic | `API-AUTH-01`, GPU-002 provisioning suite |
| R3 | Password containing an unencodable surrogate -> generic `401 INVALID_CREDENTIALS`, never `500` or a password-revealing error | `API-AUTH-02` |
| R4 | U+0000 in a password is neither rejected nor truncated; exact password bytes are hashed and compared | `API-AUTH-02` |
| R5 | No raw input, hash, token or driver exception in public responses or logs | `API-AUTH-02`, `API-AUTH-03`, `API-AUTH-13` |
| R6 | `DEC-P1-03` unchanged: ASCII SP/HT/LF/CR edge trim only, case-sensitive, no NFC/NFD or case folding; other valid Unicode, including supplementary code points, accepted | `API-AUTH-01` |

No database schema or migration changes; the existing ASCII seed fixture is unaffected. Route-level evidence (HTTP `422`/`401`, no database access for an invalid `login_name`, redaction, shared provisioning function) remains `NOT_RUN` until the Auth endpoints and provisioning are integrated; unit tests alone do not make these oracles PASS.

### 14.5. Auth request-body bounds and `D-C1`/`D-C2` — owner-directed in the PR #23 review (2026-10-24)

The team lead's review of GPU-003-C ([PR #23](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/23)) found that the unauthenticated Login route parsed a body of unbounded size and nesting, and that Logout ignored a body the contract does not allow. The lead directed the values below and approved `D-C1` and `D-C2`; this section records them with the code and tests in the same L2 PR. They are **approved when the L2 review of PR #23 confirms this diff**.

| Rule | Behavior | Oracle |
|---|---|---|
| B1 media type | Login requires `Content-Type: application/json`; an optional `charset` parameter must be `utf-8`; otherwise `400 INVALID_JSON` | `API-AUTH-03` |
| B2 size | Login raw body at most 16 KiB (16,384 bytes). A declared `Content-Length` above the limit is rejected without reading the body; leading zeros are allowed, and a numeric value too long to convert safely counts as above the limit. Each received chunk is checked against the remaining quota **before** it is copied, so an absent or misleading `Content-Length` or one very large ASGI chunk cannot make the API buffer more than the limit. Over the limit -> `413 PAYLOAD_TOO_LARGE` | `API-AUTH-03` |
| B3 parsing | Strict UTF-8 JSON, no duplicate keys, no `NaN`/`Infinity`, at most 8 nested arrays/objects (checked before parsing); every parser failure -> `400 INVALID_JSON`, never `500`. A malformed `Content-Length` value -> `400 INVALID_JSON` | `API-AUTH-03` |
| B4 order | B1–B3 are decided before any account read; responses and logs never echo the body | `API-AUTH-03`, `API-AUTH-13` |
| B5 Logout | Any nonempty Logout body or nonzero declared `Content-Length` (of any length) -> `400 INVALID_JSON`, checked before the token and the account read; an empty body (with or without a zero `Content-Length`) is accepted | `API-AUTH-12` |
| `D-C1` | Missing, invalid or expired user JWT on `/auth/me` and `/auth/logout` -> `401 UNAUTHORIZED` with `WWW-Authenticate: Bearer`, aligned with Listings §7.9. The Jobs group keeps its separately specified `UNAUTHENTICATED` mapping (§8) | `API-AUTH-05`, `API-AUTH-06`, `API-AUTH-07` |
| `D-C2` | Login for an account with a missing, invalid or ambiguous role mapping -> the same generic `401 INVALID_CREDENTIALS` as other login failures, plus a redacted server-side warning; never a default role or Admin, never a hint that the account exists | `API-AUTH-08` |

A reverse-proxy or server-wide request-size limit is useful as an additional defense but does not replace B2, which is tested in the application. No database schema change. Route-level tests with test doubles exist in PR #23; database-backed and mounted-application evidence remains `NOT_RUN`.

### 14.6. Listings request-body bounds — `CR-GPU-004-BODY-01` (2026-10-25)

**APPROVED_FOR_IMPLEMENTATION (L2 design scope only):** [team-lead decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6395344255) on [TV4's proposal](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6395120213), reviewed baseline `18003795558cf022cc1b3a20a7f41d7af3946ceb`. Change path **A: atomic design + implementation in PR #17**; not approval for merge/deployment, not a replacement for two independent human reviews.

| Rule | Approved Listings behavior | Existing oracle |
|---|---|---|
| Scope | POST create and PATCH update only; no Auth/Jobs/schema/grant/shared-App policy changes | `API-LIST-07`, `API-LIST-11` |
| Byte bound | At most 16,384 raw bytes inclusive; declared length checked before stream reads and actual chunks checked before copying. Missing/understated length never disables the actual-byte check; one huge chunk cannot force an oversized accumulation buffer. Leading zeros allowed; an excessive numeric length counts as oversize | `API-LIST-07`, `API-LIST-11` |
| Parse bound | Strict UTF-8 JSON, no duplicate keys or NaN/Infinity, at most 8 arrays/objects counting root; ignore brackets/escapes inside strings. Check nesting before invoking the JSON parser | `API-LIST-07`, `API-LIST-11` |
| Rejection | Above byte limit -> 413 PAYLOAD_TOO_LARGE. Malformed framing/UTF-8/JSON, duplicate keys, constants, above depth limit or parser exhaustion -> 400 INVALID_JSON, never 500 or input/exception echo | `API-LIST-07`, `API-LIST-11`, `API-COM-01` |
| Precedence | Auth -> WORKER role -> body checks -> Listing UoW/SQL/mutation. Rejected body enters zero Listing UoW and performs zero Listing mutation; Auth can still read the account to establish the principal | `API-LIST-07`, `API-LIST-08`, `API-LIST-11` |
| Unchanged contracts | Typed/unknown-field errors, ownership, capacity/state, UUIDs, DTOs and cursor remain as §7. Pause/resume remain bodyless with early rejection; Auth body-before-account/Logout ordering is not copied to Listings | `API-LIST-01..18` |

Reuse reviewed bounded-reader/strict-parser helpers where appropriate; the Listings byte limit is independently specified even though it matches Login today. No new API test ID is introduced: extend the existing POST/PATCH/common oracles above. Actual tests must identify their code HEAD and distinguish HTTP/persistence doubles from real PostgreSQL, audit, races and browser E2E. R1–R4 and the final human review gate remain open until their own evidence/actions are accepted.

## 15. Traceability: API contract → requirements → storage/transactions → test evidence

| Requirements / policy | API section(s) | Owning database/transaction | Proposed validation |
|---|---|---|---|
| UC-G01; NFR-S01/S02 | §4-6 Auth | `users`, `roles`, `user_roles` | `API-AUTH-01..14` |
| FR-WR-01..04 | §7 Listings; §11 Reputation | `workers`, `gpu_listings`, `worker_public_keys`, aggregates, TX-PAUSE-EDIT | `API-LIST-01..18`; `API-REP-01..05` |
| FR-JL-01..04 | §8 Jobs | `jobs`, `simulation_references`; TX-SUBMIT/CANCEL/ALLOCATE | `API-JOB-01..16`, DBTX, INT |
| FR-JL-05/06; FR-SR-01..04 | §8-9, §13 | `execution_attempts`, `allocations`, `execution_outbox`, `result_inbox`, `signed_results` | `API-INT-01..12`, `API-RES-01..06`, ADR-004, ADR-005 |
| FR-DP-01..03; ADR-006 | §10 Disputes | `disputes`, `simulation_references`, `retention_exceptions`; TX-DISPUTE/RETENTION | `API-DSP-01..12`, DAT, DBTX |
| FR-RP-01/02 | §11 Reputation | `job_reputation_contributions`, lifetime aggregates; TX-FINALIZE/RESOLVE | `API-REP-01..05`, SEC, REL |
| FR-DB-01/02 | §12 Dashboard | Read-only role-filtered projections; `audit_events` separate TTL | `API-DASH-01..09`, OBS |
| NFR-R01..08, S01..07 | §3, §13-14 | Protected DB transactions & service auth; no direct Simulator DB | `API-COM-01..08`, COM, AUTH, DBTX |
| NFR-P01..05, QA-PER/SCA | §7/8/12 read+submit routes | ADR-007 fixed 736 VU configuration | `PER-01..06`, `SCA-01..06`, `LDCFG-01..09` (all `NOT_RUN`) |

## 16. Review record and handoff — documentation only

| Item | Design status at v0.10 (2026-10-25); scoped runtime evidence is separate |
|---|---|
| Logical/physical/transaction Database Design (18 tables) | **APPROVED_DESIGN**; no SQL migration run |
| Stateless HS256 JWT / 900-second lifetime / volatile-memory storage / no refresh and no server-side Logout revocation | **APPROVED_DESIGN** at the owner-approved policy scope |
| Public API — Auth, Listings, Jobs, Results, Disputes, Reputation, Dashboard | **APPROVED_DESIGN** as described; 100 contract cases are `NOT_RUN` |
| Internal HTTP dispatch / callback | **APPROVED_DESIGN**; exact `simulation_input` allowlist is `{ "workload_profile": "demo-v1" }`; ADR-004 V1 remains authoritative |
| Resolved API decisions | `API-OPEN-01/02/06` **APPROVED (2026-10-18)** at their scopes in §14.2 and recorded in this synchronization |
| Additional Authentication profile details | **APPROVED as `DEC-P1-03` (2026-10-21)**; synchronized in §§4.5 and 14.3 at v0.7 |
| Login/password Unicode validation | **APPROVED as `CR-GPU-003-UNICODE-01` (2026-10-24)**; recorded in §§4.2, 4.5, 6 and 14.4 at v0.8; route-level tests `NOT_RUN` |
| Auth request-body bounds; `D-C1`, `D-C2` | **Owner-directed in the PR #23 review (2026-10-24)**; recorded in §§3.3, 4.2–4.4, 6 and 14.5 at v0.9; approved with the L2 review of PR #23; route tests with test doubles only |
| Listings request-body bounds | **APPROVED_FOR_IMPLEMENTATION**, `CR-GPU-004-BODY-01` (§14.6), 16,384 bytes / depth 8, Auth/WORKER-before-body; atomic L2 design+implementation in #17, required final human reviews/integration gates unchanged |
| ADR-008 technology stack | **ACCEPTED (2026-10-18)** in its own ADR; no implementation/test evidence |
| Actual API code, DB migrations, test runners, benchmarks | **NOT_STARTED / NOT_RUN**; this document records design only |

**Handoff:** `API-OPEN-01/02/06` are resolved at the owner-approved scope in §14.2, and the extra Auth profile details in §§4.5 and 14.3 are resolved by `DEC-P1-03`; `CR-GPU-003-UNICODE-01` (§14.4) adds the approved NUL/surrogate validation. Any implementation must follow a separately authorized coding slice and the normal branch/PR gates. This document approval validates design text, not executable behavior or measured performance.
