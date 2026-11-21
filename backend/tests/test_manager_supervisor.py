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
    GroupRunner,
    ManagerGroup,
    ManagerGroupContext,
    ManagerRuntimeMode,
    ManagerSupervisor,
    ManagerSupervisorError,
    ReportedGroupStall,
    TransientManagerDependencyError,
)


async def _wait_for_stop(context: ManagerGroupContext) -> None:
    await context.stop_event.wait()


def _with_required_groups(
    runners: dict[ManagerGroup, GroupRunner],
) -> dict[ManagerGroup, GroupRunner]:
    """Add controlled waiting peers for tests of one or two active runners."""
    complete = {group: _wait_for_stop for group in ManagerGroup}
    complete.update(runners)
    return complete


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
            runners=_with_required_groups(
                {
                    ManagerGroup.SCHEDULING_ALLOCATION: slow_runner,
                    ManagerGroup.OUTBOX_DISPATCH_RETRY: fast_runner,
                }
            ),
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
        peer_stopping = {
            ManagerGroup.OUTBOX_DISPATCH_RETRY: asyncio.Event(),
            ManagerGroup.INBOX_VERIFICATION_FINALIZATION_DEADLINE: asyncio.Event(),
        }
        allow_peer_cleanup = asyncio.Event()
        peer_finished = {group: asyncio.Event() for group in peer_stopping}
        trigger_failure = asyncio.Event()
        started = {group: asyncio.Event() for group in ManagerGroup}
        contexts: dict[ManagerGroup, ManagerGroupContext] = {}
        claims = dict.fromkeys(ManagerGroup, 0)

        async def failing_runner(context: ManagerGroupContext) -> None:
            contexts[context.group] = context
            claims[context.group] += int(context.claims_allowed)
            started[context.group].set()
            await trigger_failure.wait()
            raise ValueError("synthetic fatal fault")

        def make_peer_runner(group: ManagerGroup):
            async def peer_runner(context: ManagerGroupContext) -> None:
                contexts[group] = context
                claims[group] += int(context.claims_allowed)
                started[group].set()
                try:
                    await context.stop_event.wait()
                    peer_stopping[group].set()
                    await allow_peer_cleanup.wait()
                finally:
                    peer_finished[group].set()

            return peer_runner

        supervisor = ManagerSupervisor(
            runners={
                ManagerGroup.SCHEDULING_ALLOCATION: failing_runner,
                **{
                    group: make_peer_runner(group)
                    for group in peer_stopping
                },
            }
        )
        manager_task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in started.values())),
            timeout=2,
        )
        assert all(count == 1 for count in claims.values())
        assert all(context.claims_allowed for context in contexts.values())
        trigger_failure.set()
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in peer_stopping.values())),
            timeout=2,
        )
        assert all(not context.claims_allowed for context in contexts.values())
        assert not manager_task.done()
        assert not any(event.is_set() for event in peer_finished.values())
        allow_peer_cleanup.set()

        with pytest.raises(
            ManagerSupervisorError, match="all supervised tasks have stopped"
        ) as exc:
            await asyncio.wait_for(manager_task, timeout=2)

        assert exc.value.cause_type == "ValueError"
        assert all(event.is_set() for event in peer_finished.values())
        assert all(count == 1 for count in claims.values())
        assert supervisor.active_task_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provided_groups",
    [
        (ManagerGroup.SCHEDULING_ALLOCATION,),
        (
            ManagerGroup.SCHEDULING_ALLOCATION,
            ManagerGroup.OUTBOX_DISPATCH_RETRY,
        ),
    ],
    ids=["scheduler-only", "scheduler-plus-outbox"],
)
def test_partial_required_groups_fail_before_any_runner_or_claim(
    provided_groups: tuple[ManagerGroup, ...],
) -> None:
    async def scenario() -> None:
        runner_calls: list[ManagerGroup] = []
        business_claims: list[ManagerGroup] = []

        def make_runner(group: ManagerGroup):
            async def runner(context: ManagerGroupContext) -> None:
                runner_calls.append(group)
                if context.claims_allowed:
                    business_claims.append(group)

            return runner

        supervisor = ManagerSupervisor(
            runners={group: make_runner(group) for group in provided_groups}
        )
        assert supervisor.runtime_mode is ManagerRuntimeMode.PHASE2_RUNTIME
        assert not supervisor.dependency_gate_open

        with pytest.raises(RuntimeError, match="missing required groups"):
            await supervisor.run()

        assert runner_calls == []
        assert business_claims == []
        assert supervisor.active_task_count == 0
        assert all(
            snapshot.dependency_status == "BLOCKED_BY_DEPENDENCY"
            for snapshot in supervisor.snapshot().values()
        )

    asyncio.run(scenario())


def test_full_required_group_set_opens_gate_and_starts_all_groups() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        started = {group: asyncio.Event() for group in ManagerGroup}
        contexts: dict[ManagerGroup, ManagerGroupContext] = {}

        def make_runner(group: ManagerGroup):
            async def runner(context: ManagerGroupContext) -> None:
                contexts[group] = context
                started[group].set()
                await context.stop_event.wait()

            return runner

        supervisor = ManagerSupervisor(
            runners={group: make_runner(group) for group in ManagerGroup},
            stop_event=stop_event,
        )
        assert supervisor.runtime_mode is ManagerRuntimeMode.PHASE2_RUNTIME
        assert supervisor.dependency_gate_open
        manager_task = asyncio.create_task(supervisor.run())
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in started.values())),
            timeout=2,
        )

        assert all(context.claims_allowed for context in contexts.values())
        assert all(
            snapshot.dependency_status is None
            for snapshot in supervisor.snapshot().values()
        )
        stop_event.set()
        await asyncio.wait_for(manager_task, timeout=2)

    asyncio.run(scenario())


def test_unexpected_group_return_fails_fast() -> None:
    async def scenario() -> None:
        async def returned_runner(_: ManagerGroupContext) -> None:
            return

        supervisor = ManagerSupervisor(
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: returned_runner}
            )
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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            ),
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
            runners=_with_required_groups(
                {ManagerGroup.OUTBOX_DISPATCH_RETRY: runner}
            ),
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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            ),
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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            )
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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            ),
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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            )
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
    stop_event = asyncio.Event()
    supervisor = ManagerSupervisor(stop_event=stop_event)
    snapshots = supervisor.snapshot()
    contexts = [ManagerGroupContext(supervisor, group) for group in ManagerGroup]

    assert set(snapshots) == set(ManagerGroup)
    assert supervisor.runtime_mode is ManagerRuntimeMode.FOUNDATION
    assert not supervisor.dependency_gate_open
    assert all(
        snapshot.lifecycle is GroupLifecycle.DEGRADED
        and snapshot.dependency_status == "BLOCKED_BY_DEPENDENCY"
        for snapshot in snapshots.values()
    )
    assert all(not context.claims_allowed for context in contexts)
    assert sum(context.claims_allowed for context in contexts) == 0
    assert not hasattr(supervisor, "phase2_ready")
    assert supervisor.active_task_count == 0

    stop_event.set()
    asyncio.run(supervisor.run())
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
                    group_runners=_with_required_groups(
                        {ManagerGroup.SCHEDULING_ALLOCATION: runner}
                    ),
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


@pytest.mark.parametrize(
    "probe_outcome",
    [True, False, "raise"],
    ids=["true", "false", "exception"],
)
def test_cancelled_database_probe_preserves_cancellation_and_engine_order(
    probe_outcome: bool | str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_started = threading.Event()
    release_probe = threading.Event()
    probe_finished = threading.Event()

    def blocking_probe(_engine) -> bool:
        probe_started.set()
        release_probe.wait()
        try:
            if probe_outcome == "raise":
                raise RuntimeError("sensitive probe detail")
            return bool(probe_outcome)
        finally:
            probe_finished.set()

    class Engine:
        disposed = False

        def dispose(self) -> None:
            assert probe_finished.is_set()
            self.disposed = True

    async def scenario() -> None:
        try:
            engine = Engine()
            settings = Settings(_env_file=None)
            monkeypatch.setattr(manager_main, "Settings", lambda: settings)
            monkeypatch.setattr(manager_main, "configure_logging", lambda _level: None)
            monkeypatch.setattr(manager_main, "create_engine", lambda _url: engine)
            monkeypatch.setattr(manager_main, "database_is_ready", blocking_probe)
            monkeypatch.setattr(
                manager_main,
                "signal",
                SimpleNamespace(SIGINT=None, SIGTERM=None),
            )

            task = asyncio.create_task(manager_main.run())
            assert await asyncio.wait_for(
                asyncio.to_thread(probe_started.wait, 2), timeout=3
            )

            cancellation_delivered = asyncio.Event()
            task.cancel()
            asyncio.get_running_loop().call_soon(cancellation_delivered.set)
            await cancellation_delivered.wait()
            assert not task.done()
            assert not engine.disposed

            release_probe.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)

            assert probe_finished.is_set()
            assert engine.disposed
            assert not any(
                active.get_name() == "manager:db-probe" and not active.done()
                for active in asyncio.all_tasks()
            )
        finally:
            release_probe.set()

    asyncio.run(scenario())


def test_uncancelled_database_probe_exception_is_propagated() -> None:
    def broken_probe() -> bool:
        raise RuntimeError("database readiness failure")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="database readiness failure"):
            await run_manager(
                settings=Settings(_env_file=None),
                database_probe=broken_probe,
            )
        assert not any(
            active.get_name() == "manager:db-probe" and not active.done()
            for active in asyncio.all_tasks()
        )

    asyncio.run(scenario())


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
            runners=_with_required_groups(
                {ManagerGroup.SCHEDULING_ALLOCATION: runner}
            )
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
