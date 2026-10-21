# GPU Resource Marketplace - Codex Repository Instructions

**Team Contribution Rules:** v1.0 APPROVED by project owner (2026-10-20).<br>
**Project state:** Architecture and design documents accepted; coding has NOT been authorized merely by drafting these rules.<br>
**Repository:** `SE2026-BC-04/gpu-resource-marketplace`.

**MANDATORY for humans and agents:** [CONTRIBUTING.md](CONTRIBUTING.md) is the team entrypoint; [Team Contribution Rules](docs/development/team-contribution-rules.md) set branch/commit/PR/merge gates; [Change Control](docs/development/change-control.md) requires prior decisions for L2/L3 changes. The [PR template](.github/pull_request_template.md) records independent human approvals and actual tests. Do not treat Codex review as permission to merge or `AGENTS.md` as an automatically enforced GitHub branch rule.

## Read before acting

1. `docs/requirements.md` is the MVP scope and business-rules baseline. Read the relevant `docs/functional-requirements.md` / `docs/non-functional-requirements.md` items and acceptance criteria.
2. `docs/architecture/system-architecture.md`, `docs/architecture/quality-attributes.md`, and accepted `docs/architecture/decisions/ADR-001-*.md` through `ADR-008-*.md` define architecture and technology choices.
3. `docs/design/database-design.md`, `api-contract.md`, `module-design.md`, and `test-design.md` define approved logical contracts and mandatory test designs.
4. `CONTRIBUTING.md` and `docs/development/team-contribution-rules.md` govern Git collaboration. `docs/development/change-control.md` governs approvals. If the separately proposed `docs/development/coding-rules.md` and `implementation-gates.md` have been committed and approved, also follow them; do not assume absent files are installed. `.github/pull_request_template.md` defines PR evidence.

**Source precedence:** approved SRS/FR/NFR and accepted ADRs first; approved Database/API/Module/Test Design next; development rules/AGENTS next. Where they disagree, cite exact conflicting sections and stop for a human decision. Never silently change an accepted contract. Design documents are NOT proof of implementation.

**Documentation synchronization gate:** The owner accepted `API-OPEN-01/02/06` on 2026-10-18, but GitHub `main` may still have the previous API Contract/AGENTS revision. Before coding, check that `docs/design/api-contract.md` records v0.5 (or later) with all three accepted decisions: HS256 user JWT/900 seconds/browser volatile memory; trimmed case-sensitive logins; exactly `simulation_input={"workload_profile":"demo-v1"}`. If not, request the approved documentation update first. ADR-008 Option B is accepted; never revert its status.

## Scope, authority and working mode

- The REAL MVP is simulation-only, not real GPU execution. It uses 736 benchmark VUs (552 Client / 147 Worker / 37 Admin), 23-day Job-history and audit retention, strict 168-hour Dispute filing, and 18-hour initial change-request response target. Do not import the separate AD-090 assignment's 99/28-day/22-hour/privacy-erasure variant.
- **Before explicit owner authorization to start coding:** only review/write requested Markdown documentation or rules. Do NOT generate application files, migrations, tests, Docker/Compose files, workflows, or change the GitHub repository.
- **After coding is explicitly authorized:** implement ONLY the named slice. Do not infer blanket permission to build the whole MVP. Before any change, state in Vietnamese: (1) Muc tieu, (2) Quy trinh, (3) affected files/contracts, (4) exact acceptance/test evidence, (5) decisions/blockers. Keep changes small and reviewable.
- Never autonomously commit, push, merge, deploy, alter GitHub permissions/settings, change accepted requirements/ADRs, add a 19th table, add a new service, or install a new framework without explicit permission. Every contribution must use a topic branch and an independently reviewed PR per team rules; this applies to Codex and human contributors.
- Follow the approved stack: Python 3.12/FastAPI/Pydantic 2/SQLAlchemy 2 synchronous Sessions/psycopg 3/Alembic, PostgreSQL 16, React 19/TypeScript/Vite/Node 24, uv+uv.lock/npm+package-lock, Docker Compose v2, pytest/Vitest/RTL/Playwright/k6. Exact compatible patches and image digests must be pinned during implementation; do not fabricate lockfiles.

## Code execution rules

- API, Manager and Worker Simulator are separate processes in ONE modular-monolith logical backend. API/Manager may use the shared DB/domain package; Simulator MUST NOT connect to PostgreSQL or receive oracle tables, DB credentials, or any private truth/reference. Simulator may reuse only pure DB-free signing/wire helpers.
- PostgreSQL transactions are the source of truth for locks and exactly-once committed effects. Lock Listing before Job; follow `database-design.md` section 11. Never hold domain locks over HTTP, simulated execution, or sleeps. `SKIP LOCKED` may claim Listings/Outbox, NEVER skip the FIFO-head queued Job.
- Preserve FIFO per Listing by `jobs.enqueue_seq`, atomic capacity, one Job lifecycle terminal transition, one GPU release, one accepted result, and one effective reputation contribution. A paused Listing blocks new submissions/allocations, not running Jobs; only a Client can cancel its own QUEUED Job.
- Preserve PostgreSQL Outbox/Inbox plus authenticated internal HTTP. An HTTP `202` dispatch is not successful execution; a callback `202` only means durable Inbox ingress. Manager must verify signed result AND context independently before finalization.
- Preserve ADR-004 V1: 11 exact fields, version prefix, RFC 8785 JCS, Ed25519, immutable original signed payload/signature and retained verification key. Reject malformed/duplicate-key JSON. Never treat the signed claim as simulation ground truth. SYSTEM_FAULT has no signed Worker receipt and no Worker reputation penalty.
- Preserve ADR-005's 2s due-work poll, 30s fenced lease, 2s connect/5s total HTTP timeout, persisted 2/4/8/16/30s backoff, finish_due+10s missing-receipt probe and hard deadline `finish_due_at + 120s`. The DB-trusted callback decision is strictly `< hard_deadline_at`; process committed on-time Inbox before fallback even if Manager restarts late.
- For Disputes, require retained accepted signed evidence and at most one timely filing in `[terminal_at, terminal_at + 168h)`. Resolve from separately protected deterministic reference. Adjust lifetime reputation at most once. Hold OPEN evidence past 23 days; warning within 1h of detection, CRITICAL at 24h, adjudication retry every 15m, post-resolution expired-detail cleanup within 1h.
- End-user auth owner-approved policy: a dedicated API secret of at least 256 bits signs HS256 JWTs with exactly 900 seconds lifetime; no refresh token or user-session table; browser token storage is volatile-memory-only; Logout does not immediately revoke a token server-side; protected requests re-check ACTIVE account/role; login trims surrounding whitespace, matches case-sensitively, and uses the same rule for seeding/provisioning and login. The JWT claim/header profile beyond HS256 and trusted `iat` / `exp=iat+900` (including exact `iss`, `aud`, `typ`, and `sub` requirements), fractional NumericDate representation, exact whitespace code-point set, and Unicode normalization remain `NEEDS_OWNER_DECISION`; do not implement Authentication against a guessed choice. These decisions do not block a GPU-001 foundation slice that excludes Authentication. The API secret is distinct from the two direction-specific >=256-bit internal service tokens and Worker Ed25519 private keys.
- Manager dispatch `simulation_input` MUST be exactly `{ "workload_profile": "demo-v1" }`: no extra keys, arbitrary commands, client-chosen outcomes, secret seed, expected digest, or oracle fields. This rule does not invent the simulated-output algorithm; use approved fixtures/test vectors and escalate any unspecified format.
- Public API must use approved `/api/v1` route and error/DTO contracts. Authoritative ownership/role checks run on the server; Browser must never call Manager/Simulator/DB. Do not log or return passwords, hashes, JWTs, service Bearers, private keys, oracle records or raw signed secrets. Successful login may return its access token to that requester ONLY as the approved response.

## Code Review Rules

Review each PR for **materially consequential defects first**, not cosmetic formatting. Every finding should state severity (P0/P1/P2), file:line, violated FR/NFR/ADR/design ID, concrete failure/reproduction and smallest safe fix. Check at least:

1. Scope/authority: approved business and stack constraints; no AD-090 feature bleed or unauthorized extra table/service.
2. Architecture boundaries: Simulator cannot import DB repositories or know oracle; distinct process and internal-token directions.
3. Concurrency: Listing->Job lock order, true FIFO head, no GPU over-allocation, atomic terminal/release/reputation, crash-safe Outbox/Inbox and deadline ordering.
4. Cryptography: ADR-004 exact signed bytes, signature/context verification, safe key custody, retained evidence; no arbitrary JSON serialization substituted for JCS.
5. Auth/DTOs: enforce owner-approved JWT lifetime/signing/storage/logout policy, surrounding-whitespace trim with case-sensitive matching and seed/login consistency, exact `simulation_input`, role/owner checks and approved 401/403/404/409/422 semantics. Treat the remaining JWT claim/header profile, fractional NumericDate representation and Unicode normalization repertoire as `NEEDS_OWNER_DECISION` until approved; no token/PII leakage.
6. Dispute/retention: strict half-open 7-day cutoff, original receipt untouched, exactly-once correction and OPEN-evidence hold.
7. Verification: acceptance test IDs and exact command/results for changed slices; real PostgreSQL multi-session races where needed; tests NOT_RUN must never be reported PASS. No invented performance numbers.

Only review changed code against applicable approved gates; do not demand entire MVP implementation for an early foundation PR. Codex review is advisory and never replaces human review or required CI checks. Enforce the approved human-team rules: no direct push to main; one task per PR; Conventional Commit messages; no self-approval or self-merge; L0/L1 requires one independent human reviewer; L2/L3 requires two independent human reviewers. Any GitHub account with merge permission may perform the final merge after all applicable gates pass.

## Mandatory Codex delivery format

For any implementation task: summarize goal, scope and dependencies; show the intended smallest file set and design/test IDs; list commands actually run with PASS/FAIL/NOT_RUN/ERROR; report blockers and differences from the approved designs; provide a clear next review gate. If blocked, do not silently fill gaps with new policy. Do not claim a GitHub action succeeded without a tool-confirmed result.
