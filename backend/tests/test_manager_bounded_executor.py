"""Contract tests for TV1-P2A-11's isolated blocking-I/O executor core."""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest

from gpu_marketplace.manager.bounded_executor import (
    BoundedExecutor,
    ExecutorCapacityError,
    ExecutorClosedError,
    ExecutorLifecycle,
)


@asynccontextmanager
async def managed_executor(
    *, max_workers: int = 2, max_pending: int = 2
) -> AsyncIterator[BoundedExecutor]:
    executor = BoundedExecutor(max_workers=max_workers, max_pending=max_pending)
    try:
        yield executor
    finally:
        await executor.shutdown()


async def wait_for_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 3), "worker synchronization event timed out"


def test_ex01_operation_returns_result_within_capacity() -> None:
    async def scenario() -> None:
        async with managed_executor(max_workers=1, max_pending=0) as executor:
            handle = executor.submit(lambda: "complete-uow-result")
            assert await handle == "complete-uow-result"

    asyncio.run(scenario())


def test_ex02_capacity_exhaustion_is_immediate_and_typed() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking() -> str:
            started.set()
            assert release.wait(3)
            return "first"

        async with managed_executor(max_workers=1, max_pending=1) as executor:
            try:
                first = executor.submit(blocking)
                await wait_for_thread_event(started)
                second = executor.submit(lambda: "second")
                with pytest.raises(ExecutorCapacityError):
                    executor.submit(lambda: "must-not-be-accepted")
                snapshot = executor.snapshot()
                assert snapshot.accepted == 2
                assert snapshot.in_flight == 2
                assert snapshot.pending == 1
                release.set()
                assert await first == "first"
                assert await second == "second"
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex03_active_concurrency_never_exceeds_worker_bound() -> None:
    async def scenario() -> None:
        release = threading.Event()
        two_started = threading.Event()
        counter_lock = threading.Lock()
        active = 0
        peak = 0

        def blocking(index: int) -> int:
            nonlocal active, peak
            with counter_lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_started.set()
            assert release.wait(3)
            with counter_lock:
                active -= 1
            return index

        async with managed_executor(max_workers=2, max_pending=4) as executor:
            try:
                handles = [executor.submit(blocking, i) for i in range(6)]
                await wait_for_thread_event(two_started)
                snapshot = executor.snapshot()
                assert snapshot.active <= 2
                assert snapshot.pending <= 4
                assert snapshot.in_flight == 6
                release.set()
                assert await asyncio.gather(*handles) == list(range(6))
                assert peak == 2
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex04_event_loop_can_run_while_sync_operation_is_blocked() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        heartbeat = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocking() -> str:
            started.set()
            assert release.wait(3)
            return "done"

        async with managed_executor(max_workers=1, max_pending=0) as executor:
            try:
                handle = executor.submit(blocking)
                await wait_for_thread_event(started)
                loop.call_soon(heartbeat.set)
                await asyncio.wait_for(heartbeat.wait(), timeout=2)
                assert not release.is_set()
                release.set()
                assert await handle == "done"
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex05_cancelling_waiter_does_not_stop_or_duplicate_worker() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = 0

        def blocking() -> int:
            nonlocal calls
            calls += 1
            started.set()
            assert release.wait(3)
            finished.set()
            return calls

        async with managed_executor(max_workers=1, max_pending=0) as executor:
            try:
                handle = executor.submit(blocking)
                waiter = asyncio.create_task(handle.wait())
                await wait_for_thread_event(started)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert not finished.is_set()
                assert executor.snapshot().in_flight == 1
                release.set()
                assert await handle == 1
                await wait_for_thread_event(finished)
                assert calls == 1
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex06_capacity_is_held_until_actual_worker_completion() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking() -> str:
            started.set()
            assert release.wait(3)
            finished.set()
            return "finished"

        async with managed_executor(max_workers=1, max_pending=0) as executor:
            try:
                handle = executor.submit(blocking)
                waiter = asyncio.create_task(handle.wait())
                await wait_for_thread_event(started)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                with pytest.raises(ExecutorCapacityError):
                    executor.submit(lambda: "over-capacity")
                assert executor.snapshot().in_flight == 1
                release.set()
                assert await handle == "finished"
                await wait_for_thread_event(finished)
                next_handle = executor.submit(lambda: "slot-released")
                assert await next_handle == "slot-released"
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex07_worker_exception_reaches_caller_and_releases_capacity() -> None:
    async def scenario() -> None:
        async with managed_executor(max_workers=1, max_pending=0) as executor:
            def fail() -> None:
                raise ValueError("controlled worker failure")

            handle = executor.submit(fail)
            with pytest.raises(ValueError, match="controlled worker failure"):
                await handle
            assert await executor.submit(lambda: "capacity-reused") == "capacity-reused"

    asyncio.run(scenario())


def test_ex08_session_factory_and_complete_uow_stay_in_one_worker_context() -> None:
    async def scenario() -> None:
        main_thread = threading.get_ident()
        calls: list[tuple[str, int]] = []

        class FakeSession:
            def __enter__(self) -> "FakeSession":
                calls.append(("enter", threading.get_ident()))
                return self

            def commit(self) -> None:
                calls.append(("commit", threading.get_ident()))

            def rollback(self) -> None:
                calls.append(("rollback", threading.get_ident()))

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                calls.append(("close", threading.get_ident()))
                return False

        def session_factory() -> FakeSession:
            calls.append(("create", threading.get_ident()))
            return FakeSession()

        def complete_uow() -> dict[str, str]:
            with session_factory() as session:
                session.commit()
                calls.append(("write", threading.get_ident()))
                return {"result": "detached-value"}

        async with managed_executor(max_workers=1, max_pending=0) as executor:
            result = await executor.submit(complete_uow)

        assert result == {"result": "detached-value"}
        assert [event for event, _ in calls] == ["create", "enter", "commit", "write", "close"]
        worker_threads = {thread_id for _, thread_id in calls}
        assert len(worker_threads) == 1
        assert main_thread not in worker_threads

    asyncio.run(scenario())


def test_ex09_closing_admission_rejects_new_work() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=1, max_pending=0)
        executor.close_admission()
        assert executor.snapshot().lifecycle is ExecutorLifecycle.CLOSING
        with pytest.raises(ExecutorClosedError):
            executor.submit(lambda: None)
        await executor.shutdown()
        assert executor.snapshot().lifecycle is ExecutorLifecycle.CLOSED

    asyncio.run(scenario())


def test_ex10_shutdown_waits_for_actual_worker_completion() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking() -> None:
            started.set()
            assert release.wait(3)
            finished.set()

        executor = BoundedExecutor(max_workers=1, max_pending=0)
        try:
            handle = executor.submit(blocking)
            await wait_for_thread_event(started)
            shutdown = asyncio.create_task(executor.shutdown())
            marker = asyncio.Event()
            asyncio.get_running_loop().call_soon(marker.set)
            await marker.wait()
            assert not shutdown.done()
            assert executor.snapshot().lifecycle is ExecutorLifecycle.DRAINING
            release.set()
            await handle
            await shutdown
            await wait_for_thread_event(finished)
            assert executor.snapshot().lifecycle is ExecutorLifecycle.CLOSED
        finally:
            release.set()
            await executor.shutdown()

    asyncio.run(scenario())


def test_ex11_repeated_shutdown_is_idempotent() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=1, max_pending=0)
        await asyncio.gather(executor.shutdown(), executor.shutdown(), executor.shutdown())
        await executor.shutdown()
        assert executor.snapshot().lifecycle is ExecutorLifecycle.CLOSED

    asyncio.run(scenario())


def test_ex12_concurrent_caller_cancellation_preserves_all_accounting() -> None:
    async def scenario() -> None:
        release = threading.Event()
        two_started = threading.Event()
        lock = threading.Lock()
        active = 0
        calls = 0

        def blocking(index: int) -> int:
            nonlocal active, calls
            with lock:
                calls += 1
                active += 1
                if active == 2:
                    two_started.set()
            assert release.wait(3)
            with lock:
                active -= 1
            return index

        async with managed_executor(max_workers=2, max_pending=2) as executor:
            try:
                handles = [executor.submit(blocking, index) for index in range(4)]
                waiters = [asyncio.create_task(handle.wait()) for handle in handles]
                await wait_for_thread_event(two_started)
                waiters[0].cancel()
                waiters[2].cancel()
                results = await asyncio.gather(waiters[0], waiters[2], return_exceptions=True)
                assert all(isinstance(value, asyncio.CancelledError) for value in results)
                release.set()
                assert await asyncio.gather(waiters[1], waiters[3]) == [1, 3]
            finally:
                release.set()
            await executor.shutdown()
            snapshot = executor.snapshot()
            assert calls == 4
            assert snapshot.accepted == 4
            assert snapshot.completed == 4
            assert snapshot.cancelled_callers == 2
            assert snapshot.in_flight == 0

    asyncio.run(scenario())


def test_ex13_saturated_executor_does_not_accept_unbounded_pending_work() -> None:
    async def scenario() -> None:
        release = threading.Event()
        two_started = threading.Event()

        def blocking() -> None:
            with counter_lock:
                nonlocal started_count
                started_count += 1
                if started_count == 2:
                    two_started.set()
            assert release.wait(3)

        counter_lock = threading.Lock()
        started_count = 0
        async with managed_executor(max_workers=2, max_pending=3) as executor:
            try:
                handles = [executor.submit(blocking) for _ in range(5)]
                await wait_for_thread_event(two_started)
                for _ in range(100):
                    with pytest.raises(ExecutorCapacityError):
                        executor.submit(lambda: None)
                snapshot = executor.snapshot()
                assert snapshot.in_flight == 5
                assert snapshot.active <= 2
                assert snapshot.pending <= 3
                assert snapshot.accepted == 5
                release.set()
                await asyncio.gather(*handles)
            finally:
                release.set()

    asyncio.run(scenario())


def test_ex14_shutdown_leaves_no_owned_pending_or_active_work() -> None:
    async def scenario() -> None:
        executor = BoundedExecutor(max_workers=2, max_pending=1)
        handles = [executor.submit(lambda value=value: value) for value in range(3)]
        assert await asyncio.gather(*handles) == [0, 1, 2]
        await executor.shutdown()
        snapshot = executor.snapshot()
        assert snapshot.active == 0
        assert snapshot.pending == 0
        assert snapshot.in_flight == 0
        assert snapshot.lifecycle is ExecutorLifecycle.CLOSED

    asyncio.run(scenario())


def test_ex15_two_independent_call_paths_make_forward_progress() -> None:
    async def scenario() -> None:
        slow_started = threading.Event()
        release_slow = threading.Event()
        slow_finished = threading.Event()
        fast_finished = threading.Event()

        def slow_scheduler_uow() -> str:
            slow_started.set()
            assert release_slow.wait(3)
            slow_finished.set()
            return "scheduler"

        def fast_outbox_uow() -> str:
            fast_finished.set()
            return "outbox"

        async with managed_executor(max_workers=2, max_pending=1) as executor:
            try:
                slow = executor.submit(slow_scheduler_uow)
                await wait_for_thread_event(slow_started)
                fast = executor.submit(fast_outbox_uow)
                assert await fast == "outbox"
                await wait_for_thread_event(fast_finished)
                assert not slow_finished.is_set()
                release_slow.set()
                assert await slow == "scheduler"
            finally:
                release_slow.set()

    asyncio.run(scenario())


def test_ex16_shutdown_waits_for_cleanup_and_accounts_cancelled_worker_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        started = threading.Event()
        allow_failure = threading.Event()
        cleaned = threading.Event()
        calls: list[tuple[str, int]] = []

        class FailingSession:
            def __enter__(self) -> "FailingSession":
                calls.append(("enter", threading.get_ident()))
                return self

            def rollback(self) -> None:
                calls.append(("rollback", threading.get_ident()))

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                calls.append(("close", threading.get_ident()))
                cleaned.set()
                return False

        def failed_uow() -> None:
            with FailingSession() as session:
                try:
                    started.set()
                    assert allow_failure.wait(3)
                    raise RuntimeError("controlled UoW error")
                except RuntimeError:
                    # Models the UoW owner rolling back before its context closes.
                    session.rollback()
                    raise

        executor = BoundedExecutor(max_workers=1, max_pending=0)
        try:
            handle = executor.submit(failed_uow)
            waiter = asyncio.create_task(handle.wait())
            await wait_for_thread_event(started)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            shutdown = asyncio.create_task(executor.shutdown())
            marker = asyncio.Event()
            asyncio.get_running_loop().call_soon(marker.set)
            await marker.wait()
            assert not shutdown.done()
            assert not cleaned.is_set()
            allow_failure.set()
            await shutdown
            await wait_for_thread_event(cleaned)
            snapshot = executor.snapshot()
            assert snapshot.lifecycle is ExecutorLifecycle.CLOSED
            assert snapshot.in_flight == 0
            assert snapshot.completed == 1
            assert snapshot.failed == 1
            assert [name for name, _ in calls] == ["enter", "rollback", "close"]
            assert len({thread_id for _, thread_id in calls}) == 1
            assert "worker failed after caller cancellation" in caplog.text
        finally:
            allow_failure.set()
            await executor.shutdown()

    with caplog.at_level(logging.ERROR, logger="gpu_marketplace.manager.bounded_executor"):
        asyncio.run(scenario())
