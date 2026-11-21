"""Isolated scheduler-loop orchestration; not a production allocator.

The async cycle port is deliberately local and carries no Listing/Job DTO. It is
not the pending TV2 ``TX-ALLOCATE`` or TV4 FIFO-policy interface. A future adapter
must keep each complete synchronous UoW in one bounded-executor worker context;
this module never owns a database Session and is not wired into Manager runtime.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_SECONDS = 2.0


class SchedulingCycle(Protocol):
    """A completed scan operation with no cross-owner result DTO."""

    async def __call__(self) -> None: ...


WaitForInterval = Callable[[asyncio.Event, float], Awaitable[bool]]


async def _wait_for_stop_or_interval(
    stop_event: asyncio.Event, interval_seconds: float
) -> bool:
    """Return whether stop interrupted the cadence wait."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
    except TimeoutError:
        return stop_event.is_set()
    return True


class SchedulerOrchestrator:
    """Run one non-overlapping, stop-aware scheduling cycle at a time.

    ``initial_scan_immediately`` is required because exact startup timing remains
    pending owner agreement. A normal return from ``cycle`` records local progress
    for both empty and successful scans. This is not a health/readiness assertion.
    The optional synchronous completion callback reports progress only, not
    Manager readiness, and runs after that timestamp is recorded. If it raises,
    the runner fails and propagates the error; the completed business cycle
    remains recorded and is not retried.
    Transient classification is injected; transient failures are logged without
    exception details and propagate because no retry budget is approved here.
    Other exceptions also propagate and stop this runner.
    """

    def __init__(
        self,
        *,
        cycle: SchedulingCycle | None,
        stop_event: asyncio.Event | None,
        claim_allowed: Callable[[], bool] | None,
        initial_scan_immediately: bool,
        scan_interval_seconds: float = DEFAULT_SCAN_INTERVAL_SECONDS,
        is_transient_failure: Callable[[Exception], bool] | None,
        on_cycle_completed: Callable[[], None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wait_for_interval: WaitForInterval = _wait_for_stop_or_interval,
    ) -> None:
        if cycle is None:
            raise ValueError("A scheduling-cycle port is required")
        if stop_event is None:
            raise ValueError("A stop event is required")
        if claim_allowed is None:
            raise ValueError("A claim-permission gate is required")
        if is_transient_failure is None:
            raise ValueError("A transient-failure classifier is required")
        if type(initial_scan_immediately) is not bool:
            raise ValueError("initial_scan_immediately must be a bool")
        if (
            isinstance(scan_interval_seconds, bool)
            or not isinstance(scan_interval_seconds, (int, float))
            or not math.isfinite(scan_interval_seconds)
            or scan_interval_seconds <= 0
        ):
            raise ValueError("scan_interval_seconds must be a finite positive number")

        self._cycle = cycle
        self._stop_event = stop_event
        self._claim_allowed = claim_allowed
        self._initial_scan_immediately = initial_scan_immediately
        self._scan_interval_seconds = float(scan_interval_seconds)
        self._is_transient_failure = is_transient_failure
        self._on_cycle_completed = on_cycle_completed
        self._monotonic_clock = monotonic_clock
        self._wait_for_interval = wait_for_interval
        self._running = False
        self._last_completed_monotonic: float | None = None

    @property
    def last_completed_monotonic(self) -> float | None:
        """Monotonic timestamp of the last normally completed scan, if any."""
        return self._last_completed_monotonic

    async def run(self) -> None:
        """Run until stopped; a stop signal waits for any in-flight cycle to end."""
        if self._running:
            raise RuntimeError("SchedulerOrchestrator is already running")

        self._running = True
        try:
            if not self._initial_scan_immediately:
                if await self._wait_for_interval(
                    self._stop_event, self._scan_interval_seconds
                ):
                    return

            while not self._stop_event.is_set():
                if not self._claim_allowed():
                    if await self._wait_for_interval(
                        self._stop_event, self._scan_interval_seconds
                    ):
                        return
                    continue

                # No await occurs between this stop check and entering the port.
                if self._stop_event.is_set():
                    return

                try:
                    await self._cycle()
                except Exception as exc:
                    if self._is_transient_failure(exc):
                        logger.warning("manager_scheduler_cycle_transient_failure")
                    raise
                else:
                    self._last_completed_monotonic = self._monotonic_clock()
                    if self._on_cycle_completed is not None:
                        self._on_cycle_completed()

                if self._stop_event.is_set():
                    return
                if await self._wait_for_interval(
                    self._stop_event, self._scan_interval_seconds
                ):
                    return
        finally:
            self._running = False
