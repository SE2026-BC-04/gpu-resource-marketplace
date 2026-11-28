"""Test-injected Simulator-local composition for the Phase 2E Stage A gate.

This module deliberately requires an injected signer and HTTPX MockTransport.
It is not used by the normal application entry point and is not a production
activation mechanism.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from threading import BoundedSemaphore, Event, RLock, current_thread
import time
from typing import Callable, Protocol
from uuid import UUID, uuid4

import httpx
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from pydantic import SecretStr

from gpu_marketplace_simulator.app import create_app
from gpu_marketplace_simulator.attempt_cache import Admission, Receipt
from gpu_marketplace_simulator.attempt_cache_adapter import (
    ProducerLifecycle,
    ProducerRegistrationPort,
)
from gpu_marketplace_simulator.callback_client import (
    CallbackAccepted,
    CallbackRetryPolicy,
    FrozenCallbackReceipt,
    SimulatorCallbackClient,
)
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.deterministic import SimulationInput, simulate
from gpu_marketplace_simulator.dispatch import DispatchRequest
from gpu_marketplace_simulator.signed_v1 import (
    SignedResultV1Payload,
    SignerProvider,
    envelope_from_json,
    sign_payload,
)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ExecutionRegistration:
    attempt_id: str
    future: Future[object]
    lifecycle: ProducerLifecycle
    done: Event = field(default_factory=Event)
    wake_worker: Event = field(default_factory=Event)
    execution_allowed: Event = field(default_factory=Event)
    callback_wait_wake: Event = field(default_factory=Event)
    accepted: bool = False
    capacity_released: bool = False


def _canonical_service_token(value: str) -> bool:
    import base64
    import binascii
    import re

    if re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is None:
        return False
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return False
    return len(decoded) == 32 and base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() == value


class TestOnlyRuntimeComposition(ProducerRegistrationPort):
    """Compose real local components behind synthetic credentials and fakes."""

    __test__ = False

    def __init__(
        self,
        *,
        dispatch_token: str,
        callback_token: str,
        signer: SignerProvider,
        test_public_key: bytes,
        key_id: UUID,
        callback_transport: httpx.MockTransport,
        callback_policy: CallbackRetryPolicy,
        clock: Callable[[], datetime] | None = None,
        result_id_factory: Callable[[], UUID] = uuid4,
        before_produce: Callable[[DispatchRequest], None] | None = None,
        before_callback_schedule: Callable[[DispatchRequest], None] | None = None,
        bind_execution_future: Callable[[ProducerLifecycle, Future[object]], None] | None = None,
        on_worker_waiting_gate: Callable[[DispatchRequest], None] | None = None,
        on_bind_failure: Callable[[Future[object], bool], None] | None = None,
        cache_clock: Callable[[], float] | None = None,
        cache_max_entries: int = 64,
        cache_ttl_seconds: float = 30.0,
        producer_concurrency_limit: int = 8,
        admission_workers: int = 4,
        admission_max_outstanding: int = 16,
        worker_count: int = 2,
        max_in_flight: int = 8,
        shutdown_timeout_seconds: float = 2.0,
    ) -> None:
        if not _canonical_service_token(dispatch_token):
            raise ValueError("test dispatch token must use canonical 32-byte base64url")
        if not _canonical_service_token(callback_token):
            raise ValueError("test callback token must use canonical 32-byte base64url")
        if dispatch_token == callback_token:
            raise ValueError("dispatch and callback credentials must be distinct")
        if type(callback_transport) is not httpx.MockTransport:
            raise ValueError("Stage A callback transport must be an injected HTTPX MockTransport")
        if type(test_public_key) is not bytes or len(test_public_key) != 32:
            raise ValueError("an injected 32-byte test Ed25519 public key is required")
        if type(key_id) is not UUID or key_id.version != 4:
            raise ValueError("injected test key_id must be UUIDv4")
        if type(worker_count) is not int or worker_count < 1:
            raise ValueError("worker_count must be a positive integer")
        if type(max_in_flight) is not int or max_in_flight < worker_count:
            raise ValueError("max_in_flight must be at least worker_count")
        if type(shutdown_timeout_seconds) not in (int, float) or shutdown_timeout_seconds <= 0:
            raise ValueError("shutdown_timeout_seconds must be positive")

        self._dispatch_token = dispatch_token
        self._callback_token = callback_token
        self._signer = signer
        self._public_key = Ed25519PublicKey.from_public_bytes(test_public_key)
        self._key_id = key_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._new_result_id = result_id_factory
        self._before_produce = before_produce
        self._before_callback_schedule = before_callback_schedule
        self._bind_execution_future = bind_execution_future or (
            lambda lifecycle, future: lifecycle.bind_execution_future(future)
        )
        self._on_worker_waiting_gate = on_worker_waiting_gate
        self._on_bind_failure = on_bind_failure
        self._cache_clock = cache_clock
        self._cache_max_entries = cache_max_entries
        self._cache_ttl_seconds = cache_ttl_seconds
        self._producer_concurrency_limit = producer_concurrency_limit
        self._admission_workers = admission_workers
        self._admission_max_outstanding = admission_max_outstanding
        self._worker_count = worker_count
        self._max_in_flight = max_in_flight
        self._shutdown_timeout = float(shutdown_timeout_seconds)
        self._callback_policy = callback_policy
        self._callback_client = SimulatorCallbackClient(
            callback_url="http://backend.test/internal/v1/results/callback",
            callback_token=SecretStr(callback_token),
            policy=callback_policy,
            transport=callback_transport,
            clock=self._clock,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_started = asyncio.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="stage-a-producer"
        )
        self._capacity = BoundedSemaphore(max_in_flight)
        self._guard = RLock()
        # Every submitted Future owns one capacity permit until its done
        # callback observes actual termination. This set is bounded by
        # max_in_flight and also covers same-ID registrations overlapping TTL.
        self._active_futures: set[Future[object]] = set()
        self._active_registrations: dict[Future[object], _ExecutionRegistration] = {}
        self._futures: dict[str, Future[object]] = {}
        self._attempt_done: dict[str, Event] = {}
        self._lifecycles: dict[str, ProducerLifecycle] = {}
        self._admissions: dict[str, Admission] = {}
        self._registration_count = 0
        self._callback_results: dict[str, CallbackAccepted | Exception] = {}
        self._callback_waiters: set[Event] = set()
        self._closed = False
        self._shutdown_drained: bool | None = None
        self._shutdown_cleanup_complete: bool | None = None
        self._shutdown_deadline: float | None = None
        self._shutdown_timed_out = False
        self._shutdown_deadline_handle: asyncio.TimerHandle | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._callback_close_task: asyncio.Task[None] | None = None
        self._callback_closing = False
        self._executor_shutdown = False

    async def startup(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def shutdown(self) -> None:
        self._begin_shutdown()
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(
                self._shutdown_once(), name="stage-a-runtime-shutdown"
            )
        await asyncio.shield(self._shutdown_task)

    async def _shutdown_once(self) -> None:
        self._install_shutdown_deadline()
        with self._guard:
            pending = tuple(self._active_futures)
            deadline = self._shutdown_deadline
        remaining = max(0.0, (deadline or time.monotonic()) - time.monotonic())
        if pending and remaining > 0:
            _, not_done = await asyncio.to_thread(wait, pending, timeout=remaining)
        else:
            not_done = set(pending)

        with self._guard:
            deadline_elapsed = (
                self._shutdown_timed_out
                or deadline is None
                or time.monotonic() >= deadline
            )
        if deadline_elapsed:
            self._shutdown_timed_out = True
            self._wake_callback_waiters()
            self._cancel_queued_producers()
        if self._callback_close_task is None:
            self._start_callback_close()

        if not self._executor_shutdown:
            self._executor_shutdown = True
            self._executor.shutdown(wait=False, cancel_futures=False)

        remaining = max(0.0, (deadline or time.monotonic()) - time.monotonic())
        close_task = self._callback_close_task
        close_finished = False
        if close_task is not None and not close_task.done() and remaining > 0:
            done, _ = await asyncio.wait({close_task}, timeout=remaining)
            close_finished = close_task in done
        elif close_task is not None:
            close_finished = close_task.done()

        cleanup_ok = False
        if close_task is not None and close_finished and not close_task.cancelled():
            try:
                close_task.result()
            except BaseException:
                cleanup_ok = False
            else:
                cleanup_ok = True
        self._shutdown_cleanup_complete = cleanup_ok
        self._shutdown_drained = not not_done and not deadline_elapsed and cleanup_ok
        if not self._shutdown_drained:
            logger.warning(
                "stage_a_shutdown_incomplete",
                extra={
                    "pending_producers": len(not_done),
                    "callback_cleanup_complete": cleanup_ok,
                },
            )

    def _begin_shutdown(self) -> float:
        with self._guard:
            first_request = self._shutdown_deadline is None
            if self._shutdown_deadline is None:
                self._shutdown_deadline = time.monotonic() + self._shutdown_timeout
            deadline = self._shutdown_deadline
            self._closed = True
            waiters = tuple(self._callback_waiters)
        for waiter in waiters:
            waiter.set()
        if first_request:
            logger.info(
                "stage_a_shutdown_started",
                extra={
                    "monotonic_ns": time.monotonic_ns(),
                    "thread_name": current_thread().name,
                    "shutdown_timeout_seconds": self._shutdown_timeout,
                },
            )
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                if asyncio.get_running_loop() is loop:
                    self._install_shutdown_deadline()
                else:
                    loop.call_soon_threadsafe(self._install_shutdown_deadline)
            except RuntimeError:
                loop.call_soon_threadsafe(self._install_shutdown_deadline)
        return deadline

    def _install_shutdown_deadline(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        self._shutdown_started.set()
        if self._shutdown_deadline_handle is not None:
            return
        with self._guard:
            deadline = self._shutdown_deadline
        if deadline is None:
            return
        delay = max(0.0, deadline - time.monotonic())
        self._shutdown_deadline_handle = loop.call_later(delay, self._shutdown_deadline_reached)

    def _shutdown_deadline_reached(self) -> None:
        self._shutdown_timed_out = True
        logger.warning(
            "stage_a_shutdown_deadline_reached",
            extra={
                "monotonic_ns": time.monotonic_ns(),
                "thread_name": current_thread().name,
            },
        )
        self._wake_callback_waiters()
        self._cancel_queued_producers()
        self._start_callback_close()

    def _cancel_queued_producers(self) -> None:
        with self._guard:
            pending = tuple(
                future
                for future, registration in self._active_registrations.items()
                if registration.accepted
            )
        # Future.cancel() succeeds only before worker execution starts. Its
        # done callback remains the sole owner of capacity release and Option A
        # failure evidence; running work stays owned until actual termination.
        for future in pending:
            future.cancel()

    def _wake_callback_waiters(self) -> None:
        with self._guard:
            waiters = tuple(self._callback_waiters)
        for waiter in waiters:
            waiter.set()

    def _start_callback_close(self) -> None:
        if self._callback_close_task is not None:
            return
        self._callback_closing = True
        current = asyncio.current_task()
        logger.info(
            "stage_a_callback_close_started",
            extra={
                "monotonic_ns": time.monotonic_ns(),
                "thread_name": current_thread().name,
                "asyncio_task_name": current.get_name() if current is not None else None,
            },
        )
        if self._shutdown_deadline_handle is not None:
            self._shutdown_deadline_handle.cancel()
            self._shutdown_deadline_handle = None
        loop = self._loop
        if loop is None or loop.is_closed():
            self._shutdown_cleanup_complete = False
            return
        self._callback_close_task = loop.create_task(
            self._callback_client.aclose(), name="stage-a-callback-client-close"
        )

    async def wait_for_shutdown_start(self) -> None:
        await self._shutdown_started.wait()

    def register(
        self,
        dispatch: DispatchRequest,
        _admission: Admission,
        lifecycle: ProducerLifecycle,
    ) -> bool:
        logger.info("stage_a_registration_enter", extra={"thread_name": current_thread().name})
        if self._loop is None or self._loop.is_closed():
            return False

        wake_worker = Event()
        execution_allowed = Event()
        callback_wait_wake = Event()
        with self._guard:
            # Linearize submit-and-track with _begin_shutdown: every accepted
            # producer is either in the shutdown snapshot or is rejected.
            if self._closed or not self._capacity.acquire(blocking=False):
                return False
            try:
                future = self._executor.submit(
                    self._execute, dispatch, _admission, lifecycle,
                    wake_worker, execution_allowed, callback_wait_wake,
                )
            except BaseException as error:
                self._capacity.release()
                if isinstance(error, RuntimeError):
                    return False
                raise
            registration = _ExecutionRegistration(
                attempt_id=dispatch.attempt_id,
                future=future,
                lifecycle=lifecycle,
                wake_worker=wake_worker,
                execution_allowed=execution_allowed,
                callback_wait_wake=callback_wait_wake,
            )
            self._active_futures.add(future)
            self._active_registrations[future] = registration
        future.add_done_callback(
            lambda completed, current=registration: self._producer_done(current, completed)
        )

        try:
            self._bind_execution_future(lifecycle, future)
        except Exception:
            cancelled = future.cancel()
            try:
                if self._on_bind_failure is not None:
                    self._on_bind_failure(future, cancelled)
            finally:
                # Wake a worker that had already transitioned to RUNNING, but
                # keep execution permission closed. A failed cancel is not
                # evidence of termination; the Future callback owns release.
                wake_worker.set()
            raise

        attempt_id = dispatch.attempt_id
        logger.info("stage_a_registration_bound", extra={"thread_name": current_thread().name})
        with self._guard:
            if self._closed:
                accepted = False
            else:
                accepted = True
                registration.accepted = True
                self._futures[attempt_id] = future
                self._attempt_done[attempt_id] = registration.done
                self._lifecycles[attempt_id] = lifecycle
                self._admissions[attempt_id] = _admission
                self._registration_count += 1
                execution_allowed.set()
                wake_worker.set()
        if not accepted:
            # Shutdown won the admission race after submit/bind. Keep execution
            # fenced, then let the real Future callback own any permit release.
            future.cancel()
            wake_worker.set()
            return False
        logger.info("stage_a_registration_return", extra={"thread_name": current_thread().name})
        return True

    def _execute(
        self,
        dispatch: DispatchRequest,
        admission: Admission,
        lifecycle: ProducerLifecycle,
        wake_worker: Event,
        execution_allowed: Event,
        callback_wait_wake: Event,
    ) -> object:
        if self._on_worker_waiting_gate is not None:
            self._on_worker_waiting_gate(dispatch)
        wake_worker.wait()
        if not execution_allowed.is_set():
            return None
        if self._before_produce is not None:
            self._before_produce(dispatch)

        simulation_input = SimulationInput(
            job_id=UUID(dispatch.job_id),
            listing_id=UUID(dispatch.listing_id),
            worker_id=UUID(dispatch.worker_id),
            requested_gpu_count=dispatch.gpu_count,
            duration_seconds=dispatch.duration_seconds,
            workload_profile=dispatch.simulation_input.workload_profile,
        )
        simulated = simulate(simulation_input)
        result_id = self._new_result_id()
        finished_at = self._clock().astimezone(timezone.utc).isoformat(timespec="microseconds")
        finished_at = finished_at.replace("+00:00", "Z")
        output = simulated.output
        payload = SignedResultV1Payload(
            schema_version="1",
            result_id=str(result_id),
            job_id=dispatch.job_id,
            attempt_id=dispatch.attempt_id,
            worker_id=dispatch.worker_id,
            listing_id=dispatch.listing_id,
            outcome=output["outcome"],
            failure_reason=output["failure_reason"],
            result_digest=simulated.result_digest,
            finished_at=finished_at,
            key_id=str(self._key_id),
        )
        signed = sign_payload(payload, self._signer)
        self._public_key.verify(signed.signature_bytes, signed.signing_message)

        # This is the one and only outer-envelope serialization. Validation and
        # every callback retry retain these exact immutable bytes.
        raw_envelope = rfc8785.dumps(signed.envelope().model_dump(mode="json"))
        parsed = envelope_from_json(raw_envelope)
        if parsed.envelope.payload != signed.payload:
            raise ValueError("canonical envelope payload differs from the signed payload")
        lifecycle.complete(Receipt(result_id=result_id, raw_envelope=raw_envelope))

        if self._before_callback_schedule is not None:
            self._before_callback_schedule(dispatch)

        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError("Stage A event loop closed before callback delivery")
        receipt = FrozenCallbackReceipt(result_id=str(result_id), raw_envelope=raw_envelope)
        hard_deadline_at = datetime.fromisoformat(
            dispatch.hard_deadline_at.replace("Z", "+00:00")
        )
        callback_future = asyncio.run_coroutine_threadsafe(
            self._deliver_callback_owned(
                receipt,
                hard_deadline_at=hard_deadline_at,
            ),
            loop,
        )
        callback_future.add_done_callback(lambda _: callback_wait_wake.set())
        with self._guard:
            self._callback_waiters.add(callback_wait_wake)
            shutting_down = self._closed
        if shutting_down:
            callback_wait_wake.set()
        try:
            callback_result = self._await_callback_result(
                callback_future, callback_wait_wake, hard_deadline_at
            )
        finally:
            with self._guard:
                self._callback_waiters.discard(callback_wait_wake)
        with self._guard:
            self._callback_results[str(result_id)] = callback_result
        return result_id

    async def _deliver_callback_owned(
        self, receipt: FrozenCallbackReceipt, *, hard_deadline_at: datetime
    ) -> CallbackAccepted:
        if self._callback_closing:
            raise RuntimeError("callback delivery owner is closing")
        return await self._callback_client.deliver(
            receipt, hard_deadline_at=hard_deadline_at
        )

    def _await_callback_result(
        self,
        callback_future: Future[CallbackAccepted],
        wake: Event,
        hard_deadline_at: datetime,
    ) -> CallbackAccepted | Exception:
        hard_deadline = time.monotonic() + max(
            0.0, (hard_deadline_at - self._clock().astimezone(timezone.utc)).total_seconds()
        )
        while True:
            if callback_future.done():
                try:
                    return callback_future.result(timeout=0)
                except Exception as error:
                    return error

            wake.clear()
            # Recheck after clearing so a completion signal cannot be lost.
            if callback_future.done():
                continue
            with self._guard:
                shutdown_deadline = self._shutdown_deadline
            now = time.monotonic()
            deadline = min(
                hard_deadline,
                shutdown_deadline if shutdown_deadline is not None else hard_deadline,
            )
            remaining = deadline - now
            if remaining <= 0:
                callback_future.cancel()
                try:
                    return callback_future.result(timeout=0)
                except Exception as error:
                    return error
            wake.wait(remaining)

    def _producer_done(
        self,
        registration: _ExecutionRegistration,
        future: Future[object],
    ) -> None:
        with self._guard:
            if registration.future is future and not registration.capacity_released:
                registration.capacity_released = True
                self._active_futures.discard(future)
                self._active_registrations.pop(future, None)
                self._capacity.release()
            if self._futures.get(registration.attempt_id) is future:
                self._futures.pop(registration.attempt_id, None)
        if registration.accepted and (future.cancelled() or future.exception() is not None):
            try:
                registration.lifecycle.fail_after_start()
            except Exception:
                # Receipt completion may already have succeeded before callback
                # reporting. The original cache state remains authoritative.
                logger.debug("stage_a_failure_evidence_not_applicable")
        with self._guard:
            # Signal only this registration's event, after lifecycle failure
            # evidence is recorded. A same-ID replacement owns a different
            # Event, so stale callbacks cannot wake it.
            registration.done.set()

    def create_app(self) -> FastAPI:
        settings = Settings(
            manager_dispatch_token=SecretStr(self._dispatch_token),
            callback_token=SecretStr(self._callback_token),
            callback_url="http://backend.test/internal/v1/results/callback",
            dispatch_max_body_bytes=16_384,
            attempt_cache_max_entries=self._cache_max_entries,
            attempt_cache_ttl_seconds=self._cache_ttl_seconds,
            producer_concurrency_limit=self._producer_concurrency_limit,
            admission_executor_workers=self._admission_workers,
            admission_max_outstanding=self._admission_max_outstanding,
            shutdown_drain_timeout_seconds=self._shutdown_timeout,
        )
        app = create_app(
            settings,
            producer_registrar=self,
            runtime_lifecycle=self,
            attempt_cache_clock=self._cache_clock,
        )
        admission_executor = app.state.admission_executor
        if admission_executor is not None:
            original_shutdown = admission_executor.shutdown

            async def shutdown_with_shared_deadline(cleanup, *, timeout_seconds):
                deadline = self._begin_shutdown()
                remaining = max(0.0, min(timeout_seconds, deadline - time.monotonic()))
                return await original_shutdown(cleanup, timeout_seconds=remaining)

            admission_executor.shutdown = shutdown_with_shared_deadline
        return app

    @property
    def callback_results(self) -> dict[str, CallbackAccepted | Exception]:
        with self._guard:
            return dict(self._callback_results)

    @property
    def execution_futures(self) -> dict[str, Future[object]]:
        with self._guard:
            return dict(self._futures)

    def wait_for_attempt(self, attempt_id: str, timeout: float = 5.0) -> bool:
        with self._guard:
            event = self._attempt_done.setdefault(attempt_id, Event())
        return event.wait(timeout)

    def lifecycle_for(self, attempt_id: str) -> ProducerLifecycle:
        with self._guard:
            return self._lifecycles[attempt_id]

    def admission_for(self, attempt_id: str) -> Admission:
        with self._guard:
            return self._admissions[attempt_id]

    @property
    def registration_count(self) -> int:
        with self._guard:
            return self._registration_count

    @property
    def shutdown_drained(self) -> bool | None:
        return self._shutdown_drained

    @property
    def shutdown_cleanup_complete(self) -> bool | None:
        task = self._callback_close_task
        if task is None:
            return self._shutdown_cleanup_complete
        if not task.done() or task.cancelled():
            return False
        try:
            task.result()
        except BaseException:
            return False
        return True

    @property
    def callback_close_started(self) -> bool:
        return self._callback_closing

    @property
    def shutdown_timed_out(self) -> bool:
        return self._shutdown_timed_out

    @property
    def active_execution_count(self) -> int:
        with self._guard:
            return len(self._active_futures)

    @property
    def available_execution_capacity(self) -> int:
        # Test-only diagnostic for deterministic lifecycle assertions.
        return self._capacity._value
