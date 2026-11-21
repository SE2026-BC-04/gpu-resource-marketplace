"""Lifecycle supervision for the three Phase 2 Manager loop groups.

This module owns task lifecycle only. Business runners are supplied by their
module owners once their interfaces are available; a missing runner remains
explicitly blocked instead of being replaced by a no-op loop.
"""

from __future__ import annotations

import asyncio
import logging
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
    ) -> None:
        self.stop_event = stop_event or asyncio.Event()
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

    @property
    def failure(self) -> tuple[ManagerGroup, BaseException] | None:
        return self._failure

    @property
    def dependency_gate_open(self) -> bool:
        return self._dependency_gate_open

    @property
    def active_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

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
            if not self.stop_event.is_set():
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

    async def _stop_and_drain(self) -> None:
        self.stop_event.set()
        for state in self._states.values():
            if state.lifecycle is not GroupLifecycle.STOPPED:
                state.lifecycle = GroupLifecycle.STOPPING

        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        for state in self._states.values():
            state.lifecycle = GroupLifecycle.STOPPED

    async def _await_drain_after_cancellation(self) -> None:
        drain = asyncio.create_task(self._stop_and_drain(), name="manager:cancel-drain")
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                # A second cancellation still cannot release Engine ownership
                # before the group tasks have actually stopped.
                continue
        await drain

    def _record_progress(self, group: ManagerGroup) -> None:
        state = self._states[group]
        state.progress_count += 1
        state.last_progress_monotonic = time.monotonic()

    def _record_transient(self, group: ManagerGroup, error: BaseException) -> None:
        state = self._states[group]
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
        if not self.stop_event.is_set() and self._failure is None:
            state.lifecycle = GroupLifecycle.RUNNING
            state.diagnostic_type = None
            logger.info("manager_group_recovered", extra={"manager_group": group.value})

    def _record_stall(self, group: ManagerGroup) -> None:
        self._states[group].diagnostic_type = ReportedGroupStall.__name__
        self._record_failure(group, ReportedGroupStall())

    def _record_failure(self, group: ManagerGroup, error: BaseException) -> None:
        if self._failure is None:
            self._failure = (group, error)
            state = self._states[group]
            state.lifecycle = GroupLifecycle.DEGRADED
            state.diagnostic_type = type(error).__name__
            self._failure_event.set()
            logger.error(
                "manager_group_fatal",
                extra={"manager_group": group.value, "error_type": type(error).__name__},
            )
