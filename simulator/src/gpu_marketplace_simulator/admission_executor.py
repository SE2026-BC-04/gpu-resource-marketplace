"""Bounded offload for synchronous dispatch-admission ports."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, RLock
from typing import Callable, TypeVar

from gpu_marketplace_simulator.dispatch import AttemptAdmissionUnavailable


T = TypeVar("T")


class BoundedAdmissionExecutor:
    """Run blocking admission off-loop with bounded threads and queue size."""

    def __init__(self, *, workers: int, max_outstanding: int) -> None:
        if type(workers) is not int or workers < 1:
            raise ValueError("admission workers must be a positive integer")
        if type(max_outstanding) is not int or max_outstanding < workers:
            raise ValueError("admission max_outstanding must be >= workers")
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="dispatch-admission"
        )
        self._capacity = BoundedSemaphore(max_outstanding)
        self._lock = RLock()
        self._closed = False
        self._futures: set[Future[object]] = set()

    async def run(self, operation: Callable[..., T], *args: object) -> T:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._closed:
                raise AttemptAdmissionUnavailable("admission executor is closing")
            if not self._capacity.acquire(blocking=False):
                raise AttemptAdmissionUnavailable("admission executor is saturated")
            try:
                concurrent_future = self._executor.submit(operation, *args)
            except RuntimeError as error:
                self._capacity.release()
                raise AttemptAdmissionUnavailable("admission executor is closed") from error

            self._futures.add(concurrent_future)  # type: ignore[arg-type]

        # Releasing from the concurrent Future (not the HTTP task) keeps a
        # cancelled request's slot occupied until synchronous work really ends.
        def completed(done: Future[T]) -> None:
            with self._lock:
                self._futures.discard(done)  # type: ignore[arg-type]
            self._capacity.release()

        concurrent_future.add_done_callback(completed)
        wrapped = asyncio.wrap_future(concurrent_future, loop=loop)

        def consume_unobserved_failure(done: asyncio.Future[T]) -> None:
            if not done.cancelled():
                done.exception()

        wrapped.add_done_callback(consume_unobserved_failure)
        # Shield prevents HTTP cancellation from cancelling a queued future or
        # severing ownership while producer registration may still be running.
        return await asyncio.shield(wrapped)

    async def shutdown(
        self, cleanup: Callable[[], T] | None, *, timeout_seconds: float
    ) -> T | None:
        """Stop intake and bound cleanup waiting without blocking the ASGI loop."""
        with self._lock:
            self._closed = True
            future: Future[T] | None = None
            if cleanup is not None:
                pending = tuple(self._futures)

                def cleanup_after_admissions() -> T:
                    for admission_future in pending:
                        try:
                            admission_future.result()
                        except Exception:
                            # Cleanup still runs after a failed admission.
                            pass
                    return cleanup()

                try:
                    # At most one reserved cleanup submission beyond the
                    # semaphore-bounded request queue.
                    future = self._executor.submit(cleanup_after_admissions)
                except RuntimeError:
                    future = None

        if future is None:
            self._executor.shutdown(wait=False, cancel_futures=False)
            return None

        wrapped = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped), timeout=max(0.0, timeout_seconds)
            )
        except asyncio.TimeoutError:
            return None
        finally:
            # Running synchronous work is deliberately not cancelled. Python's
            # thread pool is nonblocking here; process-level hard stop remains
            # the only way to terminate a permanently hung worker.
            self._executor.shutdown(wait=False, cancel_futures=False)
