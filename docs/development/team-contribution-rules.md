# GPU Resource Marketplace — Team Contribution & Git Workflow Rules

**Version:** 1.0 — APPROVED by project owner (2026-10-20)<br>
**Owner:** Team leader, SE2026-T23<br>
**Applies to:** all team members and AI coding/review agents; Markdown, app code, database, tests, configuration and workflow changes.<br>
**Status:** APPROVED v1.0 by the project owner on 2026-10-20. This document sets the human team process; GitHub enforcement requires a separate repository ruleset setting.

## 1. Goal and precedence

**Goal:** every modification must be traceable, reviewable, reversible and compatible with the accepted GPU Marketplace design. The repository is the shared truth, not an individual developer's local copy.

Read the relevant source documents before editing:

| Concern | Source of truth |
|---|---|
| Approved MVP scope and business behavior | [SRS](../requirements.md), [FR](../functional-requirements.md), [NFR](../non-functional-requirements.md) |
| Architecture, trust boundaries, technology | [System Architecture](../architecture/system-architecture.md), [ADR-001..008](../architecture/decisions/ADR-001-modular-monolith.md) |
| PostgreSQL 18 tables / locking / transactions | [Database Design](../design/database-design.md) |
| HTTP contracts, JWT, internal dispatch, DTOs | [API Contract](../design/api-contract.md) |
| Modules / ownership | [Module Design](../design/module-design.md) |
| Test obligations / IDs | [Test Design](../design/test-design.md) |
| Team process and changes | This file and [Change Control](change-control.md) |

**Precedence:** approved requirements and accepted ADRs > approved detailed designs > contribution/coding rules > task-specific instructions. If documents conflict, **stop and request a recorded decision**; never adjust an accepted requirement just to make code pass.

**Scope freeze:** real MVP is deterministic GPU simulation, 736 benchmark VUs (552 Client, 147 Worker, 37 Admin), 23-day normal retention, half-open 168-hour dispute filing, and 18-hour initial change-request response target. AD-090's assignment-only variant is not this product. Approved API user token: HS256 JWT, 900s, in-memory browser storage; login is trimmed but case-sensitive; dispatch `simulation_input` only admits `{ "workload_profile": "demo-v1" }`. Confirm the corresponding API design has been synchronized to `main` before coding.

## 2. Roles and authority

| Actor | Allowed responsibility | Must not do |
|---|---|---|
| Task author | Implement assigned scope on a topic branch; commit, test, document, respond to review | Merge own PR, self-approve, silently change requirements or other modules |
| Independent reviewer | Inspect full changed diff, design compatibility, tests, security and failures; approve or request changes | Approve own PR, rubber-stamp without reading, overlook blocking FAIL |
| Domain reviewer (as assigned) | Review relevant DB/API/Manager/Simulator/security boundaries | Change another domain's accepted contract without cross-owner review |
| Team leader / delegated maintainer | Coordinate work, record decisions; may merge only when the account has GitHub merge permission and all required gates pass | Bypass review/CI gates, self-approve or self-merge |
| Codex / automation | Propose changes and review against `AGENTS.md` and approved docs | Push/merge/change settings autonomously; count as required independent human review |

**Minimum independent human reviews (APPROVED):** L0/L1 changes require **one independent human reviewer**; L2/L3 changes require **two independent human reviewers**. Reviewers must be independent of the PR author, and no author may approve or merge their own PR. Each review covers the latest meaningful diff; new logic after approval requires renewed review. Consult [Change Control](change-control.md) for levels.

## 3. Before a change: task assignment and scope

- Every task must have a unique issue/task reference **or** a traceable team-lead assignment recorded in the PR; clarify acceptance criteria and owning module/process before beginning.
- State **Mục tiêu**, **Quy trình thực hiện**, changed paths, dependencies, affected requirement/ADR/design IDs, and tests necessary to accept the slice.
- Declare whether work is **docs-only**, **implementation**, **test-only**, **bug fix**, or **design change**. A docs-only task cannot quietly introduce code/config or change product behavior.
- Avoid overlapping edits to one interface/schema across branches; the team leader coordinates ownership. Coordinate risky schema/contract modifications before coding them.
- Coding begins only after **explicit sprint authorization**; approved docs and rules do not grant blanket authorization to implement the entire MVP.

## 4. Branch policy

| Branch | Purpose | Rule |
|---|---|---|
| `main` | Stable integrated baseline | **PR-only**; no normal direct push, no force push, no deletion |
| `feat/<task>-<slug>` | Approved new behavior | Must be within an assigned MVP slice |
| `fix/<task>-<slug>` | Correct a defect | Include regression test unless reason recorded |
| `docs/<task>-<slug>` | Markdown changes | Must disclose if behavior/ADR contract is changed |
| `test/<task>-<slug>` | Test-only work | Do not silently weaken accepted assertions |
| `refactor/<task>-<slug>` | Non-behavioral restructuring | Behavior/API/data must remain unchanged; show regression evidence |
| `chore/<task>-<slug>` | Build, tooling or maintenance | No unapproved infrastructure/dependency additions |
| `hotfix/<task>-<slug>` | Urgent correction | Still requires PR, focused test, independent approval and rollback plan |

Use lowercase ASCII letters/digits/hyphens in branch suffixes; `<task>` may be a short issue number or descriptive key if no tracker ID exists (e.g. `docs/api-contract-sync`). Branch from the latest `main`; do not share a personal feature branch among unrelated tasks. Delete integrated topic branches when no longer needed. Never amend or force-push someone else's published branch without the author's consent.

**Safe start (examples, not commands to run before authorization):**

```bash
git switch main
git pull --ff-only origin main
git switch -c docs/api-contract-sync
```

## 5. Commit policy (mandatory)

1. One commit should represent **one coherent intent**, be buildable/testable when the relevant code exists, and exclude temporary debug code or unrelated refactoring. A series of small commits inside one PR is fine.
2. Use **Conventional Commits**: `type(scope): summary` (lowercase type; imperative, concise message). Allowed types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `build`, `ci`, `revert`. Scopes such as `api`, `auth`, `listings`, `jobs`, `scheduler`, `manager`, `simulator`, `db`, `disputes`, `reputation`, `frontend`, `adr` are guidance, not new modules.
3. Examples: `docs(api): accept jwt profile`; `feat(auth): validate current user role`; `fix(scheduler): stop at blocked fifo head`; `test(db): cover concurrent allocation`; `refactor(api): extract validation adapter`. **Never use misleading messages** such as `feat: complete system` for a documentation draft.
4. Before each commit inspect **what will actually be committed**:

```bash
git status
git diff --check
git diff
git add <intended-paths>
git diff --cached
git commit -m "docs(api): record approved login rules"
```

5. No passwords, `.env` secrets, access tokens, private Ed25519 keys, database dumps with user records, hidden simulation oracle, unrelated binaries/build outputs, caches or temporary files. Never bypass `.gitignore` to add sensitive data. If a secret is committed, stop and report it immediately for rotation/containment; simply deleting a later commit is not enough.
6. Do not manufacture `PASS` results in commit messages, logs or PRs. `NOT_RUN` and `BLOCKED` are explicit statuses. Keep exact reproducible commands/evidence when tests exist.
7. Do not rewrite public history, force-push to `main`, or squash away another contributor's authorship outside the approved merge workflow.

## 6. Pull Request (PR) is the unit of review

- **One PR = one task/feature or closely related fix.** Keep it reviewable; if too large, split by approved module or transaction boundary. Do not split a necessary atomic migration/contract update into incompatible main commits.
- PR title follows the same Conventional Commit format as commits, e.g. `docs(api): synchronize accepted v0.5`. Target `main`; link assigned task/issue, owning module, changed paths, FR/NFR/ADR/test IDs, scope exclusions and any design approvals.
- Complete [.github PR template](../../.github/pull_request_template.md), including the *actual* observed tests and `NOT_RUN` cases. If the PR changes an approved design, link its **prior** team-lead change decision.
- Include screenshots only when a visible UI change merits them; sensitive data must be removed. Reproduce bug fixes through a regression scenario (manual only if automated test is not yet possible and the reason is recorded).
- Use `@codex review` on an open PR if Codex GitHub review is enabled. Codex findings are advisory; reviewer and leader resolve P0/P1 concerns independently.
- A reviewer must read the actual diff and check business boundaries (not only green CI). Each comment should give a file/line, expected contract and practical fix. The author fixes in the **same PR**, pushes again and requests re-review; do not resolve threads by hiding failing behavior.
- **Default merge approach:** `Squash and merge` is recommended with a clear Conventional Commit PR title; preserve appropriate co-authorship credit. Any GitHub account with merge permission may perform the final merge after all required human approvals and applicable CI gates pass. Authors must never self-approve or self-merge.

### Do not merge if any applies

- Required independent approvals are missing, a blocking review thread is unresolved, or a reviewer approved an obsolete diff.
- The change contradicts an accepted FR/NFR/ADR/Database/API design, or a required L2/L3 design decision has not been approved.
- A relevant P0 integrity/security/regression test is **FAIL** or **NOT_RUN without an expressly accepted blocker**. Do not weaken assertions or bypass checks to force green CI.
- New secrets are exposed, authorization allows cross-account reads, Simulator receives DB/oracle access, signed bytes are silently changed, FIFO/capacity/retention invariants are weakened, or the PR introduces unauthorized scope.
- Migration, dependency/config or breaking wire/schema change has no documented compatibility, safe rollout/recovery path and relevant verification plan.

**Design-stage exception:** docs-only PRs have no application tests to execute. Mark functional tests `NOT_RUN` and perform document consistency/link reviews; do **not** claim application PASS. An early authorized foundation PR may have partial test infrastructure, but any unavailable required safety test must be disclosed and its acceptance must be explicitly decided before merge.

## 7. Mandatory project-specific change checks

| Changed area | Minimum design/test questions |
|---|---|
| DB schema, Jobs, scheduling | Still exactly 18 approved tables? Listing-before-Job locks? True per-Listing `enqueue_seq` FIFO and zero over-allocation? `DBP`, `DBTX` test cases? |
| API & JWT | Exact `/api/v1` DTO/status/role/ownership? HS256 900s, memory-only browser? No session/refresh? `API-AUTH`, `API-JOB`, `API-COM` cases? |
| Internal HTTP & Simulator | Only Outbox/Inbox + scoped service Bearers? Simulator no DB/oracle? `202` is not signature verification? `COM`, `RT`, `API-INT` cases? |
| Signed Result V1 | Exact 11-field schema/JCS/Ed25519 and immutable original evidence? `WIRE`, `SIG`, `ENUM` vectors? |
| Dispute & Reputation | Strict half-open 7-day filing, one dispute/job, deterministic resolution and exactly-once net correction? |
| Retention & audit | 23-day per-job terminal/audit-event TTL; OPEN hold and warning/CRITICAL/retry/cleanup rules unchanged? |
| Frontend, reports | Role-scoped data projection, no secret/oracle/JWT storage leaks; no direct Browser -> DB/Manager/Simulator? |
| Configuration/build | ADR-008 versions and pinned lockfiles, no unapproved broker/service, secrets excluded; only accepted Compose topology? |

A changed API/DB/ADR contract requires synchronized documentation **in the same approved design-change PR or an explicitly linked prerequisite PR**. Test IDs are defined by approved [Test Design](../design/test-design.md); do not invent claimed coverage metrics or performance success for 736 VUs.

## 8. Review, conflict, rollback and incident procedure

- When reviews disagree, record disputed requirement/section and invite the owning domain reviewer and team leader to resolve it. **Do not merge while normative policy is disputed.**
- When `main` moves, use `git fetch` then a normal merge/rebase strategy agreed with teammates; do not overwrite teammates' committed changes or resolve merge conflicts by discarding behavior blindly. Re-run affected tests after resolution.
- For a failed merged change, stop downstream dependent merges, open an incident/bug task, notify team leader, and propose a **revert PR** or reviewed correction. Do not rewrite `main` history. Document affected data/migration and whether recovery is safe.
- For a discovered credential leak: immediately alert team leader, revoke/rotate exposed credentials and investigate artifact/history exposure; do not merely redact the latest version and declare the leak fixed.
- If a task needs an unapproved change, follow [Change Control](change-control.md) *before* modifying implementation or accepted normative docs.

## 9. Making rules actually enforceable in GitHub

Markdown is **team policy, not an automatic permission barrier**. A repository admin/owner should separately enable a GitHub **branch ruleset** for `main` (Settings → Rules → Rulesets, if accessible):

1. Require a Pull Request before merging; apply the approved reviewer minimum (one independent human reviewer for L0/L1, two for L2/L3) and dismiss/refresh stale reviews after new changes where supported.
2. Block force pushes and deletions of `main`; prevent normal direct-push bypass and limit who may bypass, if allowed by the organization's plan/permissions.
3. Require conversation resolution and, **when CI workflows actually exist**, require the agreed status checks to pass. Do not configure imaginary check names before workflows exist.
4. Enforce the approved level-based human review minimum: one independent reviewer for L0/L1 and two for L2/L3. A GitHub ruleset configured for only one approval does not enforce the approved L2/L3 requirement; a suitable ruleset/CODEOWNERS process can be designed separately if needed.
5. Verify the ruleset with a harmless docs-only PR. The rules are not considered technically enforced until GitHub Settings confirms they are active.

**No GitHub settings are changed by the presence of this Markdown file.** A protected `main` rule and authorized merge permissions must be configured separately by an authorized repository admin.

## 10. Approval and versioning of this policy

**Approval record:** The project owner approved this v1.0 policy on 2026-10-20. Communicate it to all five team members and designate reviewers/delegates without hard-coding personal identities in the repo. Future modifications to this policy itself go through a `docs/` PR and the change-control level corresponding to the affected rule; no member can silently relax their own review requirement.
