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
verifier/dependency failures propagate and do not reach finalizer or deadline
evaluation. A rejection can mark only its matching Inbox item REJECTED; it
cannot itself terminalize the Job, release a GPU, or change reputation.

The finalizer adapter must use trusted persisted received_at and the
(received_at, inbox_id) candidate order. It must preserve an already-committed
on-time candidate after a late Manager restart, while new ingress at or after
the hard deadline is ineligible. TV1 makes none of these durable decisions.

At most one candidate is processed per cycle. If one is found, deadline
evaluation is deferred to a later cycle so a following on-time candidate can
be located and handled first. If no candidate is located, the coordinator only
invokes the injected authoritative deadline port without passing a page,
cursor, or exhaustion assertion. That adapter must independently recheck all
committed on-time candidates and any pending/unavailable-verification evidence
under durable state and locks. An empty locator result is never proof that
SYSTEM_FAULT fallback is safe.

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

CandidateT = TypeVar("CandidateT")
EvidenceT = TypeVar("EvidenceT")
VerifierVerdictT = TypeVar("VerifierVerdictT")
FinalizationOutcomeT = TypeVar("FinalizationOutcomeT")
DeadlineOutcomeT = TypeVar("DeadlineOutcomeT")


@dataclass(frozen=True, slots=True)
class FinalizationCycleObservation(
    Generic[FinalizationOutcomeT, DeadlineOutcomeT]
):
    """TV1-local observation of which injected coordination path completed."""

    candidate_processed: bool
    finalization_outcome: FinalizationOutcomeT | None
    deadline_outcome: DeadlineOutcomeT | None


class InboxFinalizationCoordinator(
    Generic[
        CandidateT,
        EvidenceT,
        VerifierVerdictT,
        FinalizationOutcomeT,
        DeadlineOutcomeT,
    ]
):
    """Run one candidate handoff or request an authoritative deadline check.

    All port outcomes are opaque and passed through unchanged. An exception at
    any stage propagates. In particular, an unknown finalization COMMIT is not
    retried, and an unavailable verifier cannot be converted into a definitive
    rejection or SYSTEM_FAULT decision.
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
    ) -> None:
        required_ports = {
            "locate_candidate": locate_candidate,
            "load_evidence": load_evidence,
            "verify": verify,
            "finalize": finalize,
            "evaluate_deadlines": evaluate_deadlines,
        }
        for name, port in required_ports.items():
            if not callable(port):
                raise ValueError(f"required {name} port must be callable")

        self._locate_candidate = locate_candidate
        self._load_evidence = load_evidence
        self._verify = verify
        self._finalize = finalize
        self._evaluate_deadlines = evaluate_deadlines
        self._running = False

    async def run_once(
        self,
    ) -> FinalizationCycleObservation[FinalizationOutcomeT, DeadlineOutcomeT]:
        """Process at most one committed candidate, or request deadline work."""
        if self._running:
            raise RuntimeError("Inbox finalization coordinator is already running")

        self._running = True
        try:
            candidate = await self._locate_candidate()
            if candidate is None:
                deadline_outcome = await self._evaluate_deadlines()
                return FinalizationCycleObservation(
                    candidate_processed=False,
                    finalization_outcome=None,
                    deadline_outcome=deadline_outcome,
                )

            evidence = await self._load_evidence(candidate)
            verdict = await self._verify(evidence)
            finalization_outcome = await self._finalize(
                candidate,
                evidence,
                verdict,
            )
            return FinalizationCycleObservation(
                candidate_processed=True,
                finalization_outcome=finalization_outcome,
                deadline_outcome=None,
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
                await self._cycle()
                self._last_completed_at = float(self._monotonic_clock())
                if self._on_cycle_completed is not None:
                    self._on_cycle_completed()

                if self._stop_event.is_set():
                    return
                if await self._wait_for_interval(
                    self._stop_event,
                    INBOX_POLL_INTERVAL_SECONDS,
                ):
                    return
        finally:
            self._running = False
