# TV5 Phase 2E Stage A — Runtime Composition Evidence (DRAFT)

**State:** `CODE_AUTHORIZED_WITH_LIMITS` · `LOCAL_VERIFICATION_PASS` · `DRAFT/HOLD`
**Authorization:** TV1 `DEC-P2E-STAGE-A-01`, `DEC-P2E-EIF02-SYNC-01`, and
`DEC-P2E-STAGE-A-SHUTDOWN-01`
([shutdown authorization](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/73#issuecomment-7241814719))
**Branch:** `feat/p2e-stage-a-simulator-composition`
**Authorized base:** PR #60 at `6eb520d8dd2b9a3d9fb5b9bf8246f7919d42ada4`

This is a test-only composition and verification record. It does not authorize
production activation, signing-key custody, backend delivery, merge, or stages
B/C/D. Local runtime verification is complete for this Stage A slice; exact-HEAD
GitHub CI and owner review remain pending.

## Pinned dependencies and ordinary merge history

| Component | Pinned commit | Merge commit | Merge parents | Merge tree |
|---|---|---|---|---|
| #54 deterministic Simulator | `4f5515396d0350c333b385d45fb22adae24fe566` | `8eba011beacc6facd93a3a3303dffb8956e88088` | `6eb520d8dd2b9a3d9fb5b9bf8246f7919d42ada4`, `4f5515396d0350c333b385d45fb22adae24fe566` | `9a399d044c95ae3bf13f1650e5305a7323ec67d3` |
| #55 Signed Result V1 | `d4a734e191f4bc629c8dac23520bc90a6557b143` | `bfa36dfb1dc19923095275b59e808bbc490df7fc` | `8eba011beacc6facd93a3a3303dffb8956e88088`, `d4a734e191f4bc629c8dac23520bc90a6557b143` | `896bcbdb9cad071120d0e5ba36c4a3b5a2115614` |
| #59 callback client | `065518fcd023677bd556369a02aa7e06d3eae459` | `d40e043a78c0ce233ba2a504033ff823d6681af7` | `bfa36dfb1dc19923095275b59e808bbc490df7fc`, `065518fcd023677bd556369a02aa7e06d3eae459` | `f2b2d724d2fdfba9c6d9eb21ec7ea29dff099df5` |

The only textual merge conflict was `simulator/src/gpu_marketplace_simulator/config.py`.
Resolution retained #60's dispatch/cache/executor settings and canonical
dispatch-token validator, plus #59's callback URL/token fields. Callback-token
encoding now follows the already approved 32-byte canonical unpadded base64url
representation; entropy remains the provisioner's responsibility. No conflict
in Signed Result wire semantics, identity binding, callback retry policy, raw
receipt bytes, or Attempt state semantics required owner escalation.

The merged lockfile was checked with `uv lock --check --offline --project
simulator` and resolved without changes. Exact merge parents and trees were
read from Git; all four pinned commits are ancestors of the Stage A branch.

## Proposed local composition

`runtime_composition.TestOnlyRuntimeComposition` is an explicit injected owner:

1. The existing internal dispatch route authenticates the Manager direction
   token, applies the ten-key request schema and body limit, then calls the
   bounded admission executor.
2. The existing cache adapter atomically retains the immutable fingerprint
   and one producer token. A bounded test producer executor accepts the work;
   only confirmed submission permits HTTP 202.
3. The producer maps the validated dispatch into the #54
   `demo-v1-public1` input. No protected reference, expected digest, signing
   key, or service credential is placed in dispatch data.
4. The eleven-field #55 `SignedResultV1Payload` uses an injected test signer
   and injected `key_id`. The composition verifies the raw Ed25519 signature
   against an injected synthetic public key.
5. The envelope is serialized once with RFC 8785, parsed by #55's
   `envelope_from_json`, and retained as the same immutable bytes in the
   Attempt receipt. The cache adapter binds result, attempt, job, worker, and
   listing identities. The `signed_result_v1.py` compatibility module is now
   only an identity-binding adapter around #55's canonical parser.
6. Only after receipt completion does the producer submit the exact frozen
   bytes and `result_id` to #59 through an injected `httpx.MockTransport`.
   Callback errors cannot cause a second producer, re-signing, or altered
   receipt bytes. STORED/DUPLICATE is transport acknowledgment only; it is not
   Manager verification or Job finalization.
7. Optional application lifecycle hooks are inert unless a test composition
   is explicitly injected. Shutdown stops admission, closes/drains the
   process-local cache under finite test limits, and waits for the injected
   producer/callback owner within its test limit.

The Stage A harness rejects equal dispatch/callback credentials and requires
synthetic canonical service tokens plus an HTTPX MockTransport. It does not
load keys, contact a real service, or enable normal application startup.

## TV1-authorized shutdown timeout remediation

### Baseline reproduction

Before implementation changes, the added deterministic test
`test_24_shutdown_timeout_cancels_callback_and_preserves_finished_receipt`
failed on baseline `e318829f890fa62d1545352853374c35e462dd1d`. The exact failure
was `assert runtime._callback_client._closed is True` with actual value
`False`, after `shutdown_drained` became false. Captured events showed an
active callback request, an unfinished producer Future, and the timeout log;
no permanent process hang was reproduced. This is the P2 owner gap identified
by TV3/TV4, not a separate finding.

### Ownership and budget behavior

- `TestOnlyRuntimeComposition` remains the sole Stage A owner of the callback
  client, its in-flight delivery tasks, and the producer executor. The
  test-only app composition wraps that app instance's admission-executor
  shutdown entry point to start one monotonic deadline before adapter
  close/drain begins. `app.py` and the adapter close/drain contract are
  unchanged.
- Runtime closure sets the registration fence first. Producer submission and
  active-Future tracking are linearized under the runtime guard; if shutdown
  wins while a Future is being bound, execution remains denied and the
  registration returns as rejected. The regression test proves the request
  receives 503, the producer hook is never entered, and the Future remains
  capacity-owning until its actual completion.
- The same absolute monotonic deadline bounds admission drain, producer wait,
  callback Future waiting, and observation of callback close. The worker waits
  on synchronization Events rather than polling; shutdown-start and deadline
  signals wake it. Its bridge Future is cancelled through
  `run_coroutine_threadsafe`'s owning event loop. It never blocks the ASGI loop
  on a synchronous Future wait.
- At deadline the runtime cancels only producer Futures that are still queued
  and already accepted. `Future.cancel()` success is the evidence for queued
  termination; running Futures whose cancellation is refused retain capacity
  until their done callback observes actual termination. The original Future
  callback remains the only capacity-release owner.
- `SimulatorCallbackClient.aclose()` is initiated on normal and timeout paths
  through one retained close Task. Runtime shutdown observes it only for the
  remaining budget. A cancellation-resistant transport leaves
  `shutdown_drained=False` and cleanup incomplete while the close Task and
  client remain owned. No transport close or successful drain is claimed
  until that task actually finishes. Repeated shutdown reuses the same task.
- Callback cancellation or uncertainty never becomes `CallbackAccepted`.
  Tests preserve `FINISHED`, the original `result_id`, exact immutable receipt
  bytes, one signing/production pass, and no second callback owner. No
  `FAILED_NO_RECEIPT` transition occurs after receipt completion. Option A and
  D-16 Option B are unchanged.

### Added shutdown regression cases

| Test | Evidence |
|---|---|
| `test_24` cooperative timeout | Callback cancellation starts at the deadline; producer Future terminates; capacity is released only after `Future.done`; FINISHED receipt identity/bytes remain unchanged; no acceptance is reported. |
| `test_25` same-receipt retry plus duplicate dispatch | One producer/signature/callback owner; retry is cancelled at shutdown; immutable bytes and result identity remain fixed. |
| `test_26` cancellation-resistant transport | Shutdown returns within budget as incomplete; HTTPX remains open while `aclose()` is waiting; explicit release barrier allows cleanup, transport close, and worker-thread termination. |
| `test_27` queued and running producers | Accepted queued Future is cancelled and fails closed; RUNNING Future keeps its permit while blocked, then releases once on actual completion. |
| `test_28` callback scheduling/close race | Producer paused after receipt completion cannot create an unowned callback after owner closure; receipt remains FINISHED. |
| `test_29` repeated concurrent shutdown | Shared monotonic deadline and close Task are unchanged across repeated calls; client closes once through the single owner. |
| `test_30` shutdown during producer registration | Binding Future is tracked before shutdown; late bind is rejected without producer execution or 202; capacity releases only after Future completion. |

The pre-existing tests 21–23 remain unchanged in intent and continue to cover
same-Attempt Future fencing, queued cancellation, and RUNNING cancellation
refusal. Existing successful-drain test 15 remains in place.

## Required 20 integration groups

The tests are collected in `simulator/tests/test_runtime_composition.py`.
Every group below passed in the verified native execution environment after
correcting test-oracle/harness defects. These are local test results, not GitHub
CI or owner approval.

| # | Test group | Test evidence / local status |
|---:|---|---|
| 1 | Authenticated dispatch → registration → receipt → mock callback; registration before 202 | `PASS` — test_01; HTTP 202, receipt completion, exact callback bytes and signature verification |
| 2 | Identical IN_FLIGHT/FINISHED duplicate; one producer and same receipt | `PASS` — test_02 |
| 3 | Altered retained duplicate → 409; immutable entry unchanged | `PASS` — test_03 |
| 4 | Bounded capacity → 503; no false 202 or IN_FLIGHT eviction | `PASS` — test_04 |
| 5 | Frozen deterministic V1–V4 and non-vector determinism | `PASS` — test_05 |
| 6 | Invalid signed payload, malformed JSON, duplicate JSON | `PASS` — test_06 |
| 7 | Injected signer failure → terminated-Future tombstone | `PASS` — test_07 |
| 8 | Post-202 producer exception and confirmed cancellation | `PASS` — test_08; test controls release/cancel queued Futures deterministically |
| 9 | Five independent receipt identity mismatches | `PASS` — test_09; outer result identity remains fixed while payload identities vary |
| 10 | Lost callback response after fake persistence | `PASS` — test_10 |
| 11 | STORED/DUPLICATE acknowledgment and result identity | `PASS` — test_11 |
| 12 | Retries send byte-identical receipt and same result ID | `PASS` — test_12 |
| 13 | Callback deadline/retry exhaustion; no producer rerun | `PASS` — test_13 |
| 14 | Concurrent identical/conflicting admission and lifecycle race | `PASS` — test_14; confirmed registration precedes replay batch; conflict batches target retained state |
| 15 | Shutdown/drain with active producer | `PASS` — test_15; shutdown Task is awaited through a coroutine |
| 16 | D-16 retained conflict, eviction, cold-start semantics | `PASS` — test_16 |
| 17 | Direction credential separation and invalid token rejection | `PASS` — test_17 |
| 18 | Oversize 422, auth-before-read, no sensitive leakage | `PASS` — test_18 |
| 19 | No unauthorized rerun; stale token fence and once-only release | `PASS` — test_19 |
| 20 | Canonical V1, signature verification, receipt/callback byte identity | `PASS` — test_20 |
| 21 | Expired same-Attempt re-admission while old callback is blocked | `PASS` — old Future completion signals only its own registration event; replacement Future remains pending and gets a distinct result ID |
| 22 | Queued Future bind failure | `PASS` — `cancel()` confirmed true; denied producer never enters; only the canceled Future releases its permit |
| 23 | RUNNING Future bind failure at start gate | `PASS` — `cancel()` false; execution permission remains closed; capacity remains owned until the real Future terminates; nested admission is rejected |

## Verification recorded for the shutdown remediation checkout

| Check | Actual result |
|---|---|
| Published #60 control at `6eb520d8dd2b9a3d9fb5b9bf8246f7919d42ada4` | `PASS` — health plus approved dispatch tests: 3 passed, 0.32s, outside sandbox |
| Dependency-only control at `d40e043a78c0ce233ba2a504033ff823d6681af7` | `PASS` — same health plus dispatch tests: 3 passed, 0.30s, outside sandbox |
| Baseline regression confirmation | `PASS` — temporary in-memory restoration of the old Attempt-ID event lookup made test_21 fail because the old Future signaled the replacement waiter. A standalone deterministic `Future`/gate reproduction of the old bind-failure order observed `cancel=False`, denied producer execution, and capacity reacquisition before Future termination. No repository source was changed for these reproductions. |
| Baseline shutdown regression before implementation | `FAIL` as expected on `e318829f890fa62d1545352853374c35e462dd1d` — callback client remained open after drain timeout; bounded test cleanup released the stream and closed resources |
| Stage A test file | `PASS` — 30 passed, 0 failed, native WSL; all original 23 tests plus seven shutdown cases |
| Full Simulator suite | `PASS` — 400 passed, 0 failed, 3.32s, native WSL; one Starlette/httpx deprecation warning |
| Dispatch/cache, callback, deterministic V1–V4, Node/JCS, Signed Result V1 and frozen vectors | `PASS` — 368 passed, 0 failed; Node interoperability tests were collected and executed in this focused set |
| Repeated concurrency/lifecycle/shutdown subset | `PASS` — 10 independent runs; each passed 15 tests (150 executions total). Per-run: 1–10 all `15 passed`; includes tests 08, 14–16, 19, 21–30 |
| Compile | `PASS` — `python3 -m compileall -q simulator/src/gpu_marketplace_simulator simulator/tests/test_runtime_composition.py` |
| Lock | `PASS` — `uv lock --check --offline --project simulator` resolved 30 packages; lock unchanged |
| Whitespace | `PASS` — `git diff --check` |
| Ruff | `NOT_RUN` — Ruff is not installed |
| GitHub Actions for new shutdown HEAD | `NOT_RUN` — the old #74 run is historical evidence for `e318829` only; fresh exact-SHA CI authorization was requested separately and is not inferred here |

Repeated-run detail (each command was a separate pytest subprocess on the same
code tree):

| Run | Result |
|---:|---|
| 1 | `PASS` — 15 passed |
| 2 | `PASS` — 15 passed |
| 3 | `PASS` — 15 passed |
| 4 | `PASS` — 15 passed |
| 5 | `PASS` — 15 passed |
| 6 | `PASS` — 15 passed |
| 7 | `PASS` — 15 passed |
| 8 | `PASS` — 15 passed |
| 9 | `PASS` — 15 passed |
| 10 | `PASS` — 15 passed |

Commands run from `simulator/` used `.venv/bin/python -B -m pytest -p no:cacheprovider`. The full suite reported `400 passed`; the Stage A file reported `30 passed`; the focused dispatch/cache/deterministic/interop/signed-result command reported `368 passed`. A Python subprocess harness executed the listed 15 concurrency/lifecycle/shutdown node IDs in ten separate pytest processes; every process reported `15 passed`. These are local native-WSL results, not GitHub CI. Ruff is unavailable and remains `NOT_RUN`.

At reviewed baseline `415b083`, the done callback looked up the event by Attempt ID, and bind failure opened the execution gate and released capacity unconditionally after `Future.cancel()`. P2-01 old behavior was reproduced with a temporary in-memory legacy callback mutation against test_21; it failed because the new waiter became signaled. P2-02's old sequence was reproduced with a real `ThreadPoolExecutor` Future and Events: cancellation returned false, the denied task entered, and capacity was reacquired while that Future remained unfinished. Remediated tests 21–23 pass on the current local tree. These are local results, not GitHub CI.

### Environment comparison and hang diagnosis

Environment: WSL2 Linux (`6.6.87.2-microsoft-standard-WSL2`), Python 3.12.3,
uv 0.13.5, pytest 9.1.1, AnyIO 4.15.1, Starlette 1.9.0, HTTPX 0.28.1, default
asyncio Unix event-loop policy. The failing execution environment was the
Codex sandbox; the comparison environment was the approved native WSL terminal.

| Control | Sandbox result | Native WSL result |
|---|---|---|
| A. Standalone cross-thread `call_soon_threadsafe` wake | The scheduled callback ran, but its Future waiter did not wake; the asyncio 2s timeout also did not fire; external 8s timeout exit 124 | Same script: `CALLBACK_RAN`, `WAKE_OK`, 0.001s, external timeout exit 0 |
| B. Published #60 health + dispatch | Health `TestClient.__enter__` stalled; faulthandler showed AnyIO portal loop in selector wait and caller blocked in `start_task_soon` | 3 passed, 0.32s |
| C. Dependency-only d40 health + dispatch | Same `TestClient.__enter__` stall and stack shape | 3 passed, 0.30s |
| D. Stage A pre-shutdown baseline at `e318829` | Earlier bounded sandbox diagnostic stalled before the original Stage A POST response; this is separate from the shutdown P2 reproduction | Native WSL baseline passed 23/23 at `e318829`; shutdown regression independently reproduced the open callback owner after timeout |

The original stall is therefore demonstrated to be sandbox-specific: both
published/dependency-only controls failed there, while the standalone wake and
the same controls passed in native WSL. Stage A also passed in native WSL. No
production scheduling workaround was made. The first native verification
exposed four test-harness defects: self-matching result identity, assumptions
about duplicate requests during REGISTERING, passing a Task directly to
`Runner.run`, and not cancelling the queued Future until after the producer
worker had run it. Those tests were corrected; no production application code
was changed to obtain the passing result.

Sandbox stack captures and bounded timeout results were diagnostic only; they
are not counted as test passes. The full local verification is not GitHub CI.

## Decision and release boundaries

- `DEC-P2E-60-OPT-A` remains authoritative: only the actual bound execution
  Future, after confirmed termination with exception/cancellation, can support
  `IN_FLIGHT → FAILED_NO_RECEIPT`; a successful receiptless Future retains its
  slot. No Option B, D-19 repair, automatic rerun, or uncertain-producer
  eviction was added.
- D-16 Option B remains separate: same-process conflict detection exists only
  while the fingerprint is retained. After expiry/eviction/cold restart, no
  historical conflict guarantee is claimed. No durable Simulator state or
  exactly-once physical execution claim is introduced.
- E-IF-01 and E-IF-03 remain `HOLD`. E-IF-02 remains approved design with
  acceptance evidence/owner ACKs pending. Stage B/C/D remain
  `NOT_AUTHORIZED`.
- Normal `create_app()` does not receive the Stage A lifecycle owner. The
  composition requires injected synthetic credentials, an injected test
  Ed25519 key/provider and exact `httpx.MockTransport`; callback URL is the
  reserved `.test` host. No production endpoint, key store, Manager, Backend,
  PostgreSQL or Inbox is activated. Composition resource limits are explicitly
  injected test values, not production defaults.
- `lifecycle.complete()` validates the canonical #55 envelope and binds
  `result_id`, `attempt_id`, `job_id`, `worker_id` and `listing_id` before the
  cache can transition to FINISHED. Receipt stores immutable original bytes;
  callback retry tests assert byte identity. Structural parsing and the
  composition's injected-key Ed25519 verification are separate checks.
- PR #55 remains OPEN/Draft/HOLD. Its pinned dependency is permitted only for
  local Stage A testing and is not authorized to land. TV3's renewed exact-HEAD
  ACK, two independent human L2 approvals, and separate TV1 merge authorization
remain outstanding.
