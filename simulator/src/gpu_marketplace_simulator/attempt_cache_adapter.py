"""Simulator-local bridge from validated dispatches to the volatile Attempt cache."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
import logging
from threading import RLock
from typing import Protocol
from uuid import UUID

from gpu_marketplace_simulator.attempt_cache import (
    Admission,
    AttemptCache,
    AttemptState,
    CacheClosed,
    CacheFull,
    ExecutionConflict,
    ProducerFailureEvidence,
    Receipt,
)
from gpu_marketplace_simulator.dispatch import (
    AttemptAdmissionConflict,
    AttemptAdmissionOutcome,
    AttemptAdmissionUnavailable,
    DispatchRequest,
)
from gpu_marketplace_simulator.signed_result_v1 import validate_receipt_binding_v1


logger = logging.getLogger(__name__)


class ProducerRegistrationUncertain(Exception):
    """Registration may have launched work; its IN_FLIGHT owner must be kept."""


class ProducerRegistrationPort(Protocol):
    """Synchronous bounded handoff; its call never runs under the adapter lock.

    Return True only after registering exactly one producer. Return False or
    raise an ordinary Exception only when the implementation positively knows
    that no work was registered or launched. Raise
    ProducerRegistrationUncertain when it cannot prove pre-start rejection.
    This port performs handoff only; it must not execute GPU work inline.
    """

    def register(
        self,
        dispatch: DispatchRequest,
        admission: Admission,
        lifecycle: ProducerLifecycle,
    ) -> bool:
        ...


class ProducerLifecycle:
    """Trusted, Attempt-bound callback capability handed only to the registrar.

    A producer must propagate a rejected ``complete()`` call into the actual
    execution Future. It must not report successful execution after receipt
    completion was rejected; only a terminated Future with an exception or a
    completed cancellation is currently accepted as post-start failure evidence.
    """

    __slots__ = ("_adapter", "_admission")

    def __init__(
        self, adapter: AttemptCacheAdmissionAdapter, admission: Admission
    ) -> None:
        self._adapter = adapter
        self._admission = admission

    def bind_execution_future(self, execution_future: Future[object]) -> None:
        """Bind the actual producer execution Future exactly once."""
        self._adapter._bind_execution_future(self, execution_future)

    def complete(self, receipt: Receipt) -> AttemptAdmissionOutcome:
        """Retain a structurally valid, identity-bound receipt or raise.

        The producer must allow this exception to fail its execution Future.
        """
        return self._adapter.complete(self._admission, receipt)

    def fail_after_start(self) -> Admission:
        return self._adapter._fail_after_start(self)


class _RegistrationPhase(str, Enum):
    REGISTERING = "REGISTERING"
    REGISTERED = "REGISTERED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(slots=True)
class _ProducerSlot:
    admission: Admission
    phase: _RegistrationPhase
    lifecycle: ProducerLifecycle
    receipt_identity: _ReceiptIdentity
    execution_future: Future[object] | None = None


@dataclass(frozen=True, slots=True)
class _ReceiptIdentity:
    job_id: UUID
    worker_id: UUID
    listing_id: UUID


class AttemptCacheAdmissionAdapter:
    """Preserve Attempt identity and fence producer ownership across callbacks."""

    def __init__(
        self,
        *,
        cache: AttemptCache,
        producer: ProducerRegistrationPort,
        max_concurrent_producers: int,
    ) -> None:
        if type(max_concurrent_producers) is not int or max_concurrent_producers < 1:
            raise ValueError("max_concurrent_producers must be a positive integer")
        self._cache = cache
        self._producer = producer
        self._max_concurrent = max_concurrent_producers
        # Includes pending and uncertain handoffs: both consume a bounded slot.
        self._producer_slots: dict[UUID, _ProducerSlot] = {}
        self._closed = False
        self._lock = RLock()

    def _outcome(
        self,
        admission: Admission,
        *,
        newly_admitted: bool,
        producer_registered: bool,
    ) -> AttemptAdmissionOutcome:
        return AttemptAdmissionOutcome(
            attempt_id=str(admission.attempt_id),
            state=admission.state.value,
            newly_admitted=newly_admitted,
            producer_registered=producer_registered,
            receipt=admission.receipt,
            cache_admission=admission,
        )

    @staticmethod
    def _same_owner(slot: _ProducerSlot | None, admission: Admission) -> bool:
        return (slot is not None
                and slot.admission._producer_token is admission._producer_token
                and slot.admission.fingerprint == admission.fingerprint)

    def _retained_outcome(self, admission: Admission) -> AttemptAdmissionOutcome:
        if admission.state is AttemptState.IN_FLIGHT:
            slot = self._producer_slots.get(admission.attempt_id)
            if (slot is None
                    or slot.admission.fingerprint != admission.fingerprint):
                raise AttemptAdmissionUnavailable("retained producer ownership is unavailable")
            if slot.phase is not _RegistrationPhase.REGISTERED:
                # A duplicate must never receive 202 before confirmed handoff.
                raise AttemptAdmissionUnavailable("producer registration is not confirmed")
            return self._outcome(
                admission, newly_admitted=False, producer_registered=True
            )
        if admission.state is AttemptState.FINISHED and admission.receipt is not None:
            return self._outcome(
                admission, newly_admitted=False, producer_registered=True
            )
        if admission.state is AttemptState.FAILED_NO_RECEIPT:
            raise AttemptAdmissionUnavailable("retained Attempt terminated without a receipt")
        raise AttemptAdmissionUnavailable("retained Attempt has no accepted producer")

    def _rollback_prestart(self, admission: Admission) -> bool:
        """Token-fenced rollback and slot release under the adapter lock."""
        with self._lock:
            slot = self._producer_slots.get(admission.attempt_id)
            if not self._same_owner(slot, admission):
                return False
            if slot.phase is not _RegistrationPhase.REGISTERING:
                return False
            if not self._cache.abort_before_start(admission):
                # Never release capacity or forget ownership when the cache
                # token says the handoff is no longer safely removable.
                slot.phase = _RegistrationPhase.UNCERTAIN
                return False
            del self._producer_slots[admission.attempt_id]
            return True

    def _confirm_registered(self, admission: Admission) -> AttemptAdmissionOutcome:
        with self._lock:
            slot = self._producer_slots.get(admission.attempt_id)
            if self._same_owner(slot, admission):
                slot.phase = _RegistrationPhase.REGISTERED
                if self._closed:
                    raise AttemptAdmissionUnavailable("adapter is closing")
                retained = self._cache.snapshot(admission.attempt_id)
                if retained is not None and retained.state is AttemptState.IN_FLIGHT:
                    return self._outcome(
                        admission, newly_admitted=True, producer_registered=True
                    )
                if retained is not None:
                    return self._retained_outcome(retained)
                raise AttemptAdmissionUnavailable("registered Attempt is no longer retained")

            # A very fast trusted producer may complete/fail while register()
            # is returning. Re-read the retained terminal result under lock.
            retained = self._cache.snapshot(admission.attempt_id)
            if retained is None:
                raise AttemptAdmissionUnavailable("registered Attempt is no longer retained")
            if retained.fingerprint != admission.fingerprint:
                raise AttemptAdmissionUnavailable("producer ownership changed")
            if self._closed:
                raise AttemptAdmissionUnavailable("adapter is closing")
            return self._retained_outcome(retained)

    def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
        request = dispatch.model_dump(mode="json")
        attempt_id = UUID(dispatch.attempt_id)

        # Reserve Attempt identity and bounded producer capacity atomically.
        # No potentially slow producer call is made while this lock is held.
        with self._lock:
            if self._closed:
                raise AttemptAdmissionUnavailable("adapter is closing")
            try:
                retained = self._cache.snapshot(attempt_id)
                if retained is not None:
                    existing = self._cache.admit(request)
                    return self._retained_outcome(existing)
                if len(self._producer_slots) >= self._max_concurrent:
                    raise AttemptAdmissionUnavailable("producer concurrency is full")
                admission = self._cache.admit(request)
            except ExecutionConflict as error:
                raise AttemptAdmissionConflict from error
            except (CacheFull, CacheClosed) as error:
                raise AttemptAdmissionUnavailable from error

            if not admission.newly_admitted:
                # Cache state can change through expiry between snapshot and
                # admission only for terminal entries; handle by its real state.
                return self._retained_outcome(admission)
            if len(self._producer_slots) >= self._max_concurrent:
                if not self._cache.abort_before_start(admission):
                    raise AttemptAdmissionUnavailable("producer slot reservation was fenced")
                raise AttemptAdmissionUnavailable("producer concurrency is full")
            lifecycle = ProducerLifecycle(self, admission)
            self._producer_slots[attempt_id] = _ProducerSlot(
                admission,
                _RegistrationPhase.REGISTERING,
                lifecycle,
                _ReceiptIdentity(
                    UUID(dispatch.job_id),
                    UUID(dispatch.worker_id),
                    UUID(dispatch.listing_id),
                ),
            )

        # Call outside the global lock: unrelated Attempts and shutdown can
        # make progress while one registrar is slow.
        try:
            registered = self._producer.register(dispatch, admission, lifecycle)
        except ProducerRegistrationUncertain:
            with self._lock:
                slot = self._producer_slots.get(attempt_id)
                if self._same_owner(slot, admission):
                    slot.phase = _RegistrationPhase.UNCERTAIN
            logger.warning("attempt_producer_registration_uncertain")
            raise AttemptAdmissionUnavailable("producer registration is uncertain") from None
        except Exception as error:
            if not self._rollback_prestart(admission):
                logger.warning("attempt_producer_prestart_rollback_fenced")
                raise AttemptAdmissionUnavailable(
                    "pre-start rollback could not be proven"
                ) from None
            logger.warning(
                "attempt_producer_registration_rejected",
                extra={"exception_type": type(error).__name__},
            )
            raise AttemptAdmissionUnavailable("producer registration failed") from None

        if registered is not True:
            if self._rollback_prestart(admission):
                raise AttemptAdmissionUnavailable("producer rejected handoff")
            logger.warning("attempt_producer_prestart_rollback_fenced")
            raise AttemptAdmissionUnavailable(
                "pre-start rollback could not be proven"
            )
        return self._confirm_registered(admission)

    def complete(self, admission: Admission, receipt: Receipt) -> AttemptAdmissionOutcome:
        """Bind exact V1 envelope bytes to this Attempt before retaining them."""
        with self._lock:
            slot = self._producer_slots.get(admission.attempt_id)
            if not self._same_owner(slot, admission):
                raise AttemptAdmissionUnavailable("producer registration is stale")
            identity = slot.receipt_identity
        try:
            validate_receipt_binding_v1(
                receipt.raw_envelope,
                outer_result_id=receipt.result_id,
                expected_attempt_id=admission.attempt_id,
                expected_job_id=identity.job_id,
                expected_worker_id=identity.worker_id,
                expected_listing_id=identity.listing_id,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise AttemptAdmissionUnavailable("receipt is not bound to this Attempt") from error

        with self._lock:
            slot = self._producer_slots.get(admission.attempt_id)
            if not self._same_owner(slot, admission):
                raise AttemptAdmissionUnavailable("producer registration is stale")
            try:
                finished = self._cache.finish(admission, receipt)
            except Exception as error:
                raise AttemptAdmissionUnavailable("producer completion was rejected") from error
            del self._producer_slots[admission.attempt_id]
            return self._outcome(
                finished, newly_admitted=False, producer_registered=True
            )

    def _bind_execution_future(
        self, lifecycle: ProducerLifecycle, execution_future: Future[object]
    ) -> None:
        if not isinstance(execution_future, Future):
            raise TypeError("producer execution must be a concurrent Future")
        with self._lock:
            admission = lifecycle._admission
            slot = self._producer_slots.get(admission.attempt_id)
            if (not self._same_owner(slot, admission)
                    or slot.lifecycle is not lifecycle
                    or slot.execution_future is not None):
                raise AttemptAdmissionUnavailable("producer lifecycle is stale or already bound")
            slot.execution_future = execution_future

    def _fail_after_start(self, lifecycle: ProducerLifecycle) -> Admission:
        """Record only this registered producer's confirmed termination."""
        with self._lock:
            admission = lifecycle._admission
            slot = self._producer_slots.get(admission.attempt_id)
            if (not self._same_owner(slot, admission)
                    or slot.lifecycle is not lifecycle
                    or slot.execution_future is None):
                raise AttemptAdmissionUnavailable("producer registration is stale")
            execution_future = slot.execution_future
            if (execution_future.done() and not execution_future.cancelled()
                    and execution_future.exception() is None):
                # A successful Future without a retained receipt is a
                # producer-contract violation. Fail closed and alert without
                # releasing the slot or logging receipt/provider contents.
                logger.error("attempt_producer_succeeded_without_receipt")
            try:
                evidence = ProducerFailureEvidence.from_terminated_execution(
                    execution_future
                )
            except (TypeError, ValueError) as error:
                raise AttemptAdmissionUnavailable(
                    "producer termination is not confirmed"
                ) from error
            if not evidence.matches(slot.execution_future):
                raise AttemptAdmissionUnavailable("producer failure evidence is mismatched")
            try:
                failed = self._cache.fail_after_start(admission, evidence)
            except Exception as error:
                raise AttemptAdmissionUnavailable("producer failure was rejected") from error
            del self._producer_slots[admission.attempt_id]
            logger.warning("attempt_producer_terminated_without_receipt")
            return failed

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cache.close()

    def drain(self, timeout_seconds: float) -> bool:
        return self._cache.drain(timeout_seconds)

    @property
    def active_producer_count(self) -> int:
        with self._lock:
            return len(self._producer_slots)
