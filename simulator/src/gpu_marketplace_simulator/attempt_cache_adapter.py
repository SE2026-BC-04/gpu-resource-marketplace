"""Simulator-local bridge from validated dispatches to the volatile Attempt cache."""
from __future__ import annotations

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
    Receipt,
)
from gpu_marketplace_simulator.dispatch import (
    AttemptAdmissionConflict,
    AttemptAdmissionOutcome,
    AttemptAdmissionUnavailable,
    DispatchRequest,
)


class ProducerRegistrationPort(Protocol):
    """Synchronous bounded handoff; rejection guarantees that no work started.

    Implementations must return ``True`` only after registering exactly one
    producer. ``False`` or an exception must mean no producer was registered
    or launched, so the adapter can safely roll back its pre-start cache slot.
    The call must be bounded and must not execute GPU work inline.
    """

    def register(self, dispatch: DispatchRequest, admission: Admission) -> bool:
        ...


class AttemptCacheAdmissionAdapter:
    """Preserve Attempt identity while requiring successful producer handoff."""

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
        self._registered: dict[UUID, Admission] = {}
        self._closed = False
        self._lock = RLock()

    def _outcome(self, admission: Admission, *, newly_admitted: bool,
                 producer_registered: bool) -> AttemptAdmissionOutcome:
        return AttemptAdmissionOutcome(
            attempt_id=str(admission.attempt_id),
            state=admission.state.value,
            newly_admitted=newly_admitted,
            producer_registered=producer_registered,
            receipt=admission.receipt,
            cache_admission=admission,
        )

    def _rollback_rejected_handoff(self, admission: Admission) -> None:
        if not self._cache.abort_before_start(admission):
            # The token fence rejected rollback. Never claim success or remove
            # a replacement entry if another owner changed the cache meanwhile.
            raise AttemptAdmissionUnavailable("pre-start rollback was fenced")

    def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
        request = dispatch.model_dump(mode="json")
        attempt_id = UUID(dispatch.attempt_id)

        with self._lock:
            if self._closed:
                raise AttemptAdmissionUnavailable("adapter is closing")

            retained = self._cache.snapshot(attempt_id)
            if retained is None and len(self._registered) >= self._max_concurrent:
                raise AttemptAdmissionUnavailable("producer concurrency is full")

            try:
                admission = self._cache.admit(request)
            except ExecutionConflict as error:
                raise AttemptAdmissionConflict from error
            except (CacheFull, CacheClosed) as error:
                raise AttemptAdmissionUnavailable from error

            if admission.newly_admitted:
                if len(self._registered) >= self._max_concurrent:
                    self._rollback_rejected_handoff(admission)
                    raise AttemptAdmissionUnavailable("producer concurrency is full")
                try:
                    registered = self._producer.register(dispatch, admission)
                except Exception as error:
                    self._rollback_rejected_handoff(admission)
                    raise AttemptAdmissionUnavailable from error
                if registered is not True:
                    self._rollback_rejected_handoff(admission)
                    raise AttemptAdmissionUnavailable("producer rejected handoff")
                self._registered[attempt_id] = admission
                return self._outcome(
                    admission, newly_admitted=True, producer_registered=True
                )

            if admission.state is AttemptState.IN_FLIGHT:
                registered = self._registered.get(attempt_id)
                if (registered is None
                        or registered.fingerprint != admission.fingerprint):
                    raise AttemptAdmissionUnavailable("retained producer is not registered")
                return self._outcome(
                    admission, newly_admitted=False, producer_registered=True
                )

            if admission.state is AttemptState.FINISHED and admission.receipt is not None:
                return self._outcome(
                    admission, newly_admitted=False, producer_registered=True
                )
            raise AttemptAdmissionUnavailable("retained attempt has no accepted producer")

    def complete(self, admission: Admission, receipt: Receipt) -> AttemptAdmissionOutcome:
        """Record completion for the original registered producer only."""
        with self._lock:
            current = self._registered.get(admission.attempt_id)
            if (current is None or current._producer_token is not admission._producer_token):
                raise AttemptAdmissionUnavailable("producer registration is stale")
            finished = self._cache.finish(admission, receipt)
            del self._registered[admission.attempt_id]
            return self._outcome(
                finished, newly_admitted=False, producer_registered=True
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cache.close()

    def drain(self, timeout_seconds: float) -> bool:
        return self._cache.drain(timeout_seconds)

    @property
    def active_producer_count(self) -> int:
        with self._lock:
            return len(self._registered)
