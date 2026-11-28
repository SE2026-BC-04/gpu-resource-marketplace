import asyncio

import pytest

from gpu_marketplace.manager.scheduler import (
    DEFAULT_SCAN_INTERVAL_SECONDS,
    SchedulerOrchestrator,
    _wait_for_stop_or_interval,
)


def test_runner_starts_with_injected_cycle_port() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1
            stop_event.set()

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        await runner.run()

        assert calls == 1

    asyncio.run(scenario())


def test_empty_scan_records_progress_after_normal_completion() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def empty_scan() -> None:
            stop_event.set()

        runner = SchedulerOrchestrator(
            cycle=empty_scan,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            monotonic_clock=lambda: 123.5,
        )
        assert runner.last_completed_monotonic is None

        await runner.run()

        assert runner.last_completed_monotonic == 123.5

    asyncio.run(scenario())


def test_stop_signal_interrupts_the_scan_interval_wait() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1

        async def wait_for_stop(event: asyncio.Event, interval: float) -> bool:
            wait_started.set()
            return await _wait_for_stop_or_interval(event, interval)

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            scan_interval_seconds=3600,
            is_transient_failure=lambda _: False,
            wait_for_interval=wait_for_stop,
        )
        task = asyncio.create_task(runner.run())
        await wait_started.wait()
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

        assert calls == 1

    asyncio.run(scenario())


def test_preexisting_stop_prevents_any_new_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        await runner.run()

        assert calls == 0

    asyncio.run(scenario())


def test_one_runner_rejects_overlapping_run_loops_and_cycles() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        in_flight = 0
        maximum_in_flight = 0

        async def cycle() -> None:
            nonlocal in_flight, maximum_in_flight
            in_flight += 1
            maximum_in_flight = max(maximum_in_flight, in_flight)
            cycle_started.set()
            await release_cycle.wait()
            in_flight -= 1

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        first_run = asyncio.create_task(runner.run())
        await cycle_started.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await runner.run()

        stop_event.set()
        release_cycle.set()
        await asyncio.wait_for(first_run, timeout=1)

        assert maximum_in_flight == 1

    asyncio.run(scenario())


def test_transient_failure_is_observable_without_logging_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class TemporaryFailure(Exception):
        pass

    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1
            raise TemporaryFailure("sensitive connection details")

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda error: isinstance(error, TemporaryFailure),
        )
        with pytest.raises(TemporaryFailure):
            await runner.run()

        assert calls == 1
        assert runner.last_completed_monotonic is None

    asyncio.run(scenario())

    assert "manager_scheduler_cycle_transient_failure" in caplog.text
    assert "sensitive connection details" not in caplog.text


def test_fatal_cycle_failure_propagates() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()

        async def cycle() -> None:
            raise RuntimeError("invariant failure")

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        with pytest.raises(RuntimeError, match="invariant failure"):
            await runner.run()
        assert runner.last_completed_monotonic is None

    asyncio.run(scenario())


def test_missing_business_cycle_port_fails_closed() -> None:
    with pytest.raises(ValueError, match="cycle port is required"):
        SchedulerOrchestrator(
            cycle=None,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )


def test_backpressure_does_not_create_immediate_unbounded_cycles() -> None:
    class Backpressure(Exception):
        pass

    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls = 0
        in_flight = 0
        maximum_in_flight = 0

        async def cycle() -> None:
            nonlocal calls, in_flight, maximum_in_flight
            calls += 1
            in_flight += 1
            maximum_in_flight = max(maximum_in_flight, in_flight)
            in_flight -= 1
            raise Backpressure("queue is full")

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda error: isinstance(error, Backpressure),
        )
        with pytest.raises(Backpressure):
            await runner.run()

        assert calls == 1
        assert maximum_in_flight == 1
        assert runner.last_completed_monotonic is None

    asyncio.run(scenario())


def test_scan_interval_is_configurable_and_defaults_to_two_seconds() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        observed_intervals: list[float] = []

        async def cycle() -> None:
            return None

        async def stop_on_next_interval(event: asyncio.Event, interval: float) -> bool:
            observed_intervals.append(interval)
            event.set()
            return True

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            scan_interval_seconds=0.25,
            is_transient_failure=lambda _: False,
            wait_for_interval=stop_on_next_interval,
        )
        await runner.run()

        assert observed_intervals == [0.25]

    assert DEFAULT_SCAN_INTERVAL_SECONDS == 2.0
    asyncio.run(scenario())


def test_slow_async_scan_does_not_block_the_event_loop() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        scan_started = asyncio.Event()
        finish_scan = asyncio.Event()

        async def slow_scan() -> None:
            scan_started.set()
            await finish_scan.wait()

        runner = SchedulerOrchestrator(
            cycle=slow_scan,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        task = asyncio.create_task(runner.run())
        await scan_started.wait()
        probe = asyncio.create_task(asyncio.sleep(0, result="responsive"))
        assert await probe == "responsive"

        stop_event.set()
        finish_scan.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())


def test_shutdown_waits_for_in_flight_cycle_to_preserve_ownership() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        scan_started = asyncio.Event()
        finish_scan = asyncio.Event()
        completed: list[bool] = []

        async def cycle() -> None:
            scan_started.set()
            await finish_scan.wait()
            completed.append(True)

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        task = asyncio.create_task(runner.run())
        await scan_started.wait()
        stop_event.set()
        await asyncio.sleep(0)

        assert not task.done()
        assert completed == []

        finish_scan.set()
        await asyncio.wait_for(task, timeout=1)
        assert completed == [True]
        assert runner.last_completed_monotonic is not None

    asyncio.run(scenario())


def test_claim_permission_gate_prevents_cycles_until_allowed() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        permission = False
        calls = 0
        waits = 0

        async def cycle() -> None:
            nonlocal calls
            calls += 1
            stop_event.set()

        async def change_gate_after_one_interval(event: asyncio.Event, _: float) -> bool:
            nonlocal permission, waits
            waits += 1
            permission = True
            return event.is_set()

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: permission,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            wait_for_interval=change_gate_after_one_interval,
        )
        await runner.run()

        assert waits == 1
        assert calls == 1

    asyncio.run(scenario())


def test_hb01_notifies_once_after_successful_scan() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        callbacks: list[str] = []

        async def cycle() -> None:
            stop_event.set()

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append("completed"),
        )
        await runner.run()
        assert callbacks == ["completed"]

    asyncio.run(scenario())


def test_hb02_notifies_after_empty_scan() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        callbacks: list[None] = []

        async def empty_cycle() -> None:
            stop_event.set()

        runner = SchedulerOrchestrator(
            cycle=empty_cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append(None),
        )
        await runner.run()
        assert callbacks == [None]

    asyncio.run(scenario())


def test_hb03_failed_cycle_does_not_notify_or_record_progress() -> None:
    async def scenario() -> None:
        callbacks: list[None] = []

        async def failed_cycle() -> None:
            raise RuntimeError("cycle failed")

        runner = SchedulerOrchestrator(
            cycle=failed_cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append(None),
        )
        with pytest.raises(RuntimeError, match="cycle failed"):
            await runner.run()
        assert callbacks == []
        assert runner.last_completed_monotonic is None

    asyncio.run(scenario())


def test_hb04_cancelled_cycle_does_not_notify_or_record_progress() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        callbacks: list[None] = []

        async def cycle() -> None:
            started.set()
            await asyncio.Event().wait()

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append(None),
        )
        task = asyncio.create_task(runner.run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert callbacks == []
        assert runner.last_completed_monotonic is None

    asyncio.run(scenario())


def test_hb05_stop_before_first_cycle_does_not_notify() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        callbacks: list[None] = []

        async def cycle() -> None:
            pytest.fail("cycle must not start")

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append(None),
        )
        await runner.run()
        assert callbacks == []

    asyncio.run(scenario())


def test_hb06_notifies_once_for_each_completed_scan() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_count = 0
        callbacks: list[int] = []

        async def cycle() -> None:
            nonlocal cycle_count
            cycle_count += 1

        def on_completed() -> None:
            callbacks.append(cycle_count)

        async def stop_after_three(event: asyncio.Event, _: float) -> bool:
            if len(callbacks) == 3:
                event.set()
                return True
            return False

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=on_completed,
            wait_for_interval=stop_after_three,
        )
        await runner.run()
        assert cycle_count == 3
        assert callbacks == [1, 2, 3]

    asyncio.run(scenario())


def test_hb07_callback_failure_propagates_without_retrying_cycle() -> None:
    async def scenario() -> None:
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        def fail_callback() -> None:
            raise RuntimeError("heartbeat failed")

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            monotonic_clock=lambda: 44.0,
            on_cycle_completed=fail_callback,
        )
        with pytest.raises(RuntimeError, match="heartbeat failed"):
            await runner.run()
        assert cycle_calls == 1
        assert runner.last_completed_monotonic == 44.0

    asyncio.run(scenario())


def test_hb08_callback_is_optional_and_existing_runner_still_completes() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            stop_event.set()

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
        )
        await runner.run()
        assert cycle_calls == 1

    asyncio.run(scenario())


def test_hb09_progress_timestamp_is_recorded_before_callback() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        finish_cycle = asyncio.Event()
        observed_progress: list[float | None] = []

        async def cycle() -> None:
            cycle_started.set()
            await finish_cycle.wait()
            stop_event.set()

        runner: SchedulerOrchestrator

        def on_completed() -> None:
            observed_progress.append(runner.last_completed_monotonic)

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            monotonic_clock=lambda: 91.25,
            on_cycle_completed=on_completed,
        )
        assert runner.last_completed_monotonic is None
        task = asyncio.create_task(runner.run())
        await cycle_started.wait()
        assert runner.last_completed_monotonic is None
        assert observed_progress == []
        finish_cycle.set()
        await asyncio.wait_for(task, timeout=1)
        assert runner.last_completed_monotonic == 91.25
        assert observed_progress == [91.25]

    asyncio.run(scenario())


def test_hb10_closed_claim_gate_does_not_notify() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        gate_open = False
        callbacks: list[None] = []
        wait_count = 0

        async def cycle() -> None:
            stop_event.set()

        async def open_gate(event: asyncio.Event, _: float) -> bool:
            nonlocal gate_open, wait_count
            wait_count += 1
            if wait_count == 1:
                assert callbacks == []
                gate_open = True
                return False
            event.set()
            return True

        runner = SchedulerOrchestrator(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: gate_open,
            initial_scan_immediately=True,
            is_transient_failure=lambda _: False,
            on_cycle_completed=lambda: callbacks.append(None),
            wait_for_interval=open_gate,
        )
        await runner.run()
        assert wait_count == 1
        assert callbacks == [None]

    asyncio.run(scenario())
