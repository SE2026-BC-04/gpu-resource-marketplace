# TV5-P2E-05 — Receipt, Inbox and Finalizer Contract

**Status:** preserves approved boundary; precise typed verdict and some non-winner Inbox outcomes are `PROPOSED — PENDING_ACK`.

## Callback and duplicate semantics

Simulator sends the signed V1 envelope to the API callback using only `SIMULATOR_CALLBACK_TOKEN`. API authenticates before revealing/querying Inbox state, validates strict structural bounds, binds context, stores original raw bytes and trusted DB receipt time, and commits before responding. API returns `202 STORED` only for a known commit; D-01 Option C digest-plus-trusted-context `SAME` duplicate returns `202 DUPLICATE` without another row or changed `received_at`, even after terminal Job. Same `result_id` with a different digest or trusted binding context is `409 RESULT_ID_COLLISION`; this assumes SHA-256 collision resistance, not mathematical raw-byte equality. A new candidate must bind a currently eligible RUNNING attempt and satisfy `received_at < hard_deadline_at`; equality is late. `202` does not imply cryptographic verification or completion.

On timeout or unknown Inbox COMMIT, retry only original bytes and `result_id`; reconcile against the retained row. Do not manufacture a new ID for the same produced receipt. Distinct newly produced receipts after cold restart are separate candidates, not duplicates.

## Proposed verifier result (`P2E-VERDICT-CONTRACT-01`)

TV3 is the sole creator of a trusted immutable typed result after strict ADR-004 V1 parsing, JCS/Ed25519 verification and trusted key lookup. Initial 2026-11-08 candidate sketch (**superseded by the current typed-verdict addendum below**; exact types still require owner ACK):

The initial candidate list has been replaced by the complete current immutable types in the 2026-11-13 addendum below. Do **not** implement the historical thin `RejectedV1Receipt` or omit `result_id`/`envelope_sha256`.

The verdict binds one retained Inbox row and its original-byte hash; HTTP `202` or caller `verified=true` cannot create it. Original raw bytes are always preserved. The lead selected **D-01 Option C conditionally**: `envelope_sha256 = sha256(original_envelope_raw)` via PostgreSQL CHECK, and duplicate `SAME/DIFFERENT` uses digest **and trusted bound Job/Attempt context**. Cryptographic SHA-256 equivalence is not mathematical raw-byte equality; reconcile approved API/DB text under E-C1. TV1/TV2/TV3/TV5 must ACK field types, provenance, rejection taxonomy, key-retirement behavior and stale-verdict handling.

## Candidate selection and one-UoW finalization

Manager processes committed eligible candidates in trusted order `(received_at, inbox_id)`. Invalid first candidate is rejected and later candidates are still assessed. First verified, context-eligible candidate wins; exactly one finalizer serializes on the approved Listing → Job → Attempt/Allocation → Inbox → contribution → aggregate order and re-reads DB state after locks. Recheck Job RUNNING, exact Attempt/Worker/Listing/key binding, Inbox identity/hash, on-time DB timestamp and absence of prior terminal effect. Do not trust Worker `finished_at`.

TV1 invokes Manager orchestration; TV2 owns `TX-FINALIZE`/`TX-DEADLINE-FALLBACK` SQL and transaction-scoped UoW; TV3 owns verifier; TV5 owns classification/finalization policy; TV4 confirms allocation/Listings invariant. No HTTP, signing, or long verifier work under domain locks. Whether CPU verification occurs outside locks is a performance/TOCTOU decision: if outside, mandatory fresh locked recheck remains.

One commit for an accepted result includes accepted immutable Signed Result, Job terminal transition, Allocation release, `gpu_listings.allocated_gpu_count` decrement, Inbox processing, eligible contribution and aggregate delta. System fallback releases/terminalizes without signed Worker result/contribution. Any pre-commit error rolls back all. Unknown COMMIT is reconciled by reading durable state/unique keys; never repeat mutation blindly.

## Deadline fallback and non-winners

At/after hard deadline, Manager must exhaust all committed on-time candidates, using bounded deterministic batches, before SYSTEM_FAULT fallback. If a batch leaves eligible candidates pending, no fallback commit. A candidate received before deadline may be verified/finalized after restart; Worker finish timestamp cannot backdate receipt. Existing Inbox states are `PENDING/ACCEPTED/REJECTED`; do not invent `SUPERSEDED`. Exact handling/cleanup of other stored candidates after winner selection remains `PENDING_ACK`.

## No-double-effect truth table

| Path | Job / signed result | Allocation and Listing | Reputation |
|---|---|---|---|
| accepted SUCCESS | COMPLETED / one immutable accepted V1 | one ACTIVE→RELEASED; one decrement | one SUCCESS contribution; successful +1 |
| accepted WORKER_FAULT | FAILED / one accepted V1 | one release/decrement | one WORKER_FAULT; fault +1 |
| accepted JOB_FAULT | FAILED / one accepted V1 | one release/decrement | explicit NONE contribution; counters 0 |
| SYSTEM_FAULT fallback | FAILED / no Worker V1 | one release/decrement | no row; counters 0 |
| QUEUED cancel | CANCELLED / none | no allocation/delta | no contribution |
| duplicate/rejected/late candidate | no additional terminal/result | no additional release/delta | no additional contribution |

E-IF-07..10, DRT-10..18 exercise these boundaries. All are design tests; runtime `NOT_RUN`, owner ACKs `NOT PROVIDED`.

---

## Typed-verdict and DB-locked evidence sync — 2026-11-13

**This addendum supersedes the original thin DTO sketch above; it is a PROPOSAL, not an approved contract.** Current sources: TV3 [PR #49 @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49) `6.6.1–6.6.4 and TV2 [PR #46 @ ba63466](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) B-IF-05/07. TV5's cross-review is ACK_WITH_ACTIONS; no Phase 2 test was run.

`VerifiedV1Receipt(inbox_id, result_id, envelope_sha256, job_id, attempt_id, worker_id, listing_id, key_id, schema_version='1', outcome, failure_reason, result_digest, finished_at_wire, payload_jcs_raw, signature_raw)`

`RejectedV1Receipt(inbox_id, result_id, envelope_sha256, job_id, attempt_id, rejection_code)`

Both are immutable, built only by the TV3 verifier. `result_id` is **non-NULL**: invalid result IDs fail strict ingress parsing (HTTP 422) before any Inbox INSERT. Only **four definitive post-ingress rejection codes** may travel in a verifier verdict: `UNKNOWN_KEY`, `KEY_WORKER_MISMATCH`, `CONTEXT_MISMATCH`, `INVALID_SIGNATURE`. TV2 housekeeping `NOT_SELECTED` and `ALREADY_TERMINAL` are not verifier codes. Previously accepted V1 raw bytes that later fail parsing, have an unsupported schema due to code drift, suffer extractor/key-store failure, timeout or another transient invariant failure **remain PENDING** and block false SYSTEM_FAULT; none may be converted to a definitive signature rejection. Archived K1 still verifies on-time historical receipts after retirement.

**V-OUT selected conditionally by TV1 (E-C4); exact TV1/TV2/TV3/TV5 interface ACK and approved DB pseudocode reconciliation remain pending:** TV3 verifies the exact stored envelope and trusted public key *outside* Listing/Job locks, returning a provisional typed result. In TV2 `finalize_one` or `reject_candidate`, the Listing→Job→Allocation/Inbox UoW rechecks `inbox_id`, `result_id`, `envelope_sha256 = sha256(original_envelope_raw)`, bound Job/Attempt/Worker/Listing/key, `state=PENDING` and trusted `received_at < hard_deadline_at`. A swapped or stale rejection ⇒ `BindingMismatchNoop`, no Inbox mutation and no fallback progress. A provisional accepted verdict must additionally match `extract_signed_parts_v1(original_envelope_raw)` over the **locked raw bytes**: `payload_jcs_raw=UTF8(JCS(payload))` without the ADR-004 domain prefix; `signature_raw` is exactly 64 bytes from strict unpadded base64url decoding. Extractor failure on previously admitted bytes is an invariant failure, not rejection. Verification must still be genuine Ed25519; the extractor is not a substitute. V-IN is fallback only, pending lead/TV1 decision.

**HTTP and Inbox:** known new COMMIT or ambiguous COMMIT reconciled as SAME ⇒ `202 STORED` (durability, not origin of insert); known existing SAME from pre-probe or target-less `ON CONFLICT DO NOTHING` followed by post-attempt fresh probe ⇒ `202 DUPLICATE` (no timestamp change, even after Job terminal). Different bytes/bound context under same `result_id` ⇒ `409 RESULT_ID_COLLISION`. Missing binding ⇒ `404 RESULT_CONTEXT_NOT_FOUND`; non-RUNNING/stale/late admission ⇒ `409 RESULT_NOT_ACCEPTABLE`; structural/body errors ⇒ `422 INVALID_SIGNED_ENVELOPE`; unreconciled unknown COMMIT/probe ABSENT/DB unavailable ⇒ `503`. Retry **the original raw envelope and same result_id** only on timeout/5xx/503 with bounded ADR-005 backoff, not unchanged 404/409/422. TV3 proposes 16,384 raw bytes inclusive and max JSON depth four pending TV1 resource ACK; stored DB `received_at` comes from `INSERT ... RETURNING id, received_at`, and a received instant at/after deadline causes full-UoW rollback.

**D-01/E-C1: Option C was conditionally approved by TV1** ([PR #46 decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771)). Preserve raw evidence exactly, enforce PostgreSQL CHECK `envelope_sha256 = sha256(original_envelope_raw)` and restrict duplicate probe to `ABSENT/SAME/DIFFERENT` using received SHA-256 plus trusted Job/Attempt binding. This is a cryptographic equality assumption, **not** byte-exact proof; escalate any residual normative requirement for literal equality. D-02/E-C2 target-less conflict handling still requires separate source alignment/owner ACK and native-role tests. Never grant API general SELECT on retained raw bytes.

**Finalize and reputation:** TV2 `PrecedingPending` prevents a later valid candidate winning while an earlier on-time PENDING row is unsettled; `deadline_fallback(job_id)` has no caller proof and freshly checks committed Inbox under Listing→Job locks. On-time committed candidates remain finalizable **after** deadline/restart. One TV2 UoW owns Signed Result's independent byte-exact evidence, terminal Job, Allocation release, `gpu_listings.allocated_gpu_count` decrement, Inbox and reputation ledger/aggregate. SUCCESS +1 successful; WORKER_FAULT +1 fault; JOB_FAULT contributes explicit NONE/zero aggregate change; SYSTEM_FAULT creates no Signed Result/contribution/penalty. First contributing Worker aggregate UPSERT with trusted `updated_at` only on real increments remains D-11/D-12 proposed, not a SQL PASS. No Simulator DB/oracle access.

**Evidence:** TV2 `P2B-DRT-17/19..23`, TV3 V1 vectors and `P2E-DRT-10..18` are specifications only; every Phase 2 native-role PostgreSQL, concurrency, crypto and E2E test remains `NOT_RUN`.

---

## Exact producer contract reconciliation — 2026-11-19

**Source tips inspected:** TV2 PR #46 `c4956777512efc260fbf180898af2c041d0a16d6`, `docs/development/handoffs/phase2/tv2-p2b-precode/P2B_UOW_INTERFACES.md` B-IF-05/07; TV3 PR #49 `e73fb107d15296a6f317d9bed25ce76fe0657ac2`, `docs/development/handoffs/phase2/HANDOFF_TV3_Phase2C_v1.1.md` C-IF-06/10 and C-FINAL-01/03, plus `docs/architecture/phases/phase2/Phase_2C_v0.9.md` §6.6/§7.2; PR #50 consumer baseline before this edit `52c23eabd6948ad7db13d3d39d65ed920d996c9a`. These are proposal/source references, not exact-SHA ACKs. E-C4 V-OUT remains conditionally selected; this typed contract is `PROPOSED — PENDING_ACK`, not an owner-approved public API.

### Producer-defined immutable verdict field sets

TV3 constructs these immutable values only after strict parsing and the applicable verification path. The names and semantics below reproduce the current producer field set; they do not add fields or define new wire formats.

```text
VerifiedV1Receipt(
    schema_version,          # literal "1"
    inbox_id,                 # retained Inbox row identity
    result_id,                # non-null UUID from accepted ingress
    envelope_sha256,          # SHA-256 of the retained original envelope bytes
    job_id,
    attempt_id,
    worker_id,
    listing_id,
    key_id,                   # trusted registered signer key identity
    outcome,                  # ADR-004 Signed Result V1 classification
    failure_reason,           # V1 value paired with outcome
    result_digest,            # signed V1 simulation-output digest
    finished_at_wire,         # signed wire value; never the trusted receipt time
    payload_jcs_raw,          # UTF-8(JCS(payload)); no domain prefix
    signature_raw,            # exactly 64 decoded Ed25519 signature bytes
)

RejectedV1Receipt(
    inbox_id,
    result_id,                # non-null UUID from accepted ingress
    envelope_sha256,
    job_id,
    attempt_id,
    rejection_code,           # closed definitive post-ingress enum below
)
```

The definitive `rejection_code` set is exactly `UNKNOWN_KEY`, `KEY_WORKER_MISMATCH`, `CONTEXT_MISMATCH`, `INVALID_SIGNATURE`. `NOT_SELECTED` and `ALREADY_TERMINAL` are TV2 housekeeping reasons, never verifier verdicts. A structure/schema failure on bytes already admitted by ingress (`INVALID_STRUCTURE`, `UNSUPPORTED_SCHEMA_VERSION`) is an invariant break, not a definitive rejection. Any such drift, extractor failure, key-store/dependency failure, timeout, or other transient verification error leaves the row `PENDING` and fails closed; it must not advance fallback. `finished_at_wire` is signed evidence only; trusted admission ordering/deadline use database `received_at`.

### E-IF-09: exact bounded scan, durable progress and restart behavior

Use the current TV2 B-IF-05 port without adding a durable cursor:

```text
iter_eligible_inbox(job_id, cursor, bound)
    -> Batch(candidates, has_more, scanned_through)
```

- `cursor` is an in-memory pagination argument only. A batch is ordered by `(received_at, inbox_id)` and returns unsettled eligible `PENDING` rows with `received_at < hard_deadline_at`; `scanned_through` reports the scan boundary, not durable progress.
- `has_more=True` means another bounded batch remains and **blocks deadline fallback**. Fallback also independently reads current PostgreSQL Inbox state; it never trusts a Manager cursor or cached “drained” flag.
- `finalize_one` refuses a later candidate with `PrecedingPending` if an earlier on-time `PENDING` row exists under Listing → Job locks. A transient verifier failure leaves that earlier row PENDING, so the caller cannot skip it or report SYSTEM_FAULT.
- A definitive rejection may settle that candidate, after which scanning continues in stored order. The first context-eligible valid candidate wins. If two candidates are valid, the first `(received_at, inbox_id)` candidate wins even when timestamps tie; `inbox_id` is the deterministic tie-breaker.
- On Manager restart or after a crash, resume with `cursor=None` and re-read PENDING rows from PostgreSQL. Settled `ACCEPTED`/`REJECTED` rows are not returned, and idempotent finalizer/reject ports make concurrent/replayed work a no-op; no settled row gets a second finalization or reputation effect.
- After a winner is committed, nonwinner settlement is separate TV2 housekeeping (`NOT_SELECTED` / `ALREADY_TERMINAL`), not a TV3 rejection verdict. No new Inbox state or persistence for cursor is authorized.
- A candidate durably admitted with `received_at < hard_deadline_at` remains eligible for verification/finalization after the deadline or process restart. A new late callback is not made on-time by `finished_at_wire`.

Required scenario coverage is mapped to existing TV2 tests `P2B-DRT-06/-20/-21/-23/-37`, TV3 `P2C-DRT-20/21/24`, and Phase 2E `P2E-DRT-12/-13/-14/-16`, with additional Phase 2E IDs `P2E-DRT-21..28` in the Test and Release Plan. G1 coverage also includes TV3 `P2C-SIGN-09/10` and `P2C-KEY-10`. The candidate scenarios include invalid-first/valid-second, two valid rows, equal timestamps and ID tie-break, restart midway through a batch, transient early verification failure, crash after rejection, an on-time receipt finalized after deadline, and restart with PENDING rows and no persisted cursor. These are test specifications; runtime remains `NOT_RUN`.

### V-OUT transaction boundary and locked evidence

TV3 verifies outside the database lock window and supplies a provisional immutable verdict. TV2 alone owns the one-UoW finalizer/rejection ports. Under the approved lock order `Listing → Job → Allocation/Attempt → Inbox → Contribution → Aggregate`, the transaction rechecks: Inbox identity and `state=PENDING`; non-null `result_id`; `envelope_sha256` against the retained original raw bytes; bound Job/Attempt/Worker/Listing/key identities against current locked rows and trusted registered key; database `received_at < hard_deadline_at`; and current Job/Attempt eligibility. For a verified result, the locked original raw bytes are passed through `extract_signed_parts_v1`; `payload_jcs_raw` and the 64-byte `signature_raw` must equal the extracted signed parts. A stale/mismatched verdict is a no-op with zero business effects. No DB write is delegated to TV3 or TV5 outside this UoW.

The accepted outcome is one atomic commit of Signed Result evidence, terminal Job transition, Allocation release, Listing counter decrement, Inbox settlement, eligible contribution and aggregate update. SYSTEM_FAULT has no signed Worker result or contribution. Unknown COMMIT is reconciled from durable state/unique keys; never blindly retry mutation. No HTTP, key-store call, or other network I/O occurs while these locks are held. TV5 does not define an alternative Finalizer UoW. Normative DB pseudocode, grant shape, exact-SHA owner ACKs and all PostgreSQL/crypto/concurrency/runtime verification remain pending/`NOT_RUN`.

### 2026-11-18 decision and evidence clarification

- **Lead authority:** [TV1 decision #46 @ `531805b`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46#issuecomment-6849327771) selected D-01 **Option C**, D-05/D-13 **P1**, D-18/E-C3, **G1** proof of possession, E-C4 **V-OUT**, D-17 stored `INSERT ... RETURNING received_at`, and D-12 first-contributing Reputation UPSERT, all `APPROVED_DESIGN_DIRECTION_CONDITIONAL`; D-06 CAS is approved **conditionally** with missing-receipt repair port still pending.
- **Typed verdict:** exact fields in the addendum above (including non-null `result_id`, provenance hash, trusted IDs and strict extractor) remain pending owner signoff. Four definitive post-ingress rejection codes only: `UNKNOWN_KEY`, `KEY_WORKER_MISMATCH`, `CONTEXT_MISMATCH`, `INVALID_SIGNATURE`. `NOT_SELECTED`/`ALREADY_TERMINAL` are housekeeping; `INVALID_STRUCTURE`/`UNSUPPORTED_SCHEMA_VERSION` are not permitted definitive post-ingress codes. Already-admitted parser drift or transient verifier failure leaves Inbox `PENDING`.
- **D-17:** compare the actual DB-stored `received_at` from `INSERT ... RETURNING id, received_at` with trusted `hard_deadline_at` after Listing→Job locking, rolling back the entire admission UoW if equal/late.
- **D-12:** one contribution-ledger + aggregate UoW; real SUCCESS/WORKER_FAULT +1 only, trusted `updated_at`, concurrency test `P2B-DRT-19` with two distinct Jobs/Worker; NONE/SYSTEM_FAULT/duplicate/rejected no aggregate side effects.
- **Test status:** `P2B-DRT-17/19..23` and all Phase 2 PostgreSQL/native-role/concurrency/crypto/E2E tests remain `NOT_RUN`. This docs-only addendum is not owner ACK, merge approval or coding authorization.
