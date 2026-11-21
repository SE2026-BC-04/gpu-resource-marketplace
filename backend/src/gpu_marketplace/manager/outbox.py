"""Isolated lifecycle and port coordination for Manager Outbox delivery.

This module does not own persistence, HTTP policy, retry calculations, fencing,
ACKED-row repair, or Job finalization. TV2's claim port must commit and close its
claim transaction before returning, and must not return a live Session/ORM
object. TV5's transport port owns authentication, serialization, timeouts, and
mapping transport results.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Generic, Protocol, TypeVar

DISPATCH_POLL_INTERVAL_SECONDS = 2.0


class OutboxProcessingCycle(Protocol):
    """Process one bounded due-work cycle; normal return includes an empty scan."""

    async def __call__(self) -> None: ...


WaitForInterval = Callable[[asyncio.Event, float], Awaitable[bool]]
ClaimT = TypeVar("ClaimT")
TransportOutcomeT = TypeVar("TransportOutcomeT")

ClaimOneCommitted = Callable[[], Awaitable[ClaimT | None]]
Dispatch = Callable[[ClaimT], Awaitable[TransportOutcomeT]]
Settle = Callable[[ClaimT, TransportOutcomeT], Awaitable[None]]


async def _wait_for_stop_or_interval(
    stop_event: asyncio.Event, interval_seconds: float
) -> bool:
    """Return true when shutdown interrupts the polling cadence."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
    except TimeoutError:
        return stop_event.is_set()
    return True


class OutboxDispatchCoordinator(Generic[ClaimT, TransportOutcomeT]):
    """Coordinate one committed claim, one transport call, and one settlement.

    The claim handle and transport outcome are opaque here. A claim port must
    commit and close its DB transaction before returning. If COMMIT is unknown,
    the port must raise without returning a handle; this coordinator then
    cannot send HTTP blindly. The dispatch port is first invoked only after the
    claim port returns, and settlement receives the exact original claim
    context and transport outcome. A returned 202 remains only transport
    acceptance; this class has no Job-finalization port.

    The ports are provisional TV1-local injection boundaries, not the final
    TV2/TV5 DTO or transaction interfaces. A transport exception propagates and
    is not converted into an ACK or retry outcome here. TV2/TV5 adapters own
    durable reconciliation, CAS fencing, HTTP policy, and retry classification.
    Cancellation does not prove an underlying synchronous UoW has stopped; its
    executor adapter must preserve worker ownership until the operation ends.
    """

    def __init__(
        self,
        *,
        claim_one_committed: ClaimOneCommitted[ClaimT] | None,
        dispatch: Dispatch[ClaimT, TransportOutcomeT] | None,
        settle: Settle[ClaimT, TransportOutcomeT] | None,
    ) -> None:
        if claim_one_committed is None:
            raise ValueError("An Outbox committed-claim port is required")
        if dispatch is None:
            raise ValueError("An Outbox dispatch port is required")
        if settle is None:
            raise ValueError("An Outbox settlement port is required")

        self._claim_one_committed = claim_one_committed
        self._dispatch = dispatch
        self._settle = settle
        self._running = False

    async def run_once(self) -> None:
        """Process at most one returned claim; never retry a failed port here."""
        if self._running:
            raise RuntimeError("OutboxDispatchCoordinator is already running")

        self._running = True
        try:
            claim = await self._claim_one_committed()
            if claim is None:
                return

            outcome = await self._dispatch(claim)
            await self._settle(claim, outcome)
        finally:
            self._running = False


class OutboxPoller:
    """Run stop-aware, non-overlapping Outbox cycles at the approved 2s cadence.

    A closed claim gate waits for the next poll tick without running a cycle.
    Graceful stop prevents a new cycle but allows the in-flight cycle to return;
    forced task cancellation propagates and does not call the completion hook.
    Completion progress is local and is not a Manager readiness or success
    signal. No DB resources, tasks, retries, or exceptions are owned/logged here.
    """

    def __init__(
        self,
        *,
        cycle: OutboxProcessingCycle | None,
        stop_event: asyncio.Event | None,
        claim_allowed: Callable[[], bool] | None,
        on_cycle_completed: Callable[[], None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wait_for_interval: WaitForInterval = _wait_for_stop_or_interval,
    ) -> None:
        if cycle is None:
            raise ValueError("An Outbox processing-cycle port is required")
        if stop_event is None:
            raise ValueError("An Outbox stop event is required")
        if claim_allowed is None:
            raise ValueError("An Outbox claim-permission gate is required")

        self._cycle = cycle
        self._stop_event = stop_event
        self._claim_allowed = claim_allowed
        self._on_cycle_completed = on_cycle_completed
        self._monotonic_clock = monotonic_clock
        self._wait_for_interval = wait_for_interval
        self._running = False
        self._last_completed_monotonic: float | None = None

    @property
    def last_completed_monotonic(self) -> float | None:
        """Monotonic timestamp of the last normally completed poll cycle."""
        return self._last_completed_monotonic

    async def run(self) -> None:
        """Poll until stopped, waiting for any started cycle to finish."""
        if self._running:
            raise RuntimeError("OutboxPoller is already running")

        self._running = True
        try:
            while not self._stop_event.is_set():
                if not self._claim_allowed():
                    if await self._wait_for_interval(
                        self._stop_event, DISPATCH_POLL_INTERVAL_SECONDS
                    ):
                        return
                    continue

                # No await occurs between this stop check and starting the cycle.
                if self._stop_event.is_set():
                    return

                await self._cycle()
                self._last_completed_monotonic = self._monotonic_clock()
                if self._on_cycle_completed is not None:
                    self._on_cycle_completed()

                if self._stop_event.is_set():
                    return
                if await self._wait_for_interval(
                    self._stop_event, DISPATCH_POLL_INTERVAL_SECONDS
                ):
                    return
        finally:
            self._running = False
