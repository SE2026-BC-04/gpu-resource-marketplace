"""Lifecycle supervision for the three Phase 2 Manager loop groups.

This module owns task lifecycle only. Business runners are supplied by their
module owners once their interfaces are available; a missing runner remains
explicitly blocked instead of being replaced by a no-op loop.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Protocol

logger = logging.getLogger(__name__)


class ManagerGroup(str, Enum):
    SCHEDULING_ALLOCATION = "scheduling_allocation"
    OUTBOX_DISPATCH_RETRY = "outbox_dispatch_retry"
    INBOX_VERIFICATION_FINALIZATION_DEADLINE = (
        "inbox_verification_finalization_deadline"
    )


REQUIRED_MANAGER_GROUPS = frozenset(ManagerGroup)


class ManagerRuntimeMode(str, Enum):
    FOUNDATION = "FOUNDATION"
    PHASE2_RUNTIME = "PHASE2_RUNTIME"


class GroupLifecycle(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class DrainOutcome(str, Enum):
    CLEAN = "CLEAN"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    group: ManagerGroup
    lifecycle: GroupLifecycle
    dependency_status: str | None
    diagnostic_type: str | None
    progress_count: int
    last_progress_monotonic: float | None


class GroupRunner(Protocol):
    def __call__(self, context: ManagerGroupContext) -> Awaitable[None]: ...


@dataclass(slots=True)
class _GroupState:
    lifecycle: GroupLifecycle = GroupLifecycle.STARTING
    dependency_status: str | None = None
    diagnostic_type: str | None = None
    progress_count: int = 0
    last_progress_monotonic: float | None = None


class UnexpectedGroupExit(RuntimeError):
    """A required loop returned before a Manager stop was requested."""


class ReportedGroupStall(RuntimeError):
    """A configured stall observer reported an unrecoverable stall."""


class TransientManagerDependencyError(RuntimeError):
    """A dependency failure that a loop runner may recover from transiently."""


class FatalManagerConfigurationError(RuntimeError):
    """A non-recoverable Manager configuration or startup error."""


class ManagerSupervisorError(RuntimeError):
    def __init__(self, group: ManagerGroup, cause: BaseException) -> None:
        self.group = group
        self.cause_type = type(cause).__name__
        super().__init__(
            f"Manager group {group.value} failed ({self.cause_type}); "
            "all supervised tasks have stopped"
        )


class ManagerDrainIncompleteError(RuntimeError):
    def __init__(self, timed_out_groups: frozenset[ManagerGroup]) -> None:
        self.timed_out_groups = timed_out_groups
        groups = ", ".join(sorted(group.value for group in timed_out_groups))
        super().__init__(
            "Manager drain observation budget expired; outstanding groups: "
            f"{groups}"
        )


class RequiredGroupsMissingError(RuntimeError):
    def __init__(self, missing_groups: frozenset[ManagerGroup]) -> None:
        self.missing_groups = missing_groups
        missing = ", ".join(sorted(group.value for group in missing_groups))
        super().__init__(f"Manager startup blocked; missing required groups: {missing}")


class ManagerGroupContext:
    """Safe lifecycle signals exposed to an injected loop runner."""

    def __init__(self, supervisor: ManagerSupervisor, group: ManagerGroup) -> None:
        self._supervisor = supervisor
        self.group = group

    @property
    def stop_event(self) -> asyncio.Event:
        return self._supervisor.stop_event

    @property
    def claims_allowed(self) -> bool:
        """Runners must check this immediately before starting new claims."""
        return (
            self._supervisor.dependency_gate_open
            and not self.stop_event.is_set()
            and not self._supervisor.shutdown_started
            and self._supervisor.failure is None
        )

    def heartbeat(self) -> None:
        """Record useful loop progress, including a completed empty scan."""
        self._supervisor._record_progress(self.group)

    def report_transient(self, error: TransientManagerDependencyError) -> None:
        """Mark a caught transient dependency error without ending the loop.

        The runner owns retry behavior and must apply its approved bounded
        policy. Fatal configuration errors must escape the runner instead.
        This method deliberately does not invent a retry budget.
        """
        if not isinstance(error, TransientManagerDependencyError):
            raise TypeError("report_transient requires TransientManagerDependencyError")
        self._supervisor._record_transient(self.group, error)

    def report_recovered(self) -> None:
        self._supervisor._record_recovered(self.group)

    def report_stall(self) -> None:
        """Fail fast when an approved observer detects a fatal stall.

        No monitor or numeric stall threshold is activated by this slice.
        """
        self._supervisor._record_stall(self.group)


class ManagerSupervisor:
    """Supervise available Manager groups and drain them cooperatively."""

    def __init__(
        self,
        *,
        runners: Mapping[ManagerGroup, GroupRunner] | None = None,
        stop_event: asyncio.Event | None = None,
        drain_budget_seconds: float | None = None,
        drain_deadline_waiter: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if drain_budget_seconds is not None and (
            isinstance(drain_budget_seconds, bool)
            or not isinstance(drain_budget_seconds, (int, float))
            or not math.isfinite(drain_budget_seconds)
            or drain_budget_seconds <= 0
        ):
            raise ValueError("drain_budget_seconds must be finite and positive")
        if drain_deadline_waiter is not None and drain_budget_seconds is None:
            raise ValueError("drain_deadline_waiter requires an explicit drain budget")

        self.stop_event = stop_event or asyncio.Event()
        self._drain_budget_seconds = drain_budget_seconds
        self._drain_deadline_waiter = drain_deadline_waiter
        self._runners = dict(runners or {})
        self.runtime_mode = (
            ManagerRuntimeMode.PHASE2_RUNTIME
            if self._runners
            else ManagerRuntimeMode.FOUNDATION
        )
        self._states = {group: _GroupState() for group in ManagerGroup}
        self._missing_groups = REQUIRED_MANAGER_GROUPS - self._runners.keys()
        self._dependency_gate_open = not self._missing_groups
        if not self._dependency_gate_open:
            for state in self._states.values():
                state.lifecycle = GroupLifecycle.DEGRADED
                state.dependency_status = "BLOCKED_BY_DEPENDENCY"
        self._tasks: dict[ManagerGroup, asyncio.Task[None]] = {}
        self._failure: tuple[ManagerGroup, BaseException] | None = None
        self._failure_event = asyncio.Event()
        self._shutdown_started = False
        self._drain_task: asyncio.Task[None] | None = None
        self._drain_deadline_task: asyncio.Task[None] | None = None
        self._drain_observation_event = asyncio.Event()
        self._drain_outcome: DrainOutcome | None = None
        self._timed_out_groups: frozenset[ManagerGroup] = frozenset()
        self._cleanup_complete = False

    @property
    def failure(self) -> tuple[ManagerGroup, BaseException] | None:
        return self._failure

    @property
    def dependency_gate_open(self) -> bool:
        return self._dependency_gate_open

    @property
    def shutdown_started(self) -> bool:
        return self._shutdown_started

    @property
    def active_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    @property
    def drain_outcome(self) -> DrainOutcome | None:
        return self._drain_outcome

    @property
    def cleanup_complete(self) -> bool:
        return self._cleanup_complete

    async def wait_for_drain_timeout(self) -> DrainOutcome:
        """Wait for the drain observation to resolve as CLEAN or INCOMPLETE."""
        if self._drain_budget_seconds is None:
            raise RuntimeError("No drain observation budget is configured")
        await self._drain_observation_event.wait()
        if self._drain_outcome is None:
            raise RuntimeError("Drain observation completed without an outcome")
        return self._drain_outcome

    def snapshot(self) -> Mapping[ManagerGroup, GroupSnapshot]:
        return MappingProxyType(
            {
                group: GroupSnapshot(
                    group=group,
                    lifecycle=state.lifecycle,
                    dependency_status=state.dependency_status,
                    diagnostic_type=state.diagnostic_type,
                    progress_count=state.progress_count,
                    last_progress_monotonic=state.last_progress_monotonic,
                )
                for group, state in self._states.items()
            }
        )

    async def run(self) -> None:
        """Start available runners, then stop and await all owned tasks."""
        try:
            if (
                self.runtime_mode is ManagerRuntimeMode.PHASE2_RUNTIME
                and not self._dependency_gate_open
            ):
                raise RequiredGroupsMissingError(self._missing_groups)
            if self.stop_event.is_set():
                await self._stop_and_drain()
                return

            started_events: list[asyncio.Event] = []
            for group, runner in self._runners.items():
                if self.stop_event.is_set():
                    break
                started = asyncio.Event()
                started_events.append(started)
                task = asyncio.create_task(
                    self._run_group(group, runner, started),
                    name=f"manager:{group.value}",
                )
                self._tasks[group] = task

            if started_events:
                await asyncio.gather(*(event.wait() for event in started_events))

            stop_waiter = asyncio.create_task(
                self.stop_event.wait(), name="manager:stop-signal"
            )
            failure_waiter = asyncio.create_task(
                self._failure_event.wait(), name="manager:failure-signal"
            )
            try:
                await asyncio.wait(
                    {*self._tasks.values(), stop_waiter, failure_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for waiter in (stop_waiter, failure_waiter):
                    if not waiter.done():
                        waiter.cancel()
                await asyncio.gather(
                    stop_waiter,
                    failure_waiter,
                    return_exceptions=True,
                )

            await self._stop_and_drain()
            if self._failure is not None:
                group, cause = self._failure
                # The underlying exception may contain a DSN or another
                # sensitive configuration value; expose its type only.
                raise ManagerSupervisorError(group, cause) from None
        except asyncio.CancelledError:
            # Do not let outer cleanup dispose the shared Engine while an
            # injected runner is still unwinding. No unapproved timeout is used.
            self.stop_event.set()
            await self._await_drain_after_cancellation()
            raise

    async def _run_group(
        self,
        group: ManagerGroup,
        runner: GroupRunner,
        started: asyncio.Event,
    ) -> None:
        state = self._states[group]
        state.lifecycle = GroupLifecycle.RUNNING
        state.dependency_status = None
        logger.info("manager_group_running", extra={"manager_group": group.value})
        started.set()
        context = ManagerGroupContext(self, group)
        try:
            await runner(context)
            if not self._shutdown_started and not self.stop_event.is_set():
                self._record_failure(group, UnexpectedGroupExit())
        except asyncio.CancelledError as error:
            # Supervisor shutdown is cooperative; a cancelled group has not
            # proven that its in-flight work completed cleanly.
            self._record_failure(group, error)
            raise
        except BaseException as error:
            self._record_failure(group, error)
            raise
        finally:
            state.lifecycle = GroupLifecycle.STOPPED

    def _start_drain(self) -> asyncio.Task[None]:
        """Close claims and return the single Supervisor-owned drain task."""
        self._shutdown_started = True
        self.stop_event.set()
        for state in self._states.values():
            if state.lifecycle is not GroupLifecycle.STOPPED:
                state.lifecycle = GroupLifecycle.STOPPING
        if self._drain_task is None:
            self._drain_task = asyncio.create_task(
                self._drain_owned_tasks(), name="manager:drain"
            )
        return self._drain_task

    async def _drain_owned_tasks(self) -> None:
        tasks = tuple(self._tasks.values())
        all_tasks_done = asyncio.gather(*tasks, return_exceptions=True)
        deadline_task: asyncio.Task[None] | None = None
        timed_out = False
        try:
            if tasks and self._drain_budget_seconds is not None:
                deadline_waiter = self._drain_deadline_waiter or asyncio.sleep
                deadline_task = asyncio.create_task(
                    deadline_waiter(self._drain_budget_seconds),
                    name="manager:drain-deadline",
                )
                self._drain_deadline_task = deadline_task
                done, _ = await asyncio.wait(
                    {all_tasks_done, deadline_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if deadline_task in done and not all_tasks_done.done():
                    try:
                        deadline_task.result()
                    except Exception as error:
                        logger.error(
                            "manager_drain_deadline_wait_failed",
                            extra={"error_type": type(error).__name__},
                        )
                    timed_out = True
                    self._timed_out_groups = frozenset(
                        group for group, task in self._tasks.items() if not task.done()
                    )
                    self._drain_outcome = DrainOutcome.INCOMPLETE
                    self._drain_observation_event.set()
                    logger.error(
                        "manager_drain_incomplete",
                        extra={
                            "outstanding_manager_groups": sorted(
                                group.value for group in self._timed_out_groups
                            ),
                            "outstanding_group_count": len(self._timed_out_groups),
                        },
                    )
                    # The budget bounds observation only. Keep this task and
                    # every runner reference owned until actual completion.
                    await asyncio.shield(all_tasks_done)
                else:
                    if not deadline_task.done():
                        deadline_task.cancel()
                    await asyncio.gather(deadline_task, return_exceptions=True)
                    await all_tasks_done
            else:
                await all_tasks_done
        finally:
            if deadline_task is not None and not deadline_task.done():
                deadline_task.cancel()
                await asyncio.gather(deadline_task, return_exceptions=True)

        for group, state in self._states.items():
            task = self._tasks.get(group)
            if task is None or task.done():
                state.lifecycle = GroupLifecycle.STOPPED
        self._cleanup_complete = True
        if not timed_out:
            self._drain_outcome = DrainOutcome.CLEAN
            self._drain_observation_event.set()
        else:
            logger.warning(
                "manager_drain_cleanup_completed_after_timeout",
                extra={
                    "timed_out_manager_groups": sorted(
                        group.value for group in self._timed_out_groups
                    ),
                    "cleanup_complete": True,
                },
            )

    async def _stop_and_drain(self) -> None:
        drain = self._start_drain()
        await asyncio.shield(drain)
        if (
            self._drain_outcome is DrainOutcome.INCOMPLETE
            and self._failure is None
        ):
            raise ManagerDrainIncompleteError(self._timed_out_groups)

    async def _await_drain_after_cancellation(self) -> None:
        drain = self._start_drain()
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                # Repeated caller cancellation cannot release task ownership.
                continue
        await drain

    def _record_progress(self, group: ManagerGroup) -> None:
        state = self._states[group]
        state.progress_count += 1
        state.last_progress_monotonic = time.monotonic()

    def _record_transient(self, group: ManagerGroup, error: BaseException) -> None:
        state = self._states[group]
        if self._can_change_lifecycle(group):
            state.lifecycle = GroupLifecycle.DEGRADED
        state.diagnostic_type = type(error).__name__
        logger.warning(
            "manager_group_degraded",
            extra={
                "manager_group": group.value,
                "error_type": type(error).__name__,
            },
        )

    def _record_recovered(self, group: ManagerGroup) -> None:
        state = self._states[group]
        if self._can_change_lifecycle(group) and self._failure is None:
            state.lifecycle = GroupLifecycle.RUNNING
            state.diagnostic_type = None
            logger.info("manager_group_recovered", extra={"manager_group": group.value})

    def _can_change_lifecycle(self, group: ManagerGroup) -> bool:
        return (
            not self._shutdown_started
            and not self.stop_event.is_set()
            and self._states[group].lifecycle
            not in {GroupLifecycle.STOPPING, GroupLifecycle.STOPPED}
        )

    def _record_stall(self, group: ManagerGroup) -> None:
        self._states[group].diagnostic_type = ReportedGroupStall.__name__
        self._record_failure(group, ReportedGroupStall())

    def _record_failure(self, group: ManagerGroup, error: BaseException) -> None:
        if self._failure is None:
            self._failure = (group, error)
            state = self._states[group]
            if self._can_change_lifecycle(group):
                state.lifecycle = GroupLifecycle.DEGRADED
            state.diagnostic_type = type(error).__name__
            self._failure_event.set()
            logger.error(
                "manager_group_fatal",
                extra={"manager_group": group.value, "error_type": type(error).__name__},
            )
