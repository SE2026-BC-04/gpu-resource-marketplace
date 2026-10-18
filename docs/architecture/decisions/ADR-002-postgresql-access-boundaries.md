# ADR-002 — Direct PostgreSQL access for Backend API and Manager; no Worker Simulator DB access

**Status:** ACCEPTED — formal record of an **already-approved** architectural boundary, not a new design decision  
**Recorded:** 2026-10-18  
**Decision provenance:** Previously approved in `docs/architecture/system-architecture.md` §3–4 and its decision register; this document makes that missing decision record explicit. The original approval date is not asserted here.  
**Scope:** GPU Resource Marketplace, simulation-only MVP  
**Implementation and tests:** `NOT_RUN`; neither database privileges nor transaction behavior have been implemented or verified.  
**Repository path:** `docs/architecture/decisions/ADR-002-postgresql-access-boundaries.md`

## 1. Context and goal

The Backend API must respond to interactive user requests, while the automated Manager performs asynchronous FIFO scheduling, capacity allocation, cryptographic result verification, Dispute decisions, Reputation effects and data cleanup. Both need consistent, durable PostgreSQL transactions over shared business state.

Worker Simulator is a logically separate execution and signing component. If it receives direct access to the application database, it could bypass Signed Result verification and change Job states, allocations, protected ground truth, Disputes or Reputation. At the other extreme, forcing all Manager operations through the public Backend API would introduce additional service hops and complicate atomic multi-table scheduling transactions.

**Goal:** define the minimum clear persistence access boundary without changing the approved business rules or introducing an additional data service.

## 2. Decision — previously approved

1. **Backend API directly accesses PostgreSQL** through shared domain/repository code for its authorized responsibilities: user/Listing commands, Job submission, cancellation of the Client's own `QUEUED` Job, eligible Dispute creation, durable Signed Result Inbox ingress and role-filtered reads.
2. **Automated Manager directly accesses the same PostgreSQL application state** using the shared domain/repository code for strict FIFO selection, atomic allocation and execution Outbox creation, Signed Result verification/finalization, GPU release, deterministic Dispute resolution, lifetime Reputation accounting and retention cleanup.
3. **Worker Simulator has no direct PostgreSQL connection, credentials, application ORM session or access to Manager-protected deterministic reference/oracle data.** It receives execution instructions from Manager and submits Ed25519 Signed Results to the Backend API via authenticated **internal HTTP**. The approved durable handoffs and credential scopes are defined in **ADR-003/ADR-005**.
4. **API and Manager have distinct mutation ownership** even though they use the same database and may import shared code. Backend API may persist a received *unverified* receipt in Inbox, but only Manager accepts the final result, applies the terminal Job transition, releases allocation and updates Reputation.
5. **PostgreSQL commits, not process memory or HTTP acknowledgments, establish authoritative state.** All read-modify-write decisions affecting capacity, lifecycle, deadlines or reputation require concurrency-safe transactions and database-enforced uniqueness/guards as appropriate.
6. These boundaries **do not imply** that detailed SQL schema, database roles/grants, migration ordering, pool sizes or exact API routes are already fixed. Those belong to Database Design and API Contract; protect the boundaries during implementation with suitable least-privilege configuration and tests.

The decision does **not** authorize Manager to make arbitrary user-facing changes, nor does sharing repository code permit the Simulator to import a database-enabled code path.

## 3. Alternatives and rationale

The following explains the previously selected architecture; it is not presented as a new approved trade-study.

| Approach | Benefit | Limitation | Result |
|---|---|---|---|
| Every backend component calls API for all reads/writes | One HTTP-facing database entry point | Manager scheduling/finalization require complex multi-operation atomicity through additional internal APIs; API availability becomes the sole persistence gateway | Not selected |
| **API and Manager share repository code and direct PostgreSQL (selected)** | Short database transactions, shared invariants, no duplicate service API; clear separation of interactive vs automated writers | Requires explicit mutation ownership, locks, privilege controls and tests on one shared datastore | **ACCEPTED** |
| Simulator also accesses PostgreSQL | Fewer callback steps | Breaks execution/signing trust boundary and permits unverified simulator output to mutate authoritative state | Prohibited |
| Independent databases per component | Stronger isolation in a distributed system | Distributed consistency and synchronization are outside MVP requirements | Not selected |

## 4. Write ownership matrix

| Data or operation | Backend API | Manager | Worker Simulator |
|---|---|---|---|
| Account authentication / RBAC and Listing commands | **Owner of user-facing commands** | Reads required Listing state for scheduling | No direct DB access |
| Create Client Job (`QUEUED`) | **Owner**, with authorization and eligibility checks | Reads queued Jobs; cannot impersonate Client submitter | No direct DB access |
| Cancel own `QUEUED` Job | **Owner**, transactional race-safe change | Must observe cancellation when scheduling | No direct DB access |
| Allocate GPU, set `RUNNING`, record execution Outbox | Not allowed outside Manager | **Owner**, single atomic transaction | No direct DB access |
| Ingest signed callback into Result Inbox | **Owner of authenticated durable ingress** | Consumes inbox for verification | **HTTP callback only** |
| Accept Signed Result; set `COMPLETED`/`FAILED`; release GPU | Not allowed | **Owner**, idempotent transaction | No direct DB access |
| Client opens eligible Dispute | **Owner** | Reads and later resolves pending Disputes | No direct DB access |
| Resolve Dispute, adjust lifetime Reputation | Not allowed | **Owner**, once-only effect | No direct DB access |
| Cleanup/retention exception handling | Reads authorized status | **Owner** | No direct DB access |
| Protected deterministic ground truth / oracle | No public Client/Worker exposure; trusted server boundaries only | **Trusted resolution reader** | **No access** |

The above is a **logical command ownership** matrix; PostgreSQL table-level grants are still a physical-design task. Mutations that race across API and Manager must serialize to a single legal outcome (e.g. Cancel vs Allocate; Pause vs Allocate). Admin observes state via API and cannot manually adjudicate.

## 5. Atomicity, delivery and failure boundaries

- **Listing/Job mutations:** apply ownership, Listing state and Job lifecycle preconditions in the same committed transaction as the user-command write. Reject conflicting transitions deterministically.
- **Allocation/Outbox (ADR-003):** Manager uses PostgreSQL locks or equivalent safe conditional updates to choose FIFO head, check availability, allocate and insert a durable dispatch event atomically; **do not hold a database transaction open across HTTP dispatch**.
- **Inbox/finalization (ADR-003/004):** API commits each authenticated received receipt before acknowledging; Manager verifies cryptographic bytes and DB context, then finalizes Job/release/eligible reputation contribution in a single idempotent transaction.
- **Retry/deadline (ADR-005):** transport may redeliver requests or Signed Results, but committed business effects are once-only. Inbox server-trusted time, not Worker-provided `finished_at`, determines deadline eligibility.
- **Retention (ADR-006):** Manager coordinates evidence holds and deletion while lifetime Worker Reputation aggregates persist.

**Critical distinction:** *at-least-once transport* can execute/callback more than once, whereas finalizing a Job, releasing GPU and posting an effective reputation contribution must each have a single committed business effect.

## 6. Consequences and limitations

- **Positive:** Manager can use short ACID transactions for scheduler correctness; UI/API stays responsive; an untrusted Simulator must cross an authenticated callback and signature verification boundary.
- **Costs:** API and Manager can contend for Job/Listing rows; careful transaction scopes, indexes, deadlock handling and state machine tests are necessary.
- **Security limitation:** a common database is a shared failure/security domain. Logical ownership alone is not a substitute for database permissions, secret separation and least privilege. Concrete DB roles/grants remain to be specified and tested in Database Design.
- **Operational limitation:** PostgreSQL availability is central; this ADR does not promise multi-region high availability or protection against complete database loss.

## 7. Verification references (design only; `NOT_RUN`)

These checks trace to already-reviewed quality and ADR invariants; they are not additional product scope:

| Check | Pass condition |
|---|---|
| Simulator access boundary | Simulator runtime has no PostgreSQL connection string/credential, direct ORM path or successful DB connection; it only uses internal HTTP |
| API ownership | No authenticated HTTP endpoint or code path bypasses Manager to finalize Job, change GPU allocation or adjust reputation |
| Inbox/Manager separation | API stores callback durably without deciding signature validity; Manager verifies and applies business effects once |
| Cancel/Allocate or Pause/Allocate race | Exactly one legal committed outcome; no negative or over-capacity allocation; no post-Pause allocation |
| Duplicate Signed Result | One final Job, one effective release, at most one eligible Worker reputation contribution |
| Oracle/key separation | Worker Simulator cannot read protected simulation reference or Manager's public-key authority; Worker signing private keys do not reach frontend/API |

All verification remains `NOT_RUN` until implementation and objective evidence exist.

## 8. Related decisions and unresolved detailed design

- [ADR-001 — Modular Monolith](ADR-001-modular-monolith.md): overall process boundaries.
- [ADR-003 — Internal communication](ADR-003-internal-communication.md): transactional Outbox/Inbox + HTTP.
- [ADR-004 — Signed Result V1](ADR-004-signed-result.md): canonical bytes and Ed25519 checks.
- [ADR-005 — Retry/timeout/internal authentication](ADR-005-retry-timeout-internal-auth.md): recovery and directional tokens.
- [ADR-006 — Evidence retention](ADR-006-dispute-retention.md): lifetime aggregates and exceptional holds.
- [ADR-007 — Load testing](ADR-007-load-test-configuration.md): repeatable 736-VU profile.
- [ADR-008 — Technology stack](ADR-008-technology-stack.md): remains **PROPOSED / REVIEW** until approved separately.

**Out of scope here:** physical tables/columns/FKs, connection roles/grants, SQL locking statements, migrations, API status codes and implementation tests. These need a separate review before claiming the persistence boundary is enforced in running software.
