# ADR-001 — Modular Monolith with separate API, Manager and Worker Simulator processes

**Status:** ACCEPTED — formal record of an **already-approved** architectural boundary, not a new design decision  
**Recorded:** 2026-10-18  
**Decision provenance:** Previously approved in `docs/architecture/system-architecture.md` §3 and its decision register; this ADR supplies the missing rationale and repository record. The original approval date is not asserted here.  
**Scope:** GPU Resource Marketplace, simulation-only MVP  
**Implementation and tests:** `NOT_RUN`; no working deployment or benchmark is claimed.  
**Repository path:** `docs/architecture/decisions/ADR-001-modular-monolith.md`

## 1. Context and goal

The five-person MVP combines Worker GPU Listings, Client-selected Jobs, strict per-Listing FIFO scheduling, deterministic simulation, Ed25519-signed results, automatic disputes and lifetime reputation. These workflows require explicit domain ownership, concurrency-safe persistence and recoverability but do not require an independently deployed microservice fleet.

The architecture must separate interactive HTTP handling from asynchronous scheduling and simulated Worker execution. In particular, the Worker Simulator needs a distinct signing-key boundary and must not be able to authoritatively finalize Jobs or inspect protected simulation ground truth.

**Goal:** use a small, understandable codebase while retaining **separate runtime responsibilities** and the option to test or restart processes independently.

## 2. Decision — previously approved

Adopt a **Modular Monolith** with the following runtime and source-code boundaries:

1. Maintain **one repository and one logical application/domain codebase** for the backend. Domain logic and database repository operations shared by the Backend API and Manager must have a single owning implementation; do not duplicate business rules in each process.
2. Run **Backend API**, **Automated Manager** and **Worker Simulator** as **three separate long-lived runtime processes**. The browser/web frontend and PostgreSQL are distinct supporting components, not additional business microservices.
3. **Backend API** owns authenticated user-facing operations (including Worker Listings, Client Job submission/queued cancellation, Dispute submission and read-only dashboards) and authenticated durable Signed Result ingress; it does not independently allocate GPUs, finalize Jobs or mutate Worker Reputation.
4. **Manager** owns strict FIFO scheduling, transactional allocation/release, reliable execution dispatch coordination, Signed Result verification/finalization, deterministic Dispute resolution, lifetime Reputation effects and retention cleanup.
5. **Worker Simulator** owns deterministic mock execution and signing with the relevant Worker's private Ed25519 key. It has **no direct application PostgreSQL access** and no access to Manager-protected dispute reference/oracle data. Its internal HTTP boundary and callback are specified by **ADR-003**; its DB restriction is recorded by **ADR-002**.
6. PostgreSQL holds **durable authoritative application state**. Process-local caches and memory cannot replace committed Job, attempt, allocation, Outbox/Inbox, Dispute or Reputation state.
7. The system remains a **simulation**: no real GPU execution, real financial settlement, blockchain, Kubernetes or external message broker is introduced by this decision.

These statements document the previously accepted architecture. Exact framework versions and Compose images remain the separately proposed **ADR-008** until approved.

## 3. Architectural options and rationale

The following is a **retrospective explanation** of the approved decision, not a claim that a fresh alternatives review was formally conducted on the recorded date.

| Approach | Strength | Cost or risk | Outcome |
|---|---|---|---|
| Single process with embedded Scheduler/Simulator | Least process setup | HTTP work, background scheduling and signing share a failure/runtime boundary; harder to isolate keys and test independent restarts | Not the selected architecture |
| **Modular Monolith, separate processes (selected)** | Shared domain rules with independent process failures and a dedicated Worker signing boundary; smaller operational scope than microservices | Shared persistence requires strict transaction and module ownership; no full infrastructure-level trust isolation | **ACCEPTED** |
| Independent microservices with service-owned databases | Stronger deployability separation at scale | Distributed transactions/event contracts and operational overhead are unnecessary for simulation-only MVP | Not selected |

This decision follows the approved architecture drivers for data integrity, reliability, security, modifiability, testability and delivery complexity; it does **not** promise measured throughput or high availability.

## 4. Ownership and coordination boundaries

| Component | Allowed responsibility | Forbidden authoritative action |
|---|---|---|
| Web frontend | Role-specific interface and HTTP requests | Trustworthy Job state, cryptographic signing secrets, protected oracle |
| Backend API | Auth/RBAC, Listing/user commands, `QUEUED` Job creation/cancellation, Dispute filing, result Inbox ingress, role-filtered reads | GPU allocation, finalization, reputation mutation outside Manager |
| Manager | FIFO, scheduling, allocations, verified result finalization, dispute decision, reputation and cleanup | Worker private-key ownership; impersonating a Client |
| Worker Simulator | Simulate and sign; receive dispatch and send callback | Direct DB writes or reads; mutation of deterministic ground truth |
| PostgreSQL | Persist committed authoritative domain state | Simulate jobs or hold the Worker's private signing key in publicly readable application state |

**Design rule:** sharing a codebase does not merge the three processes or override these ownership restrictions. Logical module names are recommendations, not required directory/package names.

## 5. Consequences and trade-offs

- **Positive:** simple source/dependency management; reusable transaction-safe domain code; separate crash/restart scenarios for Manager and Simulator; straightforward local demonstration for a five-person team.
- **Costs:** shared PostgreSQL creates contention and a larger database failure domain; mistakes in shared module ownership could allow API-side domain mutations unless implemented and tested carefully.
- **Security limitation:** process separation is **not** proof of security isolation between administrators or hosts. For MVP, Worker signing keys are separated from API/Manager and protected by application/service credentials. Network guarantees are governed by **ADR-005**.
- **Performance limitation:** the 736-VU campaign is a **test design** (ADR-007), not evidence that this process architecture meets p95 objectives.
- **Future changes:** splitting a domain into an independent service requires a new ADR and data/transaction review, not an assumption that logical modules are already distributed services.

## 6. Verification references (design only; `NOT_RUN`)

These checks trace to existing requirements and Quality Attribute Scenarios; they do not add new product features or claim executed test results:

| Check | Pass condition |
|---|---|
| Process separation | API, Manager and Simulator are distinct running processes; stopping one does not require terminating the others |
| Shared domain ownership | API and Manager call a common implementation for shared business invariants instead of maintaining divergent rules |
| Restart recovery | A committed Job/allocation/outbox survives Manager restart and is processed according to ADR-003/005 without duplicate business effects |
| Signing boundary | Simulator-only secrets never appear in API/frontend artifacts; Simulator is not given Manager oracle data |
| Business isolation | Client/Worker API calls cannot finalize a Job or directly alter lifetime Reputation |

Evidence is required before labeling any check `PASS`; otherwise its execution state remains `NOT_RUN`.

## 7. Related decisions and open implementation details

- [ADR-002 — PostgreSQL access boundary](ADR-002-postgresql-access-boundaries.md): which process may touch the application DB directly.
- [ADR-003 — Durable internal communication](ADR-003-internal-communication.md): Manager-to-Simulator dispatch, Simulator-to-API callback, Outbox/Inbox.
- [ADR-004 — Signed Result V1](ADR-004-signed-result.md): signature and verification contract.
- [ADR-005 — Retry, timeout and service authentication](ADR-005-retry-timeout-internal-auth.md): failure recovery on internal HTTP.
- [ADR-006 — Evidence retention](ADR-006-dispute-retention.md): lifecycle exceptions.
- [ADR-007 — Load testing](ADR-007-load-test-configuration.md): reproducible test profile.
- [ADR-008 — Technology stack](ADR-008-technology-stack.md): still **PROPOSED**, not accepted by this ADR.

Exact database tables/indexes/roles, API endpoint payloads, implementation package layout and deployment image pins are **not decided here** and will require their respective later designs.
