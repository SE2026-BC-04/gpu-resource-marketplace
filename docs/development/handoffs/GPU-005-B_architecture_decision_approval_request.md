# GPU-005-B Architecture Decision & Approval Request

**Status:** `DRAFT — PROPOSED — NOT OWNER APPROVED`
**Baseline:** `main@538802adebeaeb74dcccd0c025f3a7abc81336c0`
**Runtime tests:** `NOT_RUN`
**Cross-phase ACK:** `NOT PROVIDED`

## 1. Executive summary

GPU-005-B proposes a protected deterministic simulation reference created atomically with the Job in `TX-SUBMIT`.

The proposal uses:

- Public deterministic generation.
- RFC 8785 JCS.
- SHA-256.
- `seed_value` as the persisted PostgreSQL-compatible field.
- Rejection sampling.
- Algorithm version `demo-v1-public1`.
- Exact canonical input/output objects.
- No reference, seed, expected outcome, digest, or secret in Simulator dispatch.

V1/V2/V3 are `VERIFIED CALCULATION` only. Runtime tests are `NOT_RUN`, cross-phase ACK is `NOT PROVIDED`, and the design is not approved.

Baseline evidence: [GPU-005 handoff](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/development/handoffs/GPU-005_member5_handoff.md#L77-L91), [Phase 1E](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/architecture/phases/phase1e_job_submission_queue.md#L128-L142).

## 2. Recommended option

Approve the following proposal for review:

1. Use the public deterministic algorithm documented in the companion technical specification.
2. Fix the byte-level constants:

```text
SEED_DOMAIN = "seed"
OUTCOME_DOMAIN = "outcome"
WORK_UNITS_DOMAIN = "work_units"
PREFIX_UTF8 = "GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n"
LF = 0x0A
counter = UINT32 big-endian, starting at 0
rejection => counter + 1
JCS output has no final newline
```

3. Keep the internal dispatch unchanged:

```json
{"workload_profile":"demo-v1"}
```

4. Treat `demo-v1` as a frozen workload profile compatible with `demo-v1-public1`.
5. Preserve Signed Result V1 and ADR-004.
6. Keep the three fixed vectors unchanged.

Status: `PROPOSED — NOT OWNER APPROVED`.

## 3. Decisions requiring approval

| Decision | Recommended option | Alternative | Trade-off | Status |
|---|---|---|---|---|
| Public reference | Accept reproducible public algorithm with protected storage boundary | Secret oracle/opaque reference | Public algorithm is testable but predictable | `PROPOSED — NOT OWNER APPROVED` |
| Algorithm version | Freeze `demo-v1` compatibility with `demo-v1-public1` | Manager routing or versioned dispatch | Freeze preserves contract; routing is more flexible | `PROPOSED — NOT OWNER APPROVED` |
| Output schema | Freeze exact schema in companion specification | Defer to Phase 2 | Early freeze stabilizes digest; later changes require versioning | `PROPOSED — NOT OWNER APPROVED` |
| Outcome mapping | 80% `SUCCESS`, 10% `WORKER_FAULT`, 10% `JOB_FAULT` | Other distribution | Simple and unbiased with rejection sampling | `PROPOSED — NOT OWNER APPROVED` |
| PAUSED replay | Joint TV4/TV5/group-lead decision | Replay-first or admission-first | Existing documents have conflicting behavior | `BLOCKED` |

## 4. Cross-phase impact

Missing implementation alone is not classified as `CONFIRMED_IMPACT`. Current classifications are:

| Area | Classification | Reason |
|---|---|---|
| TV2 database/reference | `POTENTIAL_IMPACT` | Schema, permissions and transaction implementation must consume the proposed `seed_value` contract |
| TV3 authentication | `POTENTIAL_IMPACT` | GPU-005 consumes authenticated principal/client identity; no specific contract change is proposed |
| TV4 listings | `POTENTIAL_IMPACT` | Replay ordering conflicts with PAUSED admission semantics |
| Phase 2 Simulator | `POTENTIAL_IMPACT` | Output schema and algorithm-version compatibility require review |
| Signed Result V1 | `NO_IMPACT` proposed | This package does not change ADR-004 |
| Dispute | `POTENTIAL_IMPACT` | Dispute consumes independently protected reference data |
| GPU-005-D implementation | Separate implementation readiness | Not a new design impact classification |

Evidence: [Inter-Phase Change Control](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/538802adebeaeb74dcccd0c025f3a7abc81336c0/docs/development/interphase-change-control.md#L9-L18).

## 5. Required reviewers

| Reviewer | Review scope |
|---|---|
| Group lead | Architecture policy, public predictability, versioning, unresolved conflicts |
| TV2 | `seed_value`, reference schema, grants, UoW and transaction boundary |
| TV3 | Authenticated principal and client identity consumed by GPU-005 |
| TV4 | ACTIVE/PAUSED admission, Listing lock and replay behavior |
| Member 5 | TX-SUBMIT, idempotency, protected reference integration |
| Phase 2 owner | Simulator output, version compatibility, Signed Result and Dispute |

No ACK is created or implied by this document.

## 6. GPU-005-B approval checklist

- [ ] Public deterministic reference policy approved.
- [ ] Exact prefix and LF bytes approved.
- [ ] Exact domain labels approved: `seed`, `outcome`, `work_units`.
- [ ] UINT32 big-endian counter and rejection increment approved.
- [ ] No-final-newline JCS rule approved.
- [ ] Exact canonical input approved.
- [ ] Exact expected output schema approved.
- [ ] Outcome distribution approved.
- [ ] `seed_value` field and signed-bigint conversion approved.
- [ ] `demo-v1`/`demo-v1-public1` compatibility policy approved.
- [ ] Signed Result V1 compatibility confirmed by Phase 2 owner.
- [ ] Replay-on-PAUSED resolved by TV4/TV5/group lead.
- [ ] TV2 schema/permission review completed.
- [ ] Required cross-phase ACKs provided with evidence.
- [ ] V1/V2/V3 retained unchanged and labeled `VERIFIED CALCULATION`.
- [ ] Runtime tests remain `NOT_RUN` until actually executed.

## 7. GPU-005-D implementation blockers

These are implementation blockers, not additional GPU-005-B design decisions:

- Approved generator specification is required before generator implementation.
- Real GPU-002 Job/reference repositories and UoW are required.
- Real Listing-first locking is required.
- Real GPU-003 principal/client identity integration is required.
- Idempotency and concurrent duplicate behavior must be implemented and tested.
- Replay-on-PAUSED must be resolved before full TX-SUBMIT acceptance.
- Runtime vector, PostgreSQL, Simulator, Signed Result and Dispute tests must run.

The absence of these implementations does not by itself justify `CONFIRMED_IMPACT`; each concrete interface or behavior change must be reviewed under change control.

## 8. GPU-005-C readiness

After coding authorization, GPU-005-C may develop independently:

- Public Job DTOs.
- Request validation.
- Route/controller structure.
- Read projections.
- Cancel validation.
- Idempotency header parsing.
- Mock-based unit tests.

GPU-005-C must wait for upstream integration before relying on:

- TV2 repository/UoW signatures.
- `simulation_references` schema and permissions.
- TV4 Listing query/lock/capacity behavior.
- TV3 principal/client-ID implementation.
- Final PAUSED replay semantics.

## 9. Approval blockers remaining

The package remains `DRAFT — PROPOSED — NOT OWNER APPROVED` because the following remain unresolved:

1. Group-lead approval of public predictability.
2. Exact output-schema approval.
3. Outcome-distribution approval.
4. Algorithm-version deployment compatibility approval.
5. TV4/TV5/group-lead replay decision for PAUSED Listing.
6. TV2 protection and permission confirmation.
7. Phase 2 owner confirmation for Simulator/Signed Result/Dispute compatibility.
8. Cross-phase ACKs.

## 10. Review request

Please review the companion technical specification and record decisions for the checklist above. Until those decisions and ACKs exist, this package must not be labeled `APPROVED_DESIGN`, and no runtime test may be labeled `PASS`.
