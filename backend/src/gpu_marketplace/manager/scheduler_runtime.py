"""Supervisor-owned adapter for the Manager scheduling/allocation group.

This module only connects the lifecycle signals of ``ManagerGroupContext`` to
the existing scheduler orchestrator. It does not compose a production
allocation cycle, configure retries, or activate the Manager runtime.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from gpu_marketplace.manager.scheduler import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    SchedulingCycle,
    SchedulerOrchestrator,
    WaitForInterval,
)
from gpu_marketplace.manager.supervisor import (
    GroupRunner,
    ManagerGroup,
    ManagerGroupContext,
)


def create_scheduler_group_runner(
    *,
    cycle: SchedulingCycle,
    initial_scan_immediately: bool,
    is_transient_failure: Callable[[Exception], bool],
    wait_for_interval: WaitForInterval | None = None,
    monotonic_clock: Callable[[], float] | None = None,
) -> GroupRunner:
    """Create a runner for the Supervisor's scheduling/allocation group.

    Startup timing and transient classification remain explicit inputs. The
    Scheduler retains its accepted cadence and owns its normal stop-aware wait;
    optional wait/clock injection is passed through for deterministic tests.
    Each completed scan, including an empty scan, reports progress through the
    Supervisor heartbeat. This signal is progress only and is not readiness.
    """

    async def run(context: ManagerGroupContext) -> None:
        if context.group is not ManagerGroup.SCHEDULING_ALLOCATION:
            raise ValueError(
                "Scheduler group runner requires the scheduling/allocation group"
            )

        scheduler_options: dict[str, object] = {}
        if wait_for_interval is not None:
            scheduler_options["wait_for_interval"] = wait_for_interval
        if monotonic_clock is not None:
            scheduler_options["monotonic_clock"] = monotonic_clock

        scheduler = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=context.stop_event,
            claim_allowed=lambda: context.claims_allowed,
            initial_scan_immediately=initial_scan_immediately,
            scan_interval_seconds=DEFAULT_SCAN_INTERVAL_SECONDS,
            is_transient_failure=is_transient_failure,
            on_cycle_completed=context.heartbeat,
            **scheduler_options,  # type: ignore[arg-type]
        )
        await scheduler.run()

    return run
