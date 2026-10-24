# GPU Resource Marketplace — Change Control & Approval Matrix

**Version:** 1.1 — proposed 2026-10-24; effective if merged<br>
**Scope:** classification and approval **before** code or accepted design contracts are changed. This proposed amendment changes how human PR review is recorded; it does not amend the SRS or ADRs.

See the [Team Contribution Rules](team-contribution-rules.md) and root [CONTRIBUTING](../../CONTRIBUTING.md) for branch, commit, PR and merge workflow.

## 1. Change classes and review gates

| Level | Typical examples | Prior decision required? | Minimum human review before merge |
|---|---|---|---|
| **L0 — Non-normative** | Spelling, formatting, broken docs link, explanatory clarification with no contract change | Authorized docs task; no ADR needed | 1 independent reviewer; GitHub `Approve` or explicit approval comment |
| **L1 — Within accepted contract** | Implement approved endpoint; fix a bug without changing expected behavior; add a test; internal refactor preserving contract | Assigned coding slice + acceptance tests; coding must already be authorized | 1 independent reviewer; GitHub `Approve` or explicit approval comment |
| **L2 — Normative design or compatibility** | Change API path/DTO/error, existing table/column/constraint, JWT policy, signed V1 wire, lock ordering, retention, dependency/architecture behavior | **Team-lead approval before implementation**, documented impact analysis, revised affected design/ADR/test IDs | 2 independent human reviewers; each uses GitHub `Approve` or explicit approval comment |
| **L3 — MVP scope/architecture expansion** | 19th table, extra service/broker, real GPU, billing, extra actor/role, external privacy-erasure adapter, new requirements, breaking cross-module strategy | **Explicit stakeholder/owner change decision** and updated SRS/ADR/acceptance plan before any implementation | 2 independent human reviewers; each uses GitHub `Approve` or explicit approval comment; no work until accepted |

**Risk overrides label:** a one-line change to signing, auth, queue capacity, locks, dispute deadline or data deletion is **L2**, not L0/L1. Never rename a breaking change `refactor` to avoid approval. An emergency hotfix still uses a branch/PR and independent review; accelerated coordination does not authorize rewriting `main` or ignoring correctness.

For comment-based PR review, each independent reviewer must explicitly confirm the current diff, for example by commenting `Approved for merge` after reviewing it. Naming the reviewed HEAD SHA is optional. A new commit requires renewed confirmation. This is separate from the prior team-lead/stakeholder change decision required for L2/L3, and it does not override a GitHub branch rule that requires a submitted review approval.

## 2. Required change-request record (for L2/L3)

Record the following in a GitHub issue or linked design-change PR, not only in chat:

| Field | Description |
|---|---|
| CR ID / requester / UTC date | Unique traceable identifier and requester |
| Problem and evidence | Exact observed issue, reproduction, stakeholder need or inconsistency |
| Current accepted baseline | Affected SRS/FR/NFR IDs, ADR number, Database/API/Module/Test Design sections |
| Proposed change and alternatives | At least the current no-change option and concrete safe replacement |
| Impact | User behavior, security, schema/migrations, HTTP compatibility, tests, scope, schedule, dependencies and operations |
| Migration/backward compatibility | How persisted records, versions and clients will continue working or safely transition |
| Acceptance and rollback | PASS/FAIL oracle(s), fixtures, safe recovery or revert plan |
| Decision | `PROPOSED`, `APPROVED`, `REJECTED`, `DEFERRED`; approver, decision date, rationale |

**18-hour requirement:** the approved product constraint is an **initial response to a change request within 18 hours**, not a promise to implement/merge within 18 hours. Keep the distinction in CR records and communications.

## 3. Sequence for L2/L3 change

1. **STOP** implementation of the conflicting/breaking slice; keep ongoing unrelated work independent.
2. Open or link a CR, classify L2/L3 and record exact docs/FR/NFR/ADR/test IDs affected.
3. Team leader/stakeholder reviews alternatives and records a decision; `PROPOSED` does **not** authorize implementation.
4. If approved, update the normative documents and their cross-links, including acceptance test IDs. Use an ADR update/new ADR when architecture, cryptographic wire format or process/data boundary changes.
5. Obtain human review of the **documentation change first** (or an explicitly accepted atomic documentation+implementation PR if backwards compatibility permits). Do not code against a conflicting `main` baseline.
6. Implement in an authorized, narrowly scoped branch; produce test evidence and migrate data only with a reviewed safe plan.
7. Review and merge only after the applicable PR gates pass. Any GitHub user with merge permission may perform the merge; the PR author may not review, approve, or merge their own PR. Record the approved CR in the PR description and link the merging commit.

## 4. Protected invariants: changes always require escalation

- FIFO uses `jobs.enqueue_seq`, Listing-before-Job global lock order and atomic GPU reservation/release.
- Separate API / Manager / Worker Simulator, no Simulator PostgreSQL/oracle access, durable Outbox/Inbox.
- Signed Result V1 RFC 8785 JCS + Ed25519 exact wire/bytes; accepted original receipt immutable.
- Signed result verification, trusted oracle/adjudication and once-only Worker reputation are distinct authorities.
- Dispute filing `[terminal_at, terminal_at + 168 hours)`, Job history 23-day expiry, OPEN evidence hold, separate audit TTL and exception escalation.
- JWT HS256 900 seconds, no refresh/session, browser volatile-memory storage and role/ownership guard; case-sensitive trimmed login; exact single-field `simulation_input={"workload_profile":"demo-v1"}`.
- Simulation-only six-MVP-module scope, 736 VU benchmark profile and accepted ADR-008 stack.

## 5. Documentation synchronization gate (current repository)

At the time this policy was prepared, GitHub `main` still contained `docs/design/api-contract.md` v0.4 and `AGENTS.md` with outdated `OPEN` labels for choices **already explicitly approved** by the owner. **Before any coding sprint**, merge the accepted API v0.5 (or newer) documentation sync PR. Do not treat this policy as permission to bypass that prerequisite. Until then, design review can proceed but actual auth/simulation implementation should remain blocked.

**Status vocabulary:** `APPROVED_DESIGN` means approved text; `NOT_RUN` means never executed. Neither is equivalent to `PASS`. Record only tool-verified results and commit-specific evidence.
