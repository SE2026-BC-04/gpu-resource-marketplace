import asyncio
import logging
import threading
from dataclasses import dataclass

import pytest

from gpu_marketplace.manager.bounded_executor import (
    BoundedExecutor,
    ExecutorCapacityError,
    ExecutorClosedError,
)
from gpu_marketplace.manager.outbox import OutboxDispatchCoordinator
from gpu_marketplace.manager.outbox_executor import OutboxExecutorAdapter


@dataclass(frozen=True)
class _Claim:
    claim_id: str


@dataclass(frozen=True)
class _Outcome:
    accepted: bool


def _executor() -> BoundedExecutor:
    return BoundedExecutor(max_workers=1, max_pending=0)


def _assert_no_pending_executor_tasks() -> None:
    current = asyncio.current_task()
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not current
        and task.get_name().startswith("manager:bounded-executor")
        and not task.done()
    ]
    assert pending == []


def test_sync_claim_and_settlement_preserve_typed_results_and_async_dispatch() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        event_loop_thread = threading.get_ident()
        claim = _Claim("claim-typed")
        outcome = _Outcome(True)
        worker_threads: list[int] = []
        dispatch_threads: list[int] = []
        settled: list[tuple[_Claim, _Outcome]] = []

        def sync_claim() -> _Claim:
            worker_threads.append(threading.get_ident())
            return claim

        async def dispatch(received_claim: _Claim) -> _Outcome:
            dispatch_threads.append(threading.get_ident())
            assert received_claim is claim
            return outcome

        def sync_settle(received_claim: _Claim, received_outcome: _Outcome) -> None:
            worker_threads.append(threading.get_ident())
            settled.append((received_claim, received_outcome))

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=adapter.wrap_claim(sync_claim),
            dispatch=dispatch,
            settle=adapter.wrap_settlement(sync_settle),
        )
        await coordinator.run_once()
        await executor.shutdown()

        assert worker_threads
        assert all(thread_id != event_loop_thread for thread_id in worker_threads)
        assert dispatch_threads == [event_loop_thread]
        assert settled == [(claim, outcome)]
        assert executor.snapshot().accepted == 2
        assert executor.snapshot().completed == 2
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_sync_operation_runs_off_loop_while_event_loop_remains_responsive() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        event_loop_thread = threading.get_ident()
        worker_started = asyncio.Event()
        loop_progress = asyncio.Event()
        release_worker = threading.Event()
        worker_finished = threading.Event()

        def blocked_sync_claim() -> int:
            thread_id = threading.get_ident()
            loop.call_soon_threadsafe(worker_started.set)
            assert release_worker.wait(timeout=5)
            worker_finished.set()
            return thread_id

        claim_port = adapter.wrap_claim(blocked_sync_claim)
        watchdog = threading.Timer(2.0, release_worker.set)
        watchdog.daemon = True
        watchdog.start()
        try:
            task = asyncio.create_task(claim_port())
            await asyncio.wait_for(worker_started.wait(), timeout=1)
            loop.call_soon(loop_progress.set)
            await asyncio.wait_for(loop_progress.wait(), timeout=1)
            assert not worker_finished.is_set()
            release_worker.set()
            worker_thread = await task
        finally:
            release_worker.set()
            watchdog.cancel()
            await executor.shutdown()

        assert worker_thread != event_loop_thread
        assert worker_finished.is_set()
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_worker_exception_propagates_original_and_diagnostic_is_redacted(caplog) -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        sentinel = "OUTBOX-SYNC-PRIVATE-DETAIL"
        error = RuntimeError(sentinel)

        def broken_claim() -> _Claim:
            raise error

        claim_port = adapter.wrap_claim(broken_claim)
        with caplog.at_level(logging.ERROR, logger="gpu_marketplace.manager.bounded_executor"):
            with pytest.raises(RuntimeError) as caught:
                await claim_port()
        await executor.shutdown()

        assert caught.value is error
        assert "bounded_executor_operation_failed" in caplog.text
        assert sentinel not in caplog.text
        assert executor.snapshot().failed == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_capacity_exhaustion_does_not_start_claim_dispatch_or_settlement() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        blocker_started = asyncio.Event()
        release_blocker = threading.Event()
        calls: list[str] = []

        def blocker() -> None:
            loop.call_soon_threadsafe(blocker_started.set)
            assert release_blocker.wait(timeout=5)

        blocker_handle = executor.submit(blocker)
        try:
            await asyncio.wait_for(blocker_started.wait(), timeout=2)

            def sync_claim() -> _Claim:
                calls.append("claim")
                return _Claim("unadmitted")

            async def dispatch(_claim: _Claim) -> _Outcome:
                calls.append("dispatch")
                return _Outcome(True)

            def settle(_claim: _Claim, _outcome: _Outcome) -> None:
                calls.append("settle")

            coordinator = OutboxDispatchCoordinator(
                claim_one_committed=adapter.wrap_claim(sync_claim),
                dispatch=dispatch,
                settle=adapter.wrap_settlement(settle),
            )
            with pytest.raises(ExecutorCapacityError):
                await coordinator.run_once()

            assert calls == []
            assert executor.snapshot().accepted == 1
            assert executor.snapshot().in_flight == 1
        finally:
            release_blocker.set()
            await blocker_handle.wait()
            await executor.shutdown()

        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_closed_executor_admission_propagates_without_outbox_side_effects() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        executor.close_admission()
        calls: list[str] = []

        def sync_claim() -> _Claim:
            calls.append("claim")
            return _Claim("closed")

        async def dispatch(_claim: _Claim) -> _Outcome:
            calls.append("dispatch")
            return _Outcome(True)

        async def settle(_claim: _Claim, _outcome: _Outcome) -> None:
            calls.append("settle")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=adapter.wrap_claim(sync_claim),
            dispatch=dispatch,
            settle=settle,
        )
        try:
            with pytest.raises(ExecutorClosedError):
                await coordinator.run_once()
            assert calls == []
            assert executor.snapshot().accepted == 0
        finally:
            await executor.shutdown()

        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_cancellation_before_worker_admission_submits_nothing() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        calls: list[str] = []

        def sync_claim() -> _Claim:
            calls.append("claim")
            return _Claim("not-started")

        claim_port = adapter.wrap_claim(sync_claim)
        task = asyncio.create_task(claim_port())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert calls == []
        assert executor.snapshot().accepted == 0
        await executor.shutdown()
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_cancellation_during_worker_keeps_executor_slot_until_real_completion() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        worker_started = asyncio.Event()
        release_worker = threading.Event()
        calls = 0

        def blocked_claim() -> _Claim:
            nonlocal calls
            calls += 1
            loop.call_soon_threadsafe(worker_started.set)
            assert release_worker.wait(timeout=5)
            return _Claim("late")

        claim_port = adapter.wrap_claim(blocked_claim)
        task = asyncio.create_task(claim_port())
        try:
            await asyncio.wait_for(worker_started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            snapshot = executor.snapshot()
            assert snapshot.in_flight == 1
            assert snapshot.active == 1
            assert snapshot.cancelled_callers == 1
            with pytest.raises(ExecutorCapacityError):
                await claim_port()
            assert calls == 1
        finally:
            release_worker.set()
            await executor.shutdown()

        snapshot = executor.snapshot()
        assert snapshot.in_flight == 0
        assert snapshot.completed == 1
        assert calls == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_late_success_after_cancellation_is_accounted_without_resubmission() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        worker_started = asyncio.Event()
        release_worker = threading.Event()
        completed: list[_Claim] = []
        submitted_calls = 0
        result = _Claim("late-success")

        def slow_claim() -> _Claim:
            nonlocal submitted_calls
            submitted_calls += 1
            loop.call_soon_threadsafe(worker_started.set)
            assert release_worker.wait(timeout=5)
            completed.append(result)
            return result

        claim_port = adapter.wrap_claim(slow_claim)
        task = asyncio.create_task(claim_port())
        try:
            await asyncio.wait_for(worker_started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert executor.snapshot().in_flight == 1
        finally:
            release_worker.set()
            await executor.shutdown()

        assert completed == [result]
        assert submitted_calls == 1
        assert executor.snapshot().accepted == 1
        assert executor.snapshot().completed == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_late_worker_failure_after_cancellation_is_redacted_and_accounted(caplog) -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        worker_started = asyncio.Event()
        release_worker = threading.Event()
        sentinel = "LATE-OUTBOX-WORKER-SECRET"

        def failing_claim() -> _Claim:
            loop.call_soon_threadsafe(worker_started.set)
            assert release_worker.wait(timeout=5)
            raise RuntimeError(sentinel)

        claim_port = adapter.wrap_claim(failing_claim)
        task = asyncio.create_task(claim_port())
        try:
            await asyncio.wait_for(worker_started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert executor.snapshot().in_flight == 1
        finally:
            release_worker.set()
            with caplog.at_level(
                logging.ERROR, logger="gpu_marketplace.manager.bounded_executor"
            ):
                await executor.shutdown()

        assert executor.snapshot().failed == 1
        assert "bounded_executor_operation_failed" in caplog.text
        assert sentinel not in caplog.text
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_capacity_rejection_during_settlement_is_not_reported_as_success() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        blocker_started = asyncio.Event()
        release_blocker = threading.Event()
        calls: list[str] = []
        claim = _Claim("committed-claim")
        outcome = _Outcome(True)

        def blocker() -> None:
            loop.call_soon_threadsafe(blocker_started.set)
            assert release_blocker.wait(timeout=5)

        blocker_handle = executor.submit(blocker)
        try:
            await asyncio.wait_for(blocker_started.wait(), timeout=2)

            async def claim_one_committed() -> _Claim:
                calls.append("claim")
                return claim

            async def dispatch(received_claim: _Claim) -> _Outcome:
                assert received_claim is claim
                calls.append("dispatch")
                return outcome

            def sync_settle(_claim: _Claim, _outcome: _Outcome) -> None:
                calls.append("settle")

            coordinator = OutboxDispatchCoordinator(
                claim_one_committed=claim_one_committed,
                dispatch=dispatch,
                settle=adapter.wrap_settlement(sync_settle),
            )
            with pytest.raises(ExecutorCapacityError):
                await coordinator.run_once()

            assert calls == ["claim", "dispatch"]
            assert coordinator._running is False
        finally:
            release_blocker.set()
            await blocker_handle.wait()
            await executor.shutdown()

        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_cancellation_during_settlement_is_not_reported_as_success_or_retried() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        loop = asyncio.get_running_loop()
        settle_started = asyncio.Event()
        release_settlement = threading.Event()
        settlement_done = threading.Event()
        calls: list[str] = []
        claim = _Claim("claim-1")
        outcome = _Outcome(True)

        async def claim_one_committed() -> _Claim:
            calls.append("claim")
            return claim

        async def dispatch(_claim: _Claim) -> _Outcome:
            calls.append("dispatch")
            return outcome

        def sync_settle(_claim: _Claim, _outcome: _Outcome) -> None:
            calls.append("settle")
            loop.call_soon_threadsafe(settle_started.set)
            assert release_settlement.wait(timeout=5)
            settlement_done.set()

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=adapter.wrap_settlement(sync_settle),
        )
        task = asyncio.create_task(coordinator.run_once())
        try:
            await asyncio.wait_for(settle_started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not settlement_done.is_set()
            assert executor.snapshot().in_flight == 1
            assert calls == ["claim", "dispatch", "settle"]
            assert coordinator._running is False
        finally:
            release_settlement.set()
            await executor.shutdown()

        assert settlement_done.is_set()
        assert calls.count("settle") == 1
        assert executor.snapshot().completed == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_complete_synchronous_uow_stays_in_one_worker_context() -> None:
    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        event_loop_thread = threading.get_ident()
        phases: list[tuple[str, int]] = []

        def complete_uow() -> _Claim:
            phases.append(("begin", threading.get_ident()))
            phases.append(("read", threading.get_ident()))
            phases.append(("commit_and_close", threading.get_ident()))
            return _Claim("one-worker-uow")

        try:
            returned_claim = await adapter.wrap_claim(complete_uow)()
        finally:
            await executor.shutdown()

        worker_threads = {thread_id for _, thread_id in phases}
        assert [phase for phase, _ in phases] == ["begin", "read", "commit_and_close"]
        assert len(worker_threads) == 1
        assert event_loop_thread not in worker_threads
        assert returned_claim == _Claim("one-worker-uow")
        assert executor.snapshot().accepted == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())


def test_unknown_claim_commit_propagates_without_dispatch_or_resubmission() -> None:
    class CommitOutcomeUnknown(RuntimeError):
        pass

    async def scenario() -> None:
        executor = _executor()
        adapter = OutboxExecutorAdapter(executor)
        calls: list[str] = []
        unknown = CommitOutcomeUnknown("commit result is unknown")

        def uncertain_claim() -> _Claim:
            calls.append("claim")
            raise unknown

        async def dispatch(_claim: _Claim) -> _Outcome:
            calls.append("dispatch")
            return _Outcome(True)

        async def settle(_claim: _Claim, _outcome: _Outcome) -> None:
            calls.append("settle")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=adapter.wrap_claim(uncertain_claim),
            dispatch=dispatch,
            settle=settle,
        )
        try:
            with pytest.raises(CommitOutcomeUnknown) as caught:
                await coordinator.run_once()
        finally:
            await executor.shutdown()

        assert caught.value is unknown
        assert calls == ["claim"]
        assert executor.snapshot().accepted == 1
        assert executor.snapshot().failed == 1
        _assert_no_pending_executor_tasks()

    asyncio.run(scenario())
