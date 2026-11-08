# OPEN_DECISION_REGISTER — Phase 2B pre-code task TV2-P2B-05

**Owner:** TV2 · **Status:** `DRAFT` · **Date:** 2026-11-08
TV2 records what is blocked and who decides. TV2 does **not** close any item that belongs to the lead, TV3, TV4 or TV5, and does not treat `APPROVED_DESIGN_CONDITIONAL` as `PASS`.

## 1. Decisions TV2 needs from others (D-xx)

| ID | Question | Why it blocks TV2 | Decider | Where discussed |
|---|---|---|---|---|
| D-01 | Is SHA-256 equality (schema CHECK `envelope_sha256 = sha256(original_envelope_raw)`) accepted as byte equality for duplicate callbacks, or must the comparison be byte-for-byte in PostgreSQL (probe function with a new non-superuser owner role)? | decides grants, one optional function and a role-bootstrap change | lead (TV3/TV5 consulted) | `INBOX_DUPLICATE_PRIVILEGES.md` **TV3 (2026-11-08, PR #46): no objection to option C as a security input; the lead still decides. If accepted, TV3 updates the "prefilter" sentence in `Phase_2C` DR-C2.** |
| D-02 | Unique-collision handling for the same `result_id` on different Jobs: `INSERT ... ON CONFLICT DO NOTHING` then probe, or catch `23505`, roll back, re-read in a new transaction | error-mapping table of `B-IF-02` | TV3 + TV2 + TV5 | same **TV3 ACK: `ON CONFLICT (result_id) WHERE result_id IS NOT NULL DO NOTHING RETURNING id`, then probe in a new statement; TV5 ACK still pending.** |
| D-03 | Key readiness, K1→K2 rotation, key compromise policy | `B-IF-08`; no schema change, but TV2 must not guess | lead, TV3, TV5 | `Phase_2C`, `Phase_2E` |
| D-04 | May the Manager write `audit_events` for Phase 2 events (`ALLOCATE`, `FINALIZE`, fallback)? Which events and metadata? | Manager has no `audit_events` grant; also the audit finding on #39 is the owner's triage | lead / TV1 | handoff §7 |
| D-05 | Contents of `execution_outbox.dispatch_payload` (job id, attempt id, gpu_count, duration, seed?) and a rule that it never carries oracle values | Simulator must not know the protected reference; the column is immutable once written | TV5 + TV1 | `Phase_2E` |
| D-06 | Outbox CHECKs: `(lease_owner IS NULL) = (lease_until IS NULL)` and CLAIMED ⇒ lease present | constrains how the dispatcher clears a lease after ACK/RETRY | TV1 | `PHASE2_SCHEMA_MATRIX.md` §4 |
| D-07 | Hash CHECK on `result_inbox` and the maximum callback body size | CHECK cost and `bytea` bound | TV3 (body bound) | schema matrix §5 **TV3 proposal (pending TV1 + TV5): keep the hash CHECK; body bound 16,384 raw bytes inclusive, at most 4 JSON levels counting the root, checked from `Content-Length` and while streaming; every bound/parse failure is `422 INVALID_SIGNED_ENVELOPE`. TV2 has not verified these values.** |
| D-08 | Do we ever store an unbound rejected Inbox row? If yes: state, `processed_at`, insert path and who may insert | baseline says "reject without a row" | TV3 + TV5 | schema matrix §5 **TV3 proposal (pending TV5): no unbound rejected row; `401/404/409/422` store nothing and write only a redacted structured log.** |
| D-09 | Keep the optional partial index on active allocations for reconciliation? | one extra index | TV4 + TV1 | schema matrix §3 |
| D-10 | `signed_results` stores its own copy of the envelope (design choice) vs referencing the Inbox row | Inbox rows can purge on their own schedule, so a copy is the safer reading; confirm | TV5 | schema matrix §6 |
| D-11 | `worker_reputation_aggregates.updated_at`: Manager `UPDATE` grant on the column vs a trigger that sets it | the column has only a `now()` default, so an update that does not touch it leaves it stale | TV5 + TV2 | `PHASE2_ROLE_GRANTS.md` §2 |
| D-12 | Are aggregate rows created when a Worker is created (Phase 1 provisioning) or upserted on the first finalization? No code creates them today | decides Manager `INSERT` on the aggregate | TV5 + TV3 (provisioning) | `PHASE2_ROLE_GRANTS.md` §2 |
| D-13 | Does `attempt_id` need to be caller-chosen (grant `INSERT(attempt_id)`) or taken from `RETURNING`? | one column privilege | TV1 + TV5 | role grants §1 |
| D-14 | Does TV5's Phase 2 finalization policy read `simulation_references`? Default answer in this plan: no (Phase 3 dispute) | Manager `SELECT` on the oracle must stay off unless needed | TV5 | role grants §2 |
| D-15 | `signed_results` update-reject trigger as defense in depth: yes or no | one trigger | TV2 + reviewers | `GUARDS_TRIGGER_PLAN.md` |
| D-16 | X-02 cold-restart conflict contract | affects reconcile semantics after restart | lead + TV1/TV5 | `Phase_2A`, `Phase_2E` |
| D-17 | Deadline test and stored `received_at` must be the same instant (TV3 review action 3). Default in these docs: `INSERT ... RETURNING id, received_at`, roll back as `Ineligible(late)` if `received_at >= hard_deadline_at`; needs API `SELECT(id, received_at)`. Alternative: `BEFORE INSERT` trigger that sets `received_at` and raises when late (no extra grant, third trigger) | grant list and trigger count | TV3 + TV2 (TV5 consulted) | `INBOX_DUPLICATE_PRIVILEGES.md` §4 item 5 |

## 2. Errata X-01 (proposed text for TV4 + TV2 ACK)

**Finding.** `Phase_2D_v0.9.md` line 285 reads: `conditional update Listing reserved_gpu_count += head.requested_gpu_count`. No such column exists. The Phase 1 column is `gpu_listings.allocated_gpu_count` (`0001_phase1b_baseline.py`, with `CHECK (allocated_gpu_count >= 0 AND allocated_gpu_count <= total_gpu_count)`), and `database-design.md` §11.3 uses `allocated_gpu_count`.
**Correction.** Read every `reserved_gpu_count` in `Phase_2D_v0.9.md` (including the sentence of `P2D-TX-04` "reserved GPU total") as `gpu_listings.allocated_gpu_count`, equal to `SUM(allocations.gpu_count) WHERE state='ACTIVE'` for that Listing.
**Constraints.** No schema change, no new column, no rename. The conditional update stays `SET allocated_gpu_count = allocated_gpu_count + :n WHERE id = :listing AND allocated_gpu_count + :n <= total_gpu_count` and must affect exactly one row.
**Form.** A reviewed errata note or PR on the design file by TV4; TV2 ACKs by file SHA. TV2 does not edit `Phase_2D_v0.9.md` (TV4's file) in this branch.

## 3. Blockers outside TV2

| ID | Item | Owner | Effect on TV2 |
|---|---|---|---|
| X-02 | cold restart contract | lead | `B-IF-05/07` reconcile wording |
| X-03 | key compromise policy | lead, TV3, TV5 | `B-IF-08` |
| X-04..09 | remaining cross-file findings in `REVIEW_CROSS_PHASE_CONSISTENCY_v1.0.md` | various | the review file is not in this repository snapshot; TV2 has not read X-04..09 and classifies them only after it is shared |
| G1 | coding gate. Under the 2026-11-08 process notice it opens when the Phase 2 architecture docs (this package included) are reviewed across owners, approved and merged into `main`; then one task = one branch = one PR into `main`. The handoff's separate G1 record (scope, base SHA, reviewers, test cluster, rollback policy) is satisfied by that notice only if the lead says so | lead | blocks tasks `TV2-P2B-07..17` |

## 4. Not TV2's to decide (do not do)

Key rotation/compromise, cold-restart conflict resolution, FIFO/fairness policy, Completed/Failed/Reputation classification, Simulator behavior, Phase 3 retention/disputes, widening `/health/ready`, merging.
