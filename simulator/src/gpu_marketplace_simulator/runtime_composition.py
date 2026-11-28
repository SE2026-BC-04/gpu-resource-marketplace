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
        self._futures: dict[str, Future[object]] = {}
        self._attempt_done: dict[str, Event] = {}
        self._lifecycles: dict[str, ProducerLifecycle] = {}
        self._admissions: dict[str, Admission] = {}
        self._registration_count = 0
        self._callback_results: dict[str, CallbackAccepted | Exception] = {}
        self._closed = False
        self._shutdown_drained: bool | None = None

    async def startup(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def shutdown(self) -> None:
        self._shutdown_started.set()
        with self._guard:
            self._closed = True
            pending = tuple(self._active_futures)
        _, not_done = await asyncio.to_thread(
            wait, pending, timeout=self._shutdown_timeout
        )
        self._shutdown_drained = not not_done
        self._executor.shutdown(wait=False, cancel_futures=False)
        if not not_done:
            await self._callback_client.aclose()
        else:
            logger.warning("stage_a_producer_drain_timed_out", extra={"pending": len(not_done)})

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
        with self._guard:
            if self._closed:
                return False
        if not self._capacity.acquire(blocking=False):
            return False

        wake_worker = Event()
        execution_allowed = Event()
        try:
            future = self._executor.submit(
                self._execute, dispatch, _admission, lifecycle,
                wake_worker, execution_allowed,
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
        )
        with self._guard:
            self._active_futures.add(future)
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
            self._futures[attempt_id] = future
            self._attempt_done[attempt_id] = registration.done
            self._lifecycles[attempt_id] = lifecycle
            self._admissions[attempt_id] = _admission
            self._registration_count += 1
            registration.accepted = True
        execution_allowed.set()
        wake_worker.set()
        logger.info("stage_a_registration_return", extra={"thread_name": current_thread().name})
        return True

    def _execute(
        self,
        dispatch: DispatchRequest,
        admission: Admission,
        lifecycle: ProducerLifecycle,
        wake_worker: Event,
        execution_allowed: Event,
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

        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError("Stage A event loop closed before callback delivery")
        receipt = FrozenCallbackReceipt(result_id=str(result_id), raw_envelope=raw_envelope)
        callback_future = asyncio.run_coroutine_threadsafe(
            self._callback_client.deliver(
                receipt,
                hard_deadline_at=datetime.fromisoformat(
                    dispatch.hard_deadline_at.replace("Z", "+00:00")
                ),
            ),
            loop,
        )
        try:
            accepted = callback_future.result()
        except Exception as error:
            # Receipt is already immutable and FINISHED. Callback failure never
            # retries production, changes the bytes, or re-signs the result.
            with self._guard:
                self._callback_results[str(result_id)] = error
        else:
            with self._guard:
                self._callback_results[str(result_id)] = accepted
        return result_id

    def _producer_done(
        self,
        registration: _ExecutionRegistration,
        future: Future[object],
    ) -> None:
        with self._guard:
            if registration.future is future and not registration.capacity_released:
                registration.capacity_released = True
                self._active_futures.discard(future)
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
        return create_app(
            settings,
            producer_registrar=self,
            runtime_lifecycle=self,
            attempt_cache_clock=self._cache_clock,
        )

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
    def active_execution_count(self) -> int:
        with self._guard:
            return len(self._active_futures)

    @property
    def available_execution_capacity(self) -> int:
        # Test-only diagnostic for deterministic lifecycle assertions.
        return self._capacity._value
