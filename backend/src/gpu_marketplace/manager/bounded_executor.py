"""Bounded owner for complete synchronous Manager operations.

This component owns admission and thread lifetime only. Callers submit one
complete synchronous unit (for example, a complete transaction-scoped UoW),
which must create, use, commit-or-rollback, and close its own Session inside
the callable. Return detached/scalar data only; never return a live Session or
an attached ORM object. The component does not define database or business
policy and is not wired into the Manager runtime here.

``ThreadPoolExecutor`` has an internal queue without a size limit. Admission
therefore caps all submitted-but-not-accounted work at ``max_workers +
max_pending``; its internal queue is consequently finite and can never grow
beyond that same total bound. Once worker slots are occupied, ``max_pending``
limits additional admitted work. Saturation is immediate and explicit;
callers do not wait in an unbounded admission queue.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BoundedExecutorError(RuntimeError):
    """Base class for controlled executor admission and lifecycle failures."""


class ExecutorCapacityError(BoundedExecutorError):
    """Raised immediately when active plus queued work has reached capacity."""


class ExecutorClosedError(BoundedExecutorError):
    """Raised when submission is attempted after admission has closed."""


class ExecutorLifecycle(str, Enum):
    ACCEPTING = "accepting"
    CLOSING = "closing"
    DRAINING = "draining"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ExecutorSnapshot:
    lifecycle: ExecutorLifecycle
    active: int
    pending: int
    completed: int
    failed: int
    cancelled_callers: int
    accepted: int
    in_flight: int
    capacity: int
    max_workers: int
    max_pending: int


@dataclass(slots=True)
class _OwnedOperation:
    future: concurrent.futures.Future[Any]
    caller_cancelled: threading.Event


class OperationHandle(Generic[T]):
    """Await one accepted operation without transferring worker ownership.

    Cancelling ``wait()`` cancels only that caller's wait. The wrapped worker
    future remains shielded and owned by ``BoundedExecutor`` until completion.
    The same handle may be awaited again to observe its eventual outcome.
    """

    __slots__ = ("_future", "_caller_cancelled", "_on_caller_cancelled")

    def __init__(
        self,
        future: asyncio.Future[T],
        caller_cancelled: threading.Event,
        on_caller_cancelled: Callable[[], None],
    ) -> None:
        self._future = future
        self._caller_cancelled = caller_cancelled
        self._on_caller_cancelled = on_caller_cancelled

    async def wait(self) -> T:
        if asyncio.get_running_loop() is not self._future.get_loop():
            raise RuntimeError("operation handle must be awaited on its owning event loop")
        try:
            return await asyncio.shield(self._future)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                self._caller_cancelled.set()
                self._on_caller_cancelled()
            raise

    def __await__(self):
        return self.wait().__await__()


class BoundedExecutor:
    """Run admitted synchronous callables on a finite, bounded thread pool.

    ``max_workers`` and ``max_pending`` are required because approved
    production sizing remains pending. Values are explicit at construction
    time, including in tests; this class provides no production preset.

    This shared pool does not provide per-group fairness. The eventual
    Scheduling, Outbox, and Inbox/Finalization integration still needs an
    approved allocation/fairness policy and measured worker/pool sizing.

    All public lifecycle and inspection methods are event-loop-affine. A
    component instance belongs to one asyncio event loop. Call ``shutdown``
    before closing that loop so actual worker completion and thread cleanup are
    observable.
    """

    def __init__(
        self,
        *,
        max_workers: int,
        max_pending: int,
        thread_name_prefix: str = "manager-blocking-io",
    ) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 0:
            raise ValueError("max_pending must be a non-negative integer")
        if not thread_name_prefix:
            raise ValueError("thread_name_prefix must not be empty")

        self._max_workers = max_workers
        self._max_pending = max_pending
        self._capacity = max_workers + max_pending
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._lifecycle = ExecutorLifecycle.ACCEPTING
        self._loop: asyncio.AbstractEventLoop | None = None
        self._records: dict[int, _OwnedOperation] = {}
        self._next_operation_id = 0
        self._accepted = 0
        self._completed = 0
        self._failed = 0
        self._cancelled_callers = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._shutdown_task: asyncio.Task[None] | None = None

    def submit(
        self,
        operation: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> OperationHandle[T]:
        """Admit one complete synchronous operation or raise immediately.

        Submission must occur on the executor's owning event loop. Admission
        creates no waiting caller task: a saturated executor raises
        ``ExecutorCapacityError`` before submitting anything to the pool.
        Async functions and callables that return awaitables are rejected.
        """

        loop = self._bind_loop()
        if self._lifecycle is not ExecutorLifecycle.ACCEPTING:
            raise ExecutorClosedError("bounded executor is not accepting work")
        if len(self._records) >= self._capacity:
            raise ExecutorCapacityError("bounded executor capacity is exhausted")
        if not callable(operation):
            raise TypeError("operation must be callable")
        if inspect.iscoroutinefunction(operation):
            raise TypeError("bounded executor accepts synchronous callables only")

        self._next_operation_id += 1
        operation_id = self._next_operation_id
        caller_cancelled = threading.Event()

        def invoke() -> T:
            result = operation(*args, **kwargs)
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                raise TypeError("bounded executor callable returned an awaitable")
            return result

        try:
            worker_future = self._thread_pool.submit(invoke)
        except BaseException:
            if not self._records:
                self._drained.set()
            raise

        self._records[operation_id] = _OwnedOperation(
            future=worker_future,
            caller_cancelled=caller_cancelled,
        )
        self._accepted += 1
        self._drained.clear()
        worker_future.add_done_callback(
            lambda future, current_id=operation_id: self._schedule_completion(
                current_id, future
            )
        )

        wrapped_future: asyncio.Future[T] = asyncio.wrap_future(worker_future, loop=loop)
        wrapped_future.add_done_callback(
            lambda future, cancellation=caller_cancelled: self._observe_wrapped_outcome(
                future, cancellation
            )
        )
        return OperationHandle(
            future=wrapped_future,
            caller_cancelled=caller_cancelled,
            on_caller_cancelled=self._record_caller_cancellation,
        )

    def close_admission(self) -> None:
        """Reject future submissions while leaving accepted work owned."""

        self._bind_loop()
        if self._lifecycle is ExecutorLifecycle.ACCEPTING:
            self._lifecycle = ExecutorLifecycle.CLOSING

    async def shutdown(self) -> None:
        """Close admission, drain actual worker calls, then close the pool.

        There is deliberately no timeout here: no approved numeric shutdown
        budget exists yet. Cancellation of a caller waiting for shutdown is
        shielded; the tracked shutdown task continues and can be awaited again.
        """

        loop = self._bind_loop()
        if self._lifecycle is ExecutorLifecycle.CLOSED:
            return
        if self._shutdown_task is None:
            self.close_admission()
            self._lifecycle = ExecutorLifecycle.DRAINING
            self._shutdown_task = loop.create_task(
                self._finish_shutdown(),
                name="manager:bounded-executor-shutdown",
            )
        await asyncio.shield(self._shutdown_task)

    def snapshot(self) -> ExecutorSnapshot:
        """Return event-loop-consistent counts without exposing futures."""

        self._bind_loop()
        active = 0
        pending = 0
        completed_owned = 0
        failed_owned = 0
        for record in self._records.values():
            future = record.future
            if future.done():
                completed_owned += 1
                if _future_failed(future):
                    failed_owned += 1
            elif future.running():
                active += 1
            else:
                pending += 1

        return ExecutorSnapshot(
            lifecycle=self._lifecycle,
            active=active,
            pending=pending,
            completed=self._completed + completed_owned,
            failed=self._failed + failed_owned,
            cancelled_callers=self._cancelled_callers,
            accepted=self._accepted,
            in_flight=len(self._records),
            capacity=self._capacity,
            max_workers=self._max_workers,
            max_pending=self._max_pending,
        )

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError("bounded executor operation requires a running event loop") from None
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("bounded executor is bound to a different event loop")
        return loop

    def _schedule_completion(
        self,
        operation_id: int,
        future: concurrent.futures.Future[Any],
    ) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._complete_on_loop, operation_id, future)
        except RuntimeError:
            # A correctly shut down instance waits for this callback before
            # the owning loop closes. Log only a fixed message if misused.
            logger.critical("bounded executor worker completed after its event loop closed")

    def _complete_on_loop(
        self,
        operation_id: int,
        future: concurrent.futures.Future[Any],
    ) -> None:
        if self._records.pop(operation_id, None) is None:
            return
        self._completed += 1
        if _future_failed(future):
            self._failed += 1
        if not self._records:
            self._drained.set()

    def _record_caller_cancellation(self) -> None:
        self._cancelled_callers += 1

    @staticmethod
    def _observe_wrapped_outcome(
        future: asyncio.Future[Any],
        caller_cancelled: threading.Event,
    ) -> None:
        if future.cancelled():
            return
        try:
            error = future.exception()
        except asyncio.CancelledError:
            return
        if error is not None and caller_cancelled.is_set():
            logger.error(
                "bounded executor worker failed after caller cancellation",
                extra={"error_type": type(error).__name__},
            )

    async def _finish_shutdown(self) -> None:
        await self._drained.wait()
        await asyncio.to_thread(
            self._thread_pool.shutdown,
            wait=True,
            cancel_futures=False,
        )
        self._lifecycle = ExecutorLifecycle.CLOSED


def _future_failed(future: concurrent.futures.Future[Any]) -> bool:
    if not future.done():
        return False
    try:
        return future.exception() is not None
    except concurrent.futures.CancelledError:
        return True
