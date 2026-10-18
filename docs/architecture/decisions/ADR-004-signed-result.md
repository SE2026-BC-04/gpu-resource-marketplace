# ADR-004 - Canonical Ed25519 signed-result contract

**Status:** ACCEPTED (2026-10-18) - V1 JCS/Ed25519 signing contract, enum semantics, wire encodings, JSON Schema and public verification vector approved for design; implementation/tests `NOT_RUN`  
**Version:** 0.4 (V1 wire contract accepted 2026-10-18; documentation-only status update, no MVP scope change)  
**Decision date:** 2026-10-18  
**Prerequisite:** [ADR-003 (ACCEPTED)](ADR-003-internal-communication.md)  
**Owners:** Result Verification / Worker Simulator / Backend API  
**Scope:** Cryptographic wire format and signing verification. The project is simulation-only; signing is not proof of real GPU work.

## 1. Context

The Worker Simulator signs a result and sends it through an authenticated HTTP callback to the Backend API. The API durably stores raw signed input in `result_inbox`; the Manager checks the signature against a registered Worker public key and binds the claimed Worker, Listing, Job and `attempt_id` before accepting one final result. A dispute uses independently persisted deterministic reference data to determine whether a correctly signed *claim* is truthful. HTTP service authentication is distinct from receipt signatures.

Raw JSON is not safe to sign naively across different serializers: key order, whitespace, string escaping, numeric encodings and timestamps may differ even if two parsers produce equivalent objects. The project requires a byte-exact, versioned contract before writing interoperable signer/verifier implementations.

## 2. Options evaluated

| Alternative | Advantage | Risk/cost | Assessment |
|---|---|---|---|
| A - Sign ordinary `JSON.stringify` bytes | Fast for a single JavaScript runtime | Serialization may change by runtime/field order; difficult cross-language compatibility | REJECT for cross-process cryptographic contract |
| **B - RFC 8785 JCS canonical JSON + UTF-8 domain prefix + Ed25519** | Deterministic serialization across conforming languages, JSON-compatible HTTP/DB tooling, supports versioned receipts | Need vetted JCS library; strict value/number rules | **ACCEPTED (cryptographic approach)** |
| C - Deterministic CBOR / binary envelope | Compact and unambiguous if profiled rigorously | Less readable; additional tooling and interop test burden | DEFER |

## 3. Accepted V1 wire contract (2026-10-18)

**Payload fields (all covered by the Ed25519 signature):**

| Field | Accepted type and validation |
|---|---|
| `schema_version` | ASCII string `"1"`; any other version rejected by the V1 verifier unless separately supported |
| `result_id` | RFC 9562 UUIDv4 in canonical lowercase format; unique across result ingestion |
| `job_id` | Existing Job ID; must equal persisted current Job |
| `attempt_id` | Stable logical execution attempt ID; must equal current RUNNING attempt; retry uses same ID |
| `worker_id` | Existing Worker ID; match selected Listing owner and registered key |
| `listing_id` | Existing Listing ID; must match the Job's chosen Listing |
| `outcome` | **ACCEPTED:** exact uppercase string `SUCCESS` or `FAILED`; maps to Job terminal state only after valid signature/context checks |
| `failure_reason` | **ACCEPTED:** JSON `null` iff `SUCCESS`; exact uppercase `WORKER_FAULT` or `JOB_FAULT` iff signed `FAILED`. `SYSTEM_FAULT` is Manager-owned, never a value in Signed Result V1 |
| `result_digest` | Lowercase `sha256:` + 64 hex digits over canonical simulated output bytes; never a Client-supplied adjudication outcome |
| `finished_at` | Worker-reported UTC timestamp string using fixed `YYYY-MM-DDTHH:mm:ss.ffffffZ`; not authoritative Job `terminal_at` |
| `key_id` | Public key-version identifier registered to that Worker; archived verifying public keys retained while related evidence exists |

### 3.1. Accepted outcome/failure semantic contract (review decision, 2026-10-18)

The user approved the exact V1 enum combinations and their **verified, contextualized, first-acceptance-only** effects. The Worker-supplied `outcome` is a signed **claim**, not independently trusted ground truth. This section is **ACCEPTED for design**, and its tests are `NOT_RUN`.

| V1 `outcome` | V1 `failure_reason` | After one valid receipt is accepted | Lifetime Worker counters |
|---|---|---|---|
| `SUCCESS` | JSON `null` | Job -> `COMPLETED` | `successful_jobs += 1`; `worker_fault_jobs` unchanged |
| `FAILED` | `WORKER_FAULT` | Job -> `FAILED` | `worker_fault_jobs += 1`; `successful_jobs` unchanged |
| `FAILED` | `JOB_FAULT` | Job -> `FAILED` | Neither counter changes |
| `FAILED` | JSON `null` or `SYSTEM_FAULT` | **Reject invalid V1 receipt** | No state/counter effect |
| `SUCCESS` | Any non-null value | **Reject invalid V1 receipt** | No state/counter effect |
| Any other enum/spelling/case/missing field | Any value | **Reject invalid V1 receipt** | No state/counter effect |

- A Manager-only timeout/unavailable-result path may close a Job as `FAILED` with a **system-owned** `SYSTEM_FAULT` classification, without producing or accepting a Worker-signed V1 receipt. It never penalizes Worker Reputation. The bounded timeout/retry policy remains **OPEN in ADR-005**.
- Verified-but-inaccurate signed claims stay preserved: deterministic Dispute adjudication can later mark the dispute `UPHELD` and adjust the **effective** per-Job classification/counters **once** without editing the original receipt.
- Rejecting an invalid receipt does not imply automatically terminalizing a Job. The Manager applies its separately approved retry/fallback policy; invalid signed input cannot by itself change job status, release allocation or alter reputation.
- Signature validation, role/worker/listing/job/attempt binding, and unique terminal effects are independent mandatory acceptance gates. A well-formed pair of enum values alone is never sufficient.

**Approved deterministic enum test designs (all execution statuses: `NOT_RUN`):**

| ID | Setup and action | Binary PASS oracle |
|---|---|---|
| `ENUM-01` | Valid, correctly signed and correctly bound `SUCCESS` + `null` receipt for one `RUNNING` Job; replay exact callback | Job is `COMPLETED`; `successful_jobs` delta exactly `+1`; `worker_fault_jobs` delta `0`; exactly one accepted result and one GPU release after replay |
| `ENUM-02` | Valid signed/bound `FAILED` + `WORKER_FAULT` receipt; replay | Job is `FAILED`; `worker_fault_jobs` delta exactly `+1`; `successful_jobs` delta `0`; one accepted result/release after replay |
| `ENUM-03` | Valid signed/bound `FAILED` + `JOB_FAULT` receipt | Job is `FAILED`; both lifetime counter deltas `0`; exactly one accepted result/release |
| `ENUM-04` | Signed/bound `SUCCESS` + `WORKER_FAULT` or `JOB_FAULT` (each fixture) | Schema rejection for both; no acceptance/finalization, release, or reputation effects from either receipt |
| `ENUM-05` | Signed/bound `FAILED` + `null` or `SYSTEM_FAULT` (each fixture) | Schema rejection for both; no acceptance/finalization, release, or reputation effects from either receipt |
| `ENUM-06` | Signed/bound receipt with unknown/missing/case-changed `outcome` or `failure_reason` (each fixture); separately trigger Manager-owned timeout fallback without an accepted receipt | All invalid enum receipts rejected with no business effects; only Manager fallback, if its ADR-005 conditions are met, produces `FAILED/SYSTEM_FAULT` with counter deltas `0` and exactly one release |

The timeout fixture in `ENUM-06` is **BLOCKED for execution until ADR-005 provides a deterministic deadline**, and must not be reported as passed before then. ADR-004 accepts the V1 canonicalization and wire encoding in Sections 3.2-3.4, but does not approve numeric retry/timeout budgets or HTTP error/status contracts.

### 3.2. Accepted exact V1 wire encodings (2026-10-18)

**Goal:** avoid implementation-dependent interpretations between Python API/Manager and the Worker Simulator. The following V1 encodings are **ACCEPTED for design** together with the enum semantics in Section 3.1; application implementation and integration tests remain `NOT_RUN`.

| Component | Accepted exact V1 rule | Deterministic rejection |
|---|---|---|
| `schema_version` | JSON string exactly `"1"`, not integer `1` | Unknown/nonstring version => reject V1 |
| `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `key_id` | JSON strings containing **RFC 9562 UUIDv4** rendered as canonical **lowercase** `8-4-4-4-12` hex with hyphens; no whitespace or braces | Uppercase, missing dashes, non-v4 UUID or nonstring => reject V1; persisted ID/ownership must still match |
| `finished_at` | UTC string exactly `YYYY-MM-DDTHH:mm:ss.ffffffZ` (six fractional digits, uppercase `T`/`Z`, valid Gregorian date/time) | Missing six-digit fraction, offset e.g. `+07:00`, invalid date, leap second or wrong case => reject V1 |
| `result_digest` | JSON string `sha256:` + **exactly 64 lowercase hex** over `SHA256(UTF8(JCS_RFC8785(simulated_output_json_object)))` | Wrong prefix, uppercase hex, incorrect length or nondeterministic/invalid output JSON => reject or fail matching oracle as applicable |
| `signature` (outer HTTP envelope) | Base64url **without `=` padding** of **exactly 64 Ed25519 signature bytes**, 86 ASCII base64url characters | Padding, noncanonical alphabet, failed decode or length !=64 => reject |
| `signature_encoding` (outer HTTP envelope) | ASCII string exactly `base64url-no-padding`; no alternate encodings permitted in V1 | Anything else => reject |
| Versioned signing input | ASCII prefix bytes `GPU-MARKETPLACE:SIGNED-RESULT:V1\n`, followed by UTF-8 RFC 8785 JCS serialization of **all and only** 11 payload fields, with no signature metadata included | Prefix mismatch, missing/extra/duplicate JSON keys, malformed JSON, unexpected primitive types => reject |

Additional semantics: `finished_at` is Worker-reported and **never** defines trusted `terminal_at`, dispute filing cutoff or 23-day cleanup eligibility. The Manager uses server/database-trusted times for those. `result_digest` is a hash of the Worker's claimed deterministic output object, while the immutable **independent** simulation reference holds the expected outcome/digest for a later Dispute. This ADR proposes the digest algorithm, **not** the shape of all simulated-output fields, which must be defined with the simulation/API contract. `JCS` does not silently normalize Unicode, and invalid I-JSON values/duplicate property names must be rejected at strict parsing.

**Illustrative output-object digest fixture (ASCII only):**

```json
{"job_id":"22222222-2222-4222-8222-222222222222","value":"ok"}
```

The JSON above is already JCS-canonical. Its UTF-8 SHA-256 is:

```text
sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38
```

**Complete V1 payload fixture (fixed public verification vector in Section 3.4):**

```json
{
  "schema_version": "1",
  "result_id": "11111111-1111-4111-8111-111111111111",
  "job_id": "22222222-2222-4222-8222-222222222222",
  "attempt_id": "33333333-3333-4333-8333-333333333333",
  "worker_id": "44444444-4444-4444-8444-444444444444",
  "listing_id": "55555555-5555-4555-8555-555555555555",
  "outcome": "SUCCESS",
  "failure_reason": null,
  "result_digest": "sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38",
  "finished_at": "2026-10-18T08:00:00.000000Z",
  "key_id": "66666666-6666-4666-8666-666666666666"
}
```

**Deterministic encoding test designs (all execution statuses `NOT_RUN`):**

| ID | Fixture/action | PASS oracle |
|---|---|---|
| `WIRE-01` | Valid UUIDv4 strings for all six identifiers, then uppercase/invalid-format/type variants | Valid format accepted; every invalid variant rejected; DB matching still required |
| `WIRE-02` | Parse exact UTC microsecond timestamp, then offsets/omitted precision/invalid dates | Exactly one canonical form accepted; all noncanonical/invalid variants rejected |
| `WIRE-03` | Hash fixed output-object fixture via two independent conforming implementations | Both produce the exact 64-hex digest shown above and agree byte-for-byte on canonical output |
| `WIRE-04` | Encode/decode a 64-byte Ed25519 signature; then padded/alternative-encoding/length-mutated inputs | Canonical signature is exactly 86 base64url characters and round trips; malformed signatures are rejected |
| `WIRE-05` | Serialize all 11 fields in permuted JSON key order and sign fixed domain-prefixed bytes | Both runtimes generate identical signing bytes; altered prefix/version fails signature validation |
| `WIRE-06` | Duplicate payload key, extra field, missing field, forbidden numeric primitive | Reject before acceptance/finalization; no Job/Reputation effect |
| `WIRE-07` | Worker changes claimed `finished_at` while server-owned `terminal_at` is fixed | Signed input mutation fails signature; valid newly signed Worker timestamp does not alter retention/dispute boundaries |

**Approved scope (2026-10-18):** canonical UUIDv4 casing, UTC microsecond timestamps, digest input algorithm, unpadded Base64url signature, exact signing prefix, V1 envelope schema and fixed public verification vector. The simulated-output object's full schema, HTTP status codes, physical database columns and actual cross-runtime product implementation are **outside this ADR**. No product test is claimed to have run.

**Canonical bytes (ACCEPTED):**

```text
payload_json = JCS_RFC8785(payload)            # strict valid JSON; use a conformant library
signed_bytes = UTF8("GPU-MARKETPLACE:SIGNED-RESULT:V1\n") || UTF8(payload_json)
signature = Ed25519.Sign(worker_private_key, signed_bytes)
```

The prefix provides **domain separation**, so these bytes cannot be confused with a signature for another API or document. Do not sign an object containing its own signature field. The HTTP callback wraps `{payload, signature, signature_encoding}`; `signature_encoding` is fixed to `base64url-no-padding`, and is not inside the payload. The Manager reconstructs the signed bytes from the exact accepted schema and validates both signature and contextual ownership.

**Compatibility policy:** once published, V1 validation and signed bytes are immutable. A future V2 introduces a separate versioned schema and signed-byte prefix; never silently add or reorder V1 fields. Retained V1 receipts, including evidence preserved past 23 days for an unresolved Dispute, must remain verifiable. Key rotation management UI is not an MVP requirement.

**Input discipline:** use strings for UUID-like IDs and timestamps; no floats, NaN, Infinity or ambiguous timestamps in the signed V1 schema. Enforce exact allowed field set (reject missing/extra fields unless expressly versioned). Public keys are looked up by `(worker_id, key_id)` and must match the Job's selected Listing; never trust a supplied public key in the callback as authority.

**Storage and trust:** API stores the raw payload and signature durably without making the cryptographic business decision. Manager verifies signature and persisted context; only a successful acceptance transaction can terminalize and update reputation. A cryptographically valid but oracle-inaccurate result remains potentially disputable. Always preserve the original signed evidence bytes; finalization and historical verification are distinct operations.

### 3.3. V1 machine-readable JSON Schema (ACCEPTED)

This is the **same V1 receipt** from Section 3.2, expressed as one JSON Schema Draft 2020-12 for the HTTP envelope. It is **not a new feature, API endpoint or database schema**. The API can validate the envelope before storing it; the Manager must still verify Ed25519, ownership, attempt binding, temporal state and once-only business effects. A conforming verifier **must reject duplicate JSON property names before parsing** (a parsed object/JSON Schema alone cannot detect duplicates). It must also validate actual Gregorian calendar dates, which the regex alone cannot fully establish, and reject non-I-JSON/JCS-invalid values. Strict Base64url decoding must re-encode to the identical unpadded form and yield exactly 64 signature bytes.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GPU Marketplace Signed Result V1 HTTP Envelope",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "payload",
    "signature",
    "signature_encoding"
  ],
  "properties": {
    "payload": {
      "$ref": "#/$defs/payload"
    },
    "signature": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{86}$"
    },
    "signature_encoding": {
      "type": "string",
      "const": "base64url-no-padding"
    }
  },
  "$defs": {
    "uuid_v4": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "payload": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "schema_version",
        "result_id",
        "job_id",
        "attempt_id",
        "worker_id",
        "listing_id",
        "outcome",
        "failure_reason",
        "result_digest",
        "finished_at",
        "key_id"
      ],
      "properties": {
        "schema_version": {
          "type": "string",
          "const": "1"
        },
        "result_id": {
          "$ref": "#/$defs/uuid_v4"
        },
        "job_id": {
          "$ref": "#/$defs/uuid_v4"
        },
        "attempt_id": {
          "$ref": "#/$defs/uuid_v4"
        },
        "worker_id": {
          "$ref": "#/$defs/uuid_v4"
        },
        "listing_id": {
          "$ref": "#/$defs/uuid_v4"
        },
        "outcome": {
          "type": "string",
          "enum": [
            "SUCCESS",
            "FAILED"
          ]
        },
        "failure_reason": {
          "enum": [
            null,
            "WORKER_FAULT",
            "JOB_FAULT"
          ]
        },
        "result_digest": {
          "type": "string",
          "pattern": "^sha256:[0-9a-f]{64}$"
        },
        "finished_at": {
          "type": "string",
          "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\\.[0-9]{6}Z$"
        },
        "key_id": {
          "$ref": "#/$defs/uuid_v4"
        }
      },
      "oneOf": [
        {
          "properties": {
            "outcome": {
              "const": "SUCCESS"
            },
            "failure_reason": {
              "type": "null"
            }
          }
        },
        {
          "properties": {
            "outcome": {
              "const": "FAILED"
            },
            "failure_reason": {
              "enum": [
                "WORKER_FAULT",
                "JOB_FAULT"
              ]
            }
          }
        }
      ]
    }
  }
}
```

**Status:** V1 JSON Schema accepted for design on 2026-10-18. `Draft202012Validator.check_schema` and representative positive/negative enum fixtures were checked locally while authoring the document; **no product-level `WIRE-*` or `SIG-*` integration test has been executed**. A local schema self-check does **not** establish RFC 8785 interoperability for arbitrary Unicode/numbers.

### 3.4. Frozen public verification vector for V1 (ACCEPTED)

This vector uses the illustrative V1 payload and simple ASCII output-object fixture already shown in Section 3.2. For this specific ASCII-only fixture, compact JSON with lexicographically sorted member names matches RFC 8785 JCS; general implementations **must use a conforming JCS implementation**, not substitute arbitrary `json.dumps(sort_keys=True)` or `JSON.stringify` for all inputs.

**Canonical simulated-output JSON (UTF-8, no trailing newline):**

```json
{"job_id":"22222222-2222-4222-8222-222222222222","value":"ok"}
```

- Expected `result_digest`: `sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38`.
- Signing prefix is exactly the 33 ASCII bytes ``GPU-MARKETPLACE:SIGNED-RESULT:V1\n`` where `\n` denotes one LF byte (`0x0a`), **not** two printable characters.
- **Canonical payload JSON (500 UTF-8 bytes; no newline at end):**

```json
{"attempt_id":"33333333-3333-4333-8333-333333333333","failure_reason":null,"finished_at":"2026-10-18T08:00:00.000000Z","job_id":"22222222-2222-4222-8222-222222222222","key_id":"66666666-6666-4666-8666-666666666666","listing_id":"55555555-5555-4555-8555-555555555555","outcome":"SUCCESS","result_digest":"sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38","result_id":"11111111-1111-4111-8111-111111111111","schema_version":"1","worker_id":"44444444-4444-4444-8444-444444444444"}
```

- Signed bytes: `ASCII_PREFIX || UTF8(CANONICAL_PAYLOAD_JSON)`; total **533 bytes**.
- Expected SHA-256 of signed bytes (a test oracle, **not** the Ed25519 signature): `152b4b0f1dd8c4a1ed96524247dc682892a0cfa661fbc396d32af5bfdcd16728`.
- Public test Ed25519 key (32-byte raw hex; **not secret**): `d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a`.
- Expected Ed25519 signature (64 bytes, Base64url without padding):

```text
903mx-bzZtTjVuZR_r6BfuZt-ghu4IG_Tknq1_wkFTv4SFE91BJ_1uDXwt-AGU71cki9s-xzwU8QdRQOWQT2AQ
```

**Oracle:** verify the signature against the raw public key and the exact 533 signed bytes: verification must succeed. Change any one signed field or the LF/domain prefix without creating a new signature: verification must fail. Reorder input JSON properties or add non-significant whitespace: strict parsing + JCS must reconstruct identical bytes. Reuse the same `result_id` with different signed bytes: integrity conflict, not overwrite. A separate Worker key or a mismatched persisted `attempt_id` must fail the Manager's *contextual* acceptance even if raw cryptographic verification succeeds. The public key/signature can be checked without publishing any private key; **no signing seed/private material is part of the deliverable**.

The authoring fixture was checked with Python Ed25519 cryptography; this is **documentation-vector verification only**, not a claim that the application or a production signer/verifier exists. The test suite `WIRE-01..07`, `SIG-01..12` is still `NOT_RUN` (and the cross-runtime test is not fulfilled by an authoring self-check).

## 4. Fixed V1 decisions and implementation boundaries

1. **ACCEPTED:** RFC 8785 JCS serialization, Ed25519, and the exact `GPU-MARKETPLACE:SIGNED-RESULT:V1\n` signing prefix in Section 3.2. Cross-runtime product interoperability remains to be tested.
2. **ACCEPTED:** the `outcome`/`failure_reason` combinations in Section 3.1 and the `result_digest` input/encoding in Section 3.2. The full simulation-output schema is outside this signing-contract ADR.
3. **ACCEPTED:** canonical lowercase UUIDv4 IDs, six-digit UTC `finished_at`, fixed V1 payload/envelope fields, and unpadded Base64url Ed25519 signature; HTTP response/error codes are not defined here.
4. **REQUIRED BY EXISTING ARCHITECTURE:** verify archived `(worker_id, key_id)` public keys while retained signed evidence exists; private keys must never be published or stored in tracked artifacts. This ADR does not add a key-management UI.
5. **ACCEPTED FOR DESIGN:** V1 Draft 2020-12 JSON Schema and the fixed public canonical-byte/signature vector in Sections 3.3-3.4. The documentation fixture check is not evidence of a working application verifier.

No additional V1 wire-format design decision remains pending **inside ADR-004**. ADR-005 timeout/retry and service-authentication details, database columns and API error/status codes stay separately open. All implementation, interop and integration tests remain `NOT_RUN`.

## 5. Mandatory deterministic test designs for implementation (`NOT_RUN`)

| ID | Fixture/action | Exact PASS condition |
|---|---|---|
| `SIG-01` | Same payload with different JSON key order/whitespace | Conformant implementations compute identical JCS bytes and signed bytes |
| `SIG-02` | Serialize fixed fixture in two selected runtimes | Byte-for-byte equal canonical payload and domain-prefixed signed bytes |
| `SIG-03` | Generate an ephemeral Ed25519 key, sign V1, verify with its public key | Signature verifies; private key is not committed/logged |
| `SIG-04` | Mutate each signed field (including result digest/version/time), keeping old signature | Every altered signed input is rejected |
| `SIG-05` | Verify under another Worker's registered key or forged `key_id` | Always rejected; no mutation to Job/Reputation |
| `SIG-06` | Reuse authentic signature for a different Job/Listing/attempt | Rejected on contextual binding even if cryptographic verification succeeds |
| `SIG-07` | Unsupported `schema_version` and malformed/extra JSON fields | Rejected with defined validation error; no finalization |
| `SIG-08` | Replay same receipt; reuse `result_id` with different bytes | Identical replay idempotent; different bytes conflict; at most one terminal business effect |
| `SIG-09` | Retained V1 receipt signed by historical key; rotate active public key | Retained V1 verifies with archived key; key material remains nonsecret |
| `SIG-10` | Valid signature claiming wrong simulated outcome vs protected oracle | Signature verification succeeds; eligible Dispute resolves `UPHELD`; no overwrite of original bytes |
| `SIG-11` | Future V2 in a test-only change exercise | V2 verifies under V2 rules, V1 bytes remain verifiable and unchanged |
| `SIG-12` | Invalid UTC timestamp/number/NaN/duplicate JSON object key | Strict parsing/schema rejects rather than interpreting ambiguous payload |

For each test preserve test ID, input fixture, expected canonical-byte hash, actual bytes/hash, public key ID, error type, commit SHA and `PASS/FAIL` output. `SIG-11` is an evolution/change-exercise test, **not mandatory V2 implementation in MVP**. Until implemented, every test is `NOT_RUN`; if a chosen RFC8785 library/schema is missing, execution is `BLOCKED`, not PASS.

## 6. Consequences and trade-offs

- **Modifiability vs cryptographic compatibility:** a versioned schema costs more setup but avoids retroactive changes to signed evidence.
- **Security vs developer ergonomics:** strict canonical inputs reject loose JSON, timezone forms and extra fields; this is deliberate.
- **Performance:** JCS/Ed25519 verification adds CPU cost; profile under the approved 736-VU workload rather than assume compliance.
- **Not equivalent to attestation:** a valid Worker signature is an integrity/identity check; oracle-based truthfulness is handled separately by Dispute Mock.

## 7. Final decision and scope

**ADR-004 is ACCEPTED (2026-10-18).** The approved Signed Result V1 design consists of RFC 8785 JCS + Ed25519 + exact versioned signing prefix, the 11-field signed payload and its allowed enum combinations, the fixed wire encodings, JSON Schema and public verification vector in Sections 3.1-3.4. The V1 contract is now the implementation reference; incompatible changes require a new versioned decision, not silent edits to V1.

This is **design acceptance only**: the application signer/verifier has not been implemented or tested, all `ENUM-*`, `WIRE-*` and `SIG-*` product tests remain `NOT_RUN` (and the Manager-timeout portion of `ENUM-06` is `BLOCKED` pending ADR-005). No new feature, database/API design, coding work, change to already accepted ADRs, or extension of MVP scope is authorized by this documentation decision.
