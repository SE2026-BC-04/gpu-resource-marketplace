# Contributing to GPU Resource Marketplace

**Version:** 1.1 — proposed 2026-10-24; effective if merged<br>
**Applies to:** every contributor, including team leader, reviewers, GitHub-connected agents and Codex.<br>
**Project:** `SE2026-BC-04/gpu-resource-marketplace` — simulation-only MVP.

> This is the **human collaboration entrypoint**, not a replacement for the approved SRS/ADRs or a coding authorization. Read the [full team rules](docs/development/team-contribution-rules.md) and [change-control procedure](docs/development/change-control.md) before changing files.

## Golden rules

1. **Never push directly to `main` for a normal change.** Open a task-specific branch, commit there, and create a Pull Request (PR). The same applies to Markdown design changes.
2. **One ticket/slice = one branch = one focused PR.** Do not combine unrelated API, DB, UI and documentation changes.
3. **No unilateral contract changes.** Do not change accepted FR/NFR, ADR-001..008, the approved 18-table schema, the public/internal API or security invariants without prior design-change approval.
4. **No self-merge or self-review.** Every PR requires independent human review: one reviewer for L0/L1 and two reviewers for L2/L3. A reviewer may confirm in a submitted GitHub `Approve` review or an explicit PR comment made after reviewing the current diff; new commits require renewed confirmation. Codex does not count.
5. **Evidence before merge.** Record exact tests executed, outcomes and relevant requirements/test IDs. `NOT_RUN` is never `PASS`.
6. **No secrets, destructive commands or unrelated formatting.** Check staged diffs, dependency changes, config and data migration impact.
7. **Codex review is supplementary.** A Codex comment does not replace human review confirmation or required CI; Codex/agents follow the same change authority rules as humans.

## One PR from start to finish

1. Choose an authorized task, owner, scope, affected design IDs and test expectations. For design-affecting changes, use [Change Control](docs/development/change-control.md) **before** implementing them.
2. Update local `main` with `git pull --ff-only origin main`, then create a named branch (`feat/`, `fix/`, `docs/`, `test/`, `refactor/`, `chore/`).
3. Change only the assigned slice. Write and run the applicable tests; update design docs **only after** any required approval.
4. Review `git status`, `git diff --check`, `git diff` and `git diff --cached`; stage intentional paths, not incidental files.
5. Commit with **Conventional Commits**: `type(scope): imperative summary` (examples below). Push the topic branch, not `main`.
6. Create a PR into `main` using the [PR template](.github/pull_request_template.md). Link the task, FR/NFR/ADR, relevant tests, risk level and any skipped checks.
7. Resolve review comments on the same PR with new commits; rerun affected checks; obtain the required independent human review confirmations. Any GitHub account with merge permission may merge after all applicable gates are satisfied. No author may review or merge their own PR. A formal GitHub branch-protection requirement still applies even when the team accepts a comment as review evidence.

```text
feat(listings): create worker listing endpoint
fix(scheduler): preserve fifo head on insufficient capacity
test(jobs): cover cancel allocate race
docs(api): document accepted simulation input contract
refactor(manager): separate outbox dispatch from transaction
chore(tooling): pin reproducible test dependencies
```

## Coding readiness

The owner approved **ADR-008** and the three API design decisions: HS256 JWT / 900s / memory-only, trimmed case-sensitive login, and exact `simulation_input={"workload_profile":"demo-v1"}`. **Check that `docs/design/api-contract.md` on the branch contains the accepted v0.5-or-later baseline before implementing them.** GitHub `main` was still at v0.4 when this rulebook was drafted; documentation synchronization is a separate PR, not permission to code.

The owner must separately authorize the first **coding sprint**. These contribution rules themselves do **not** authorize writing application code, migrations or deployment automation.

See [Team Contribution Rules](docs/development/team-contribution-rules.md) for roles, branching, commit/review gates, conflict handling, security, rollback and GitHub ruleset recommendations.
