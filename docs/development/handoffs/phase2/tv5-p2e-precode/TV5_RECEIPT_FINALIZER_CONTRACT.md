# TV5-P2E-05 — Receipt, Inbox and Finalizer Contract

**Status:** preserves approved boundary; precise typed verdict and some non-winner Inbox outcomes are `PROPOSED — PENDING_ACK`.

## Callback and duplicate semantics

Simulator sends the signed V1 envelope to the API callback using only `SIMULATOR_CALLBACK_TOKEN`. API authenticates before revealing/querying Inbox state, validates strict structural bounds, binds context, stores original raw bytes and trusted DB receipt time, and commits before responding. API returns `202 STORED` only for a known commit; exact retained byte-and-context duplicate returns `202 DUPLICATE` without another row or changed `received_at`, even after terminal Job. Same `result_id` with changed raw bytes/context is `409 RESULT_ID_COLLISION`. A new candidate must bind a currently eligible RUNNING attempt and satisfy `received_at < hard_deadline_at`; equality is late. `202` does not imply cryptographic verification or completion.

On timeout or unknown Inbox COMMIT, retry only original bytes and `result_id`; reconcile against the retained row. Do not manufacture a new ID for the same produced receipt. Distinct newly produced receipts after cold restart are separate candidates, not duplicates.

## Proposed verifier result (`P2E-VERDICT-CONTRACT-01`)

TV3 is the sole creator of a trusted immutable typed result after strict ADR-004 V1 parsing, JCS/Ed25519 verification and trusted key lookup. Candidate shape (semantic proposal, exact names/types unfrozen):

`VerifiedV1Receipt(inbox_id, envelope_sha256, result_id, job_id, attempt_id, worker_id, listing_id, key_id, outcome, failure_reason, result_digest, schema_version)` or `RejectedV1Receipt(inbox_id, rejection_code)`.

The verdict binds one retained Inbox row and its original-byte hash; HTTP `202` or caller `verified=true` cannot create it. Exact raw bytes are authoritative, not hash alone. TV1/TV2/TV3/TV5 must ACK field types, provenance, rejection taxonomy, key-retirement behavior and stale-verdict handling.

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
