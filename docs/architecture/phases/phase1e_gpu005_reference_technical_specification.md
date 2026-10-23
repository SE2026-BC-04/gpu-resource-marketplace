# GPU-005-B Reference Technical Specification

**Status:** `DRAFT — PROPOSED — NOT OWNER APPROVED`
**Baseline:** `main@538802adebeaeb74dcccd0c025f3a7abc81336c0`
**Runtime tests:** `NOT_RUN`
**Cross-phase ACK:** `NOT PROVIDED`
**Owner:** Thành viên 5 — GPU-005

## 1. Scope and approved invariants

This document specifies the proposed protected deterministic simulation reference created during `TX-SUBMIT`. It does not change API Contract, Database Design, ADR-004, or the internal dispatch allowlist.

The following invariants are already present in the baseline design:

- An accepted Job has exactly one protected simulation reference.
- Job and reference are created atomically in `TX-SUBMIT`.
- The reference is immutable after creation.
- The public Job DTO, frontend DTO, and Simulator dispatch do not contain the reference.
- The Simulator does not access PostgreSQL or protected reference data.
- The dispatch `simulation_input` is exactly `{"workload_profile":"demo-v1"}`.
- The reference fields are `seed_value`, `algorithm_version`, `expected_outcome`, `expected_failure_reason`, and `expected_digest`.
- `expected_digest` has the form `sha256:` followed by 64 lowercase hexadecimal characters.
- Signed Result V1 and its RFC 8785 JCS/Ed25519 boundary remain unchanged.

Evidence: [AGENTS.md](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/AGENTS.md#L30-L38), [Phase 1E](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/architecture/phases/phase1e_job_submission_queue.md#L118-L142), [Database Design](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/design/database-design.md#L307-L319).

The generator details in this document are `PROPOSED — NOT OWNER APPROVED`; the baseline explicitly classified them as `SPEC_REQUIRED`.

## 2. Algorithm identity and byte-level constants

```text
algorithm_version = "demo-v1-public1"
PREFIX_UTF8 = UTF-8 bytes of "GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n"
LF = one byte 0x0A
SEED_DOMAIN = "seed"
OUTCOME_DOMAIN = "outcome"
WORK_UNITS_DOMAIN = "work_units"
```

The prefix ends with exactly one LF byte (`0x0A`). The domain separator is exactly one LF byte (`0x0A`). There is no CR byte.

For canonical input bytes `I`, domain string `D`, and counter `C`:

```text
H(D, C) = SHA-256(
    PREFIX_UTF8
    || UTF-8(D)
    || LF
    || I
    || LF
    || UINT32_BE(C)
)
```

`UINT32_BE(C)` is exactly four bytes, unsigned 32-bit big-endian. The initial counter is `0`. If rejection sampling rejects a candidate, the counter increases by exactly `1` and the next candidate is derived with that counter.

The canonical JSON byte sequence has no automatically appended final newline. The LF bytes shown above are only the prefix/domain separators in the hash input; they are not appended to the JCS document.

These constants are now explicit in this proposed document. The three previously verified vectors are retained unchanged. No vector byte was changed in this documentation revision; therefore no vector recomputation or changed digest explanation is required.

## 3. Exact canonical input

The input object contains exactly these fields:

```json
{"algorithm_version":"demo-v1-public1","duration_seconds":60,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","requested_gpu_count":2,"worker_id":"11111111-1111-4111-8111-111111111111","workload_profile":"demo-v1"}
```

The object is serialized with RFC 8785 JCS and encoded as UTF-8. No final newline is added.

For V2 and V3, only `duration_seconds` changes to `2` and `1` respectively. All other fields remain identical.

## 4. Seed conversion

Let:

```text
seed_digest = H(SEED_DOMAIN, 0)
u64 = UINT64_BE(seed_digest[0:8])
seed_value = u64 & 0x7FFFFFFFFFFFFFFF
```

`seed_value` is the exact persisted field name and is compatible with PostgreSQL signed `bigint`.

## 5. Rejection sampling and mapping

For an unsigned 32-bit candidate `r` and range size `n`:

```text
limit = floor(2^32 / n) * n
```

Candidates with `r >= limit` are rejected. The counter is incremented by one and the next candidate is generated. For an accepted candidate:

```text
index = r mod n
```

Outcome mapping:

```text
n = 100
limit = 4,294,967,200
```

| Bucket | Outcome | Failure reason |
|---:|---|---|
| 0–79 | `SUCCESS` | `null` |
| 80–89 | `FAILED` | `WORKER_FAULT` |
| 90–99 | `FAILED` | `JOB_FAULT` |

Work-unit mapping:

```text
n = 1,000,000
limit = 4,294,000,000
work_units = accepted_candidate mod 1,000,000
```

The outcome distribution and all generator constants remain `PROPOSED — NOT OWNER APPROVED`.

## 6. Expected output schema

The proposed canonical simulated-output object contains exactly:

```json
{"duration_seconds":60,"failure_reason":null,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","outcome":"SUCCESS","requested_gpu_count":2,"schema_version":"demo-v1","work_units":522303,"workload_profile":"demo-v1"}
```

Fields:

```text
duration_seconds       integer
failure_reason         null, WORKER_FAULT, or JOB_FAULT
job_id                 UUID string
listing_id             UUID string
outcome                SUCCESS or FAILED
requested_gpu_count    integer
schema_version         demo-v1
work_units             integer
workload_profile       demo-v1
```

The output schema is outside the exact output-field scope of ADR-004 and therefore remains `PROPOSED — NOT OWNER APPROVED` pending Phase 2 owner review.

## 7. Digest

```text
expected_digest = "sha256:" + lowercase_hex(
    SHA-256(UTF-8(JCS_RFC8785(expected_output_object)))
)
```

The JCS output has no final newline. This is compatible with ADR-004’s `result_digest` rule. See [ADR-004](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/architecture/decisions/ADR-004-signed-result.md#L77-L87).

## 8. Fixed vectors

Shared identifiers:

```text
job_id     = 33333333-3333-4333-8333-333333333333
listing_id = 22222222-2222-4222-8222-222222222222
worker_id  = 11111111-1111-4111-8111-111111111111
requested_gpu_count = 2
algorithm_version   = demo-v1-public1
workload_profile    = demo-v1
```

### V1

Input:

```json
{"algorithm_version":"demo-v1-public1","duration_seconds":60,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","requested_gpu_count":2,"worker_id":"11111111-1111-4111-8111-111111111111","workload_profile":"demo-v1"}
```

Output:

```json
{"duration_seconds":60,"failure_reason":null,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","outcome":"SUCCESS","requested_gpu_count":2,"schema_version":"demo-v1","work_units":522303,"workload_profile":"demo-v1"}
```

```text
seed_value = 3035342533442321017
outcome_raw = 300757047
outcome_bucket = 47
work_units = 522303
expected_digest = sha256:a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c
```

### V2

Input:

```json
{"algorithm_version":"demo-v1-public1","duration_seconds":2,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","requested_gpu_count":2,"worker_id":"11111111-1111-4111-8111-111111111111","workload_profile":"demo-v1"}
```

Output:

```json
{"duration_seconds":2,"failure_reason":"WORKER_FAULT","job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","outcome":"FAILED","requested_gpu_count":2,"schema_version":"demo-v1","work_units":634290,"workload_profile":"demo-v1"}
```

```text
seed_value = 8887054454783268118
outcome_raw = 3227470086
outcome_bucket = 86
work_units = 634290
expected_digest = sha256:9baaaaa338423c75753ecbd00da615a1f88a006eeb0a512d432635664754b7bf
```

### V3

Input:

```json
{"algorithm_version":"demo-v1-public1","duration_seconds":1,"job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","requested_gpu_count":2,"worker_id":"11111111-1111-4111-8111-111111111111","workload_profile":"demo-v1"}
```

Output:

```json
{"duration_seconds":1,"failure_reason":"JOB_FAULT","job_id":"33333333-3333-4333-8333-333333333333","listing_id":"22222222-2222-4222-8222-222222222222","outcome":"FAILED","requested_gpu_count":2,"schema_version":"demo-v1","work_units":490818,"workload_profile":"demo-v1"}
```

```text
seed_value = 2063102514678027846
outcome_raw = 3078813497
outcome_bucket = 97
work_units = 490818
expected_digest = sha256:f1c9d8e371bd4e6876a73b2414c285c6362fe01bca4d8d432169f4d484b3d749
```

Vector status:

```text
Calculation: VERIFIED CALCULATION
Runtime integration tests: NOT_RUN
Owner approval: NOT PROVIDED
```

## 9. Transaction and protection boundary

`TX-SUBMIT` must create the `QUEUED` Job and its protected reference in the same unit of work. Failure must roll back both records. The reference is not returned in public DTOs and is not placed into internal dispatch.

The Simulator receives only the approved dispatch payload and must not receive `seed_value`, expected outcome, expected digest, protected reference, database credentials, or an oracle secret.

Evidence: [API Contract internal dispatch](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/design/api-contract.md#L739-L762), [Module Design ownership](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/design/module-design.md#L124-L142).

## 10. Deployment compatibility

`algorithm_version` is immutable per Job. The internal dispatch currently does not contain `algorithm_version`; `simulation_input` remains exactly `{"workload_profile":"demo-v1"}`.

Recommended policy:

- `demo-v1` is a frozen workload profile.
- A new Simulator runtime may be deployed only if it remains compatible with `demo-v1-public1`.
- A breaking algorithm requires a new workload profile and separate owner-approved change.
- Adding `algorithm_version` to internal dispatch is outside this draft.

Status: `PROPOSED — NOT OWNER APPROVED`.

## 11. Signed Result and Dispute compatibility

This document does not modify Signed Result V1, its 11 signed fields, Ed25519, JCS, or raw evidence retention. Manager verification remains separate from reference comparison. Dispute may compare an accepted signed claim with the independently persisted reference.

Evidence: [ADR-004](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/architecture/decisions/ADR-004-signed-result.md#L77-L87).

## 12. Explicitly separate GPU-005-B approval from GPU-005-D implementation

### GPU-005-B design approval conditions

- Group lead approval of public deterministic reference policy.
- Approval of exact constants, canonical input/output, distribution, and version policy.
- TV2 schema/permission review.
- TV4/TV5 decision on replay after Listing `PAUSED`.
- Phase 2 owner review of output and Signed Result/Dispute compatibility.
- Cross-phase ACKs, if required by the final change classification.

### GPU-005-D implementation blockers

- No approved generator implementation.
- No verified real PostgreSQL transaction.
- No verified Listing-first lock implementation.
- No verified authentication integration.
- No verified idempotency/concurrency behavior.
- No runtime vector tests.

The second list must not be mislabeled as a GPU-005-B design rejection; it is implementation readiness for GPU-005-D.

## 13. Planned verification

All runtime and integration tests remain `NOT_RUN`:

- JCS interoperability.
- Byte-level prefix/domain/counter tests.
- Rejection sampling boundary tests.
- V1/V2/V3 runtime generator tests.
- Atomic Job/reference transaction tests.
- Idempotency/concurrent duplicate tests.
- Simulator compatibility tests.
- Signed Result digest verification.
- Dispute/reference comparison.

## 14. Required decisions

| Decision | Required owner | Status |
|---|---|---|
| Public outcome predictability | Group lead + Phase 2 owner | `PROPOSED — NOT OWNER APPROVED` |
| Exact algorithm constants | Group lead + TV2/Phase 2 | `PROPOSED — NOT OWNER APPROVED` |
| Exact output schema | Phase 2 owner + group lead | `PROPOSED — NOT OWNER APPROVED` |
| Outcome distribution | Group lead + Phase 2 owner | `PROPOSED — NOT OWNER APPROVED` |
| Version compatibility | Group lead + Phase 2 owner | `PROPOSED — NOT OWNER APPROVED` |
| Replay after Listing `PAUSED` | TV4 + TV5 + group lead | `BLOCKED` |
| Reference grants/permissions | TV2 + group lead | `PROPOSED — NOT OWNER APPROVED` |
