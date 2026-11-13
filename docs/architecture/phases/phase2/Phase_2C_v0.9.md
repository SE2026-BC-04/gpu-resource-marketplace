# Phase 2C - Internal Authentication and Signed Result Verification (TV3)

> **Current review snapshot (2026-11-08):** Phase 1 PR #39 is merged; accepted `main` is `bee832eaf5463df20f6c6815174322871eb6685a` (see DR-C1). This revision is **SELF_REVIEWED / AWAITING_CROSS_REVIEW**: it corrects stale baseline text and links and records the TV3 self-review in §6. It is not an owner/consumer ACK or a coding authorization. The 2026-11-07 deep review (Appendix DR-C) stays `PROPOSED_FOR_ACK`.
>
> **Cross-review revision (2026-11-09):** answers TV5's review of PR #49 (Q1–Q8) and aligns with TV2 PR #46 @ `342497c` and TV3's reviews on #46, #47 and #50. New §6.6 proposes the frozen verdict contract, rejection-code enum, verification location and key-rotation sequence; §6.7 lists two **conditional errata** to approved text that apply only if the lead decides `D-01`/`D-02`. Everything new is `PROPOSED_FOR_ACK`.
>
> **TV2 follow-up (2026-11-09, second revision):** adopts TV2's review of this PR at `942383f` and #46 @ `f315400`: per-Worker advisory lock first in the lock order, rotation gated at `TX-ALLOCATE` with `Blocked(SIGNER_NOT_READY)`, four-step K1→K2 sequence (§6.4, §6.6.5), V-IN constraints (§6.6.4). The two-active-rows quiesce marker conflicts with approved §2.4 wording, so it is a third conditional erratum `E-C3` (§6.7) for the lead.
>
> **TV5 follow-up (2026-11-09, third revision):** answers TV5's re-review at `942383f`: Q1 wording (known duplicate vs reconciled unknown commit, §6.2), parser drift is never a definitive rejection after admission (§6.6.2–6.6.3), TV3 now accepts **V-OUT** (verify outside the domain locks, locked recheck by TV2) with V-IN as fallback (§6.6.4) and erratum `E-C4` for the approved `TX-FINALIZE` pseudo-code, and the rotation fence / signer-ready points (§6.6.5).
>
> **D-18 sync (2026-11-10, fourth revision):** aligned with #46 @ `8d57bec` (D-18) and TV5's review of #46 @ `84fe452`: exact `{K1, K2}` recheck and abort that restores K1 (§6.6.5 item 6), and a **live-signer gate** with two options for the lead, G1 proof of possession (needs an internal endpoint, change control) or G2 dispatch refusal (§6.6.5 item 9).
>
> **Enum sync (2026-11-10):** the rejection-code enum is now the four post-admission verifier codes only; `INVALID_STRUCTURE` / `UNSUPPORTED_SCHEMA_VERSION` removed, matching #46 @ `1bfb864` (§6.6.2).
>
> **TV5 A–C (2026-11-13, fifth revision):** answers TV5's review of this PR at `9b337f5` (actions A–C on the live-signer gate, §6.6.5 item 9), aligned with TV2's #46 @ `ba63466`: (A) the proof identity `SignerReadiness(worker_id, key_id, public_key_fingerprint, proof_expires_at)` is bound to the sole active key under the locks (allocation predicate owned by TV2); (B) G2 cannot satisfy "unknown ⇒ not ready" after a Manager restart without an explicit bootstrap exception, so TV3 and TV5 both prefer G1; (C) startup self-check scope, proposed proof wire encoding, and tests `P2C-SIGN-07/08`. Everything new is `PROPOSED_FOR_ACK`, TTL and timeouts stay `PENDING_PARAMS`, all tests `NOT_RUN`.
>
> **Fingerprint sync (2026-11-13):** SHA-256 over `public_key_raw`, matching #46 @ `531805b` (§6.6.5 item 9).

> **Repository:** `SE2026-BC-04/gpu-resource-marketplace`  
> **Document version:** `v0.9-docs-review-20261109` (stable filename retained; inherited `P2C-GATE-01 = APPROVED_DESIGN_CONDITIONAL`), updated 2026-11-09  
> **Status:** `APPROVED_DESIGN_CONDITIONAL / DOCUMENTATION_ONLY / NOT_APPROVED_FOR_IMPLEMENTATION` (owner-approved P2C-GATE-01; technical prerequisites below remain `PENDING`)  
> **Important:** These five Phase 2A-2E files are *design work packages for five team members*. Assignment below proposes documentation ownership; it does not approve new implementation rights, modify the architectural ownership of API/Manager/Simulator, or authorize coding.  
> **Phase 2 start gate (team process, 2026-11-08):** self-review and revise design → docs PR into `main` and cross-review → leader decision and merge of the docs → code one task = one branch = one PR. No Phase 2 code before the docs and the dependencies a task needs are approved.

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

*(2026-11-09: two sentences of this approved section, the SHA-256 "prefilter" and the "loser must roll back", have proposed conditional errata `E-C1`/`E-C2` in §6.7. They take effect only after the lead decides #46 `D-01`/`D-02`; until then the text above stands.)*

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

**Recorded historical gate:** `P2C-GATE-01 = APPROVED_DESIGN_CONDITIONAL`. **Current review step (2026-11-08):** docs-first cross-review of this file and the TV3 handoff (§6), in parallel with the Phase 2A/2B/2D/2E docs PRs. Phase 1 acceptance on `main` is done (#39 merged). Do not begin Phase 2 implementation until the docs are approved and merged by the leader and the dependencies of the specific task are ACKed.

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

## 6. TV3 self-review and docs-first delivery (2026-11-08)

**Workflow (team process notice 2026-11-08):** self-review → branch `docs/phase2c-tv3-design` → docs PR into `main` → cross-review (priority pairs **TV2 ↔ TV3** callback/Inbox and **TV3 ↔ TV5** Ed25519/Signed Result/Simulator; TV1 checks compatibility) → corrections → leader decision and merge → code **one task = one branch = one PR** from the latest `main`. No self-merge, no push to `main`.

**Method:** this file and the TV3 handoff were compared with API Contract §13.2–13.3, ADR-004 §§3.2–3.4, ADR-005 §2.1 and the token rules, Database Design §§5, 12, 11.3 (`TX-INBOX-INGRESS`, `TX-FINALIZE`) and the TV2 pre-code proposals in #46 @ `517942f` (`INBOX_DUPLICATE_PRIVILEGES.md`, `P2B_UOW_INTERFACES.md`, `OPEN_DECISION_REGISTER.md`). Documentation comparison only; no code or test was run.

### 6.1. Self-review findings and corrections in this revision

| ID | Finding | Correction in this revision | Still needs |
|---|---|---|---|
| `S-01` | Stale baseline: #39 described as an unmerged Draft; #42 as a future change | Header, §2.5 and DR-C1/DR-C6 updated to `main@bee832e`, #39 merge `aff538f`, Alembic head `0005_listing_d7` | TV1 confirms the baseline |
| `S-02` | 14 relative links broken after the move into `phase2/`; three referenced files do not exist | Links repaired; absent files named as absent | — |
| `S-03` | ADR-004 §3.3 V1 JSON Schema (accepted) was not cited as the parser's normative reference | Cited in the references; the strict parser must enforce it **plus** duplicate-member rejection before dict conversion, which a JSON Schema validator cannot see | TV5 confirms the signer emits schema-valid envelopes |
| `S-04` | Handoff prescribed one branch for the whole TV3 work | Handoff §5/§9 aligned with one task = one branch = one PR | TV1 confirms |
| `S-05` | HTTP error names differ across sources: API Contract §13.2 says `409 RESULT_ID_COLLISION` and `404 RESULT_CONTEXT_NOT_FOUND`; Database Design pseudocode says `RESULT_ID_CONFLICT`/`LATE_RECEIPT`; #46 `B-IF-02` writes `409 RESULT_ID_CONFLICT` and maps `Ineligible` to "no row, redacted log" without an HTTP status | Mapping proposed in §6.2; the **API Contract names are normative** for HTTP; DB/port names stay internal | TV2 aligns `B-IF-02` text; TV5 confirms sender handling |
| `S-06` | No callback body bound exists in API Contract §13.2; #46 `D-07` asks TV3 for the maximum size | Proposal in §6.3 (no new HTTP status) | TV1 + TV5 ACK (`C-IF-02`) |
| `S-07` | Whether 401/404/409/422 paths store an unbound REJECTED Inbox row is unclear: Database Design allows retained rejected rows and an unbound purge, the API path does not need them; #46 `D-08` | TV3 position in §6.3 | TV5 ACK; TV2 records in `D-08` |
| `S-08` | Duplicate detection: DR-C2 here says SHA-256 is "only a prefilter, never the sole equality oracle"; #46 `D-01` asks the lead to accept SHA-256 equality with a stored-hash CHECK | TV3 security input in §6.3; DR-C2 text is **not** changed until the lead decides | Lead decides `D-01` |
| `S-09` | Where the signature is verified: Database Design `TX-FINALIZE` verifies inside the finalize UoW; DR-C3 allows provisional verification outside it | Clarified in §6.3: both are compatible because the verifier is pure CPU on bounded bytes. 2026-11-09: TV3 first preferred inside the UoW; third revision: TV3 accepts **V-OUT** with TV2's locked recheck, V-IN kept as fallback (§6.6.4, erratum `E-C4`) | TV1 + TV5 ACK (`C-IF-06`) |
| `S-10` | Database Design table 5 lists `worker_public_keys` as "Registry / API provision", while Appendix C2 requires a controlled provisioning identity that the `gpm_api_app` request path cannot use | Recorded as a question; no grant chosen here. 2026-11-09 correction (TV5): this is **not** #46 `D-12` (which is about `worker_reputation_aggregates` rows); key provisioning is tracked with #46 `D-03` / `C-IF-07` | TV2 + lead name the provisioning identity |
| `S-11` | Signer readiness used by TV4 `TX-ALLOCATE` (`D-IF-07`) had no TV3 proposal | Proposal in §6.4 | TV2 + TV4 + TV5 ACK (`C-IF-07/08`) |

### 6.2. Proposed callback outcome mapping (`C-IF-02`, `C-IF-03`; `PROPOSED_FOR_ACK`)

HTTP names come from API Contract §13.2 and are not changed. Port names are TV2's `B-IF-02` proposal.

| Stage | Condition | Port result (TV2) | HTTP (API Contract §13.2) | Inbox row |
|---|---|---|---|---|
| Before UoW (TV3) | Missing, malformed, wrong-direction or end-user token | — | `401` | none |
| Before UoW (TV3) | Body over bound, wrong `Content-Type`, invalid UTF-8/JSON, duplicate member, schema or wire-format violation | — | `422 INVALID_SIGNED_ENVELOPE` | none |
| In UoW | Same `result_id`, identical bytes and bound context | `ExactDuplicate` | `202 DUPLICATE` | none new; original `received_at` |
| In UoW | Same `result_id`, different bytes or context | `Collision` | `409 RESULT_ID_COLLISION` | none |
| In UoW | Claimed Job/Attempt unknown or not bindable | `Ineligible(unbound)` | `404 RESULT_CONTEXT_NOT_FOUND` | none |
| In UoW | Job not `RUNNING`, stale attempt, or `received_at >= hard_deadline_at` | `Ineligible(not_running \| late)` | `409 RESULT_NOT_ACCEPTABLE` | none |
| In UoW | New, bound, on-time candidate committed | `Stored` | `202 STORED` | one `PENDING` row |
| Commit | Outcome unknown, reconcile probe (new transaction) says `SAME` | `CommitOutcomeUnknown` → reconcile | `202 STORED` (see note) | the committed row; no write by the reconcile |
| Commit / DB | Outcome unknown and not reconciled, or DB unavailable | `CommitOutcomeUnknown` / `DependencyUnavailable` | `503` (no false durable success; ADR-005 retry) | unknown → sender retries the same bytes |

A schema-valid envelope with a wrong Ed25519 signature is **not** rejected at ingress (`202 STORED`, later `REJECTED` by the Manager), as already approved.

**Note on the reconciled row (TV5 Q1, 2026-11-09):** after an unknown commit the probe can only tell that a row with the same `result_id`, same bytes and same bound context exists; it cannot tell whether this request's own insert or an identical concurrent retry wrote it, and the difference has no observable effect. The response is therefore `202` with `receipt_status = STORED`: the receipt sent in this request is durable. The rule is the **kind of evidence**, not whether the probe ran before or after an insert (corrected after TV5's re-review at `942383f`):
- **Known duplicate → `DUPLICATE`.** Inside the UoW the request learns, without ambiguity, that another row already holds this `result_id`: either the pre-insert probe answers `SAME`, or the target-less `ON CONFLICT DO NOTHING` returns zero rows and the post-attempt fresh probe answers `SAME` (#46 `B-IF-02` `ExactDuplicate`). This includes a retained exact replay after the Job is terminal; `received_at` never changes.
- **Ambiguous commit reconciled → `STORED`.** The COMMIT outcome is unknown and a probe in a new transaction answers `SAME`. This states durability only, not which caller inserted the row.

The reconcile writes nothing. `ABSENT` (after a suppressed conflict or after an unknown commit) → `503`, never `202`.

### 6.3. TV3 positions on open questions (proposals, not decisions)

1. **Body bound (`S-06`, #46 `D-07`).** A V1 envelope is a fixed 3-key object around an 11-field payload, depth 2, a few hundred bytes. Proposal: reuse the Phase 1 approved mechanism (declared and streamed byte count, strict parser) with **16,384 raw bytes inclusive** and **at most 4 object/array levels counting the root**, and map every bound or parse failure to the existing `422 INVALID_SIGNED_ENVELOPE`. This needs **no API Contract change**: §13.2 already defines `422`, and §13.3 already tells the sender not to repeat an unchanged `422` payload. Using Phase 1's `413`/`400` instead would add callback statuses and requires change control. Values are `PROPOSED_FOR_ACK` by TV1 + TV5.
2. **Unbound rejected rows (`S-07`, #46 `D-08`).** Proposal: **no Inbox row** for `401`, `422`, `404` or `409`; a redacted structured log only (route, status, stable reason, request ID; never body, token or key). Reason: the Manager cannot use such rows, they add an API write path and retention work, and rejection is already deterministic from the response. `TX-UNBOUND-INBOX-PURGE` then stays a no-op safeguard. TV5 ACK needed.
3. **SHA-256 equality (`S-08`, #46 `D-01`).** Security input for the lead: with the API hashing the exact received bytes and a DB `CHECK` binding `envelope_sha256` to `original_envelope_raw`, a different body with the same SHA-256 would require a second-preimage attack, and the sender must already hold `SIMULATOR_CALLBACK_TOKEN`. TV3 therefore **does not object** to option C. If the lead accepts it, the DR-C2 sentence "the SHA-256 is only a prefilter, never the sole equality oracle" must be updated in the same docs cycle. Decision: lead.
4. **Same-`result_id` race (#46 `D-02`).** TV3 accepts TV2's `INSERT ... ON CONFLICT DO NOTHING RETURNING id, received_at` followed by a probe in a new statement. 2026-11-09: TV2 moved to the **target-less** form because an explicit `(result_id) WHERE ...` target needs `SELECT(result_id)`; TV3 re-ACKed it on #46 @ `342497c` with one action: a catalog test that `result_inbox` has exactly two unique constraints (PK and `uq_result_inbox_result_id`), so a future unique index cannot be swallowed silently. `ABSENT` after a suppressed conflict → `503`. The unknown-commit rule (probe in a new transaction, never re-insert blindly) is kept. This replaces the approved "loser rolls back and re-reads" text only through erratum `E-C2` (§6.7).
5. **Verification location (`S-09`).** The TV3 verifier is a pure function over bounded bytes (≤ the bound above) and a trusted 32-byte key, without network I/O. Third revision: TV3 accepts the call **outside** the domain locks (V-OUT, TV5's preference, §6.6.4); the result is provisional and the finalizer rechecks the identity fields, bytes, hash, bound context and `received_at < hard_deadline_at` from the DB, as #46 `B-IF-05/07` state.

### 6.4. Signer readiness for allocation (`C-IF-07/08`, TV4 `D-IF-07`; `PROPOSED_FOR_ACK`)

- Readiness inside `TX-ALLOCATE` is decided **only from committed DB state**: the Worker has **exactly one** `worker_public_keys` row with `retired_at IS NULL`, read under the existing locks. Zero or ambiguous → fail closed: no allocation, typed `Blocked(SIGNER_NOT_READY)` outcome (TV2 adds it to #46 `B-IF-06`; TV4's `D-IF-07` category list in #48 needs the same entry), no secret in logs.
- That the Simulator's private key matches that public key is proven by TV5 at provisioning and at Simulator startup (sign-and-verify self-check against the registered public key), **not** by an HTTP call during allocation.
- Planned K1→K2 rotation needs one **per-Worker serialization point** between `TX-ALLOCATE` for that Worker and key registration/retirement; pausing a discovered set of Listings alone leaves a read-then-update gap. TV2 named it on this PR (review at `942383f`): a transaction-scoped advisory lock keyed by the Worker, **first** in the global order, shared for `TX-ALLOCATE`, exclusive for key registration and retirement (§6.6.5). No new table, status or grant.
- K1 is retired, never deleted, while evidence references it (`P2C-KEY-03/04`).
- Suspected compromise stays `NEEDS_OWNER_DECISION` (`C-IF-09`); TV3 does not choose an incident policy here.
- TV5 (Q5) noted that one active DB key is necessary but not sufficient; the delivery of the key identity to the Simulator, the K2 readiness point and the allocate-vs-rotate gap are answered in §6.6.5.

### 6.5. Questions to close during cross-review (still `PENDING`)

| # | Question | Who answers | Status 2026-11-09 |
|---|---|---|---|
| Q1 | Accept the outcome mapping in §6.2, and align `B-IF-02` wording to `RESULT_ID_COLLISION` / `RESULT_CONTEXT_NOT_FOUND` / `RESULT_NOT_ACCEPTABLE`? | TV2, TV5 | TV5 `ACK_WITH_ACTIONS` at `942383f`; known-duplicate vs reconciled wording fixed in §6.2 (third revision); TV2 aligned `B-IF-02` in #46 |
| Q2 | Accept the body bound in §6.3 item 1 (16,384 bytes, depth 4, all failures `422`)? | TV1, TV5 | TV5 `ACK_WITH_ACTIONS` (boundary tests); TV1 pending |
| Q3 | Accept "no Inbox row for rejected callbacks" (§6.3 item 2)? | TV5, TV2 | TV5 `ACK_COMPATIBLE`; TV2 recorded in `D-08` |
| Q4 | Accept SHA-256 equality for duplicate detection (`D-01`)? | Lead | `NEEDS_LEAD_DECISION`; conditional erratum `E-C1` in §6.7 |
| Q5 | Accept the readiness rule in §6.4 and name the per-Worker serialization lock? | TV2, TV4, TV5 | TV5 P1 at `942383f` (fence not durable) answered by TV2's lock and sequence, adopted in §6.6.5 with the P1 answers; quiesce marker needs lead decision `E-C3` (§6.7); TV4 to ACK `SIGNER_NOT_READY`; TV2 recorded it as #46 `D-18` @ `8d57bec`; live-signer gate G1/G2 (§6.6.5 item 9): TV5 `ACK_WITH_ACTIONS` @ `9b337f5` (prefers G1; actions A–C answered in item 9, aligned with #46 @ `ba63466`); `SignerReadiness` field set ACKed by TV3 on #46 @ `ba63466`, fingerprint fixed in #46 @ `531805b`; still needs TV1 ACK and a lead choice |
| Q6 | Which identity provisions `worker_public_keys` (`S-10`)? Not #46 `D-12` | TV2, lead | Pending; tracked with #46 `D-03` |
| Q7 | Freeze `VerifiedV1Receipt` / `RejectedV1Receipt` fields and the rejection-code enum (`C-IF-06`)? | TV1, TV2, TV5 | TV5 `ACK_WITH_ACTIONS` at `942383f`; parser drift fixed (§6.6.2–6.6.3), V-OUT accepted (§6.6.4, `E-C4`); enum = four verifier codes, matches TV2's CHECK @ `1bfb864`; TV1 ACK pending |
| Q8 | Key-compromise incident policy (`C-IF-09`) and the cold-restart cache gap (`P2E-CACHE-GAP-01`, #46 `D-16`) | Lead (with TV1, TV5) | `NEEDS_OWNER_DECISION`; TV3 input on the cache gap given on #50 |

### 6.6. Cross-review responses (2026-11-09; `PROPOSED_FOR_ACK`)

Sources: TV5's review of this PR at `b147e66`; TV2's review of this PR at `942383f` (`ACK_WITH_ACTIONS`); TV2 #46 @ `342497c` and follow-up `f315400` (`P2B_UOW_INTERFACES.md` `B-IF-05/07`, `P2E-VERDICT-CONTRACT-01`); TV3 comments on #46, #47 and #50. Field names follow #46 so that both files describe one contract.

#### 6.6.1. Verdict types (`C-IF-06`, `P2E-VERDICT-CONTRACT-01`)

Both types are immutable and can only be built by the TV3 verifier (private constructor/factory). Neither carries raw envelope bytes, private material, a DB Session or a bare `verified=true` flag.

```text
VerifiedV1Receipt(
    inbox_id, result_id, envelope_sha256,
    job_id, attempt_id, worker_id, listing_id, key_id,
    schema_version='1', outcome, failure_reason, result_digest,
    finished_at_wire,            # signed string; never used for admission
    payload_jcs_raw,             # UTF-8(JCS(payload)), WITHOUT the domain prefix
    signature_raw                # 64 bytes, decoded from the 86-char base64url
)
RejectedV1Receipt(
    inbox_id, result_id, envelope_sha256,   # hash of the bytes actually examined
    job_id, attempt_id,                     # bound pair of the examined row
    rejection_code                          # closed enum, §6.6.2
)
```

- `inbox_id` replaces the earlier `inbox_row_id` (Appendix C3, DR-C3).
- `result_id` is non-NULL in both: ingress stores only envelopes whose `result_id` passed strict parsing.
- TV2 rechecks every identity field from the database under the locks, for **both** acceptance (`finalize_one`) and rejection (`reject_candidate`). A mismatch is a no-op (`BindingMismatchNoop` / `RejectedCandidate(BINDING_MISMATCH)`), never a verdict on another row (#46 `P2B-DRT-23`).

#### 6.6.2. Closed rejection-code enum

Verifier codes, the only values a `RejectedV1Receipt` may carry:

| Code | Meaning |
|---|---|
| `UNKNOWN_KEY` | No registered `(worker_id, key_id)` row |
| `KEY_WORKER_MISMATCH` | The `key_id` exists but belongs to another Worker |
| `CONTEXT_MISMATCH` | Signed `job_id`/`attempt_id`/`worker_id`/`listing_id` differ from the bound context |
| `INVALID_SIGNATURE` | Ed25519 verification of prefix + JCS bytes fails |

TV2's housekeeping codes for non-winners (`NOT_SELECTED`, `ALREADY_TERMINAL`) are **not** verifier verdicts and never travel in a `RejectedV1Receipt`. DB guard: TV2's `ck_result_inbox_rejection_code` in #46 (`PHASE2_SCHEMA_MATRIX.md` §5; added @ `f315400`, narrowed @ `1bfb864`) allows only the union of the two sets (four verifier + two housekeeping codes) and ties a non-NULL code to `state = 'REJECTED'`; `P2B-MIG-06` tests it.

**Parser drift is not a verdict (TV5 re-review at `942383f`).** Ingress stores a row only after the same strict V1 parser accepted its bytes, and stored bytes are immutable. So if the verifier later fails to parse, or reads an unsupported `schema_version` from, an ingress-admitted row, the cause is parser/runtime drift or corruption, never a bad receipt: it is an **invariant break** (§6.6.3), fail closed, the row stays `PENDING`, alert. It must never become `REJECTED`, because that could turn a once-admissible receipt into a false `SYSTEM_FAULT`. In Phase 2 the definitive verdicts after admission are therefore only `UNKNOWN_KEY`, `KEY_WORKER_MISMATCH`, `CONTEXT_MISMATCH` and `INVALID_SIGNATURE`. `INVALID_STRUCTURE` and `UNSUPPORTED_SCHEMA_VERSION` are therefore **not** in the enum; TV2 dropped them from the CHECK in #46 @ `1bfb864`, and `P2B-DRT-23` covers a `RejectedV1Receipt` carrying a removed or housekeeping code. Regression vector: a stored valid V1 envelope plus a deliberately failing parser ⇒ row stays `PENDING`, no `REJECTED`, fallback blocked, alert raised.

#### 6.6.3. Definitive vs transient

Only the four definitive codes above may reject (§6.6.2). These are **not** rejections: any parse or schema-version failure on ingress-admitted bytes, key row unreadable because of a DB error, a broken key invariant (zero or two active keys where one is required), extractor failure on bytes that ingress already accepted, timeout or `DependencyUnavailable`. They fail closed: no state change, the Inbox row stays `PENDING` (so `deadline_fallback` keeps answering `ContinueCandidateScan`), redacted alert. This prevents a transient fault from turning a valid on-time result into a false `SYSTEM_FAULT`.

A key retired **after** a candidate was stored is not `UNKNOWN_KEY`: the verifier still checks the retained K1 row (DR-C4 "Old K1 evidence"; #46 `B-IF-08`).

#### 6.6.4. Where verification runs, and `extract_signed_parts_v1`

- **TV3 position (third revision): V-OUT.** TV3 withdraws its earlier V-IN preference and accepts TV5's provisional choice. The TV3 verifier runs **outside** the domain locks on the immutable Inbox bytes and the trusted key row, and returns a `VerifiedV1Receipt` or `RejectedV1Receipt`. TV2's `finalize_one(job_id, verified)` / `reject_candidate(job_id, rejected)` then take the Listing → Job → Allocation → Inbox locks and recheck, on the **locked** row: `inbox_id`, `result_id`, `envelope_sha256` (DB-bound to `sha256(original_envelope_raw)`), Job/attempt/Worker/Listing/`key_id`, `received_at < hard_deadline_at`, state `PENDING`, and byte equality of `payload_jcs_raw`/`signature_raw` with `extract_signed_parts_v1` over the locked bytes. Reasons: it fits #46's current port signatures (no reentrant Session), keeps parse and Ed25519 CPU out of the lock window, and the earlier claim that in-lock verification is "far below the lock budget" was never measured (TV5). Anti-TOCTOU holds because the verified bytes are proven equal to the locked immutable bytes, and key rows are never modified except `retired_at` (a retired key still verifies retained candidates, §6.6.3). Recorded against the approved `TX-FINALIZE` pseudo-code as erratum `E-C4` (§6.7).
- **Extractor:** TV3 provides the pure, I/O-free `extract_signed_parts_v1(original_envelope_raw) -> (payload_jcs_raw, signature_raw)` used by #46 `finalize_one` to check byte equality with the carrier. Same strict parser as ingress (three envelope keys, exactly eleven payload keys, duplicate members rejected, canonical base64url). `payload_jcs_raw` excludes the `GPU-MARKETPLACE:SIGNED-RESULT:V1\n` prefix, which is added only for verification. An extractor failure is a transient/invariant fault (§6.6.3), not `BINDING_MISMATCH` and not a rejection.
- **V-IN kept as fallback only** (if TV1 rejects V-OUT): constraints from TV2's review at `942383f`: the verifier is injected into the finalize and reject ports as a pure callable (no Session, no I/O except the key row read in the same UoW), the candidate scan is bounded per UoW, the carrier drops `payload_jcs_raw`/`signature_raw`, and TV2 updates `B-IF-07`.
- **Latency evidence, both options:** `P2B-DRT-14` / `P2C-DRT-16` measure lock hold time with the chosen placement; no number is claimed before they run.
- Final choice: TV1 + TV5 (TV5 provisional V-OUT, TV3 accepts, TV2 can implement either).

#### 6.6.5. Key identity, K2 readiness and the allocate-vs-rotate gap (answer to TV5 Q5)

1. **Delivery without DB access.** One controlled provisioning step (identity per `S-10`) generates the Ed25519 pair, registers `(worker_id, key_id, public_key_raw)` in `worker_public_keys`, and writes a secret bundle `{worker_id, key_id, private key}` to the Simulator's untracked secret storage. The Simulator learns its active identity only from that bundle; it never reads the DB.
2. **Simulator startup self-check** (TV5): derive the public key from the private key, sign and verify a fixed test message, and refuse to sign (readiness failure, redacted log) on any error. The Simulator cannot know whether the DB row is active; that is enforced by the allocation rule and step 4 below.
3. **Allocation rule (§6.4):** `TX-ALLOCATE` allocates only if the Worker has exactly one active key row, read under the locks; otherwise `Blocked(SIGNER_NOT_READY)`.
4. **Per-Worker lock (TV2 proposal at `942383f`, TV3 `ACK`):** `pg_advisory_xact_lock_shared(hashtextextended('gpm:worker-key:' || :worker_id, 0))` in `TX-ALLOCATE`, the exclusive `pg_advisory_xact_lock(...)` with the same key for key registration and retirement. Executable by `PUBLIC`, so no grant change; a hash collision only causes false waiting. To be proven as native `gpm_manager_app` and as the provisioning identity (`G-01`, `S-10`).
5. **Lock order:** the Worker lock is **first**: `Worker (advisory) → Listing → Job → Allocation → Inbox → …`. `TX-ALLOCATE` reads `gpu_listings.worker_id` in its unlocked locator step (immutable under the D7 identity guard), takes the shared Worker lock, locks the Listing and rechecks `worker_id`. Submit, Cancel, Pause, Resume and Listing create never take it, so no cycle exists. A new first position in `database-design.md` §11.1 is a lock-order change: **L2 review** before coding.
6. **Planned K1 → K2 sequence (TV2, four steps; replaces the five-step draft of the first 2026-11-09 revision):**
   1. **Register K2 (quiesce).** Under the exclusive Worker lock, insert K2 with `retired_at IS NULL`. The Worker now has **two** active rows, so every later `TX-ALLOCATE` for it answers `Blocked(SIGNER_NOT_READY)`; the exclusive lock waits for in-flight allocations, which hold the shared lock until commit. Listings are not paused, so Listing create and resume need no serialization with rotation.
   2. **Drain.** Wait until every attempt of that Worker reaches a committed terminal state, including the hard-deadline fallback. Callbacks signed with K1 are verified against the K1 row as usual.
   3. **Deploy K2.** Install the K2 bundle, restart the Simulator; self-check passes.
   4. **Retire K1.** In one transaction under the exclusive Worker lock, recheck that the active rows are **exactly the expected pair `{K1, K2}`** (expected `key_id`s and the trusted step 3 self-check result are passed in by the provisioning caller; a third key, a missing key or a partial registration fails closed and writes nothing) and that no `RUNNING` attempt exists for the Worker (abort if any); then set `retired_at` on **K1 only**. One active row again; allocation resumes (TV5 action C on #46 @ `84fe452`, #46 `B-IF-06` / `P2B-DRT-28`).

   **Signer ready after K2** = step 3 passed **and** step 4 committed, **and** the live-signer gate in item 9 passes. **Abort path:** if step 3 fails, set `retired_at` on K2 under the exclusive lock (K1 stays the single active key) and keep or restore the Simulator's K1 bundle **before** the fence is lifted; K2 is never deleted by the application. A late callback signed with K1 is still verified against the retained K1 row (§6.6.3). A bug that leaves two active rows fails closed (blocked, alert), never allocates with an ambiguous signer.
   **Answers to TV5's P1 at `942383f`** (written against the earlier five-step draft):
   - *Durable fence:* the fence is the committed second active row, not the transaction lock, so it persists across the drain and deploy interval, Manager restarts and retries. It is checked inside every `TX-ALLOCATE` under the shared Worker lock. Listing create and resume may happen during rotation but cannot allocate, so no "pause all known Listings" set is needed.
   - *Privileges:* the predicate reads only `worker_public_keys`, on which the Manager already has `SELECT`; no right on `workers`, no new table, status or grant. Writing key rows stays with the provisioning identity (`S-10` / `D-03`).
   - *Trusted signer-ready gate:* "exactly one active key row" is **necessary, not sufficient** (TV5 action B on #46 @ `84fe452`): it proves the registry, not that the live Simulator holds the matching private key now. The full gate is item 9.
   - The Simulator gets no DB credentials, and no HTTP call happens while an allocation UoW is open (dispatch goes through the Outbox after commit).
7. **No partial unique index on the active key.** A `UNIQUE (worker_id) WHERE retired_at IS NULL` index (`database-design.md` §9.2-05 "Proposed policy", Phase 1B `D4`) would forbid step 1. Keeping it out, and the wording of approved §2.4 ("preserves the at-most-one-active-key invariant"), is conditional erratum `E-C3` (§6.7), lead decision.
8. **Tests (after coding authorization, `NOT_RUN`; TV2 adds the DB ones to #46):** allocate vs K2 registration barrier in both commit orders; two allocations for different Listings of one Worker run concurrently under the shared lock; allocation with two active rows answers `Blocked(SIGNER_NOT_READY)`; a Listing created or resumed during the drain cannot allocate; Manager restart and Outbox retry during the drain keep the fence; K1 retirement aborts while a `RUNNING` attempt exists; native-role `EXECUTE` proof of the advisory functions; Simulator restart with missing/mismatched bundle; K1 receipt verified after K1 retirement; abort path leaves exactly K1 active. DB cases are #46 `P2B-DRT-24..28`; the item 9 cases are TV1/TV3/TV5 tests (`P2C-SIGN-01..06` below).
9. **Live-signer gate (TV5 action B; `PROPOSED_FOR_ACK`, owners TV1 + TV3 + TV5, integration TV2 + TV4).** Goal: after a Simulator restart, or a lost or mismatched K2 after step 4, the Manager must not start new allocations for that Worker only because PostgreSQL still shows one active key.
   - **Simulator side (TV5).** At startup the Simulator loads its bundle `{worker_id, key_id, private key}`, derives the public key, signs and verifies a fixed self-test message, and only then reports itself signer-ready. Missing, unreadable or inconsistent bundle ⇒ not ready, redacted log, and it answers every dispatch for that Worker with a non-`202` "signer not ready" response so no execution starts.
   - **Manager side (TV1), outside any UoW.** Before the scheduler calls `allocate_one_listing` for a Listing of Worker W, it requires a **fresh signer proof** for W. Two options, lead decides:
     - **G1 (TV3 recommendation; TV5 also prefers G1 in its review @ `9b337f5`): proof of possession.** The Manager sends a random 32-byte nonce over the existing Manager→Simulator direction (`MANAGER_DISPATCH_TOKEN`); the Simulator returns `{worker_id, key_id, signature}` over `b"GPU-MARKETPLACE:SIGNER-PROOF:V1\n" + worker_id + "\n" + key_id + "\n" + nonce`. The Manager verifies it with TV3's pure verifier against the **single active** `worker_public_keys` row read in a short read-only transaction. The distinct domain prefix means a proof can never be replayed or reshaped into a V1 result signature (ADR-004 V1 is unchanged), and the fresh nonce prevents replay of an old proof. Needs a new internal Simulator endpoint, i.e. an **API Contract change (L2, change control)**.
       - **Proof wire (`PROPOSED_FOR_ACK`, frozen only with the endpoint).** `nonce`: exactly 32 random bytes from a CSPRNG; on the wire it is Base64url without padding (43 characters); in the signed bytes it is the **32 raw bytes**, not the text. `worker_id` and `key_id` are canonical lowercase UUID text (`8-4-4-4-12`, ADR-004), in the signed bytes as UTF-8. The signature is Ed25519 over those bytes, 64 raw bytes, Base64url without padding on the wire. Authentication is the existing `MANAGER_DISPATCH_TOKEN` direction. Request deadline and nonce lifetime are `PENDING_PARAMS`.
       - **Self-check scope (TV5 action C).** The Simulator's startup self-check (sign a fixed message, verify with the public key derived from the **same** private key) proves only that the private key is usable. It does **not** prove that the key matches the registered active `(worker_id, key_id)`. That binding comes from the Manager verifying the G1 proof against the DB key.
     - **G2 (no new endpoint): dispatch refusal.** The Simulator's "signer not ready" response to a dispatch makes the Manager mark W not ready until a later dispatch is accepted. No contract change, but the first allocation after a signer loss is spent and ends in deadline fallback `SYSTEM_FAULT` (no Worker penalty).
       - **G2 bootstrap contradiction (TV5 action B).** Under the rule "unknown ⇒ not ready ⇒ no allocation" (below), G2 can learn readiness only from a dispatch, and a dispatch exists only after an allocation. A freshly restarted Manager therefore can never become ready, because no operation probes a Worker without allocating. G2 is usable only if the lead approves an **explicit bootstrap exception**, for example one probing allocation per Worker after a Manager restart, accepting that this Job may end in fallback `SYSTEM_FAULT` (no Worker penalty). Without that exception G2 is not equivalent to G1 and TV3 does not propose it.
       - **G2 also needs its own contract (TV5 + TV1, `PENDING_PARAMS`):** the Simulator's "signer not ready" response needs an exact status, error code, retry rule and Outbox mapping, so that it is never mistaken for `202` acceptance or for `WORKER_FAULT`.
     - **Position:** TV3 keeps recommending G1 and TV5 also chose G1 at `9b337f5`; G1 needs L2 change control for the new endpoint. The lead chooses.
   - **Readiness identity and binding to the active key (TV5 action A; the allocation predicate is TV2's, #46 `B-IF-06` @ `ba63466`).**
     - The gate produces `SignerReadiness(worker_id, key_id, public_key_fingerprint, proof_expires_at)`, held **only in Manager memory**, never persisted. Names and fields are exactly those of #46 `B-IF-06`; TV3 defines only what the proof contains and how it is verified.
     - The Manager passes it to `allocate_one_listing(listing_id, signer)`. Under the Worker advisory lock and the Listing lock, TV2 requires that the **sole** active `worker_public_keys` row has `key_id = signer.key_id` and a matching fingerprint of `public_key_raw`, that `signer.worker_id` equals the Listing's Worker, and that `clock_timestamp() < signer.proof_expires_at`; otherwise `Blocked(SIGNER_NOT_READY)`, committed as a no-op. A cached K1 proof therefore cannot pass once K2 is the only active key.
     - **Fingerprint (`PROPOSED_FOR_ACK`, TV2 and TV3 aligned).** `public_key_fingerprint` is the SHA-256 of the 32 raw `public_key_raw` bytes, exactly as #46 `B-IF-06` @ `531805b` states it: 64-character lowercase hexadecimal, `encode(sha256(public_key_raw), 'hex')` in PostgreSQL and `hashlib.sha256(public_key_raw).hexdigest()` in the Manager, with no domain prefix, no base64 and no key id mixed in. The DB compares it to the locked row; `P2B-DRT-29` asserts both sides give the same value for the same key (known-answer vector from TV3, owed with the test fixtures). It only identifies which key a proof was made for: not a secret, not a signature.
     - The Manager **drops** a cached proof when a key of that Worker is registered, activated or retired, when `proof_expires_at` passes, and on Manager restart.
   - **Readiness state** is in Manager memory only, per Worker, with a short TTL (`PENDING_PARAMS`). Manager restart ⇒ unknown ⇒ not ready until proven again (fail closed). A failed or expired proof gives the same `Blocked(SIGNER_NOT_READY)` category as the key-count check, without opening a UoW. The scheduler pre-filter that withholds a Worker without a fresh proof is an optimization; the under-lock check above is the safety net.
   - **Rules kept:** no HTTP while holding the advisory lock or any row lock; the Simulator gets no DB credentials; the proof is never stored as evidence and never affects reputation.
   - **Residual risk, stated:** the signer can still be lost between a successful proof and dispatch (window ≤ TTL), **including a Simulator restart inside the TTL** while the Manager still holds a valid cached proof. That attempt gets no valid receipt and ends in deadline fallback `SYSTEM_FAULT` without penalty; it cannot produce a wrongly accepted result. A short TTL narrows this window but TV3 does not claim it removes it, and no TTL value is proposed here (`PENDING_PARAMS`). Cold-restart bundle loss and compromise stay `P2E-CACHE-GAP-01` / `D-16` / `C-IF-09` (lead).
   - **Tests (`NOT_RUN`):** `P2C-SIGN-01` Simulator restart without bundle ⇒ no allocation for W **once the earlier proof has expired or been invalidated**; `P2C-SIGN-02` bundle key ≠ registered active key after step 4 ⇒ no allocation **after proof expiry or invalidation** (before that, see `P2C-SIGN-07`); `P2C-SIGN-03` Manager restart ⇒ no allocation until a fresh proof; `P2C-SIGN-04` replayed or wrong-`worker_id` proof rejected; `P2C-SIGN-05` a SIGNER-PROOF signature does not verify as a V1 result signature and vice versa; `P2C-SIGN-06` no HTTP call while the Worker advisory lock or a row lock is held; `P2C-SIGN-07` Simulator restart **inside** the TTL (cached proof still valid) ⇒ the allocation may proceed, the dispatch gets the "signer not ready" answer or no valid receipt, and the Job ends in deadline fallback `SYSTEM_FAULT` without Worker penalty (the stated residual risk, expected outcome recorded, not hidden); `P2C-SIGN-08` proof for K1, then K2 activated, then allocate with the K1 proof ⇒ `Blocked(SIGNER_NOT_READY)`, and a fresh K2 proof ⇒ allocation allowed (TV3 side of #46 `P2B-DRT-29`, both commit orders by barrier).

#### 6.6.6. Alignment with #46 @ `342497c` (`C-IF-04`, `C-IF-10`)

- **Admission instant:** `INSERT ... RETURNING id, received_at` and rollback as `Ineligible(late)` when `received_at >= hard_deadline_at` (#46 `D-17`, TV3 ACK); boundary tests T-D2 (b)/(c) are the technique for `P2C-DRT-10`.
- **Earliest winner:** `finalize_one` answers `PrecedingPending` while an earlier on-time `PENDING` row exists; invalid-first/valid-second works for any batch size.
- **Fallback:** `deadline_fallback(job_id)` takes no caller-supplied proof; under Listing → Job locks it re-reads that no on-time `PENDING` row remains. A transiently unverifiable row stays `PENDING` and blocks fallback (§6.6.3).
- **Processing after the deadline:** finalization tests only the **stored** `received_at`, never the current time, so an on-time row is still processed after a restart.
- Status: proposed by TV2, `PENDING_ACK` TV1 + TV3 + TV5; DR-C5 is read together with these points.

### 6.7. Conditional errata to approved text (apply only after the lead's decision)

These do not change approved text now. They state exactly what would change, so the lead can decide once for Phase 2B, 2C, 2D and 2E (TV5 Q4; TV2 key-rotation proposal).

| ID | Approved text affected | Change if the lead decides | Unchanged either way |
|---|---|---|---|
| `E-C1` (`D-01`) | §2.3 "SHA-256 as an efficient prefilter and exact byte equality for the final decision"; DR-C2 "only a prefilter, never the sole equality oracle" | If **option C** is chosen: equality of the API-computed SHA-256 of the received bytes with the stored `envelope_sha256`, which a DB CHECK binds to `sha256(original_envelope_raw)`, is the duplicate test (cryptographic equivalence, not literal byte comparison). If **option B**: text unchanged, byte comparison in a reviewed probe function | Bytes are stored exactly as received; no re-serialization; `P2C-REPLAY-09` (equivalent JSON, different bytes ⇒ `409`) still holds; the API never gets general raw `SELECT` |
| `E-C2` (`D-02`) | §2.3 "a concurrent loser of the unique insertion **must roll back** its transaction and re-read the winner"; DR-C2 same | Accepted equivalent: target-less `INSERT ... ON CONFLICT DO NOTHING RETURNING id, received_at`, zero rows ⇒ fresh probe statement; `ABSENT` ⇒ `503` | PostgreSQL UNIQUE decides; no in-memory authority; unknown commit reconciled in a new transaction; `P2C-REPLAY-04/05` cover both commit orders |
| `E-C3` (Phase 1B `D4`, §6.6.5) | §2.4 "make K2 the sole active key via controlled provisioning that preserves the at-most-one-active-key invariant"; DR-C4 "coordinate pauses/admission of **all** affected Listings"; `database-design.md` §9.2-05 "Proposed policy" partial unique index on the active key | If the lead accepts TV2's quiesce marker: "at most one active key per Worker **outside a rotation window**; during rotation two active rows are the quiesce marker and allocation fails closed"; the partial unique index is not added (`D4` closed as "not added"); DR-C4 admission control is met by gating `TX-ALLOCATE`, not by pausing Listings. If rejected: keep the invariant and the index, quiesce by pausing all the Worker's Listings, and Listing create/resume must then also take the shared Worker lock | K1 is never retired while a related attempt is `RUNNING`; K1 is retained for evidence; allocation needs exactly one active key; rotation is serialized by the per-Worker lock |
| `E-C4` (V-OUT, §6.6.4) | `database-design.md` §11 `TX-FINALIZE` pseudo-code: "lock candidate rows only AFTER Job lock. For each candidate: verify exact ADR-004 bytes, key_id/public key, … schema, signature" (verification inside the locked UoW) | If TV1 + TV5 confirm V-OUT and the lead accepts: Ed25519 verification and parsing run before the locks on the immutable Inbox bytes; inside the locked UoW the finalizer proves the candidate is the verified one (row id, `result_id`, DB-bound SHA-256, bound context, `key_id`, extractor byte equality, on-time, `PENDING`) before any effect. If V-IN is kept: text unchanged | One accepted result per Job; invalid candidate `REJECTED` before fallback, never a Job failure by itself; transient faults keep `PENDING`; no network I/O under locks; bytes and keys trusted only from the DB |

Nothing in §6 changes an approved decision, adds a table, service, status code or dependency, or claims an executed test. The one exception is **proposed only**: option G1 in §6.6.5 item 9 would add an internal Manager→Simulator endpoint and therefore needs an API Contract change through change control (L2) before anyone relies on it.

## Approved design references

- [SRS](../../../requirements.md), [FR](../../../functional-requirements.md), [NFR](../../../non-functional-requirements.md).
- [System Architecture](../../system-architecture.md), [Module Design](../../../design/module-design.md), [Database Design](../../../design/database-design.md), [API Contract](../../../design/api-contract.md), [Test Design](../../../design/test-design.md).
- [ADR-001 to ADR-008](../../decisions/), especially ADR-002 (data access), ADR-003 (Outbox/Inbox), [ADR-004](../../decisions/ADR-004-signed-result.md) (signed result, including the accepted V1 JSON Schema §3.3 and public vector §3.4) and [ADR-005](../../decisions/ADR-005-retry-timeout-internal-auth.md) (retries, deadlines, service tokens).
- [Phase 1E](../phase1e_job_submission_queue.md), [GPU-005-B reference proposal](../phase1e_gpu005_reference_technical_specification.md) and the [TV3 handoff](../../../development/handoffs/phase2/HANDOFF_TV3_Phase2C_v1.1.md).

The formerly linked `phase2_readiness_and_handoffs.md`, `phase2_decision_register.md` and `phase2_test_and_acceptance_plan.md` do not exist on `main`. Use the approved sources above, §6 and the handoff; absent files are not approval or evidence.

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

*(2026-11-09: field names and the rejection enum are superseded by the proposal in §6.6.1–6.6.2; `inbox_row_id` is now `inbox_id`.)*

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

| Subject | Statement (updated 2026-11-08) | Evidence / remaining action |
|---|---|---|
| Current `main` | `bee832eaf5463df20f6c6815174322871eb6685a`, after docs intake [#44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44) (five Phase 2 designs and five handoffs) | Merge of #44 is not completion of their cross-review or coding gates |
| PR #39 | **Merged** by TV1 as `aff538f79997c6e2bfcf359b176a82f2cd9ecc53` (source head `3482bce3cc9726543b9345a5224d8db1b9fc6454`); PR #42 (Auth browser E2E, role-credential restore) is included transitively | [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39); [CI run 42385995533](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533) is **Phase 1** evidence only |
| Migration baseline | Alembic graph on this `main`: single head `0005_listing_d7` (read-only check, no migration run for this review) | TV2 freezes the Phase 2 migrations and grants (#46) |
| Phase 1 authentication | HS256 JWT with shared principal and browser-session path wired on `main` | Do **not** reuse user JWT as internal Bearer or claim internal endpoint tests PASS |
| Existing Manager | `manager/service.py` is still the foundation idle runner; no Phase 2 verifier/consumer runtime exists on `main` | Review implementation only after the docs gate and the task's own approval |
| ADR-004 | Immutable V1 payload of exactly 11 fields, JCS RFC 8785, Ed25519, fixed domain prefix, accepted JSON Schema (§3.3), fixed public signature vector (§3.4) | No implicit V2, additional payload fields or alternate wire encoding |
| GPU-005-B | The Phase 1 reference generator and vector checks are on `main` via #39. Phase 2E approval of the 9-field mock output/algorithm compatibility is conditional | Do not use #39 to claim Phase 2 runtime compatibility |
| Phase 2B | v1.3 on `main`; TV2's pre-code proposals in [#46](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) (`B-IF-01..09`, `D-01..16`) cover the Inbox probe, collision handling, `received_at` and historical keys | TV3 answers are in §6; actual ACK is given on #46 by file SHA; no SQL executed |

### DR-C2. Strict callback input, authorization and replay: two distinct validation points

**API ingress: do only the work required to authenticate and safely store a candidate.** Authenticate the exact direction-scoped `SIMULATOR_CALLBACK_TOKEN` before any Inbox query that reveals records or any write. End-user JWT, opposite `MANAGER_DISPATCH_TOKEN`, missing/duplicate malformed Authorization headers and invalid Bearer values fail closed; errors/logs do not echo secrets. Enforce HTTP method/Content-Type, an explicitly bounded raw-body size and bounded parse depth/CPU cost (numerical budgets `PENDING TV1/TV3`). Use original received bytes for Inbox evidence and byte-identical replay comparison. Never serialize a parsed Pydantic/dict object and call those bytes the original envelope.

**Parse valid JSON strictly at both envelope/payload levels:** exactly three envelope keys `payload`, `signature`, `signature_encoding`; exactly 11 signed payload keys; reject duplicate object members *before* dict conversion, missing/extra fields, invalid JSON/I-JSON (including nonfinite numbers and invalid Unicode), wrongly typed fields and noncanonical UUIDv4/timestamp/base64url. A conforming RFC 8785 JCS implementation is needed for signing/verification; `json.dumps(sort_keys=True)` is not a general-purpose JCS substitute. `signature_encoding = "base64url-no-padding"` and 86 canonical ASCII Base64url characters must decode/re-encode to exactly 64 signature bytes.

**Ingestion must not pre-judge cryptography:** a well-formed, context-bound receipt can be stored with `202 STORED` even if its signature later fails. The API must not invent a `COMPLETED` or `FAILED` effect from `202`; Manager verifies later. Rejecting an invalid signature is a **Manager Inbox** processing outcome, not an instruction to penalize the Worker immediately. Response codes/meanings come from API Contract §13.2: wrong token `401`; malformed V1 envelope `422`; unknown Job `404` without cross-user leakage; new late/stale/terminal candidate `409`; same `result_id` changed original bytes `409`; committed new candidate or exact retained duplicate `202`.

**Replay lookup is scoped to the authenticated callback and retained trusted binding.** For an existing `result_id`, require same original raw bytes and same persisted binding/identity, then `202 DUPLICATE` even if its Job is now terminal; preserve the original `received_at`. Same ID with changed bytes yields `409 RESULT_ID_COLLISION`. If two inserts race, PostgreSQL UNIQUE decides the winner: the losing writer **rolls back** its UoW, opens a new read transaction and compares the committed winner's exact bytes and binding. The SHA-256 stored alongside the bytes is only a prefilter, never the sole equality oracle. A freshly received, different `result_id` is a separate candidate, not a replay. *(Both sentences are subject to the conditional errata `E-C1`/`E-C2` in §6.7, effective only after the lead decides #46 `D-01`/`D-02`.)*

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

*(2026-11-09: superseded by §6.6.1, which renames `inbox_row_id` to `inbox_id`, adds `result_id`, `envelope_sha256`, `job_id`, `attempt_id` to the rejection and replaces `signed_payload_fingerprint` with `payload_jcs_raw`/`signature_raw`.)*

Only TV3's trusted verifier produces a `VerifiedV1Receipt` after signature, wire and registered-key checks. It must not be constructible from untrusted HTTP JSON as a sufficient authorization object. No raw signing private key, protected reference, direct SQLAlchemy Session, ORM-managed lock or mutable `verified=True` claim crosses the TV3→TV5 boundary. If verification happens outside the Finalizer transaction, its result is **provisional**: TV5 and TV2 must re-read the **committed** Inbox evidence after Listing→Job→Allocation→Inbox locks, compare candidate identity/hash and exact persisted binding, recheck `RUNNING`, immutable Attempt, `received_at < hard_deadline_at`, key eligibility, and prior accepted result. No network calls under these domain locks. If evidence/context diverges, no finalization or reputation update is allowed.

**Signature != oracle truth:** a signed but inaccurate `result_digest`, `outcome` or failure class remains a valid *signed claim* when wire, signature and context validate. It can be accepted once and later evaluated against the protected deterministic reference by the approved Phase 3 Dispute flow. TV3 must not query reference data or silently reject a cryptographically valid receipt only because the public mock oracle would differ. The approved `demo-v1-public1` reference is public/recomputable; it is not an anti-cheat guarantee or evidence of real GPU execution.

### DR-C4. Key registration, planned rotation and incident-response boundary

- **Provisioning gap:** Phase 1 Worker creation does **not** guarantee a usable Ed25519 signer per schedulable Worker. The MVP needs an explicitly trusted, non-UI provisioning procedure: generate/store only the private material in Simulator-accessible **untracked secret storage**, register `(worker_id,key_id,public_key_raw,registered_at,retired_at)` through a narrowly authorized DB role/function, prove each active public key maps to the private key used for dispatch. Never ship a Worker private key in dispatch JSON, API/Manager settings, public DTO, logs or Git. Missing/mismatched key => fail closed before dispatch/acceptance; automatic insecure default signing key is forbidden.
- **DB invariant:** preserve `worker_public_keys` PK `key_id`, `(worker_id,key_id)` association, 32-byte public key and `RESTRICT` historical FK for `signed_results`; the approved physical design proposes a partial UNIQUE for at most one `retired_at IS NULL` key/Worker. Exact DDL/GRANT/permission SQL remains TV2's responsibility; review it on native non-owner connections.
- **Planned K1→K2 rotation:** no related `RUNNING` Job/Attempt during retirement. Merely `SELECT no RUNNING` followed by independent UPDATE is **not race-safe**. The proposed runbook must coordinate pauses/admission of **all** affected Listings and `TX-ALLOCATE`, serialize the final no-RUNNING recheck and K2 activation with a compatible lock order, prove runtime Simulator reloads/pins K2, then resume admission. Guard the case where a new Listing is added/resumed mid-rotation. If a new Worker lock/operation would alter approved lock order or granted privileges, require explicit L2 design review instead of silently adding it.
- **Old K1 evidence:** retain public K1 while an accepted Signed Result or open-Dispute evidence may need it. Also verify any already committed on-time K1 Inbox after Manager delay/rotation; do **not** reject merely because `retired_at` is set by the time the Manager processes it. Signer private-key durability across Simulator restarts and Worker→key mapping must be tested separately.
- **Suspected private-key compromise:** quiescent planned rotation is **not** an emergency incident response. Fail closed on new use and record the security hold; do not decide silently whether already-received signed candidates are trustworthy, how RUNNING work resolves, or how affected references/evidence are retained. Those are `OPEN_SECURITY_POLICY / NEEDS_OWNER_DECISION`. Do not introduce a third credential/token meaning or a key-management service without approval.

### DR-C5. Multiple result IDs, ordering, deadline and reconciliation

*(2026-11-09: read together with §6.6.3 and §6.6.6, which align this section with TV2's `B-IF-05/07` proposal on #46 @ `342497c`: `PrecedingPending`, fallback without caller proof, stored-instant admission, transient faults keep rows `PENDING`. Still `PENDING_ACK`.)*

- The same logical `attempt_id` and one durable Outbox event may yield **multiple different** `result_id` after a cold Simulator restart. Accept each *new* correctly bound and on-time candidate into durable Inbox while Job remains RUNNING. Do not treat different IDs as exact replay and do not assume an in-memory Simulator cache survives a crash.
- Manager must process eligible committed on-time candidates in deterministic `(received_at, result_inbox.id)` order. Invalid candidates become `REJECTED` with a stable redacted reason; first cryptographically valid and context-eligible candidate wins `signed_results` with `UNIQUE(job_id)`, then TV5's one atomic Finalization releases GPUs and records the eligible contribution. Later candidates cause **zero** extra business effects. The exact terminal/non-winning Inbox status (from existing `PENDING/ACCEPTED/REJECTED`) and bounded cleanup behavior are `PENDING TV1/TV2/TV3/TV5 ACK`, not auto-approved.
- Before a deadline fallback to `FAILED/SYSTEM_FAULT`, examine **every** committed Inbox candidate admitted `received_at < hard_deadline_at`, including those in subsequent batches or delayed after restart. A fixed page cap cannot silently hide a later valid candidate. `received_at == hard_deadline_at` is late. Race-safety requires a Listing→Job lock, fresh `READ COMMITTED` lookup after lock, and never holding an Inbox lock before acquiring Listing/Job. The boundary test must prove callback-first and fallback-first commit orders.
- Keep fault isolation: a malformed callback/token issue must not crash the Manager supervisor as a database-corrupt condition; an actual invalid schema/privilege/key trust invariant at startup or verification boundary must fail closed with appropriate supervised escalation. Exact fault taxonomy and bounded concurrency are `PENDING TV1/TV3`.

### DR-C6. Deployment, native DB ACL and test evidence

**Current API listener is host-reachable from local loopback.** Serving `/internal/v1/results/callback` on it is approved for the local single-host MVP but its path is not network-private merely because the word `internal` appears in the URL. A browser or local process must not bypass `SIMULATOR_CALLBACK_TOKEN`, even if CORS differs; CORS is not an authentication boundary. Non-loopback exposure requires explicit ingress restrictions and separate transport-encryption/security approval. Manager and Simulator stay separate processes inside the existing five-service Compose topology.

**PostgreSQL privileges:** API needs narrowly authorized insert/duplicate-check behavior; Manager needs trusted persisted Inbox/public-key reads and controlled accepted-result inserts; Simulator has **no SQL identity**. PostgreSQL column-level SELECT is not a per-row security policy: choose and review a narrowly scoped function/role boundary or an explicit least-privilege read design, test against real native `gpm_api_app`/`gpm_manager_app` sessions. The Phase 1 reference grants do not imply arbitrary new Phase 2 read or write access. Avoid raw envelope/oracle in audit metadata.

**Repeatable test environment:** use safety-marked disposable PostgreSQL 16 with safe role-password teardown. PR #39 full browser+HTTP+PostgreSQL and four green CI jobs are **Phase 1 evidence**, not `P2C-NET`, `SIG`, `WIRE`, `P2C-REPLAY` or `P2C-KEY` execution. PR #42 merged into #39 and is now part of `main`; tests that rotate role passwords must reuse its restore fixture (`restored_e2e_role_credentials` / `role_credentials.py`). After coding permission, cross-runtime signer/verifier tests, actual signed callback HTTP/DB, crash barriers and key rotation races must record exact Git SHA, schema revision and CI run; skipped/blocked tests are not PASS.

### DR-C7. Explicit cross-owner interface gates (all `PENDING_ACK`)

| ID | Must agree on before relevant implementation | Owners |
|---|---|---|
| `C-IF-01` | Exact Bearer provisioning, direction separation, refusal of JWT/opposite token and missing-secret startup semantics | TV1 + TV3 + TV5 |
| `C-IF-02` | Callback raw-body size/depth limits, duplicate-key parser, `Content-Type`, HTTP responses, log redaction | TV1 + TV3 + TV5 |
| `C-IF-03` | Narrow DB read/compare of original Inbox bytes, unique-collision retry and commitment/unknown-commit handling | TV2 + TV3 + TV5 |
| `C-IF-04` | Trusted DB admission clock after Listing→Job locks, original timestamp on replay, exact-deadline cutoff | TV1 + TV2 + TV3 |
| `C-IF-05` | RFC8785/Ed25519 cross-language fixture, registered-key binding, strict V1 verifier API | TV2 + TV3 + TV5 |
| `C-IF-06` | Immutable `VerifiedV1Receipt`/`RejectedV1Receipt`, evidence recheck and provenance in Finalizer UoW (proposal §6.6.1–6.6.4) | TV1 + TV2 + TV3 + TV5 |
| `C-IF-07` | One active Worker public key, private signer provisioning, restart reload and missing-key fail closed (§6.4, §6.6.5) | TV1 + TV2 + TV3 + TV5 |
| `C-IF-08` | Quiescent key rotation serialized with new Listing allocation and historical key read (sequence §6.6.5) | TV1 + TV2 + TV3 + TV4 + TV5 |
| `C-IF-09` | Emergency compromise incident disposition; no implicit revocation, deletion, acceptance or automatic rotation | TV1 + TV3 + TV5; owner L2 if changing normative rules |
| `C-IF-10` | Multi-result-id Inbox ordering/nonwinner handling, after-deadline recovery, test crash barriers (alignment §6.6.6) | TV1 + TV2 + TV3 + TV5 |
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
