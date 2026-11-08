# INBOX_DUPLICATE_PRIVILEGES — Phase 2B pre-code task TV2-P2B-03 (`B-IF-02`, `B-IF-03`)

**Owner:** TV2 · **Status:** `PROPOSED_FOR_ACK` by TV3 + TV5; one sub-decision belongs to the lead · **Date:** 2026-11-08
**Problem (`Phase_2B_v1.3.md` §2.4 item 1, handoff §6.2):** for a callback whose `result_id` already exists, return `202 DUPLICATE` if the bytes (and bound context) are identical, `409` if the bytes differ. A digest-only comparison is not accepted as proof by the design. PostgreSQL column `SELECT` is **not** row-limited: to put `result_id` or `original_envelope_raw` in a `WHERE`, the role needs `SELECT` on that column for every row.

## 1. What the ingress path needs to learn

For one `(result_id, received bytes, derived bound_job_id, bound_attempt_id)`:

| Answer | Meaning | HTTP |
|---|---|---|
| `ABSENT` | no stored row with that `result_id` | continue to the new-candidate path |
| `SAME` | stored bytes identical **and** stored `bound_job_id/bound_attempt_id` equal the freshly derived pair | `202 DUPLICATE`, no write, original `received_at` kept |
| `DIFFERENT` | same `result_id`, different bytes or different bound context | `409 RESULT_ID_COLLISION` (API Contract §13.2; `RESULT_ID_CONFLICT` appears only in the Database Design pseudocode), no write |

It must work after the Job is terminal and while it is still `RUNNING`, and it must never return the stored bytes to the caller.

## 2. Options

| | A. Column `SELECT` for the API | B. Reviewed probe function | C. Hash column `SELECT` + `sha256` CHECK |
|---|---|---|---|
| Mechanism | grant `R(result_id, bound_job_id, bound_attempt_id, original_envelope_raw)`; compare in SQL | `SECURITY DEFINER` function `probe(result_id uuid, body bytea, job uuid, attempt uuid) → text` returning only `ABSENT/SAME/DIFFERENT`; API gets `EXECUTE` and no table `SELECT` | grant `R(result_id, bound_job_id, bound_attempt_id, envelope_sha256)`; the API hashes the body it received and compares; schema CHECK forces `envelope_sha256 = sha256(original_envelope_raw)` |
| Byte-exact compare | yes, in SQL | yes, in SQL | up to SHA-256 collision resistance |
| What the API role could read if compromised | every stored raw envelope | nothing but the three-value answer | every stored digest, not the bytes |
| New objects | none | one function, plus a function owner (DB owner or a new `NOLOGIN` role, which touches the D1 role bootstrap) | none |
| Fits "no unrestricted raw export" (§2.4) | **no** | yes | yes |
| Fits "digest alone is not proof" (§2.4) | yes | yes | **needs the lead to accept SHA-256 equality as byte equality** |

## 3. Recommendation (TV2, for ACK)

1. **Reject A.** It hands the API every stored envelope for a feature that needs a yes/no.
2. **Default to C** if the lead accepts that, with the stored-hash CHECK in place, hash equality is the byte-equality test. It adds no function, no role and no `SECURITY DEFINER` surface, and it keeps all Phase 2 DB code `SECURITY INVOKER` like D2/D3/D7.
3. **Use B** if the lead insists on a byte-for-byte comparison inside PostgreSQL. B requires: fixed `SET search_path = pg_catalog`, fully qualified names, typed arguments only, `REVOKE ALL ... FROM PUBLIC`, `EXECUTE` to `gpm_api_rw` only, an owner that is **not** a superuser (new `NOLOGIN` role with `SELECT` on `result_inbox`), and a role-bootstrap change reviewed by TV1.
Decision owner for "SHA-256 equality is enough": the lead (**D-01**). TV3 and TV5 confirm the HTTP mapping (**D-02**).

## 4. Race analysis (applies to every option)

New-candidate path, READ COMMITTED, after the Auth token is checked outside the UoW:

1. Unlocked locator read of `jobs.listing_id`; `LOCK Listing → LOCK Job`. Two callbacks for the **same Job** serialize on the Job lock. The second one runs its probe after the first committed and sees it: `SAME` (or `DIFFERENT`). No unique violation can happen between them.
2. Two callbacks with the **same `result_id` but different Jobs** do not share a Job lock. They collide at the partial unique index `uq_result_inbox_result_id`. Use `INSERT ... ON CONFLICT DO NOTHING RETURNING id, received_at` (**no conflict target**, see item 3): PostgreSQL makes the second inserter wait for the first to commit or abort, then returns no row; the adapter then probes in a **new statement** (READ COMMITTED sees the winner) and maps to `SAME`/`DIFFERENT`, which for different Jobs is `DIFFERENT` (different bound context) → `409`. This removes the "catch `23505`, roll back the whole UoW, re-read in a new transaction" detour the handoff describes. Either mechanism satisfies the contract; the `ON CONFLICT` form needs TV3/TV2 ACK because it changes the error-mapping table in `B-IF-02` (**D-02**).
3. **Conflict target and privileges (TV4 review).** PostgreSQL 16 requires `SELECT` on the columns named in an explicit conflict target and its index predicate (`ON CONFLICT (result_id) WHERE result_id IS NOT NULL`), even for `DO NOTHING`. Under option B (and A) the API has no `SELECT(result_id)`, so the explicit form would fail with `42501` before any duplicate exists. Therefore the adapter uses the **target-less** form `ON CONFLICT DO NOTHING`, which needs only `INSERT` (plus `SELECT(id, received_at)` for `RETURNING`). The only unique indexes of `result_inbox` are the primary key `id` (never supplied by the API, generated by default) and `uq_result_inbox_result_id`, so a suppressed conflict is a `result_id` collision. Zero returned rows is always followed by the fresh probe; if the probe answers `ABSENT` (which should be impossible) the port raises `DependencyUnavailable` (`503`, redacted log) and **never** answers `202`. Option C keeps `R(result_id, ...)` for the probe only. The claim is design analysis of the PostgreSQL 16 documentation; `P2B-DRT-02` / `G-01` run the exact statement as `gpm_api_app` under each option to confirm.
4. Unknown COMMIT (`40003`, connection loss): do not insert again; run the probe in a new transaction. `SAME` ⇒ the first insert committed ⇒ answer `202`. `ABSENT` ⇒ it did not ⇒ the sender will retry. This is the only retry of a mutation and it is decided from DB state.
5. **One instant for the deadline test and for the stored value (TV3 review, action 3).** If the adapter read `t = clock_timestamp()`, tested `t < hard_deadline_at`, and the column default then called `clock_timestamp()` again at `INSERT`, the stored `received_at` would be a later instant than the tested one: a callback tested at `deadline − 1 µs` could be stored at or after the deadline, answered `202`, and then ignored by fallback as late. The adapter therefore tests the **stored** instant: `INSERT ... RETURNING id, received_at`; if `received_at >= hard_deadline_at` it rolls the UoW back and returns `Ineligible(late)`. This needs `SELECT(id, received_at)` for the API on `result_inbox` (timestamps and ids only, no bytes; see `PHASE2_ROLE_GRANTS.md`). A stronger alternative is a `BEFORE INSERT` trigger that sets `received_at := clock_timestamp()` and raises when it is not before the attempt's `hard_deadline_at`; it needs no extra grant but adds a third trigger (decision **D-17**).
6. A replay after the Job reached a terminal state must not change `received_at`, add an Outbox event or create any business effect (`P2B-DRT-05`).

## 5. Bound-context equality

`SAME` requires the stored `bound_job_id/bound_attempt_id` to equal the pair the API derives **now** from the locked Job and its `execution_attempts` row. For a duplicate whose Job was purged, the Inbox row is purged with it (normal Job-bound rows follow Job history), so the probe returns `ABSENT` and the callback is ineligible as a late/unknown result; this matches the design and is covered by `P2B-DRT-05`.

## 6. Tests this decision must satisfy (all `NOT_RUN`)

`P2B-DRT-03` (two concurrent identical callbacks → one row, both `202`), `P2B-DRT-04` (same id, different bytes or different context → `409`, no overwrite), `P2B-DRT-05` (retained duplicate after terminal / lost ACK → `202`, no new event/effect/timestamp), plus `G-02` (API cannot read raw bytes outside the approved path), a two-session barrier test for the cross-Job same-`result_id` collision, and `P2B-DRT-17` (the stored `received_at` is never at or after `hard_deadline_at` for a `202` response; boundary test next to TV3's `P2C-DRT-10`).

## 7. Cross-review status

TV3 (`ACK_WITH_ACTIONS` on `517942f`, PR #46 comment 2026-11-08): agrees with rejecting option A, the three-value probe, `SAME` requiring equal bound context, and D-02 (`ON CONFLICT ... DO NOTHING` then probe); does not object to option C for D-01 (the lead decides); proposes the D-07 body bound and D-08 "no unbound row". Actions 1–3 are applied above and in `P2B_UOW_INTERFACES.md`.
