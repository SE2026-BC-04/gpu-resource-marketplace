# Phase 2C - Internal Authentication and Signed Result Verification (TV3)

> **Review v0.9 (2026-11-07):** Deep document review of v0.8 against accepted ADR-003/004/005, API Contract §13, Database Design §§9/11, Phase 2A v0.9 and Phase 2B v1.3. Earlier owner-approved Phase 2C design choices remain conditionally approved; the additional Appendix DR-C below is **PROPOSED_FOR_ACK**, not a unilateral architectural change. PR #39 at `44579ed84605` is Phase 1 Draft, not an approved Phase 2 runtime.

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Document version:** `v0.9-DEEP-REVIEW` (revises local v0.8; inherited `P2C-GATE-01 = APPROVED_DESIGN_CONDITIONAL`, updated 2026-11-07)  
> **Status:** `APPROVED_DESIGN_CONDITIONAL / DOCUMENTATION_ONLY / NOT_APPROVED_FOR_IMPLEMENTATION` (owner-approved P2C-GATE-01; technical prerequisites below remain `PENDING`)  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate:** Phase 1 integration must be accepted on `main`, affected interfaces reviewed, and coding separately authorized.

> **Proposed documentation owner:** TV3 - Authentication and security owner (`giakhanh-hub`)

## 1. Goal and boundary

Design how the existing API accepts an **authenticated raw callback** and how the **Manager** later validates a versioned Worker-signed result. TV3 is proposed as the documentation owner for service-token security, wire validation and cryptographic verifier contracts; that does **not** move finalization/write ownership out of the Manager.

Keep end-user HS256 JWT authentication separate from two directional internal service Bearer credentials (each at least 256 random bits). Do not expose Manager/Simulator to browsers, give Simulator database access, or treat service authentication as Ed25519 receipt validation.

## 2. Proposed design deliverables (TV3)

| ID | Document deliverable | Required evidence/source |
|---|---|---|
| `P2C-01` | Directional auth matrix (Manager -> Simulator, Simulator -> API) | ADR-005; no confused-deputy token use |
| `P2C-02` | Raw Inbox ingress validation and exact response/error mapping | API Contract section 13; source of truth is committed Inbox |
| `P2C-03` | Signed Result V1 verifier and historical key-binding design | ADR-004 and public vector; strict version/envelope |
| `P2C-04` | Threat model for replay, malformed JSON, wrong Worker/Listing/Attempt, secret leaks | Security negative-case matrix |
| `P2C-05` | Independent compatibility handoff to TV5 finalizer, TV2 DB and TV1 Manager | No business effects at API ingress |

## 2.1. Approved P2C-DEC-01 - independent V1 verifier boundary

**Decision (2026-11-07): `P2C-DEC-01 = APPROVED_DESIGN` - option A.** TV3 designs an independent, testable **strict V1 parser and Ed25519 verifier**; TV5 keeps Job finalization, GPU release and reputation business logic. TV1 integrates the verifier into Manager. TV2 supplies trusted persistence/key lookup interfaces. This does **not** approve code, a new process/service/table, or cross-owner source edits.

### Verification responsibilities and contract

| Layer / owner | Allowed work | Forbidden work |
|---|---|---|
| TV3, strict parser | Validate exact envelope and 11 signed fields, no extra/missing/duplicate JSON keys; validate UUIDv4, timestamp, enum pairs, JCS/I-JSON and base64url signature encoding | No Job state change, raw Inbox write, allocation, reputation update or oracle decision |
| TV3, pure cryptographic verifier | Reconstruct `UTF8("GPU-MARKETPLACE:SIGNED-RESULT:V1\n") || UTF8(JCS(payload))`; verify Ed25519 with a **trusted supplied** Worker public key; return typed success or a stable redacted rejection class | Never trust a public key supplied in the HTTP envelope; never access Worker private keys or DB as an implicit side effect |
| TV2, trusted read adapters | Look up persisted `(worker_id, key_id)` public key and retained key metadata; expose Job/Listing/Attempt/Inbox reads with controlled permissions | No crypto policy decisions or false acceptance via DB insert |
| TV1, Manager orchestration | Load candidate from committed Inbox; obtain trusted context and key; call verifier; pass candidate and proof of verification to TV5 finalization integration | No duplicate ad hoc signature algorithm; no premature terminal Job write |
| TV5, Manager-owned finalization | Revalidate current DB state/identity/attempt/deadline and unique receipt under Listing -> Job locks; atomically apply accepted result/terminal state/release/eligible reputation effect | Cannot treat a verifier success as proof of oracle truth; cannot finalize solely from untrusted claims or HTTP `202` |

**Expected typed outputs (conceptual, not executable API contract):** `VerifiedV1Receipt` containing verified parsed claims, registered signer `(worker_id, key_id)`, canonical signed-byte digest and reference to immutable raw Inbox evidence; or `RejectedV1Receipt` containing a stable non-secret error category. The type, ownership and exact error names require TV1/TV2/TV5 ACK before coding. A bare `verified=true` flag or raw callback claims alone MUST NOT authorize finalization.

**Race boundary:** any pre-check or signature verification performed outside a DB transaction is advisory until the finalizer rechecks the committed Inbox candidate, trusted signer binding, RUNNING Job/Attempt, retained on-time receipt and one-time effects under the approved Listing -> Job lock discipline. No long network wait is allowed while domain locks are held. Retired public keys must remain available for historical verification while accepted evidence is retained; historical validity policy remains defined by ADR-004.

**Negative-case design evidence:** known ADR-004 public vector, tampered prefix/field/signature, duplicate key in JSON, wrong Worker/Listing/Job/Attempt, unknown historical key, claimed but unregistered key and valid signature with oracle-inaccurate outcome. A valid but false signed claim is **not** rejected solely for mismatching protected ground truth; Phase 3 Dispute checks truth separately.

**Pending cross-owner ACKs:** TV3/TV5 on verifier-to-finalizer contract; TV2/TV3 on trusted public key lookup and raw-byte evidence; TV1/TV3 on Manager integration and redacted errors. All Phase 2 runtime tests remain `NOT_RUN`.

## 2.2. Approved `P2C-OPEN-02` - existing API listener for internal callback

**Decision (2026-11-07): `P2C-OPEN-02 = APPROVED_DESIGN` - Option A.** Retain the existing Backend API HTTP listener for the internal signed-result callback route `/internal/v1/results/callback`; do **not** add a separate API listener, port or sixth service for Phase 2. This is an owner-approved *design choice*, not an authorization to change Compose, API routes or runtime code.

**Security requirements inherited from accepted ADR-005 and API Contract section 13:**

1. Authenticate the exact `SIMULATOR_CALLBACK_TOKEN` (at least 256 unpredictable bits) **before** accepting callback content as trusted, creating any Inbox record or disclosing internal data. A missing/invalid token, end-user JWT or opposite-direction `MANAGER_DISPATCH_TOKEN` must be rejected with no persistent Inbox/business effect. The dispatch receiver separately accepts only `MANAGER_DISPATCH_TOKEN`.
2. Fail closed when a required service credential is missing or malformed; source it from environment-injected/untracked secret material. Do not log raw Bearer headers, Ed25519 private keys or protected oracle records. Compare secrets without data-dependent timing when practical.
3. In **local Compose** the host port remains bound to `127.0.0.1`; the callback shares that HTTP listener, so it is still reachable by software on the local host. Do **not** describe the endpoint as internal-network-only, private merely because undocumented, or inaccessible to local processes. The token is mandatory regardless of apparent network isolation.
4. Before exposing the API beyond the trusted local single-host setup, the deployment owner **must** review and enforce explicit ingress controls blocking external access to `/internal/v1/results/callback` (or separately approve a more isolated topology). Bearer-over-HTTP on the existing isolated single-host network is the approved MVP trade-off, **not** production-grade network confidentiality; an untrusted network requires a separate TLS/mTLS decision.
5. The API's `202` acknowledges only a **committed raw Inbox record** or byte-identical retained duplicate. It is not a signature check, successful execution acknowledgement or finalization. Manager performs Ed25519/context checks before TV5's terminal transaction.

**Compatibility and future tests (all `NOT_RUN`):** `P2C-NET-01` valid callback token commits durable Inbox and returns `202`; `P2C-NET-02` wrong/missing/opposite-direction/user JWT rejected with `401` and zero writes; `P2C-NET-03` demonstrate local host can reach the route but not bypass Bearer, confirm no callback path in browser-facing UI/docs, and require a deployment ingress gate before any non-loopback exposure; `P2C-NET-04` secret missing/malformed fails closed and no sensitive values appear in error/log output.

**Cross-owner ACKs pending:** TV1 (Compose/API listener, deployment ingress and health), TV3 (auth dependency and negative tests), TV5 (Simulator callback client). No new service, DB role or wire field is approved.

## 2.3. Approved `P2C-OPEN-03` - PostgreSQL-authoritative durable replay and duplicate handling

**Decision (2026-11-07): `P2C-OPEN-03 = APPROVED_DESIGN`.** The owner approved the PostgreSQL-authoritative approach and cross-owner handoff described below. This decision fixes the *design algorithm* but does not constitute TV2/TV3/TV5/TV1 human ACK, validate SQL, execute tests, or authorize code/repository changes. The business semantics remain those already accepted in ADR-003/005 and API Contract section 13.2:

- Authenticate service Bearer before any Inbox write; reject unauthorized callbacks without side effects. Strictly parse the envelope, including duplicate JSON-key rejection.
- For a *retained* `result_id`, compare the **exact original raw envelope bytes**, using a stored SHA-256 as an efficient prefilter and exact byte equality for the final decision. An authenticated, byte-identical retry of the same bound receipt returns `202 DUPLICATE` **without changing original `received_at` or requiring Job to remain RUNNING**, including when the Job became terminal after its first ingest. The same ID with changed bytes returns `409 RESULT_ID_COLLISION`, without overwriting the evidence.
- For a *new* `result_id`, lock Listing then Job, verify active RUNNING attempt and persisted context, capture trusted DB time **after** Job lock, require `received_at < hard_deadline_at`, persist the exact raw bytes, and return `202 STORED` **only after commit**.
- Enforce uniqueness in PostgreSQL; a concurrent loser of the unique insertion **must roll back** its transaction and re-read the winner before deciding identical-duplicate versus changed-bytes conflict. No in-memory replay cache can be authoritative, and a read-before-insert by itself is not concurrency protection.
- Cryptographic correctness is evaluated by Manager *later*. A schema-valid but bad-signature envelope can be durably stored; it cannot finalize a Job or change reputation. After authorized Job-history purge, indefinite duplicate recognition is **not** promised.

**Approved design ownership split (implementation ACK pending):** TV3 (strict parser, authorized replay/error semantics, negative tests), TV2 (unique index, trusted raw-byte/hash storage and transactional re-read semantics), TV5 (callback retries preserve same `result_id` and exact raw bytes), TV1 (Manager Inbox consumer integration). Pending owner ACKs: TV2/TV3/TV5/TV1.

**Required proposed test matrix (`NOT_RUN`; no execution evidence):** `P2C-REPLAY-01` exact duplicate while RUNNING; `02` exact duplicate after terminal commit; `03` same ID changed raw body; `04` two concurrent identical submissions; `05` concurrent changed-body collision; `06` replay with wrong service credential; `07` brand-new late callback at hard deadline; `08` valid on-time Inbox processed after deadline; `09` semantically equivalent JSON with different raw bytes must **not** be silently treated as byte-identical; `10` no unlimited dedup promise after retention purge.

**Review gate:** the durable algorithm is accepted as the Phase 2C/2B/2E *design* handoff. Before implementation, independently approve exact interfaces/DB SQL and obtain TV1, TV2, TV3, TV5 ACKs under inter-phase change control. Required tests remain `NOT_RUN`; no data-layer ownership or ADR contract is silently changed.

## 2.4. Approved `P2C-OPEN-04` - quiescent Worker public-key rotation

**Decision (2026-11-07): `P2C-OPEN-04 = APPROVED_DESIGN` - Option B (quiescent rotation).** The owner selected a simple planned-rotation policy for the simulation MVP: **do not retire/replace active key K1 while the same Worker has any related Job/Attempt in `RUNNING` state**. Wait for those attempts to reach a committed terminal state or the approved deadline fallback; then use controlled provisioning to retire K1 and activate K2. This policy adds **no key-management UI, additional service, or database table**, and is **not a coding authorization**.

**Pre-existing, binding security requirements (ADR-004 + Database Design):**

1. Resolve the verifier public key strictly by persisted `(worker_id, key_id)`, validating ownership against the Job/Listing/Attempt. Do not allow an untrusted callback to select an arbitrary public key as authority.
2. Keep the original K1 public-key row and its 32-byte raw key for historical V1 verification whenever any retained accepted `signed_results`/open-dispute evidence refers to it. The accepted signed payload and signature remain immutable; `signed_results` key FKs and `RESTRICT` deletion protect the reference. No Worker private signing key belongs in the application database or tracked repository.
3. A V1 receipt with a valid historical signature is not automatically a *newly admissible* receipt: Inbox admission time, Job RUNNING state, attempt identity and finalization must still pass the existing ADR-003/004/005 gates. A retained already accepted receipt must remain independently verifiable even after K1 retirement.
4. A forged Worker `finished_at` is **not** evidence of when a key was used and must not override trusted database times.

**Planned rotation protocol (design, SQL/locking NOT YET APPROVED):**

- Before retiring K1, verify using trusted committed DB state that the Worker has **no related RUNNING Job/Attempt**. The check and activation must coordinate with concurrent `TX-ALLOCATE` and Simulator signing so that a new attempt cannot be dispatched using a stale K1 after K2 takes effect. A read-then-update without appropriate serialization **is not sufficient**.
- Retire K1 and make K2 the sole active key via controlled provisioning that preserves the at-most-one-active-key invariant. Future execution/callbacks use K2; any already retained K1 evidence is verified with archived K1. Exact SQL, transaction lock order, runtime key refresh and provisioning ownership require **TV1/TV2/TV3/TV4/TV5 technical ACK** before coding.
- When a callback was durably stored before K1's permitted retirement but processed later, the finalizer still verifies its stored exact bytes with K1 under current Job/Attempt/Inbox context. Normal rotation must not reclassify a previously admitted valid candidate as an invalid signature simply because K1 is now retired.
- If a private signing key is suspected compromised, **stop the normal rotation procedure and fail closed** while the security owner and team lead approve an incident response. Do not promise that waiting for all RUNNING Jobs is safe in a compromise. Incident revocation, in-flight handling and recovery are **OPEN / NOT AUTHORIZED**, not inferred from this decision.

**Mandatory negative/compatibility tests — designs only, `NOT_RUN`:**

| Test | PASS oracle |
|---|---|
| `P2C-KEY-01` | A registered active public key validates the correct V1 signed claim; no private key is read from DB |
| `P2C-KEY-02` | Wrong Worker/key ID, unregistered key or forged callback-provided key is rejected |
| `P2C-KEY-03` | An accepted K1 receipt still verifies from archived K1 after K2 becomes active |
| `P2C-KEY-04` | A key referenced by retained accepted evidence cannot be deleted; no accepted raw evidence is rewritten |
| `P2C-KEY-05` | On-time Inbox committed with K1, Manager delayed until after permitted rotation: verification uses K1 and follows normal finalization invariants |
| `P2C-KEY-06` | Planned retirement is refused while a related Job/Attempt is RUNNING; once terminal, K2 activation is consistent |
| `P2C-KEY-07` | Rotation racing a new allocation/dispatch cannot produce an ambiguous/stale key binding; implementation must demonstrate race-safe serialization |
| `P2C-KEY-08` | Forged Worker `finished_at` cannot evade key rules; no private keys, service tokens or protected oracle leak to logs/HTTP |
| `P2C-KEY-09` | Suspected compromise does not silently continue normal rotation or accept new use of the suspected key; the exception stays blocked pending incident policy |

**Required human handoffs:** TV2 confirms physical public-key FK/uniqueness and provisioning transaction; TV3 confirms verifier and key-selection semantics; TV4 confirms allocation concurrency; TV5 confirms Simulator key activation, retry and signing behavior; TV1 confirms Manager orchestration and Compose boundary. Under the inter-phase change-control rule, source owner and every affected downstream owner ACK real interface/contract changes. No such ACK or executed test is claimed here.

## 2.5. Phase 2C acceptance and conditional-approval gate (P2C-GATE-01 APPROVED_CONDITIONAL)

**Decision (2026-11-07): `P2C-GATE-01 = APPROVED_DESIGN_CONDITIONAL` (Option A).** The team lead accepts the Phase 2C architecture and design ownership: independent strict V1 parser/Ed25519 verifier (`P2C-DEC-01`), existing API listener with direction-scoped Bearer protection (`P2C-OPEN-02`), PostgreSQL-authoritative exact-byte callback replay handling (`P2C-OPEN-03`), and planned quiescent key rotation preserving historical verification (`P2C-OPEN-04`). **This is not implementation approval, inter-phase ACK, code merge authorization, or executed test evidence.** All unresolved technical and security gates remain `PENDING`. Continue design review at **Phase 2D**; Phase 2C design can be revisited if a downstream contract requires change-control.

The following are **design acceptance requirements** for later implementation, **not PASS claims**. The conditional approval freezes the reviewed direction while retaining unresolved details as explicit `PENDING` gates:

| Gate | Required observable evidence | Owner coordination |
|---|---|---|
| `P2C-ACC-01` | Only the correct direction-scoped 256-bit-or-stronger Bearer authorizes each internal route; missing/wrong/end-user JWT/opposite token is rejected before effect | TV3, TV1, TV5 |
| `P2C-ACC-02` | Strict V1 parsing and RFC 8785 JCS + Ed25519 verification match ADR-004 public test vector across runtimes; reject malformed/extra/duplicate JSON keys | TV3, TV5 |
| `P2C-ACC-03` | Valid cryptography with wrong Job/Worker/Listing/Attempt/key is rejected; no premature finalization; verified signed claim is not oracle truth | TV3, TV2, TV5 |
| `P2C-ACC-04` | PostgreSQL exact-byte duplicate `202` vs changed-byte collision `409`, including concurrent callbacks and post-terminal replay | TV2, TV3, TV5 |
| `P2C-ACC-05` | On-time Inbox candidate remains eligible after delayed processing; callback received at/after hard deadline is rejected | TV2, TV3, TV1, TV5 |
| `P2C-ACC-06` | Historical K1 public key verifies retained evidence after normal K2 rotation, and forbidden key deletion is blocked | TV2, TV3, TV5 |
| `P2C-ACC-07` | Planned rotation cannot race with RUNNING jobs or new allocation; incident compromise route fails closed pending a separately approved policy | TV1, TV2, TV3, TV4, TV5 |
| `P2C-ACC-08` | No signing private key, service Bearer, protected reference or unredacted sensitive envelope leaks through logs, API projections, config or Simulator DB access | TV1, TV2, TV3, TV5 |
| `P2C-ACC-09` | Manager finalization after verifier passes performs one terminal transition, one GPU release and at most one reputation contribution even under replay/crash | TV1, TV2, TV3, TV5 |

**Evidence policy:** relevant `WIRE-*`, `SIG-*`, `AUTH-*`, `API-INT-*`, `COM-*`, `P2C-REPLAY-*` and `P2C-KEY-*` test plans remain `NOT_RUN` until there is executable code, test fixture, DB revision, commit SHA and real results. Do not infer implementation success from documentation. A separate future coding authorization and Phase 1 baseline acceptance are required.

**Open before implementation:** (i) exact verifier/result typed interface and owner ACKs; (ii) exact DB key-rotation lock/provisioning transaction and runtime key refresh; (iii) concrete secret-injection/ingress protection in Compose; (iv) emergency compromise runbook; (v) integration evidence. None changes frozen ADR-004 V1 bytes or introduces another database table.

**Recorded historical gate:** `P2C-GATE-01 = APPROVED_DESIGN_CONDITIONAL`. Current review step: **owner review of Phase 2C v0.9**, after conditional reviews of Phase 2A v0.9 and Phase 2B v1.3; Phase 2D follows only if the owner accepts this revision. Do not begin Phase 2 implementation until separate authorization, Phase 1 acceptance and requisite human ACKs.

## 3. Accepted V1 receipt semantics

- Payload has **exactly eleven signed fields** under ADR-004: `schema_version`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at`, `key_id`.
- The verifier uses RFC 8785 JCS and UTF-8 bytes prefixed by `GPU-MARKETPLACE:SIGNED-RESULT:V1\n`, then Ed25519 against the registered Worker `(worker_id, key_id)` public key. Preserve strict UUIDv4, timestamp, digest and signature encodings and reject missing/extra/duplicate keys.
- `SUCCESS` requires `failure_reason=null`; `FAILED` permits only `WORKER_FAULT` or `JOB_FAULT`. `SYSTEM_FAULT` is Manager-owned without a Worker signature and contributes no negative reputation.
- Verify **both** cryptography and persisted Job/Attempt/Worker/Listing context; retain original signed payload/signature evidence. An authentic signature confirms who signed a claim, not whether it agrees with protected ground truth.
- Simulator owns the private signing key and must not receive `simulation_references` or other protected oracle fields.

## 4. Ingress and verification boundary

1. API authenticates the dedicated callback token, binds an existing `RUNNING` Job/Attempt under Listing-before-Job locks, obtains trusted time **after** locks, and persists original raw bytes into `result_inbox`.
2. Admit a new candidate only if `received_at < hard_deadline_at`; identical retry preserves original time; changed bytes under same ID are a conflict.
3. HTTP `202` means **durable ingress**, never signature acceptance, terminal Job state, GPU release or reputation update.
4. Manager separately consumes Inbox, verifies signature/context and makes result-acceptance decision; finalizer (Phase 2E design) controls the atomic terminal/release/contribution transaction.
5. Invalid on-time messages become rejected candidates. Do not declare immediate Worker failure; wait for another valid candidate or approved deadline fallback.

## 5. Tests, dependencies and unresolved gates

- Design tests `WIRE-01..07`, `ENUM-01..06`, `DBTX-08..11`, including duplicate JSON keys, invalid JCS, signed payload mutation, unknown/retired keys, wrong direction Bearer, wrong Job/Attempt/Worker, original-byte replay and exact deadline.
- TV2 must confirm Inbox, original-byte handling and public-key constraints; TV5 must confirm finalization/reputation compatibility; TV1 confirms service topology and diagnostic redaction.
- **Status alignment (2026-11-07):** GPU-005-B public `demo-v1-public1` algorithm, nine-field mock output, V1–V4 fixtures and version/least-privilege policy were conditionally approved **in the local Phase 2E design package** (`P2E-GPU005B-GATE-01` and `P2E-GATE-01`). GitHub PR #39 approves only Phase 1 protected-reference creation; Phase 2 Simulator/output compatibility has **not** been synchronized into GitHub or tested. TV3 must preserve ADR-004 V1 signed payload and should not implement the reference generator inside authentication.
- **Docs exit:** signed-receipt and ingress matrices with concrete negative-test design and owner ACKs. **Runtime status:** `NOT_RUN`.

## Approved design references

- [SRS](../../requirements.md), [FR](../../functional-requirements.md), [NFR](../../non-functional-requirements.md).
- [System Architecture](../system-architecture.md), [Module Design](../../design/module-design.md), [Database Design](../../design/database-design.md), [API Contract](../../design/api-contract.md), [Test Design](../../design/test-design.md).
- [ADR-001 to ADR-008](../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), ADR-004 (signed result) and ADR-005 (retries and deadlines).
- [Phase 1E](phase1e_job_submission_queue.md), [GPU-005-B reference proposal](phase1e_gpu005_reference_technical_specification.md), [Phase 2 readiness](../../development/phase2_readiness_and_handoffs.md), [Phase 2 decisions](../../development/phase2_decision_register.md) and [Phase 2 test plan](../../design/phase2_test_and_acceptance_plan.md).

Only the existing approved baselines are normative. This Phase 2C work package has **conditional design approval only**; unresolved technical interfaces and gates remain pending. Other work packages are reviewed separately. This document does not execute any Phase 2 tests (`NOT_RUN`).

## Appendix PR39-C (2026-11-07): Security, signer provisioning and typed verification

**Status:** `DESIGN-SUPPLEMENT / SIGNER PROVISIONING CONTRACT PENDING ACK / NO CODE AUTHORIZED`.

### C1. Phase 1 baseline vs Phase 2 trust

PR #39 wires user HS256 JWT and shared Auth principal. These tokens are **not** reusable as internal dispatch/callback authorization. Phase 2 retains independent `MANAGER_DISPATCH_TOKEN` and `SIMULATOR_CALLBACK_TOKEN` (at least 256 random bits each); using an end-user JWT or opposite-direction token must fail before Inbox writes. The chosen existing API listener for callback can be reached from the local host even when host-published on loopback; token checks are mandatory, and non-loopback deployment needs explicit ingress/TLS review.

### C2. Missing bootstrap contract: usable Worker Ed25519 keys

**Gap:** Phase 1 creates Worker profiles but does not by itself prove that every schedulable Worker has a registered active Ed25519 public key and an accessible Simulator private key. A simulator cannot produce a valid V1 receipt without that pair. Before first Phase 2 dispatch, TV2/TV3/TV5 must agree on a **trusted, non-UI, MVP key-provisioning procedure** that:

1. Generates private material only inside an untracked secret source accessible to the Simulator; does not store private keys in API, Manager, PostgreSQL, Git or logs.
2. Registers only `(worker_id,key_id,public_key_raw,registered_at,retired_at)` in existing `worker_public_keys`, with at most one active key per Worker.
3. Maps the dispatch `worker_id` to the locally available private key and matching registered `key_id`, with explicit startup/dispatch fail-closed behavior if missing/mismatched.
4. Ensures a Simulator restart can reload the key material needed for RUNNING attempts (no dependence on RAM-only signer existence).
5. Uses a controlled provisioning identity and DB privilege path; regular `gpm_api_app` request paths must not be able to replace public keys arbitrarily.

This is a **proposed handoff specification**, not a newly approved provisioning mechanism or authorization to add secret volumes/credentials. Normal rotation waits for related RUNNING work to quiesce, retains archived public keys, and resumes scheduling only after K2 availability is checked. Emergency compromise response is still explicitly open.

### C3. Typed verifier contract, proposed freeze for cross-owner ACK

`VerifiedV1Receipt` is an **internal, non-HTTP** immutable result containing at least: `inbox_row_id`, archived raw-envelope SHA-256 and stable evidence identity, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `key_id`, verified `outcome`, `failure_reason`, `result_digest` and verification scheme/version. It is produced only after strict 11-field V1 parse, fixed domain-prefixed RFC 8785/JCS canonicalization, Ed25519 verification against a trusted `(worker_id,key_id)` public key, and basic immutable contextual checks. It does not contain oracle fields, signing private material, or a mutable `verified=true` flag as sole authority.

`RejectedV1Receipt` contains `inbox_row_id`, non-secret stable rejection category, version/context diagnostics safe for logs and no business effect. Exact Python type names, error enums, producer/consumer path and resource limits remain `PENDING TV1/TV2/TV3/TV5 ACK`.

**Finalizer MUST re-read and validate committed Inbox evidence after Listing -> Job locks:** candidate identity/hash, admitted `received_at < hard_deadline_at`, same RUNNING Attempt, same Worker/Listing, no prior accepted result, applicable key, no terminal Job, and trusted DB clock. No raw callback data alone may trigger Finalization.

### C4. Negative-case evidence

- Strict JSON duplicate-key rejection, unexpected V1 fields, malformed UUIDv4/UTC timestamp, unpadded base64url signature, different domain prefix and altered claim.
- Unregistered/wrong Worker key; key rotation with delayed on-time Inbox and historical verification; fail-closed missing provisioning; explicit incident response hold.
- Exact-byte retained duplicate returns 202 even after terminal; same ID different bytes returns 409; a new ID is **not** the same duplicate and can be a second candidate for the same Job (controlled by Finalization uniqueness).
- Callback admission time is from DB after Job lock, never signed `finished_at`. Never compare `received_at` to deadline using an unlocked pre-read.

All Phase 2 cryptographic and HTTP runtime tests remain `NOT_RUN`. Existing Phase 1 CORS/Auth tests on #39 do not prove any Phase 2 callback authentication or signature verification.

---

## Appendix DR-C — Deep review v0.9: boundary, race, proof and rollout controls

> **Status of this appendix:** `DESIGN_REVIEW_SUPPLEMENT / PROPOSED_FOR_ACK`. It records corrections to documentation and specific implementation-review contracts. It neither replaces approved V1 bytes nor authorizes GitHub writes, migrations or Phase 2 coding. Security-affecting choices not already approved require TV1/TV2/TV3/TV4/TV5 ACK and, where normative, owner change control. All tests below: `NOT_RUN`.

### DR-C1. Source-of-truth and baseline status

| Subject | Correct 2026-11-07 statement | Evidence / remaining action |
|---|---|---|
| PR #39 | `OPEN / DRAFT`, reviewed head `44579ed846051dee9000078e1afd7e8ea62e7358`, base `1d8b1b2c52b759d99a072c3d0d889b375083a8c4` | [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39); four-job [Actions #42350954394](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42350954394) success pertains to **Phase 1** only |
| Phase 1 authentication | HS256 JWT with shared principal and browser-session path already wired in PR #39 | Do **not** reuse user JWT as internal Bearer or claim internal endpoint tests PASS |
| Existing Manager | `manager/service.py` is still the foundation idle runner; no Phase 2 verifier/consumer runtime exists at this head | Review implementation only after a separate coding gate |
| ADR-004 | Immutable V1 payload of exactly 11 fields, JCS RFC 8785, Ed25519, fixed domain prefix, fixed public signature vector | No implicit V2, additional payload fields or alternate wire encoding |
| GPU-005-B | The Phase 1 reference generator and vector checks exist in PR #39. Local Phase 2E approval of 9-field mock output/algorithm compatibility is conditional and **not yet reflected in GitHub** | Do not use PR #39 to claim Phase 2 runtime compatibility approval |
| Phase 2B | Deep-reviewed v1.3 proposals cover narrow raw Inbox reads, unique-conflict resolution, historical signer public keys and PostgreSQL-bound timestamps | Require actual TV2/TV3/TV5 interface ACK; no SQL execution yet |

### DR-C2. Strict callback input, authorization and replay: two distinct validation points

**API ingress: do only the work required to authenticate and safely store a candidate.** Authenticate the exact direction-scoped `SIMULATOR_CALLBACK_TOKEN` before any Inbox query that reveals records or any write. End-user JWT, opposite `MANAGER_DISPATCH_TOKEN`, missing/duplicate malformed Authorization headers and invalid Bearer values fail closed; errors/logs do not echo secrets. Enforce HTTP method/Content-Type, an explicitly bounded raw-body size and bounded parse depth/CPU cost (numerical budgets `PENDING TV1/TV3`). Use original received bytes for Inbox evidence and byte-identical replay comparison. Never serialize a parsed Pydantic/dict object and call those bytes the original envelope.

**Parse valid JSON strictly at both envelope/payload levels:** exactly three envelope keys `payload`, `signature`, `signature_encoding`; exactly 11 signed payload keys; reject duplicate object members *before* dict conversion, missing/extra fields, invalid JSON/I-JSON (including nonfinite numbers and invalid Unicode), wrongly typed fields and noncanonical UUIDv4/timestamp/base64url. A conforming RFC 8785 JCS implementation is needed for signing/verification; `json.dumps(sort_keys=True)` is not a general-purpose JCS substitute. `signature_encoding = "base64url-no-padding"` and 86 canonical ASCII Base64url characters must decode/re-encode to exactly 64 signature bytes.

**Ingestion must not pre-judge cryptography:** a well-formed, context-bound receipt can be stored with `202 STORED` even if its signature later fails. The API must not invent a `COMPLETED` or `FAILED` effect from `202`; Manager verifies later. Rejecting an invalid signature is a **Manager Inbox** processing outcome, not an instruction to penalize the Worker immediately. Response codes/meanings come from API Contract §13.2: wrong token `401`; malformed V1 envelope `422`; unknown Job `404` without cross-user leakage; new late/stale/terminal candidate `409`; same `result_id` changed original bytes `409`; committed new candidate or exact retained duplicate `202`.

**Replay lookup is scoped to the authenticated callback and retained trusted binding.** For an existing `result_id`, require same original raw bytes and same persisted binding/identity, then `202 DUPLICATE` even if its Job is now terminal; preserve the original `received_at`. Same ID with changed bytes yields `409 RESULT_ID_COLLISION`. If two inserts race, PostgreSQL UNIQUE decides the winner: the losing writer **rolls back** its UoW, opens a new read transaction and compares the committed winner's exact bytes and binding. The SHA-256 stored alongside the bytes is only a prefilter, never the sole equality oracle. A freshly received, different `result_id` is a separate candidate, not a replay.

**No false commit acknowledgment:** `202 STORED` is sent only after the Inbox COMMIT is known successful. For ambiguous COMMIT/connection loss, do not claim durable success, do not blindly retry mutations inside the same transaction and do not alter trusted admission time. The sender may retry the *same original bytes and `result_id`* and reconcile against committed PostgreSQL state. All new admission uses `clock_timestamp()` **after** Listing→Job locks and strictly tests `received_at < hard_deadline_at`; signed `finished_at` never overrides this.

### DR-C3. Trusted verifier and anti-TOCTOU finalization bridge

**Frozen cryptographic recipe:** `signed_bytes = b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n" + UTF8(JCS_RFC8785(payload))`. Here `\n` denotes the **single ASCII LF byte** in the actual prefix. Verify against a **trusted** registered 32-byte Ed25519 public key selected by persisted `(worker_id,key_id)` and the Job/Listing/Attempt binding, not a value supplied by the callback. This V1 is distinct from public simulation output `schema_version="demo-v1"`; the **Signed Result** value is `schema_version="1"`.

**Proposed immutable trust-boundary type (not yet frozen Python API):**

```text
VerifiedV1Receipt(
    inbox_row_id, envelope_sha256, result_id, job_id, attempt_id,
    worker_id, listing_id, key_id, outcome, failure_reason, result_digest,
    signed_schema_version='1', signed_payload_fingerprint
)
RejectedV1Receipt(inbox_row_id, rejection_code)
```

Only TV3's trusted verifier produces a `VerifiedV1Receipt` after signature, wire and registered-key checks. It must not be constructible from untrusted HTTP JSON as a sufficient authorization object. No raw signing private key, protected reference, direct SQLAlchemy Session, ORM-managed lock or mutable `verified=True` claim crosses the TV3→TV5 boundary. If verification happens outside the Finalizer transaction, its result is **provisional**: TV5 and TV2 must re-read the **committed** Inbox evidence after Listing→Job→Allocation→Inbox locks, compare candidate identity/hash and exact persisted binding, recheck `RUNNING`, immutable Attempt, `received_at < hard_deadline_at`, key eligibility, and prior accepted result. No network calls under these domain locks. If evidence/context diverges, no finalization or reputation update is allowed.

**Signature != oracle truth:** a signed but inaccurate `result_digest`, `outcome` or failure class remains a valid *signed claim* when wire, signature and context validate. It can be accepted once and later evaluated against the protected deterministic reference by the approved Phase 3 Dispute flow. TV3 must not query reference data or silently reject a cryptographically valid receipt only because the public mock oracle would differ. The approved `demo-v1-public1` reference is public/recomputable; it is not an anti-cheat guarantee or evidence of real GPU execution.

### DR-C4. Key registration, planned rotation and incident-response boundary

- **Provisioning gap:** Phase 1 Worker creation does **not** guarantee a usable Ed25519 signer per schedulable Worker. The MVP needs an explicitly trusted, non-UI provisioning procedure: generate/store only the private material in Simulator-accessible **untracked secret storage**, register `(worker_id,key_id,public_key_raw,registered_at,retired_at)` through a narrowly authorized DB role/function, prove each active public key maps to the private key used for dispatch. Never ship a Worker private key in dispatch JSON, API/Manager settings, public DTO, logs or Git. Missing/mismatched key => fail closed before dispatch/acceptance; automatic insecure default signing key is forbidden.
- **DB invariant:** preserve `worker_public_keys` PK `key_id`, `(worker_id,key_id)` association, 32-byte public key and `RESTRICT` historical FK for `signed_results`; the approved physical design proposes a partial UNIQUE for at most one `retired_at IS NULL` key/Worker. Exact DDL/GRANT/permission SQL remains TV2's responsibility; review it on native non-owner connections.
- **Planned K1→K2 rotation:** no related `RUNNING` Job/Attempt during retirement. Merely `SELECT no RUNNING` followed by independent UPDATE is **not race-safe**. The proposed runbook must coordinate pauses/admission of **all** affected Listings and `TX-ALLOCATE`, serialize the final no-RUNNING recheck and K2 activation with a compatible lock order, prove runtime Simulator reloads/pins K2, then resume admission. Guard the case where a new Listing is added/resumed mid-rotation. If a new Worker lock/operation would alter approved lock order or granted privileges, require explicit L2 design review instead of silently adding it.
- **Old K1 evidence:** retain public K1 while an accepted Signed Result or open-Dispute evidence may need it. Also verify any already committed on-time K1 Inbox after Manager delay/rotation; do **not** reject merely because `retired_at` is set by the time the Manager processes it. Signer private-key durability across Simulator restarts and Worker→key mapping must be tested separately.
- **Suspected private-key compromise:** quiescent planned rotation is **not** an emergency incident response. Fail closed on new use and record the security hold; do not decide silently whether already-received signed candidates are trustworthy, how RUNNING work resolves, or how affected references/evidence are retained. Those are `OPEN_SECURITY_POLICY / NEEDS_OWNER_DECISION`. Do not introduce a third credential/token meaning or a key-management service without approval.

### DR-C5. Multiple result IDs, ordering, deadline and reconciliation

- The same logical `attempt_id` and one durable Outbox event may yield **multiple different** `result_id` after a cold Simulator restart. Accept each *new* correctly bound and on-time candidate into durable Inbox while Job remains RUNNING. Do not treat different IDs as exact replay and do not assume an in-memory Simulator cache survives a crash.
- Manager must process eligible committed on-time candidates in deterministic `(received_at, result_inbox.id)` order. Invalid candidates become `REJECTED` with a stable redacted reason; first cryptographically valid and context-eligible candidate wins `signed_results` with `UNIQUE(job_id)`, then TV5's one atomic Finalization releases GPUs and records the eligible contribution. Later candidates cause **zero** extra business effects. The exact terminal/non-winning Inbox status (from existing `PENDING/ACCEPTED/REJECTED`) and bounded cleanup behavior are `PENDING TV1/TV2/TV3/TV5 ACK`, not auto-approved.
- Before a deadline fallback to `FAILED/SYSTEM_FAULT`, examine **every** committed Inbox candidate admitted `received_at < hard_deadline_at`, including those in subsequent batches or delayed after restart. A fixed page cap cannot silently hide a later valid candidate. `received_at == hard_deadline_at` is late. Race-safety requires a Listing→Job lock, fresh `READ COMMITTED` lookup after lock, and never holding an Inbox lock before acquiring Listing/Job. The boundary test must prove callback-first and fallback-first commit orders.
- Keep fault isolation: a malformed callback/token issue must not crash the Manager supervisor as a database-corrupt condition; an actual invalid schema/privilege/key trust invariant at startup or verification boundary must fail closed with appropriate supervised escalation. Exact fault taxonomy and bounded concurrency are `PENDING TV1/TV3`.

### DR-C6. Deployment, native DB ACL and test evidence

**Current API listener is host-reachable from local loopback.** Serving `/internal/v1/results/callback` on it is approved for the local single-host MVP but its path is not network-private merely because the word `internal` appears in the URL. A browser or local process must not bypass `SIMULATOR_CALLBACK_TOKEN`, even if CORS differs; CORS is not an authentication boundary. Non-loopback exposure requires explicit ingress restrictions and separate transport-encryption/security approval. Manager and Simulator stay separate processes inside the existing five-service Compose topology.

**PostgreSQL privileges:** API needs narrowly authorized insert/duplicate-check behavior; Manager needs trusted persisted Inbox/public-key reads and controlled accepted-result inserts; Simulator has **no SQL identity**. PostgreSQL column-level SELECT is not a per-row security policy: choose and review a narrowly scoped function/role boundary or an explicit least-privilege read design, test against real native `gpm_api_app`/`gpm_manager_app` sessions. The Phase 1 reference grants do not imply arbitrary new Phase 2 read or write access. Avoid raw envelope/oracle in audit metadata.

**Repeatable test environment:** use safety-marked disposable PostgreSQL 16 with safe role-password teardown. PR #39 full browser+HTTP+PostgreSQL and four green CI jobs are **Phase 1 evidence**, not `P2C-NET`, `SIG`, `WIRE`, `P2C-REPLAY` or `P2C-KEY` execution. PR #42 is stacked on #39; its future merge may change the accepted integration baseline. After coding permission, cross-runtime signer/verifier tests, actual signed callback HTTP/DB, crash barriers and key rotation races must record exact Git SHA, schema revision and CI run; skipped/blocked tests are not PASS.

### DR-C7. Explicit cross-owner interface gates (all `PENDING_ACK`)

| ID | Must agree on before relevant implementation | Owners |
|---|---|---|
| `C-IF-01` | Exact Bearer provisioning, direction separation, refusal of JWT/opposite token and missing-secret startup semantics | TV1 + TV3 + TV5 |
| `C-IF-02` | Callback raw-body size/depth limits, duplicate-key parser, `Content-Type`, HTTP responses, log redaction | TV1 + TV3 + TV5 |
| `C-IF-03` | Narrow DB read/compare of original Inbox bytes, unique-collision retry and commitment/unknown-commit handling | TV2 + TV3 + TV5 |
| `C-IF-04` | Trusted DB admission clock after Listing→Job locks, original timestamp on replay, exact-deadline cutoff | TV1 + TV2 + TV3 |
| `C-IF-05` | RFC8785/Ed25519 cross-language fixture, registered-key binding, strict V1 verifier API | TV2 + TV3 + TV5 |
| `C-IF-06` | Immutable `VerifiedV1Receipt`/`RejectedV1Receipt`, evidence recheck and provenance in Finalizer UoW | TV1 + TV2 + TV3 + TV5 |
| `C-IF-07` | One active Worker public key, private signer provisioning, restart reload and missing-key fail closed | TV1 + TV2 + TV3 + TV5 |
| `C-IF-08` | Quiescent key rotation serialized with new Listing allocation and historical key read | TV1 + TV2 + TV3 + TV4 + TV5 |
| `C-IF-09` | Emergency compromise incident disposition; no implicit revocation, deletion, acceptance or automatic rotation | TV1 + TV3 + TV5; owner L2 if changing normative rules |
| `C-IF-10` | Multi-result-id Inbox ordering/nonwinner handling, after-deadline recovery, test crash barriers | TV1 + TV2 + TV3 + TV5 |
| `C-IF-11` | Phase 1 accepted `main` + Alembic head/roles, PR #42 impact, Phase 2 code authorization | TV1 + TV2 + TV3 |

### DR-C8. Future executable verification checklist (all `NOT_RUN`)

| Test ID | Setup/action | Binary PASS oracle |
|---|---|---|
| `P2C-DRT-01` | Correct vs missing, opposite-direction, user JWT and malformed callback Bearer | Only right-direction token can store Inbox; wrong input `401`, no DB mutation/leak |
| `P2C-DRT-02` | Send duplicate/extra envelope and payload fields, invalid I-JSON, non-v4 UUID, malformed timestamps | Every invalid V1 input rejected with `422`, no eligible Inbox or business effects |
| `P2C-DRT-03` | Test fixed ADR-004 Ed25519 vector in two conformant language runtimes | Identical JCS/domain-prefix signing bytes; exactly matched signature verification; tampered negative fixtures fail |
| `P2C-DRT-04` | Same `result_id`, identical raw bytes after job terminal | `202 DUPLICATE`, unchanged `received_at`, 1 retained Inbox evidence row |
| `P2C-DRT-05` | Same `result_id`, bytes changed only by JSON whitespace/member order | `409 RESULT_ID_COLLISION`; original immutable raw bytes stay byte-identical |
| `P2C-DRT-06` | Two independent concurrent clients race same `result_id` with identical/different bytes | UNIQUE winner; losing TX rollback/re-read; identical returns `202`, changed returns `409`, no second persisted row |
| `P2C-DRT-07` | Callback HTTP ack lost after COMMIT; repeat exact request with same ID | Recovered as duplicate, no fabricated success before DB commit or changed admission time |
| `P2C-DRT-08` | Well-formed but wrong Ed25519 signature delivered before deadline | API `202 STORED` then Manager `REJECTED`; no finalization, release or reputation effect |
| `P2C-DRT-09` | Valid signature from incorrect Worker/Listing/Job/Attempt or unknown key ID | Manager rejects bound-context mismatch; no accepted `signed_results`, terminal Job or counter mutation |
| `P2C-DRT-10` | Callback admitted at `deadline-1µs`, at deadline, and processing delayed past deadline | First eligible despite delay; equality rejected; if eligible valid receipt exists, no false SYSTEM_FAULT |
| `P2C-DRT-11` | K1 retired after RUNNING drained; retained accepted/on-time Inbox K1 receipts | Historical verification succeeds; `RESTRICT` refuses deletion while referenced; new dispatch uses K2 |
| `P2C-DRT-12` | Rotate K1→K2 racing new allocation/Listings resume + cold Simulator restart | No worker scheduled without matching active private/public key; no ambiguous signer, safe serialization |
| `P2C-DRT-13` | Two distinct valid `result_id` on one Attempt, including cold restart | First eligible ordered candidate commits once; other no extra effect; Inbox state eventually bounded/reconciled |
| `P2C-DRT-14` | Compromised/missing key, absent service secret, and non-loopback callback exposure policy | Fail closed and surface blocked policy; never log signer/token; no unauthorized receipt accepted |
| `P2C-DRT-15` | Valid Ed25519 signature with digest/outcome different from public deterministic reference | Verifier recognizes signed claim; does not assert oracle truth or update reputation by itself; later comparison is separate |
| `P2C-DRT-16` | Over-limit body, deeply nested/expensive JSON, and multi-batch Inbox backlog | Bounded parser/CPU; no 2xx for uncommitted data; no false deadline fallback from hidden valid candidates |
| `P2C-DRT-17` | Real native `gpm_api_app`, `gpm_manager_app` SQL privileges + Simulator network isolation | Only least-privilege Inbox/public-key paths succeed; no SQL credential/access in Simulator |
| `P2C-DRT-18` | Crash before/after finalizer COMMIT, retry same/different callback ID | Exactly one signed result, one GPU release and eligible contribution, even after restart |

**Implementation gates (not fulfilled by this document):** normative cross-owner ACK (`C-IF-*`), exact SQL permissions, registered signer provisioning, incident disposition, accepted Phase 1 baseline, separate team-lead code authorization, real PostgreSQL/HTTP/Compose/fault-injection results and independent human review before merge. `P2C-GATE-01` remains conditional design approval; **v0.9 addendum is not yet owner-approved**.
