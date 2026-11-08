# OPEN_DECISION_REGISTER — Phase 2B pre-code task TV2-P2B-05

**Owner:** TV2 · **Status:** `DRAFT` (updated after the lead review at `0bfccf1`) · **Date:** 2026-11-08
TV2 records what is blocked and who decides. TV2 does **not** close any item that belongs to the lead, TV3, TV4 or TV5, and does not treat `APPROVED_DESIGN_CONDITIONAL` as `PASS`.

## 1. Decisions TV2 needs from others (D-xx)

| ID | Question | Why it blocks TV2 | Decider | Where discussed |
|---|---|---|---|---|
| D-01 | Is SHA-256 equality (schema CHECK `envelope_sha256 = sha256(original_envelope_raw)`) accepted as byte equality for duplicate callbacks, or must the comparison be byte-for-byte in PostgreSQL (probe function with a new non-superuser owner role)? | decides grants, one optional function and a role-bootstrap change | lead (TV3/TV5 consulted) | `INBOX_DUPLICATE_PRIVILEGES.md` **TV3 (2026-11-08, PR #46): no objection to option C as a security input; the lead still decides. If accepted, TV3 updates the "prefilter" sentence in `Phase_2C` DR-C2.** **TV5 (2026-11-08): `NEEDS_LEAD_DECISION`. Option C is cryptographic equivalence, not a literal byte comparison; the lead must choose C explicitly and reconcile the API / Phase 2C / Phase 2E wording, or choose B. Never a general raw `SELECT`. TV5 does not treat a pending D-01 as approved; TV2 agrees and records it as open.** |
| D-02 | Unique-collision handling for the same `result_id` on different Jobs: `INSERT ... ON CONFLICT DO NOTHING` then probe, or catch `23505`, roll back, re-read in a new transaction | error-mapping table of `B-IF-02` | TV3 + TV2 + TV5 | same **TV3 ACK: `ON CONFLICT (result_id) WHERE result_id IS NOT NULL DO NOTHING RETURNING id`, then probe in a new statement.** **TV5 ACK_WITH_ACTIONS (supersedes the earlier "TV5 pending"): agrees with `ON CONFLICT … DO NOTHING` then a fresh probe, including cross-Job collision; a duplicate after terminal is still `202` if retained; unknown `COMMIT` reconciles in a new transaction; tests must cover both commit orders and no duplicate timestamp/business effect. TV2 ACK, written into `B-IF-02`.** |
| D-03 | Key readiness, K1→K2 rotation, key compromise policy | `B-IF-08`; no schema change, but TV2 must not guess | lead, TV3, TV5 | `Phase_2C`, `Phase_2E` |
| D-04 | May the Manager write `audit_events` for Phase 2 events (`ALLOCATE`, `FINALIZE`, fallback)? Which events and metadata? | Manager has no `audit_events` grant; also the audit finding on #39 is the owner's triage | lead / TV1 | handoff §7 |
| D-05 | Contents of `execution_outbox.dispatch_payload` (job id, attempt id, gpu_count, duration, seed?) and a rule that it never carries oracle values | Simulator must not know the protected reference; the column is immutable once written | TV5 + TV1 | `Phase_2E` **TV5 (blocker): wire body is exactly ten keys `outbox_event_id, job_id, attempt_id, worker_id, listing_id, gpu_count, duration_seconds, simulation_input, finish_due_at, hard_deadline_at` with `simulation_input={"workload_profile":"demo-v1"}`; never simulation_references/seed/expected/key/token. TV2 proposal P1 (full ten keys stored; ids chosen by the UoW; `INSERT(attempt_id)`, `INSERT(event_id)`; canonical serialization; shape CHECK) with fallback P2 (eight-key core, ids from columns). Needs TV1 + TV5 ACK; `P2B-DRT-18`.** |
| D-06 | Outbox CHECKs: `(lease_owner IS NULL) = (lease_until IS NULL)` and CLAIMED ⇒ lease present | constrains how the dispatcher clears a lease after ACK/RETRY | TV1 | `PHASE2_SCHEMA_MATRIX.md` §4 |
| D-07 | Hash CHECK on `result_inbox` and the maximum callback body size | CHECK cost and `bytea` bound | TV3 (body bound) | schema matrix §5 **TV3 proposal (pending TV1 + TV5): keep the hash CHECK; body bound 16,384 raw bytes inclusive, at most 4 JSON levels counting the root, checked from `Content-Length` and while streaming; every bound/parse failure is `422 INVALID_SIGNED_ENVELOPE`. TV2 has not verified these values.** **TV5 ACK_WITH_ACTIONS on the TV3 proposal: needs TV1 budget ACK and boundary tests (16,384 vs 16,385 bytes, depth 4 vs 5, chunked / wrong `Content-Length`).** |
| D-08 | Do we ever store an unbound rejected Inbox row? If yes: state, `processed_at`, insert path and who may insert | baseline says "reject without a row" | TV3 + TV5 | schema matrix §5 **TV3 proposal: no unbound rejected row; `401/404/409/422` store nothing and write only a redacted structured log.** **TV5 ACK_WITH_ACTIONS (supersedes the earlier "pending TV5"): clarified in `B-IF-02`: no *unbound* rejected row, but a structurally valid, bound, on-time receipt is stored `PENDING` and may later become `REJECTED` after signature verification.** |
| D-09 | Keep the optional partial index on active allocations for reconciliation? | one extra index | TV4 + TV1 | schema matrix §3 **TV4: not needed for correctness or FIFO; keep optional, add only if TV1/TV2 have a production reconciliation query with EXPLAIN/load evidence; seq scan is fine in correctness tests. TV2 agrees: no index in R1 unless that evidence exists.** |
| D-10 | `signed_results` stores its own copy of the envelope (design choice) vs referencing the Inbox row | Inbox rows can purge on their own schedule, so a copy is the safer reading; confirm | TV5 | schema matrix §6 **TV5 ACK_COMPATIBLE: independent copy, copied and rechecked in the same UoW, never overwritten (`B-IF-07`).** |
| D-11 | `worker_reputation_aggregates.updated_at`: Manager `UPDATE` grant on the column vs a trigger that sets it | the column has only a `now()` default, so an update that does not touch it leaves it stale | TV5 + TV2 | `PHASE2_ROLE_GRANTS.md` §2 **TV5 ACK_WITH_ACTIONS: `updated_at` advances with trusted DB time inside the Finalization UoW only on a real `SUCCESS`/`WORKER_FAULT` increment; Manager `U(updated_at)` kept; exact SQL in `B-IF-07`; PG tests assert changed vs unchanged timestamps (`P2B-DRT-19`). TV2 ACK.** |
| D-12 | Are aggregate rows created when a Worker is created (Phase 1 provisioning) or upserted on the first finalization? No code creates them today | decides Manager `INSERT` on the aggregate | TV5 (TV3 has no provisioning stake here: Worker key provisioning is a separate item under D-03, `Phase_2C` S-10) | `PHASE2_ROLE_GRANTS.md` §2 **TV5 preference (TV2 ACK, TV3 ACK pending): first contributing finalization upserts by `worker_id`; `NONE`/`SYSTEM_FAULT` never create or change a row; Manager `INSERT` + `UPDATE` grants (`PHASE2_ROLE_GRANTS.md` §2); per-Worker concurrency test.** |
| D-13 | Does `attempt_id` need to be caller-chosen (grant `INSERT(attempt_id)`) or taken from `RETURNING`? | one column privilege | TV1 + TV5 | role grants §1 **PROPOSAL, not final: P1 with D-05 (caller-chosen ids, two column grants); fallback P2 keeps DB defaults. TV5 favors P1 (ACK_WITH_ACTIONS); TV1 and lead decision pending.** |
| D-14 | Does TV5's Phase 2 finalization policy read `simulation_references`? Default answer in this plan: no (Phase 3 dispute) | Manager `SELECT` on the oracle must stay off unless needed | TV5 | role grants §2 **TV5 ACK_COMPATIBLE: no Manager `SELECT` on `simulation_references`; not an input to `TX-FINALIZE` in Phase 2 (Phase 3 dispute workflow). TV2 ACK.** |
| D-15 | `signed_results` update-reject trigger as defense in depth: yes or no | one trigger | TV2 + reviewers | `GUARDS_TRIGGER_PLAN.md` |
| D-16 | X-02 cold-restart conflict contract | affects reconcile semantics after restart | lead + TV1/TV5 | `Phase_2A`, `Phase_2E` |
| D-17 | Deadline test and stored `received_at` must be the same instant (TV3 review action 3). Default in these docs: `INSERT ... RETURNING id, received_at`, roll back as `Ineligible(late)` if `received_at >= hard_deadline_at`; needs API `SELECT(id, received_at)`. Alternative: `BEFORE INSERT` trigger that sets `received_at` and raises when late (no extra grant, third trigger) | grant list and trigger count | TV3 + TV2 (TV5 consulted) | `INBOX_DUPLICATE_PRIVILEGES.md` §4 item 5 **TV5 ACK_COMPATIBLE on the invariant (never `202` for a stored-late row); option still pending TV2 + TV3; needs native-role privilege proof and near / equal-deadline barrier tests.** |

### 1.1 Lead review findings (PR #46, `0bfccf1`) and where they are answered

| Finding | Answer | Status |
|---|---|---|
| P1-01 Outbox CAS predicates | `P2B_UOW_INTERFACES.md` B-IF-06 (claim only `PENDING`-due or `CLAIMED`-expired; ACK/RETRY/EXHAUSTED `WHERE state='CLAIMED' AND version AND owner`; fields cleared; no resurrection; repair resend is a separate port), `PHASE2_SCHEMA_MATRIX.md` §4 CHECKs, `P2B-DRT-08`, `P2B-GUARD-04` | `PROPOSED_FOR_ACK` TV1 + lead (D-06) |
| P1-02 timeout vs post-deadline finalization | `RUNTIME_BUDGET.md` §2.1: admission deadline (stored `received_at`) is separate from the processing budget; `statement_timeout` no longer tied to `hard_deadline_at`; `finalize_one` never compares `now()` with the deadline | `PROPOSED_FOR_ACK` TV1 |
| P2-03 equality clock test | `P2B_TEST_MATRIX.md` §1: T-D1 limited to Manager business time; T-D2 for `received_at` (owner-seeded rows for ±1 µs, pure `is_late`, lock-wait barrier with `pg_sleep` in a holder session, race sweep); API role gains nothing | `PROPOSED_FOR_ACK` TV2 + TV3 |
| P2-04 typed verdict / provenance | `P2B_UOW_INTERFACES.md` `P2E-VERDICT-CONTRACT-01` (fields, DB recheck, stale verdict, rejection semantics) | `PENDING_ACK` TV1 + TV3 + TV5 |
| TV4 inline P2 (`INBOX_DUPLICATE_PRIVILEGES.md`) | explicit `ON CONFLICT (result_id) WHERE ...` needs `SELECT(result_id)`, which option B does not grant: the adapter now uses the target-less `ON CONFLICT DO NOTHING` (needs `INSERT` only) followed by the fresh probe; `ABSENT` after a conflict is `DependencyUnavailable`, never `202`; verified by running the statement as `gpm_api_app` (`P2B-DRT-02`, `G-01`) | `PROPOSED_FOR_ACK` TV3 + TV4 |
| TV4 inline P2 (`P2B_UOW_INTERFACES.md`, payload CHECK) | whole predicate wrapped in `COALESCE(..., false)` and id keys must be JSON strings; JSON-null, missing, numeric and uppercase ids added to `P2B-DRT-18` | `PROPOSED_FOR_ACK` TV1 + TV5 |
| TV4 B-IF-06 asks | no-op `COMMIT` and returned (not raised) outcomes, `LISTING_NOT_FOUND` / `LOCK_BUSY` cleanup, known ids in `CommitOutcomeUnknown` plus `reconcile_allocation`, P2 grants keep `INSERT execution_outbox(attempt_id)` | `PROPOSED_FOR_ACK` TV4 + TV1 |
| TV4 inline P2 (`reconcile_allocation`) | reconcile from the durable graph (attempt + allocation + outbox rows), so a Job already terminal and an allocation already `RELEASED` still answer `AllocationCommitted`; `AllocationNotCommitted` needs the whole graph absent and the Job still `QUEUED`; otherwise `AllocationUnknown`; barrier case added to `P2B-DRT-11` | `PROPOSED_FOR_ACK` TV4 + TV1 |
| TV5 re-review at `4a68f6e` | `P2B-DRT-08` oracle split (expired lease without takeover may ACK; takeover/terminal/duplicate may not); `RejectedV1Receipt` shared name, `reject_candidate` bound to the persisted row and hash after locks; derived `payload_jcs_raw` / `signature_raw` checked with a TV3 pure extractor (`P2B-DRT-23`); field type tests kept in the Manager serializer | `PROPOSED_FOR_ACK` TV3 + TV5 + TV1 |
| TV3 re-review at `342497c` | closed rejection-code enum plus `ck_result_inbox_rejection_code`; catalog test `P2B-MIG-06`; late check right after `RETURNING` with whole-UoW rollback and `hard_deadline_at` from the locked attempt; extractor semantics, V-IN vs V-OUT, invariant-break fails closed; D-12 owner cell corrected; retired-key note | `PROPOSED_FOR_ACK` TV1 + TV5 for V-IN vs V-OUT |
| Re-review of `0bfccf1`+ | TV3, TV4, TV5 targeted reviews to be requested on the new exact HEAD | open |

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
| G0 / G1 | The lead's review states G0 and G1 are **distinct** and that this docs PR grants no implementation authority by implication. The process notice's order (docs reviewed, approved, merged; then one task = one branch = one PR into `main`) stands, and coding authorization is a separate lead decision after the docs gate. The G1 record is drafted in §3.2 and filled in by the lead | lead | blocks tasks `TV2-P2B-07..17` |

### 3.1 TV5 cross-phase blockers (PR #46 review, 2026-11-08) and where TV2 answers them

| Blocker | TV2 answer in this branch | Needs ACK from |
|---|---|---|
| A. earliest eligible candidate must win, not the first finalizer to lock | persisted-state rule: `reject_candidate` settles invalid rows; `finalize_one` returns `PrecedingPending` while an earlier `PENDING` on-time row exists (`B-IF-05`, `B-IF-07`, `P2B-DRT-20`) | TV1, TV5 |
| B. `deadline_fallback` must not trust a caller proof; `VerifiedV1Receipt` binding | no caller proof; port re-reads committed Inbox under Listing → Job; DB recheck of every binding field (`B-IF-07`, `P2B-DRT-21`); typed verdict `P2E-VERDICT-CONTRACT-01` stays `PENDING_ACK` | TV1, TV3, TV5 |
| C. one atomic finalization transaction, `SYSTEM_FAULT` has no contribution | stated in `B-IF-07`; `P2B-DRT-10`, `-19`, `-22` | TV5 |
| D-05 payload / event id / serialization | proposal P1 with fallback P2 (`B-IF-06`, `P2B-DRT-18`) | TV1, TV5 |

### 3.2 G1 record (draft for the lead; TV2 fills only the facts it can measure)

| Field | Content |
|---|---|
| Accepted Phase 1 baseline | `main` SHA, merged PR #39 commit and the single Alembic head `0005_listing_d7` as recorded in `DB_BASELINE.md`; re-measured on the merge commit of this docs PR before any R1 work |
| Affected file SHAs | the Git blob SHAs of the files in this directory at the merge commit (filled at merge) |
| Producer/consumer ACKs | per-interface matrix in `P2B_UOW_INTERFACES.md` §4 and the decision table above, each ACK quoting the exact HEAD it reviewed; `PROPOSED_FOR_ACK` is not a signed decision |
| Named reviewers | L2 change: two independent human reviewers (lead-assigned); AI/Codex reviews and author ACKs do not count |
| Scoped work items | `TV2-P2B-07..17` (R1 schema, R2 grants/guards, then one transaction port per task), each one branch, one PR into `main` |
| Disposable-DB safety | `backend/tests/db_safety.py` markers, loopback cluster on a non-5432 port, `restored_login_role_credentials`, serial DB tests (`DB_TEST_ISOLATION.md`) |
| Rollback policy | R1/R2 downgrade boundary and the preflight in `MIGRATION_DEPENDENCIES.md`; accepted revisions are never rewritten |
| Authorization | lead decision recorded in the PR or a handoff file, not implied by merging this docs PR |

## 4. Not TV2's to decide (do not do)

Key rotation/compromise, cold-restart conflict resolution, FIFO/fairness policy, Completed/Failed/Reputation classification, Simulator behavior, Phase 3 retention/disputes, widening `/health/ready`, merging.
