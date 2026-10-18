# GPU Resource Marketplace - Codex Repository Instructions

This repository defines a simulation-only GPU resource marketplace MVP. Read the approved project documents before proposing or reviewing changes. Do not infer that a documented design has been implemented.

## Sources of truth

Read the relevant files before editing or reviewing:

- `docs/requirements.md` - main SRS and approved MVP scope.
- `docs/functional-requirements.md` and `docs/non-functional-requirements.md` - requirements and acceptance targets.
- `docs/architecture/system-architecture.md` and `docs/architecture/quality-attributes.md` - process boundaries and quality scenarios.
- `docs/architecture/decisions/ADR-001-*.md` through `ADR-007-*.md` - accepted architectural decisions.
- `docs/design/database-design.md`, `api-contract.md`, `module-design.md`, and `test-design.md` - approved design baseline and its explicitly open items.

If documents appear inconsistent, identify the conflicting sections and ask for a decision; do not silently invent a new rule. `ADR-008-technology-stack.md` is still **PROPOSED**, not accepted. The API token signing/storage choice, login normalization, and exact `simulation_input` allowlist also remain open design details.

The real MVP uses a **736-virtual-user** load-test workload, **23-day** normal history/audit retention, a strict **7 x 24-hour** Dispute filing window, and an **18-hour** change-request initial response target. Do not mix in separate AD-090 assignment parameters.

## Current phase and change authority

- **Design-only phase:** create or update Markdown documentation when requested. Do not create or modify application source, SQL migrations, database scripts, Docker configuration, CI workflows, or executable tests until the project owner explicitly approves coding.
- Do not add new MVP features, actors, tables, services, or technology decisions without approval.
- Before a proposed change: state its goal, affected documents, dependencies, and acceptance criteria.
- Never commit, push, merge, release, deploy, or change GitHub settings without explicit authorization.
- Never claim functional tests, load tests, PostgreSQL migrations, or deployment have passed without observed execution evidence. Design approval is not a test result.

## Code Review Rules

Apply the following project-specific checks to Pull Requests. Prioritize consequential bugs, data corruption, trust-boundary violations, and undocumented changes to accepted contracts. Provide precise file/line references and a concrete safe alternative. Do not flag a correctly documented, explicitly unimplemented feature as a runtime defect.

### 1. Architecture and data boundaries

- Keep the approved **Modular Monolith** logical backend with separate API, Manager, and Worker Simulator processes.
- The Worker Simulator must **not** access PostgreSQL or the protected simulation reference/oracle. API and Manager use controlled shared backend/database boundaries.
- Manager-to-Simulator dispatch and Simulator-to-API callback use internal HTTP plus **transactional Outbox/Inbox**. Retries may happen, but committed business effects must not be duplicated.
- A received callback is not proof of a valid signed result. The API first durably records it; the Manager independently verifies and finalizes it.

### 2. Jobs, FIFO scheduling, and capacity

- Preserve strict FIFO ordering **per GPU Listing** using the database `enqueue_seq`; never bypass an eligible queue head just to allocate a smaller Job.
- Allocation, capacity reservation, release, and Job state updates must preserve atomicity under concurrent requests. Never over-allocate GPUs.
- Pausing a Listing prevents new submissions/allocations but does not terminate already-running Jobs. Resume restores eligibility.
- Only the owning Client may cancel a `QUEUED` Job. Terminal Job states are immutable; invalid transitions must be rejected.
- Listing capacity/model/VRAM updates must obey the accepted active-allocation, queued-demand, and nonterminal-Job guards.

### 3. Signed results and trust

- Preserve signed receipt V1: **Ed25519**, **RFC 8785 JCS**, the exact **11-field** schema, and the approved versioned signing prefix. Verify the original signed content without reconstructing or silently changing it.
- Never accept the Simulator's claimed result as an independent ground truth. The trusted simulation reference is isolated from the Simulator and public API.
- Accept at most one verified signed result per Job. Keep signed evidence immutable and retain the public verification key as long as required.
- A Manager `SYSTEM_FAULT` fallback has **no signed receipt** and must not modify Worker reputation.

### 4. Disputes, reputation, and retention

- A Dispute requires eligible verified signed evidence, is filed at most once per Job, and must be created strictly inside `[terminal_at, terminal_at + 168 hours)` using a trusted server/database clock.
- Dispute adjudication is deterministic; resulting lifetime reputation corrections are applied **exactly once**. `REJECTED` must not introduce an extra correction.
- Normal Job history expires after **23 x 24 hours** from trusted `terminal_at`; audit events follow their own 23-day rule from event creation.
- An `OPEN` Dispute holds all required evidence beyond normal expiry until resolution. Preserve the approved exception warning (within 1 hour), critical escalation (at 24 hours), retry (every 15 minutes), and post-resolution cleanup (within 1 hour) requirements.

### 5. Authentication and information disclosure

- Use only the approved `CLIENT`, `WORKER`, and `ADMIN` end-user roles; service identities are not extra user roles. Check ownership and role permissions on the server, not only in the UI.
- The approved access-token lifetime is **900 seconds**, stateless for the MVP. Logout does not immediately revoke an issued token. Do not assume an unapproved signing algorithm, token storage policy, or refresh-token mechanism.
- Never return secrets, password hashes, signing keys, internal service credentials, or protected simulation references in public responses or logs.

### 6. Documentation and verification

- For Markdown-only PRs, review traceability to the SRS, ADRs, database model, API contracts, and test design. Flag contradictions and accidental scope changes rather than demanding executable tests during the design-only phase.
- Keep `APPROVED_DESIGN`, `PROPOSED`, `OPEN`, `NOT_RUN`, `PASS`, and `FAIL` distinct. Do not promote an open decision to accepted or a future test design to PASS.
- Once coding is explicitly approved, require focused unit, integration, contract, security, and concurrency evidence for the affected invariants; cite the exact test command and observed results, including failures and tests not run.

## Review response expectations

For each substantial finding, explain: **severity, exact location, violated requirement/ADR/design rule, realistic failure scenario, and smallest safe correction**. Avoid stylistic nitpicks unless they obscure a contractual or safety-critical rule. Human approval and required CI checks remain mandatory even when Codex review finds no issues.
