import asyncio
import threading
from types import SimpleNamespace

import pytest

from gpu_marketplace.common.config import Settings
from gpu_marketplace.manager import __main__ as manager_main
from gpu_marketplace.manager.service import run_manager
from gpu_marketplace.manager.supervisor import (
    FatalManagerConfigurationError,
    GroupLifecycle,
    ManagerGroup,
    ManagerGroupContext,
    ManagerSupervisor,
    ManagerSupervisorError,
    ReportedGroupStall,
    TransientManagerDependencyError,
)


def test_supervisor_runs_three_groups_independently_and_drains_them() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        started = {group: asyncio.Event() for group in ManagerGroup}
        finished = {group: asyncio.Event() for group in ManagerGroup}

        def make_runner(group: ManagerGroup):
            async def runner(context: ManagerGroupContext) -> None:
                started[group].set()
                try:
                    await context.stop_event.wait()
                finally:
                    finished[group].set()

            return runner

        supervisor = ManagerSupervisor(
            runners={group: make_runner(group) for group in ManagerGroup},
            stop_event=stop_event,
        )
        manager_task = asyncio.create_task(supervisor.run())
        await asyncio.gather(*(event.wait() for event in started.values()))

        assert supervisor.active_task_count == 3
        assert all(
            supervisor.snapshot()[group].lifecycle is GroupLifecycle.RUNNING
            for group in ManagerGroup
        )

        stop_event.set()
        await asyncio.wait_for(manager_task, timeout=2)

        assert all(event.is_set() for event in finished.values())
        assert supervisor.active_task_count == 0
        assert all(
            supervisor.snapshot()[group].lifecycle is GroupLifecycle.STOPPED
            for group in ManagerGroup
        )

    asyncio.run(scenario())


def test_slow_group_does_not_block_progress_in_an_independent_group() -> None:
    async def scenario() -> None:
        slow_waiting = asyncio.Event()
        allow_slow_to_finish = asyncio.Event()
        fast_progress = asyncio.Event()
        stop_event = asyncio.Event()

        async def slow_runner(context: ManagerGroupContext) -> None:
            slow_waiting.set()
            await allow_slow_to_finish.wait()
            await context.stop_event.wait()

        async def fast_runner(context: ManagerGroupContext) -> None:
            await slow_waiting.wait()
            context.heartbeat()
            fast_progress.set()
            await context.stop_event.wait()

        supervisor = ManagerSupervisor(
            runners={
                ManagerGroup.SCHEDULING_ALLOCATION: slow_runner,
                ManagerGroup.OUTBOX_DISPATCH_RETRY: fast_runner,
            },
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(fast_progress.wait(), timeout=2)

        assert slow_waiting.is_set()
        assert (
            supervisor.snapshot()[ManagerGroup.OUTBOX_DISPATCH_RETRY].progress_count
            == 1
        )
        stop_event.set()
        allow_slow_to_finish.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_fatal_group_failure_stops_peers_and_waits_for_cleanup() -> None:
    async def scenario() -> None:
        peer_stopping = asyncio.Event()
        allow_peer_cleanup = asyncio.Event()
        peer_finished = asyncio.Event()

        async def failing_runner(_: ManagerGroupContext) -> None:
            raise ValueError("synthetic fatal fault")

        async def peer_runner(context: ManagerGroupContext) -> None:
            try:
                await context.stop_event.wait()
                peer_stopping.set()
                await allow_peer_cleanup.wait()
            finally:
                peer_finished.set()

        supervisor = ManagerSupervisor(
            runners={
                ManagerGroup.SCHEDULING_ALLOCATION: failing_runner,
                ManagerGroup.OUTBOX_DISPATCH_RETRY: peer_runner,
            }
        )
        manager_task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(peer_stopping.wait(), timeout=2)
        assert not manager_task.done()
        assert not peer_finished.is_set()
        allow_peer_cleanup.set()

        with pytest.raises(
            ManagerSupervisorError, match="all supervised tasks have stopped"
        ) as exc:
            await asyncio.wait_for(manager_task, timeout=2)

        assert exc.value.cause_type == "ValueError"
        assert peer_finished.is_set()
        assert supervisor.active_task_count == 0

    asyncio.run(scenario())


def test_unexpected_group_return_fails_fast() -> None:
    async def scenario() -> None:
        async def returned_runner(_: ManagerGroupContext) -> None:
            return

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: returned_runner}
        )
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)

        assert exc.value.cause_type == "UnexpectedGroupExit"
        assert supervisor.active_task_count == 0
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.STOPPED
        )

    asyncio.run(scenario())


def test_cancelled_group_during_shutdown_is_reported_as_incomplete() -> None:
    async def scenario() -> None:
        runner_started = asyncio.Event()
        stop_event = asyncio.Event()

        async def runner(context: ManagerGroupContext) -> None:
            runner_started.set()
            await context.stop_event.wait()
            raise asyncio.CancelledError()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner},
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(runner_started.wait(), timeout=2)
        stop_event.set()

        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(task, timeout=2)

        assert exc.value.cause_type == "CancelledError"
        assert supervisor.active_task_count == 0

    asyncio.run(scenario())


def test_transient_report_degrades_but_does_not_stop_runner() -> None:
    async def scenario() -> None:
        transient_reported = asyncio.Event()
        allow_recovery = asyncio.Event()
        recovered = asyncio.Event()
        stop_event = asyncio.Event()

        async def runner(context: ManagerGroupContext) -> None:
            context.report_transient(
                TransientManagerDependencyError("temporary backend fault")
            )
            transient_reported.set()
            await allow_recovery.wait()
            context.report_recovered()
            recovered.set()
            await context.stop_event.wait()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.OUTBOX_DISPATCH_RETRY: runner},
            stop_event=stop_event,
        )
        manager_task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(transient_reported.wait(), timeout=2)
        assert (
            supervisor.snapshot()[ManagerGroup.OUTBOX_DISPATCH_RETRY].lifecycle
            is GroupLifecycle.DEGRADED
        )
        assert supervisor.failure is None

        allow_recovery.set()
        await asyncio.wait_for(recovered.wait(), timeout=2)
        assert (
            supervisor.snapshot()[ManagerGroup.OUTBOX_DISPATCH_RETRY].lifecycle
            is GroupLifecycle.RUNNING
        )
        stop_event.set()
        await asyncio.wait_for(manager_task, timeout=2)

    asyncio.run(scenario())


def test_fatal_configuration_error_cannot_be_reported_as_transient() -> None:
    async def scenario() -> None:
        report_rejected = asyncio.Event()
        stop_event = asyncio.Event()

        async def runner(context: ManagerGroupContext) -> None:
            try:
                context.report_transient(FatalManagerConfigurationError())
            except TypeError:
                report_rejected.set()
            await context.stop_event.wait()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner},
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(report_rejected.wait(), timeout=2)
        assert supervisor.failure is None
        assert (
            supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION].lifecycle
            is GroupLifecycle.RUNNING
        )
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_uncaught_fatal_configuration_error_stops_manager() -> None:
    async def scenario() -> None:
        async def runner(_: ManagerGroupContext) -> None:
            raise FatalManagerConfigurationError("invalid startup configuration")

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner}
        )
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(supervisor.run(), timeout=2)
        assert exc.value.cause_type == "FatalManagerConfigurationError"

    asyncio.run(scenario())


def test_stop_signal_prevents_runner_from_starting_another_claim() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        first_claim_started = asyncio.Event()
        claim_count = 0

        async def runner(context: ManagerGroupContext) -> None:
            nonlocal claim_count
            while context.claims_allowed:
                claim_count += 1
                first_claim_started.set()
                await context.stop_event.wait()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner},
            stop_event=stop_event,
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(first_claim_started.wait(), timeout=2)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

        assert claim_count == 1

    asyncio.run(scenario())


def test_empty_scan_heartbeat_is_progress_and_stall_hook_fails_fast() -> None:
    async def scenario() -> None:
        context_ready = asyncio.Event()
        context_holder: list[ManagerGroupContext] = []

        async def runner(context: ManagerGroupContext) -> None:
            context.heartbeat()  # A completed scan with no work is still progress.
            context_holder.append(context)
            context_ready.set()
            await context.stop_event.wait()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner}
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(context_ready.wait(), timeout=2)
        snapshot = supervisor.snapshot()[ManagerGroup.SCHEDULING_ALLOCATION]
        assert snapshot.progress_count == 1
        assert snapshot.last_progress_monotonic is not None

        context_holder[0].report_stall()
        with pytest.raises(ManagerSupervisorError) as exc:
            await asyncio.wait_for(task, timeout=2)
        assert exc.value.cause_type == ReportedGroupStall.__name__
        assert supervisor.active_task_count == 0

    asyncio.run(scenario())


def test_missing_runners_are_blocked_and_never_reported_ready() -> None:
    supervisor = ManagerSupervisor()
    snapshots = supervisor.snapshot()

    assert set(snapshots) == set(ManagerGroup)
    assert all(
        snapshot.lifecycle is GroupLifecycle.DEGRADED
        and snapshot.dependency_status == "BLOCKED_BY_DEPENDENCY"
        for snapshot in snapshots.values()
    )
    assert not hasattr(supervisor, "phase2_ready")
    assert supervisor.active_task_count == 0


def test_manager_engine_is_disposed_only_after_supervised_tasks_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        runner_started = asyncio.Event()
        runner_cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        runner_finished = asyncio.Event()

        class Engine:
            def dispose(self) -> None:
                assert runner_finished.is_set()

        engine = Engine()
        settings = Settings(_env_file=None)

        async def runner(context: ManagerGroupContext) -> None:
            runner_started.set()
            try:
                await context.stop_event.wait()
            finally:
                runner_cleanup_started.set()
                await release_cleanup.wait()
                runner_finished.set()

        async def run_manager_with_test_runner(
            *,
            settings: Settings,
            database_probe,
            stop_event: asyncio.Event,
        ) -> None:
            task = asyncio.create_task(
                run_manager(
                    settings=settings,
                    database_probe=database_probe,
                    stop_event=stop_event,
                    group_runners={ManagerGroup.SCHEDULING_ALLOCATION: runner},
                )
            )
            await asyncio.wait_for(runner_started.wait(), timeout=2)
            stop_event.set()
            await asyncio.wait_for(runner_cleanup_started.wait(), timeout=2)
            assert not runner_finished.is_set()
            release_cleanup.set()
            await asyncio.wait_for(task, timeout=2)

        monkeypatch.setattr(manager_main, "Settings", lambda: settings)
        monkeypatch.setattr(manager_main, "configure_logging", lambda _level: None)
        monkeypatch.setattr(manager_main, "create_engine", lambda _url: engine)
        monkeypatch.setattr(manager_main, "database_is_ready", lambda _engine: True)
        monkeypatch.setattr(manager_main, "run_manager", run_manager_with_test_runner)
        monkeypatch.setattr(
            manager_main,
            "signal",
            SimpleNamespace(SIGINT=None, SIGTERM=None),
        )

        await manager_main.run()
        assert runner_finished.is_set()

    asyncio.run(scenario())


def test_cancellation_waits_for_sync_database_probe_worker() -> None:
    probe_started = threading.Event()
    release_probe = threading.Event()
    probe_finished = threading.Event()

    def blocking_probe() -> bool:
        probe_started.set()
        release_probe.wait()
        probe_finished.set()
        return True

    async def scenario() -> None:
        task = asyncio.create_task(
            run_manager(
                settings=Settings(_env_file=None),
                database_probe=blocking_probe,
            )
        )
        assert await asyncio.wait_for(
            asyncio.to_thread(probe_started.wait, 2), timeout=3
        )

        cancellation_delivered = asyncio.Event()
        task.cancel()
        asyncio.get_running_loop().call_soon(cancellation_delivered.set)
        await cancellation_delivered.wait()

        assert not task.done()
        assert not probe_finished.is_set()
        release_probe.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert probe_finished.is_set()

    try:
        asyncio.run(scenario())
    finally:
        release_probe.set()


def test_supervisor_cancellation_waits_for_runner_cleanup() -> None:
    async def scenario() -> None:
        runner_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        allow_cleanup = asyncio.Event()
        runner_finished = asyncio.Event()

        async def runner(context: ManagerGroupContext) -> None:
            runner_started.set()
            try:
                await context.stop_event.wait()
            finally:
                cleanup_started.set()
                await allow_cleanup.wait()
                runner_finished.set()

        supervisor = ManagerSupervisor(
            runners={ManagerGroup.SCHEDULING_ALLOCATION: runner}
        )
        task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(runner_started.wait(), timeout=2)
        task.cancel()

        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        assert not task.done()
        assert not runner_finished.is_set()
        allow_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert runner_finished.is_set()
        assert supervisor.active_task_count == 0

    asyncio.run(scenario())
