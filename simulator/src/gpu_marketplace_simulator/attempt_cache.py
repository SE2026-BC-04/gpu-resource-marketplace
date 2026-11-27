"""Process-local Attempt admission/cache core (G2-A TV5-P2E-08 only).

This module has no HTTP, DB, signer, key, callback or background execution.
D-16 Option B: a conflicting same-attempt dispatch can be detected only while
its immutable fingerprint is retained in this particular cache instance.
"""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
import re
from threading import Condition, RLock
import time
from typing import Callable, Mapping
from uuid import UUID


_DISPATCH_KEYS = frozenset({
    "outbox_event_id", "job_id", "attempt_id", "worker_id", "listing_id",
    "gpu_count", "duration_seconds", "simulation_input",
    "finish_due_at", "hard_deadline_at",
})
_UUID_KEYS = ("outbox_event_id", "job_id", "attempt_id", "worker_id", "listing_id")
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")
_MAX_INT32 = (1 << 31) - 1


class ExecutionConflict(Exception):
    """A retained attempt is bound to another immutable dispatch (HTTP 409 later)."""


class CacheFull(Exception):
    """No capacity without evicting an IN_FLIGHT attempt (transport may retry)."""


class CacheClosed(Exception):
    """The owner has begun shutdown; no new admission is allowed."""


class InvalidDispatch(ValueError):
    """Not the approved ten-key immutable Manager dispatch."""


class InvalidTransition(ValueError):
    """Stale or duplicate producer completion, or mismatched fingerprint."""


class AttemptState(str, Enum):
    IN_FLIGHT = "IN_FLIGHT"
    FINISHED = "FINISHED"
    FAILED_NO_RECEIPT = "FAILED_NO_RECEIPT"


@dataclass(frozen=True, slots=True)
class Receipt:
    result_id: UUID
    raw_envelope: bytes

    def __post_init__(self) -> None:
        if type(self.result_id) is not UUID or self.result_id.version != 4:
            raise ValueError("result_id must be UUIDv4")
        if type(self.raw_envelope) is not bytes or not self.raw_envelope:
            raise ValueError("receipt must contain nonempty immutable raw bytes")


@dataclass(frozen=True, slots=True)
class ProducerFailureEvidence:
    """Proof that the original execution Future terminated without a receipt.

    This is an internal producer-lifecycle capability, not an HTTP/API DTO.
    Construct it only after observing the actual execution Future terminate
    with an exception or completed cancellation. A timeout or request
    cancellation is not sufficient evidence.
    """

    _execution_future: Future[object] = field(repr=False, compare=False)

    @classmethod
    def from_terminated_execution(
        cls, execution_future: Future[object]
    ) -> ProducerFailureEvidence:
        if not isinstance(execution_future, Future) or not execution_future.done():
            raise ValueError("producer execution has not positively terminated")
        if execution_future.cancelled():
            return cls(execution_future)
        if execution_future.exception() is None:
            raise ValueError("successful execution is not failure evidence")
        return cls(execution_future)

    def is_confirmed(self) -> bool:
        if not self._execution_future.done():
            return False
        if self._execution_future.cancelled():
            return True
        return self._execution_future.exception() is not None

    def matches(self, execution_future: Future[object] | None) -> bool:
        return execution_future is not None and self._execution_future is execution_future


@dataclass(frozen=True, slots=True)
class Admission:
    attempt_id: UUID
    fingerprint: bytes
    state: AttemptState
    newly_admitted: bool
    receipt: Receipt | None
    _producer_token: object | None = field(default=None, repr=False, compare=False)


@dataclass(slots=True)
class _Entry:
    fingerprint: bytes
    state: AttemptState
    receipt: Receipt | None
    terminal_at: float | None
    producer_token: object | None


def _canonical_uuid(value: object, name: str) -> str:
    if type(value) is not str:
        raise InvalidDispatch(f"{name} must be canonical UUIDv4")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise InvalidDispatch(f"{name} must be canonical UUIDv4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise InvalidDispatch(f"{name} must be canonical UUIDv4")
    return value


def _utc_timestamp(value: object, name: str) -> str:
    if type(value) is not str or _TIMESTAMP_RE.fullmatch(value) is None:
        raise InvalidDispatch(f"{name} must be an exact UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidDispatch(f"{name} must be an exact UTC timestamp") from error
    return value


def _dispatch_identity(dispatch: Mapping[str, object]) -> tuple[bytes, UUID]:
    """SHA-256 of a validated, sorted, compact ten-key dispatch representation.

    This is a *cache identity*, not a wire-format/signing change; JSON key order
    does not affect identity. No extra fields, oracle references or commands.
    """
    # Accept only the JSON-decoder's plain dict representation. Arbitrary
    # Mapping implementations can change their keys/values between validation
    # and serialization, or implement surprising equality/iteration behavior.
    if type(dispatch) is not dict:
        raise InvalidDispatch("dispatch must be a plain JSON object")
    snapshot = dispatch.copy()
    if (any(type(key) is not str for key in snapshot)
            or set(snapshot) != _DISPATCH_KEYS):
        raise InvalidDispatch("dispatch must contain exactly ten approved fields")
    for name in _UUID_KEYS:
        _canonical_uuid(snapshot[name], name)
    for name in ("gpu_count", "duration_seconds"):
        n = snapshot[name]
        if type(n) is not int or not 1 <= n <= _MAX_INT32:
            raise InvalidDispatch(f"{name} must be positive int32")
    _utc_timestamp(snapshot["finish_due_at"], "finish_due_at")
    _utc_timestamp(snapshot["hard_deadline_at"], "hard_deadline_at")
    simulation = snapshot["simulation_input"]
    if type(simulation) is not dict:
        raise InvalidDispatch("simulation_input must be a plain JSON object")
    simulation = simulation.copy()
    if (any(type(key) is not str for key in simulation)
            or set(simulation) != {"workload_profile"}
            or type(simulation["workload_profile"]) is not str
            or simulation["workload_profile"] != "demo-v1"):
        raise InvalidDispatch("simulation_input must contain only demo-v1 workload_profile")

    # Serialize only the validated snapshot. Never revisit caller-owned objects
    # after validation, so concurrent mutation cannot alter the fingerprint.
    normalized = {
        "outbox_event_id": snapshot["outbox_event_id"],
        "job_id": snapshot["job_id"],
        "attempt_id": snapshot["attempt_id"],
        "worker_id": snapshot["worker_id"],
        "listing_id": snapshot["listing_id"],
        "gpu_count": snapshot["gpu_count"],
        "duration_seconds": snapshot["duration_seconds"],
        "simulation_input": {"workload_profile": "demo-v1"},
        "finish_due_at": snapshot["finish_due_at"],
        "hard_deadline_at": snapshot["hard_deadline_at"],
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).digest(), UUID(snapshot["attempt_id"])


def dispatch_fingerprint(dispatch: Mapping[str, object]) -> bytes:
    """Return the deterministic fingerprint for one validated dispatch."""
    return _dispatch_identity(dispatch)[0]


class AttemptCache:
    """Bounded, thread-safe volatile cache; numeric bounds are test injections.

    FINISHED and FAILED_NO_RECEIPT entries expire after ttl_seconds and can be
    evicted oldest-first under capacity pressure. IN_FLIGHT entries are never
    evicted or expired.
    There is no cross-process/cold-start historical conflict guarantee.
    """

    def __init__(self, *, max_entries: int, ttl_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be positive")
        if (type(ttl_seconds) not in (int, float)
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError("ttl_seconds must be positive and finite")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[UUID, _Entry] = {}
        self._closed = False
        self._last_cache_time: float | None = None
        self._condition = Condition(RLock())

    def _now(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("cache clock must return a finite monotonic number")
        now = float(value)
        if self._last_cache_time is not None and now < self._last_cache_time:
            raise ValueError("cache clock moved backwards")
        self._last_cache_time = now
        return now

    def _prune(self, now: float) -> None:
        for attempt_id, entry in list(self._entries.items()):
            if (entry.state is not AttemptState.IN_FLIGHT
                    and entry.terminal_at is not None
                    and now - entry.terminal_at >= self._ttl):
                del self._entries[attempt_id]

    def admit(self, dispatch: Mapping[str, object]) -> Admission:
        """Return newly_admitted=True exactly once for each retained attempt."""
        fingerprint, attempt_id = _dispatch_identity(dispatch)
        with self._condition:
            if self._closed:
                raise CacheClosed("attempt cache is shutting down")
            now = self._now()
            self._prune(now)
            existing = self._entries.get(attempt_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ExecutionConflict("EXECUTION_CONFLICT")
                return Admission(attempt_id, fingerprint, existing.state,
                                 False, existing.receipt)
            if len(self._entries) >= self._max_entries:
                terminal = [
                    (key, entry.terminal_at)
                    for key, entry in self._entries.items()
                    if entry.state is not AttemptState.IN_FLIGHT
                ]
                if not terminal:
                    raise CacheFull("all cache slots are IN_FLIGHT")
                oldest_id = min(terminal, key=lambda item: item[1])[0]
                del self._entries[oldest_id]
            producer_token = object()
            self._entries[attempt_id] = _Entry(
                fingerprint, AttemptState.IN_FLIGHT, None, None, producer_token
            )
            return Admission(
                attempt_id, fingerprint, AttemptState.IN_FLIGHT, True, None,
                _producer_token=producer_token,
            )

    def finish(self, admission: Admission, receipt: Receipt) -> Admission:
        """Bind exact original receipt bytes and ID once; never re-sign on replay."""
        if (type(admission) is not Admission or not admission.newly_admitted
                or admission._producer_token is None):
            raise InvalidTransition("only the original producer can finish")
        if type(receipt) is not Receipt:
            raise InvalidTransition("completion requires an immutable Receipt")
        with self._condition:
            entry = self._entries.get(admission.attempt_id)
            if (entry is None or entry.fingerprint != admission.fingerprint
                    or entry.state is not AttemptState.IN_FLIGHT
                    or entry.producer_token is not admission._producer_token):
                raise InvalidTransition("attempt is absent, changed or already finished")
            terminal_at = self._now()
            entry.state = AttemptState.FINISHED
            entry.receipt = receipt
            entry.terminal_at = terminal_at
            self._condition.notify_all()
            return Admission(admission.attempt_id, admission.fingerprint,
                             AttemptState.FINISHED, False, receipt)

    def fail_after_start(
        self,
        admission: Admission,
        evidence: ProducerFailureEvidence,
    ) -> Admission:
        """Retain a token-fenced terminal failure only after positive proof.

        The terminal tombstone keeps the original fingerprint and has no
        receipt. It cannot be transitioned to another terminal state.
        """
        if (type(admission) is not Admission or not admission.newly_admitted
                or admission._producer_token is None):
            raise InvalidTransition("only the original producer can fail")
        if (type(evidence) is not ProducerFailureEvidence
                or not evidence.is_confirmed()):
            raise InvalidTransition("producer termination is not confirmed")
        with self._condition:
            entry = self._entries.get(admission.attempt_id)
            if (entry is None or entry.fingerprint != admission.fingerprint
                    or entry.state is not AttemptState.IN_FLIGHT
                    or entry.producer_token is not admission._producer_token):
                raise InvalidTransition("attempt is absent, changed or already terminal")
            entry.state = AttemptState.FAILED_NO_RECEIPT
            entry.receipt = None
            entry.terminal_at = self._now()
            self._condition.notify_all()
            return Admission(
                admission.attempt_id, admission.fingerprint,
                AttemptState.FAILED_NO_RECEIPT, False, None,
            )

    def abort_before_start(self, admission: Admission) -> bool:
        """Remove only the original IN_FLIGHT slot after a proven pre-start rejection.

        The opaque producer token fences rollback from a stale registration
        attempt after eviction, re-admission, completion, or replacement.
        Callers must use this only when the producer boundary guarantees that
        no work was accepted or launched.
        """
        if (type(admission) is not Admission or not admission.newly_admitted
                or admission._producer_token is None):
            return False
        with self._condition:
            entry = self._entries.get(admission.attempt_id)
            if (entry is None or entry.state is not AttemptState.IN_FLIGHT
                    or entry.fingerprint != admission.fingerprint
                    or entry.producer_token is not admission._producer_token):
                return False
            del self._entries[admission.attempt_id]
            self._condition.notify_all()
            return True

    def snapshot(self, attempt_id: UUID) -> Admission | None:
        with self._condition:
            self._prune(self._now())
            entry = self._entries.get(attempt_id)
            if entry is None:
                return None
            return Admission(attempt_id, entry.fingerprint, entry.state,
                             False, entry.receipt)

    def close(self) -> None:
        """Reject later admissions. In-flight work remains available to drain."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def drain(self, timeout_seconds: float) -> bool:
        """Wait for producers to finish; never discard an in-flight entry."""
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds < 0):
            raise ValueError("timeout_seconds must be nonnegative and finite")
        with self._condition:
            deadline = time.monotonic() + timeout_seconds
            while any(e.state is AttemptState.IN_FLIGHT for e in self._entries.values()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True
