# Pull Request — GPU Resource Marketplace

> Follow [Team Contribution Rules](../docs/development/team-contribution-rules.md) and [Change Control](../docs/development/change-control.md). This template does not itself prevent a direct push to `main`; GitHub Rulesets must enforce that separately.

## 1. Task and purpose

- **Task / issue / assignment ID:**
- **Author / owning module:**
- **Change class:** L0 / L1 / L2 / L3 (justify high-risk or design-changing classification)
- **Goal — Mục tiêu:**
- **Change summary — Sửa những gì:**
- **Explicitly out of scope:**

## 2. Traceability and approval

- **FR/NFR / use case IDs:**
- **ADR / Database / API / Module Design references:**
- **Test Design IDs:**
- **Prior approval / decision record (mandatory for L2/L3):** approver, date, CR / link
- **Any added table, service, role, dependency or contract?** No / Yes — approved link:

## 3. Changes and risks

- **Changed paths:**
- **Behavior change vs refactor/docs only:**
- **Authorization, data exposure, secrets, concurrency, signatures, retention impact:**
- **Database migration/config or compatibility impact:** N/A / Explain
- **Safe rollback / recovery approach:**

## 4. Actual verification (not anticipated)

| Test ID / check | Environment / exact command | Actual result (`PASS`, `FAIL`, `BLOCKED`, `ERROR`, `NOT_RUN`) | Evidence / log |
|---|---|---|---|
| | | | |

- **Tests intentionally NOT_RUN and why:**
- **Known failures and unresolved blockers:**
- **Docs updated / linked prerequisite design PR:**

## 5. Author checklist

- [ ] Branch created from current `main`; no direct changes pushed to `main`.
- [ ] PR changes only the assigned task; commit/PR title uses `type(scope): summary`.
- [ ] Staged diff reviewed, `git diff --check` reviewed, no unrelated files or real secrets.
- [ ] Approved FR/NFR/ADR and Database/API contracts are preserved; L2/L3 approval linked if needed.
- [ ] Relevant tests actually run, with exact results; no `NOT_RUN` test labelled `PASS`.
- [ ] Sensitive data/role checks, FIFO/locks, signed evidence, reputation and retention assessed or marked N/A with reason.
- [ ] Changed interfaces or behavior have synchronized approved Markdown documentation.
- [ ] Deployment/migration/rollback implications documented when applicable.

## 6. Reviewer and merge gate

- [ ] L0/L1: **one independent human reviewer**; L2/L3: **two independent human reviewers** have approved the latest meaningful diff.
- [ ] No PR author self-approved; Codex review does not count toward the required human reviewer total.
- [ ] Required discussions resolved; no unresolved P0/P1 issue, secret leak or failing required test.
- [ ] CI status checks passed where configured, or absence/blocker is explicitly recorded.
- [ ] Codex review requested where connected (`@codex review`); advisory only, **not** a substitute for human approval.
- [ ] A GitHub account with merge permission performs the final merge only after all gates pass; the PR author does not self-merge.
