import asyncio
from collections.abc import Awaitable, Callable

import pytest

from gpu_marketplace.manager.scheduler import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    SchedulingCycle,
    WaitForInterval,
)
from gpu_marketplace.manager.supervisor import (
    DrainOutcome,
    GroupLifecycle,
    GroupRunner,
    ManagerDrainIncompleteError,
    ManagerGroup,
    ManagerGroupContext,
    ManagerRuntimeMode,
    ManagerSupervisor,
    ManagerSupervisorError,
)
from gpu_marketplace.manager.scheduler_runtime import create_scheduler_group_runner


async def _wait_for_stop(context: ManagerGroupContext) -> None:
    await context.stop_event.wait()


def _required_runners(scheduling_runner: GroupRunner) -> dict[ManagerGroup, GroupRunner]:
    runners = {group: _wait_for_stop for group in ManagerGroup}
    runners[ManagerGroup.SCHEDULING_ALLOCATION] = scheduling_runner
    return runners


def _runner(
    cycle: SchedulingCycle,
    *,
    wait_for_interval: WaitForInterval | None = None,
    is_transient_failure: Callable[[Exception], bool] | None = None,
) -> GroupRunner:
    kwargs: dict[str, object] = {
        "cycle": cycle,
        "initial_scan_immediately": True,
        "is_transient_failure": is_transient_failure or (lambda _: False),
    }
    if wait_for_interval is not None:
        kwargs["wait_for_interval"] = wait_for_interval
    return create_scheduler_group_runner(**kwargs)  # type: ignore[arg-type]


def _assert_no_pending_manager_tasks() -> None:
    current = asyncio.current_task()
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not current
        and task.get_name().startswith("manager:")
        and not task.done()
    ]
    assert pending == []


class _ControlledDeadline:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.expire = asyncio.Event()

    async def __call__(self, budget_seconds: float) -> None:
        assert budget_seconds > 0
        self.started.set()
        await self.expire.wait()


def test_int01_scheduler_uses_supervisor_stop_event_and_stops_cadence() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()
        observed_events: list[asyncio.Event] = []
        cycles = 0

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        async def wait_for_stop(event: asyncio.Event, interval: float) -> bool:
            assert interval == DEFAULT_SCAN_INTERVAL_SECONDS
            observed_events.append(event)
            wait_started.set()
            await event.wait()
            return True

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(cycle, wait_for_interval=wait_for_stop)
            ),
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(wait_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

        assert observed_events == [stop_event]
        assert cycles == 1
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int02_claim_gate_is_read_live_for_each_scheduler_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_count = 0
        cycles = 0
        gate_closed = asyncio.Event()

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        supervisor: ManagerSupervisor

        async def wait_for_interval(event: asyncio.Event, _: float) -> bool:
            nonlocal wait_count
            wait_count += 1
            if wait_count == 1:
                # A latched Supervisor shutdown closes claims even before its
                # stop signal is observed by this controlled scheduler wait.
                supervisor._shutdown_started = True
                gate_closed.set()
                return False
            stop_event.set()
            return True

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(cycle, wait_for_interval=wait_for_interval)
            ),
            stop_event=stop_event,
        )
        await asyncio.wait_for(supervisor.run(), timeout=2)

        assert gate_closed.is_set()
        assert cycles == 1
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int03_closed_claim_gate_prevents_initial_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycles = 0
        wait_started = asyncio.Event()

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        async def wait_for_interval(_: asyncio.Event, __: float) -> bool:
            wait_started.set()
            stop_event.set()
            return True

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(cycle, wait_for_interval=wait_for_interval)
            ),
            stop_event=stop_event,
        )
        supervisor._shutdown_started = True
        await asyncio.wait_for(supervisor.run(), timeout=2)

        assert wait_started.is_set()
        assert cycles == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int04_successful_cycle_increments_supervisor_progress_once() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_completed = asyncio.Event()
        allocations = ["allocation-1"]

        async def cycle() -> None:
            assert allocations == ["allocation-1"]
            cycle_completed.set()
            stop_event.set()

        supervisor = ManagerSupervisor(
            runners=_required_runners(_runner(cycle)), stop_event=stop_event
        )
        await asyncio.wait_for(supervisor.run(), timeout=2)

        assert cycle_completed.is_set()
        assert supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].progress_count == 1
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int05_completed_empty_scan_reports_progress() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def empty_scan() -> None:
            stop_event.set()
            return None

        supervisor = ManagerSupervisor(
            runners=_required_runners(_runner(empty_scan)), stop_event=stop_event
        )
        await asyncio.wait_for(supervisor.run(), timeout=2)

        snapshot = supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION]
        assert snapshot.progress_count == 1
        assert snapshot.last_progress_monotonic is not None
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int06_failed_cycle_does_not_emit_heartbeat() -> None:
    async def scenario() -> None:
        async def failed_cycle() -> None:
            raise ValueError("cycle failed")

        supervisor = ManagerSupervisor(
            runners=_required_runners(_runner(failed_cycle))
        )
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)

        assert exc.value.cause_type == "ValueError"
        assert supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].progress_count == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int07_transient_classification_preserves_failure_contract() -> None:
    class TemporaryCycleFailure(RuntimeError):
        pass

    async def scenario() -> None:
        async def transient_cycle() -> None:
            raise TemporaryCycleFailure("sensitive diagnostic")

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(
                    transient_cycle,
                    is_transient_failure=lambda error: isinstance(
                        error, TemporaryCycleFailure
                    ),
                )
            )
        )
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)

        assert exc.value.cause_type == "TemporaryCycleFailure"
        assert supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].progress_count == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int08_fatal_exception_reaches_supervisor() -> None:
    class FatalCycleFailure(RuntimeError):
        pass

    async def scenario() -> None:
        async def fatal_cycle() -> None:
            raise FatalCycleFailure("fatal")

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(
                    fatal_cycle,
                    is_transient_failure=lambda _: False,
                )
            )
        )
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)

        assert exc.value.group is ManagerGroup.SCHEDULING_ALLOCATION
        assert exc.value.cause_type == "FatalCycleFailure"
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int09_caller_cancellation_is_not_swallowed_and_cycle_remains_owned() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        cycle_observed_stop = asyncio.Event()
        release_cycle = asyncio.Event()
        contexts: list[ManagerGroupContext] = []

        async def cycle() -> None:
            cycle_started.set()
            await contexts[0].stop_event.wait()
            cycle_observed_stop.set()
            await release_cycle.wait()

        adapter = _runner(cycle)

        async def capture_context(context: ManagerGroupContext) -> None:
            contexts.append(context)
            await adapter(context)

        supervisor = ManagerSupervisor(
            runners=_required_runners(capture_context), stop_event=stop_event
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        task.cancel()
        await asyncio.wait_for(cycle_observed_stop.wait(), timeout=2)

        assert not task.done()
        assert supervisor.active_task_count == 1
        release_cycle.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert supervisor.cleanup_complete
        assert supervisor.active_task_count == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int10_stop_during_cadence_wait_prevents_next_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()
        cycles = 0

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        async def wait_for_stop(event: asyncio.Event, _: float) -> bool:
            wait_started.set()
            await event.wait()
            return True

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(cycle, wait_for_interval=wait_for_stop)
            ),
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(wait_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

        assert cycles == 1
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int11_stop_inflight_cycle_keeps_supervisor_ownership_until_completion() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        deadline = _ControlledDeadline()

        async def cycle() -> None:
            cycle_started.set()
            await release_cycle.wait()

        supervisor = ManagerSupervisor(
            runners=_required_runners(_runner(cycle)),
            stop_event=stop_event,
            drain_budget_seconds=5.0,
            drain_deadline_waiter=deadline,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(deadline.started.wait(), timeout=2)

        assert not task.done()
        assert supervisor.active_task_count == 1
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.STOPPING
        )
        release_cycle.set()
        await asyncio.wait_for(task, timeout=2)

        assert supervisor.drain_outcome is DrainOutcome.CLEAN
        assert supervisor.cleanup_complete
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int12_drain_timeout_retains_inflight_cycle_ownership() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        deadline = _ControlledDeadline()

        async def cycle() -> None:
            cycle_started.set()
            await release_cycle.wait()

        supervisor = ManagerSupervisor(
            runners=_required_runners(_runner(cycle)),
            stop_event=stop_event,
            drain_budget_seconds=5.0,
            drain_deadline_waiter=deadline,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(deadline.started.wait(), timeout=2)
        deadline.expire.set()

        assert await asyncio.wait_for(supervisor.wait_for_drain_timeout(), timeout=2) is DrainOutcome.INCOMPLETE
        assert supervisor.active_task_count == 1
        assert not supervisor.cleanup_complete
        assert not task.done()
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.STOPPING
        )

        release_cycle.set()
        with pytest.raises(ManagerDrainIncompleteError):
            await asyncio.wait_for(task, timeout=2)

        assert supervisor.cleanup_complete
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.STOPPED
        )
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int13_recovery_cannot_reopen_claims_after_shutdown() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        deadline = _ControlledDeadline()
        contexts: list[ManagerGroupContext] = []

        async def cycle() -> None:
            cycle_started.set()
            await release_cycle.wait()
            contexts[0].report_recovered()
            assert not contexts[0].claims_allowed
            assert (
                supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
                is GroupLifecycle.STOPPING
            )

        adapter = _runner(cycle)

        async def capture_context(context: ManagerGroupContext) -> None:
            contexts.append(context)
            await adapter(context)

        supervisor = ManagerSupervisor(
            runners=_required_runners(capture_context),
            stop_event=stop_event,
            drain_budget_seconds=5.0,
            drain_deadline_waiter=deadline,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(deadline.started.wait(), timeout=2)

        assert not contexts[0].claims_allowed
        contexts[0].report_recovered()
        assert not contexts[0].claims_allowed
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.STOPPING
        )

        release_cycle.set()
        await asyncio.wait_for(task, timeout=2)
        assert not contexts[0].claims_allowed
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int14_scheduler_adapter_leaves_no_detached_manager_tasks() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()

        async def cycle() -> None:
            return None

        async def wait_for_stop(event: asyncio.Event, _: float) -> bool:
            wait_started.set()
            await event.wait()
            return True

        supervisor = ManagerSupervisor(
            runners=_required_runners(
                _runner(cycle, wait_for_interval=wait_for_stop)
            ),
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(wait_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int15_adapter_rejects_non_scheduling_manager_group() -> None:
    async def scenario() -> None:
        cycles = 0
        stop_event = asyncio.Event()

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        adapter = _runner(cycle)
        runners = {group: _wait_for_stop for group in ManagerGroup}
        runners[ManagerGroup.OUTBOX_DISPATCH_RETRY] = adapter
        supervisor = ManagerSupervisor(runners=runners, stop_event=stop_event)

        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)

        assert exc.value.group is ManagerGroup.OUTBOX_DISPATCH_RETRY
        assert exc.value.cause_type == "ValueError"
        assert cycles == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())


def test_int16_foundation_mode_behavior_remains_unchanged() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        cycles = 0

        async def cycle() -> None:
            nonlocal cycles
            cycles += 1

        supervisor = ManagerSupervisor(stop_event=stop_event)
        assert supervisor.runtime_mode is ManagerRuntimeMode.FOUNDATION
        await asyncio.wait_for(supervisor.run(), timeout=2)

        assert supervisor.runtime_mode is ManagerRuntimeMode.FOUNDATION
        assert supervisor.cleanup_complete
        assert supervisor.drain_outcome is DrainOutcome.CLEAN
        assert cycles == 0
        _assert_no_pending_manager_tasks()

    asyncio.run(scenario())
