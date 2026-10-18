# ADR-006 — Evidence retention for unresolved disputes

**Status:** ACCEPTED  
**Decision date:** 2026-10-18  
**Scope:** Data lifecycle, Dispute Mock, Manager recovery, observability; no new user actor or GPU feature.  
**Sources:** `docs/requirements.md` v1.3; `docs/non-functional-requirements.md` v1.2 (NFR-D02/D06/D07/D08); `docs/architecture/quality-attributes.md` v0.12; FR-DP-01..03.

## Context

A Client may submit at most one Dispute in `[terminal_at, terminal_at+7d)`. Normal detailed Job evidence becomes eligible for cleanup after `terminal_at+23d`. A valid, timely filed Dispute may remain OPEN at history expiry due to process crashes, database outages or adjudication bugs. Deleting required evidence would prevent correct oracle-based adjudication and potentially corrupt lifetime reputation.

## Decision (approved)

1. While such a Dispute is OPEN at the expiry boundary, atomically persist a durable retention-exception marker, detection time and reason; preserve the original signed receipt bytes, verifier public key/key ID, protected simulation reference, dispute and relevant Job/reputation attribution. **There is no fixed maximum hold**: required evidence stays until `RESOLVED`.
2. Admin-visible `WARNING` must be recorded no later than 3600 seconds after `detected_at`. When still OPEN at `detected_at+86400s`, severity becomes `CRITICAL` at its due evaluation. Escalation never implies automatic adjudication; Admin remains read-only for business actions.
3. Manager schedules deterministic adjudication retries on successive 900-second due instants while the Manager/DB are healthy; a restart must pick up overdue work using durable due timestamps. Retries are idempotent and never create a second Dispute decision or reputation effect. The policy does not assert that retries happened while the service was offline.
4. If a Dispute resolves after Job history expiry, finalize the decision and one effective reputation adjustment atomically; clean up now-expired linked evidence no later than 3600 seconds after `resolved_at` when services are healthy. If it resolves before expiry, preserve history until the normal expiry.
5. Do not extend unrelated operational audit-log TTLs; domain evidence retained under the exception must be independently sufficient for verification. Restrict sensitive oracle/key metadata access. No unconditional guarantee that every record is physically deleted at exactly 23 days is made.

## Rationale and consequences

- Preserves the ability to decide UPHELD/REJECTED from independently persisted ground truth and correct lifetime reputation.
- Trades a bounded retention duration for correctness and verifiability in exceptional failure cases. It can increase storage and privacy risk during a prolonged outage; expose an operational CRITICAL warning and investigate rather than silently purging or inventing a decision.
- The eventual physical design may use an exception row or equivalent durable metadata; the exact table/queue structure is deferred to Database Design.

## Deterministic verification

Existing approved `DAT-06`, `DAT-07` and `DAT-08` verify basic hold, release and crash handling. Proposed new checks `DAT-EX-01..06` in `quality-attributes.md` cover warning deadline, CRITICAL threshold, retries, restart recovery, post-resolution cleanup and lack of silent hard purge. **All tests are NOT_RUN** and the addendum cases still need test-design review. Record `detected_at`, due instants, Job/Dispute IDs and the resulting effective reputation counters in each test report.

## Non-goals

No automatic REJECTED/UPHELD fallback at a calendar deadline; no manual Admin arbitration in MVP; no retention extension for unrelated audit data; no claim of production-grade privacy/erasure compliance.
