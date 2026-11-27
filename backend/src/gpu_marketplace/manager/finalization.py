"""Isolated Inbox verification/finalization orchestration for the Manager.

This module owns no database, cryptographic, Job-state, release, or reputation
policy. Its injected ports are provisional TV1-local boundaries, not frozen
TV2/TV3/TV5 DTOs or transaction signatures.

The candidate locator must return only committed, unlocked immutable locator
data. Evidence loading must return immutable trusted context; neither port may
return a live SQLAlchemy Session or locked ORM object across an await. The pure
verifier runs outside domain row locks. Only the four approved definitive
rejection codes (UNKNOWN_KEY, KEY_WORKER_MISMATCH, CONTEXT_MISMATCH,
INVALID_SIGNATURE) may be represented as a rejection verdict; dependency,
parser, evidence-extraction, and key-invariant failures must raise through the
verifier port. The finalizer must re-read and validate the stored original
evidence under Listing -> Job -> Allocation -> Inbox -> Contribution ->
Aggregate locks before any durable effect, with no Worker advisory lock. A
typed verified or definitively rejected verdict is passed through unchanged;
only an explicitly classified transient evidence/verifier dependency failure
is contained locally, leaving the Inbox PENDING and allowing the deadline port
to inspect durable state. Unexpected errors and cancellation propagate. A
rejection can mark only its matching Inbox item REJECTED; it cannot itself
terminalize the Job, release a GPU, or change reputation.

The finalizer adapter must use trusted persisted received_at and the
(received_at, inbox_id) candidate order. It must preserve an already-committed
on-time candidate after a late Manager restart, while new ingress at or after
the hard deadline is ineligible. TV1 makes none of these durable decisions.

At most one candidate is processed per cycle. Every normally completed cycle
also invokes the injected authoritative deadline port, whether or not a
candidate was found. The adapter receives no page, cursor, or exhaustion
assertion and must independently recheck committed on-time candidates and
pending/unavailable-verification evidence under durable state and locks. An
empty locator result is never proof that SYSTEM_FAULT fallback is safe. The
progress classifiers are TV1-local scheduling adapters; they do not freeze
TV2/TV3/TV5 outcomes. Candidate discovery remains one opaque candidate per
call: D-20 pagination, deferred-candidate revisit policy, and durable unknown-
COMMIT reconciliation remain blocked until owner ACKs and measured budgets.

The poller is a lifecycle helper, not a readiness signal. It serializes cycles,
uses the approved 2-second cadence, records only local monotonic progress, and
lets the Manager supervisor observe failures by propagating them.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar


INBOX_POLL_INTERVAL_SECONDS = 2.0
_TRANSIENT_VERIFICATION_DIAGNOSTIC = "verification_dependency_unavailable"

CandidateT = TypeVar("CandidateT")
EvidenceT = TypeVar("EvidenceT")
VerifierVerdictT = TypeVar("VerifierVerdictT")
FinalizationOutcomeT = TypeVar("FinalizationOutcomeT")
DeadlineOutcomeT = TypeVar("DeadlineOutcomeT")


@dataclass(frozen=True, slots=True)
class FinalizationCycleObservation(
    Generic[FinalizationOutcomeT, DeadlineOutcomeT]
):
    """TV1-local observation of bounded work and its continuation signal."""

    candidate_processed: bool
    finalization_outcome: FinalizationOutcomeT | None
    deadline_outcome: DeadlineOutcomeT | None
    continue_immediately: bool = False


class InboxFinalizationCoordinator(
    Generic[
        CandidateT,
        EvidenceT,
        VerifierVerdictT,
        FinalizationOutcomeT,
        DeadlineOutcomeT,
    ]
):
    """Run one candidate handoff and an authoritative deadline check.

    All port outcomes are opaque and passed through unchanged. Both progress
    classifiers are TV1-local scheduling adapters, not shared business enums.
    A normally completed cycle always invokes the deadline port, whether or not
    it found a candidate. An exception from verification/evidence loading is
    contained only when the injected classifier explicitly marks it transient;
    the reporter receives a fixed redacted code, never the exception. Other
    exceptions, cancellation, and unknown COMMIT outcomes propagate. No
    operation is blindly retried or locally authorized as SYSTEM_FAULT.
    """

    def __init__(
        self,
        *,
        locate_candidate: Callable[[], Awaitable[CandidateT | None]] | None,
        load_evidence: Callable[[CandidateT], Awaitable[EvidenceT]] | None,
        verify: Callable[[EvidenceT], Awaitable[VerifierVerdictT]] | None,
        finalize: Callable[
            [CandidateT, EvidenceT, VerifierVerdictT],
            Awaitable[FinalizationOutcomeT],
        ]
        | None,
        evaluate_deadlines: Callable[[], Awaitable[DeadlineOutcomeT]] | None,
        candidate_made_progress: Callable[
            [CandidateT, FinalizationOutcomeT], bool
        ]
        | None,
        deadline_made_progress: Callable[[DeadlineOutcomeT], bool] | None,
        is_transient_dependency_failure: Callable[[Exception], bool] | None,
        report_transient_dependency_failure: Callable[[CandidateT, str], None]
        | None,
    ) -> None:
        required_ports = {
            "locate_candidate": locate_candidate,
            "load_evidence": load_evidence,
            "verify": verify,
            "finalize": finalize,
            "evaluate_deadlines": evaluate_deadlines,
            "candidate_made_progress": candidate_made_progress,
            "deadline_made_progress": deadline_made_progress,
            "is_transient_dependency_failure": is_transient_dependency_failure,
            "report_transient_dependency_failure": report_transient_dependency_failure,
        }
        for name, port in required_ports.items():
            if not callable(port):
                raise ValueError(f"required {name} port must be callable")

        self._locate_candidate = locate_candidate
        self._load_evidence = load_evidence
        self._verify = verify
        self._finalize = finalize
        self._evaluate_deadlines = evaluate_deadlines
        self._candidate_made_progress = candidate_made_progress
        self._deadline_made_progress = deadline_made_progress
        self._is_transient_dependency_failure = is_transient_dependency_failure
        self._report_transient_dependency_failure = report_transient_dependency_failure
        self._running = False

    async def run_once(
        self,
    ) -> FinalizationCycleObservation[FinalizationOutcomeT, DeadlineOutcomeT]:
        """Process at most one candidate, then request deadline work every cycle."""
        if self._running:
            raise RuntimeError("Inbox finalization coordinator is already running")

        self._running = True
        try:
            candidate = await self._locate_candidate()
            candidate_processed = candidate is not None
            finalization_outcome: FinalizationOutcomeT | None = None
            candidate_made_progress = False
            if candidate is not None:
                try:
                    evidence = await self._load_evidence(candidate)
                    verdict = await self._verify(evidence)
                except Exception as error:
                    if not self._is_transient_dependency_failure(error):
                        raise
                    # The durable Inbox remains PENDING. The owner deadline
                    # adapter must recheck that evidence and defer fallback
                    # only for its bound Job; TV1 makes no durable decision.
                    self._report_transient_dependency_failure(
                        candidate,
                        _TRANSIENT_VERIFICATION_DIAGNOSTIC,
                    )
                else:
                    finalization_outcome = await self._finalize(
                        candidate,
                        evidence,
                        verdict,
                    )
                    candidate_made_progress = bool(
                        self._candidate_made_progress(
                            candidate,
                            finalization_outcome,
                        )
                    )

            # This port is an opportunity for authoritative durable evaluation,
            # not proof of cursor exhaustion or permission to terminalize a Job.
            deadline_outcome = await self._evaluate_deadlines()
            deadline_made_progress = bool(
                self._deadline_made_progress(deadline_outcome)
            )
            return FinalizationCycleObservation(
                candidate_processed=candidate_processed,
                finalization_outcome=finalization_outcome,
                deadline_outcome=deadline_outcome,
                # If a candidate is present, its adapter classification controls
                # continuation so a no-change outcome cannot busy-spin. With an
                # empty discovery result, productive deadline work can continue.
                continue_immediately=(
                    candidate_made_progress
                    if candidate is not None
                    else deadline_made_progress
                ),
            )
        finally:
            self._running = False


async def _wait_for_stop_or_interval(
    stop_event: asyncio.Event,
    interval_seconds: float,
) -> bool:
    """Return true if shutdown interrupts the polling cadence."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
    except TimeoutError:
        return stop_event.is_set()
    return True


class InboxFinalizationPoller:
    """Stop-aware non-overlapping poller for one injected processing cycle."""

    def __init__(
        self,
        *,
        cycle: Callable[[], Awaitable[object]] | None,
        stop_event: asyncio.Event | None,
        claim_allowed: Callable[[], bool] | None,
        on_cycle_completed: Callable[[], None] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        wait_for_interval: Callable[[asyncio.Event, float], Awaitable[bool]]
        | None = None,
    ) -> None:
        required_ports = {
            "cycle": cycle,
            "claim_allowed": claim_allowed,
        }
        for name, port in required_ports.items():
            if not callable(port):
                raise ValueError(f"required {name} port must be callable")
        if (
            stop_event is None
            or not callable(getattr(stop_event, "is_set", None))
            or not callable(getattr(stop_event, "wait", None))
        ):
            raise ValueError("required stop_event must provide is_set() and wait()")
        if on_cycle_completed is not None and not callable(on_cycle_completed):
            raise ValueError("on_cycle_completed must be callable when provided")
        if monotonic_clock is not None and not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable when provided")
        if wait_for_interval is not None and not callable(wait_for_interval):
            raise ValueError("wait_for_interval must be callable when provided")

        self._cycle = cycle
        self._stop_event = stop_event
        self._claim_allowed = claim_allowed
        self._on_cycle_completed = on_cycle_completed
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._wait_for_interval = wait_for_interval or _wait_for_stop_or_interval
        self._last_completed_at: float | None = None
        self._running = False

    @property
    def last_completed_at(self) -> float | None:
        """Local monotonic progress only; it is not Manager readiness."""
        return self._last_completed_at

    async def run(self) -> None:
        """Run cycles until stop; let cycle, hook, and cancellation failures out."""
        if self._running:
            raise RuntimeError("Inbox finalization poller is already running")

        self._running = True
        try:
            while not self._stop_event.is_set():
                if not self._claim_allowed():
                    if await self._wait_for_interval(
                        self._stop_event,
                        INBOX_POLL_INTERVAL_SECONDS,
                    ):
                        return
                    continue

                # Re-check after the synchronous gate so a requested shutdown
                # never starts another cycle after the gate returns.
                if self._stop_event.is_set():
                    return

                # Graceful stop does not cancel this await. Forced task
                # cancellation propagates and bypasses completion bookkeeping.
                cycle_observation = await self._cycle()
                self._last_completed_at = float(self._monotonic_clock())
                if self._on_cycle_completed is not None:
                    self._on_cycle_completed()

                if self._stop_event.is_set():
                    return
                if getattr(cycle_observation, "continue_immediately", False) is True:
                    # Yield so other event-loop work can run; the loop top
                    # rechecks stop and admission before starting another cycle.
                    await asyncio.sleep(0)
                    continue
                if await self._wait_for_interval(
                    self._stop_event,
                    INBOX_POLL_INTERVAL_SECONDS,
                ):
                    return
        finally:
            self._running = False
