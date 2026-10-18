# ADR-008 - Implementation technology stack and local packaging

**Status:** **ACCEPTED** — Option B approved by project owner on 2026-10-18 (design decision only)  
**Version:** 0.2 (2026-10-18; decision accepted, no implementation)  
**Date:** 2026-10-18  
**Project:** GPU Resource Marketplace - simulation-only MVP  
**Intended repository path:** `docs/architecture/decisions/ADR-008-technology-stack.md`  
**Implementation / test status:** `NOT_RUN`; no application source, migrated schema, successful deployment or measured benchmark is claimed.

## 1. Goal, scope and review boundary

Select one *small, reproducible* application/framework stack for the already-approved modular-monolith MVP. Do not add a GPU runtime, real billing, blockchain, message broker, Kubernetes, public Worker onboarding or any new functional requirement. This ADR decides technology families, runtime boundaries, packaging and test-tool families; it does not design database tables, HTTP endpoint payloads, user-authentication protocol, hosting infrastructure, or a UI design system.

**Binding prior decisions (unchanged):**

- ADR-001/002: separate Backend API, Manager and Worker Simulator processes in one logical modular monolith; Backend API and Manager share domain/repository code and PostgreSQL; Simulator must not directly access PostgreSQL.
- ADR-003: PostgreSQL transactional Execution Outbox / Result Inbox, authenticated internal HTTP and at-least-once delivery with idempotent **committed** business effects; no broker requirement.
- ADR-004: canonical Signed Result V1 - RFC 8785 JCS, Ed25519, strict 11-field schema, versioned prefix, SHA-256 and interoperable public test vector. Signing secrets belong to Simulator; public verifier metadata belongs to trusted Backend/Manager.
- ADR-005: 2s Manager due-work polling, fenced 30s leases, 2s/5s internal connect/total HTTP timeout, persisted 2/4/8/16/30-second backoff, hard execution deadline and two direction-scoped 256-bit service Bearer tokens.
- ADR-006: 7-day strict Dispute filing window, 23-day normal detail retention, open-Dispute evidence hold until resolved and approved warning/retry/cleanup handling.
- ADR-007: 736-VU repeatable k6 profile, 2 API execution units, 1 Manager process, 1 Simulator process (128 in-flight simulation cap), 1 PostgreSQL instance on the fixed single-node SUT benchmark. No performance target has been met until measured.
- SRS/FR/NFR and all 11 approved quality-scenario designs remain normative. This ADR cannot overrule FIFO, capacity, ownership, lifecycle, retention or reputation invariants.

## 2. Alternatives

| Option | Main stack | Advantages | Limitations | Review position |
|---|---|---|---|---|
| A | Full TypeScript: Node.js + NestJS API/Manager/Simulator, React + PostgreSQL | One application language; strong typing across frontend/backend | More backend framework structure for a small MVP; additional work to express trusted scheduler transactions and canonical signing consistently | Feasible alternative, not selected as first recommendation |
| **B** | **Python/FastAPI modular backend + React/TypeScript frontend + PostgreSQL + Docker Compose** | Direct mapping to existing three Python-compatible processes; simple deterministic simulation, mature PostgreSQL/Ed25519 tooling, small team learning surface | Two application languages, need strict frontend/backend contract and event-loop/DB-call discipline | **ACCEPTED (Option B)** |
| C | Django (DRF) API + separate Python Manager/Simulator + React + PostgreSQL | Mature ORM/auth/migrations, batteries included | Adds Django framework conventions and API/admin machinery not required by approved user roles; still requires independent scheduler processes | Feasible alternative, not preferred for this MVP |

**Accepted decision: B (2026-10-18).** Technology is chosen for delivery simplicity and compatibility with accepted architecture, **not** on an unmeasured promise that it meets 736-VU latency targets. A performance failure requires measuring and fixing the actual bottleneck; this ADR does not authorize bypassing any integrity constraint.

## 3. Accepted technology register (reference runtime families/versions)

| Area | Accepted selection | Scope / rationale |
|---|---|---|
| Backend language | **Python 3.12** as baseline runtime major/minor | Shared Backend API/Manager domain code and Simulator's Python-based deterministic fixtures/crypto. Pin exact patch/image when implementing. |
| HTTP API | **FastAPI** + **Pydantic 2** + Uvicorn ASGI | Validated request/response DTOs and role-scoped REST APIs; API is source of public HTTP contracts. |
| Data access | **SQLAlchemy 2.x** (synchronous Session) + **psycopg 3** | Explicit transactional PostgreSQL row locks/conditional updates, short-lived sessions and shared repository modules for API + Manager. Call sync DB operations from FastAPI synchronous (`def`) handlers/dependencies, not blocking `async def` event-loop handlers. |
| Schema migration | **Alembic** | One versioned migration sequence, executed once before app readiness; physical tables/indexes/constraints belong to later Database Design. |
| Scheduler / Manager | **One Python process** using shared domain/repository package + bounded poll loop + `httpx` for outbound dispatch | Not Celery, no Redis and no external broker. Keep network calls outside DB transactions. Manager controls scheduling/finalization/adjudication/retention. |
| Worker Simulator | **Separate Python service** with FastAPI inbound dispatch, `httpx` authenticated callback, bounded asynchronous simulation tasks | One process with at most 128 in-flight simulation attempts **in ADR-007 benchmark**. No PostgreSQL URL, connection or secret oracle access; retries can re-execute simulation, but DB effects are idempotent. |
| Signing | Python `cryptography` Ed25519 + independently validated **RFC 8785 JCS implementation**, plus standard SHA-256 | Must reproduce ADR-004 byte-exact test vectors. Reject duplicate/raw-invalid JSON keys before canonicalization; never use arbitrary `json.dumps` bytes for signatures. |
| Database | **PostgreSQL 16** (single instance for MVP) | Already mandated DB type; select a currently supported reference major; patch release/image digest pinned before code or benchmark execution. |
| Frontend | **React 19 + TypeScript + Vite** | Client/Worker/Admin role-scoped SPA; browser accesses only Backend API and never PostgreSQL/Manager/Simulator directly. No SSR or real-time broker. |
| Frontend runtime | **Node.js 24 LTS** for toolchain, `npm` and committed `package-lock.json` | Stable install with `npm ci`. Build Vite static assets; single frontend container serves them in Compose (static server technology is a packaging detail). |
| Python dependencies | **`uv` + `pyproject.toml` + committed `uv.lock`** | Reproducible environment for API/Manager/Simulator; use frozen locked install, no floating dependencies at execution time. |
| Local deployment | **Docker Compose v2**, five long-lived services: `frontend`, `api`, `manager`, `simulator`, `postgres` | CPU-only single-host MVP; isolated service network(s), DB connectivity only from API/Manager. A one-shot migration task is allowed and does not count as a sixth long-lived service. |
| Backend tests | **pytest** plus isolated real PostgreSQL integration fixtures; HTTP boundary tests via an appropriate client | Run approved deterministic QA/ADR contracts; mock clock and transactional barriers where specified. |
| Frontend tests | **Vitest + React Testing Library**; minimal **Playwright** end-to-end smoke | Check UI role behavior and core user journey without inventing additional user features. |
| Load tests | **k6 per ADR-007**, separately version/image pinned | ADR-008 does not change workload, hardware, thresholds or already accepted nine LDCFG cases. |

**Dependency version policy:** The major/minor reference versions listed above are **accepted architecture decisions**, not an assertion that packages or containers have already been installed. When implementation starts, capture exact compatible patch versions, dependency-lock digests, container image digests and language/runtime manifests, and re-run regression checks on any update. FastAPI, `uv`, Vite, TypeScript, SQLAlchemy minor/patch versions are selected *from mutually compatible supported releases at coding time*, never from unreviewed latest-tag drift.

**Version-lifecycle context (checked 2026-10-18):** Node.js 24 is on the LTS line; PostgreSQL 16 remains supported by upstream. Official source references: https://nodejs.org/en/about/previous-releases ; https://www.postgresql.org/support/versioning/ ; Vite toolchain compatibility: https://vite.dev/guide/ . These links provide lifecycle context for the **accepted reference** baseline; they do not prove an installed application exists.

## 4. Accepted runtime and module boundaries

```text
Browser (React/TypeScript SPA)
    |
    v
Backend API (FastAPI, 2 execution units in ADR-007 reference benchmark)
    |                  ^
    |                  | callback: authenticated signed receipt
    v                  |
PostgreSQL        Worker Simulator (Python; Ed25519 private keys)
    ^                  ^
    |                  | dispatch: authenticated internal HTTP
    |
Manager (Python polling/retry/finalization; 1 process in benchmark)

Note: Only Backend API and Manager have DB credentials or DB-network access.
```

- **Shared Python package:** domain models, business guards, repositories and transactional services are shared **only** between API and Manager. The Simulator may import pure, DB-free Signed Result schema/canonical-signing helpers but must not import or receive the DB repository, the protected simulation truth oracle, or Manager-only admin operations.
- **Ownership rule:** Backend API handles user-facing writes/role authorization, durable Inbox ingress and read projections; Manager alone schedules/allocates/finalizes/adjudicates/reconciles; Simulator handles dispatch and Worker-result signatures. The framework must not create a second unauthorized write path.
- **Database correctness:** Listing locks, strictly ordered FIFO, deduplication, one release/reputation effect and retention holds are enforced by durable PostgreSQL transactions/constraints. Never rely on a process-local Python lock for cross-process GPU capacity safety.
- **Sync/async discipline:** DB-backed API endpoints use synchronous SQLAlchemy and short transactions with FastAPI `def` handlers or an explicit thread boundary; Simulator uses bounded asynchronous tasks for mock time waits and network I/O. Do not hold PostgreSQL locks over `httpx` calls, sleeps or simulated execution.
- **Network:** The accepted Compose design separates app HTTP and DB networks so the Simulator cannot reach PostgreSQL. Enforce distinct accepted ADR-005 Bearer secrets per HTTP direction, and treat Ed25519 as a separate content-authenticity check.
- **Single host, no production-HA claim:** Compose is accepted for the CPU-only, single-host MVP under this ADR. The single-host trusted-network assumption from ADR-005 still applies; public/multi-host traffic would require separate TLS/security design, out of scope here.

## 5. Costs, risks, and explicitly deferred details

| Consequence / risk | Mitigation / boundary |
|---|---|
| Python backend + TypeScript frontend involve two languages | Define contracts in API Design; compile TypeScript and run schema/HTTP integration tests; do not manually duplicate sensitive validation as frontend authority. |
| Synchronous SQLAlchemy may constrain two-API-worker throughput | Keep DB sessions/transactions short, separate blocking and asynchronous work; benchmark with ADR-007; do not claim p95 PASS before measurement. |
| Simulated 128 in-flight attempts may produce duplicate physical work after retry/restart | Persist business guards in PostgreSQL Outbox/Inbox and stable `attempt_id`; only one finalized Job and one reputation effect. |
| JCS/Ed25519 library differences can silently alter signing bytes | Use ADR-004 public vector and cross-library contract tests; strict parser rejects duplicate keys; test tamper/replay/key binding. |
| Secrets can leak through configs, image layers, logs or frontend bundle | Inject test secrets at runtime, untracked `.env` files, do not bake keys into images, scan built frontend/logs and tracked files; Simulator lacks DB/oracle. |
| Dependency/version drift undermines reproducibility | Lock Python/Node deps and container digests, freeze manifest for benchmark, run reproducible clean setup checks. |

**Explicitly not decided in ADR-008:** physical entity/column/index design and migration ordering; exact external/internal API routes or HTTP error taxonomy; end-user login session/token model; UI styling/component library; detailed infrastructure beyond CPU-only Compose; deployment on cloud/production; acceptance results. The requirements, current decisions and 736-VU workload remain unchanged.

## 6. Approved deterministic verification cases (design only; all `NOT_RUN`)

The following **ten** checks verify the *selected stack* without replacing pre-approved QA/ADR tests. Every MUST check has an independently inspectable oracle; failure of a required check is `FAIL`, absent implementation/evidence is `NOT_RUN` or `BLOCKED`, never an assumed PASS.

| ID | Fixture / action | Binary PASS oracle |
|---|---|---|
| `STACK-01-BOOT` | Clean checkout with version-pinned inputs and documented demo secrets; run documented Compose bring-up, migration task and service health checks. | Exactly five expected long-lived services healthy (UI/API/Manager/Simulator/Postgres), all documented prerequisite commands succeed, zero hidden manual edits or real-GPU dependencies; DB schema at pinned head revision. |
| `STACK-02-LOCKS` | Fresh rebuild twice from same Git commit, Python `uv.lock`, Node `package-lock.json`, exact image manifests. | Python/Node/PostgreSQL major/minor runtimes match approved register; complete resolved package/version hashes and base image digests identical across builds; no latest/floating dependency in scored manifests. |
| `STACK-03-DB-BOUNDARY` | Inspect Compose secrets, credentials and DB network; attempt direct DB connection from Simulator container; verify API and Manager DB transactions. | Simulator has zero DB credentials and cannot reach PostgreSQL; API/Manager DB-backed checks can connect with correct roles; no browser-accessible DB. |
| `STACK-04-PROCESS-BOUNDARY` | Run one listing -> queued Job -> Manager allocation -> Simulator callback; inspect traced writers and processes. | Only API records the authorized submit and durable result ingress; only Manager allocates/finalizes/updates reputation; Simulator signs but writes no DB state; 1 accepted final result/reputation effect after retransmission. |
| `STACK-05-SIGNED-VECTOR` | Execute ADR-004 canonicalization/sign/verify public vector in the real Python packages; tamper one signed field and send duplicate-key JSON. | Exact canonical UTF-8/digest/signature bytes equal approved vector; valid verifies, both tampered payload and duplicate-key raw JSON rejected; no accepted terminal effect for invalid input. |
| `STACK-06-MIGRATIONS` | Apply Alembic migrations to empty PostgreSQL fixture, record schema revision; reapply twice; run fixture count checks. | Final schema head revision stable; zero duplicate migration entries, users/listings/keys or invalid FK; no second-run mutation beyond explicitly permitted, versioned fixture effects. |
| `STACK-07-ASYNC-SAFETY` | Inject a 1-second blocked SQL call through a DB-backed API route while a 50-ms event-loop heartbeat runs; release 129 concurrent Simulator tasks with a controlled barrier; crash/restart Simulator before callback ACK. | API heartbeat maximum delay stays `<200 ms` despite the blocked SQL thread; 129th attempt is not marked in-flight until a slot frees (`max_in_flight<=128`); Manager preserves the same `attempt_id` on retry, with one finalization and one reputation effect. Missing trace/barrier evidence => `BLOCKED`. |
| `STACK-08-UI-RBAC` | Build SPA and run role-bound smoke sessions for Client/Worker/Admin with forbidden cross-role mutations. | TS production build succeeds; API enforces role and object ownership regardless of UI state; browser frontend does not call Manager/Simulator/Postgres directly. |
| `STACK-09-SECRETS` | Scan Git-tracked source, built static bundle, Docker build context/layers and emitted logs for injected tokens/private keys. | No injected secret bytes or Worker private keys appear in tracked artifacts, browser assets, image layers or logs; distinct ADR-005 service tokens are absent from unauthorized processes. |
| `STACK-10-LOAD-PROFILE` | Compare running reference SUT process/config snapshot with accepted ADR-007 benchmark manifest before launch. | Exactly 2 API execution units, 1 Manager, 1 Simulator with cap 128, 1 PostgreSQL; k6 on separate host; 736-VU workload untouched. Otherwise test campaign `BLOCKED` rather than claimed performance PASS. |

**Approval scope (2026-10-18):** The project owner approved the *tool families/reference runtime versions and ten `STACK-01..10` test designs*, not any executable test result. Actual implementation must later lock exact minor/patch/build digests and produce recorded PASS/FAIL evidence. No technology choice can weaken the accepted security, domain or retention guarantees.

## 7. Recorded approval and remaining implementation gates

**ACCEPTED (Option B, 2026-10-18):** Python 3.12 + FastAPI/Pydantic 2 + SQLAlchemy 2/psycopg 3 + Alembic; separate Python Manager and Worker Simulator using `httpx`, `cryptography` and RFC 8785 JCS; PostgreSQL 16; React 19 + TypeScript + Vite on Node.js 24 LTS; `uv`+`npm` lockfiles; Docker Compose v2 with five long-lived services; pytest/Vitest/Playwright and the already accepted k6 profile. All ten `STACK-01..10` checks are accepted **as test designs** (`NOT_RUN`). Existing Database/API/Module/Test Design documents remain authoritative for their respective contracts. Application code, migrations and benchmarks require separate explicit coding authorization.

**Current disposition: ACCEPTED (user decision 2026-10-18).** The companion documentation-status updates are included in this Markdown-only approval bundle. `API-OPEN-01` (token algorithm/storage), `API-OPEN-02` (login normalization), and the exact `simulation_input` allowlist remain OPEN and are **not** implicitly approved by this ADR. No application code or successful test execution is asserted.
