"""Byte-preserving transport for an already-produced Signed Result V1 receipt."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import re
import time
from typing import Awaitable, Callable
from uuid import UUID

import httpx
from pydantic import SecretStr


CALLBACK_PATH = "/internal/v1/results/callback"
_SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{86}$")
_RECEIPT_STATUSES = frozenset({"STORED", "DUPLICATE"})


class CallbackClientError(Exception):
    """Base class for safe callback transport outcomes."""


class InvalidCallbackConfiguration(CallbackClientError):
    """Callback URL, token or policy is missing or invalid."""


class InvalidFrozenReceipt(CallbackClientError):
    """Receipt bytes and their declared immutable result identity disagree."""


class CallbackProtocolError(CallbackClientError):
    """The server response cannot be interpreted as an approved acknowledgement."""


class CallbackResponseTooLarge(CallbackProtocolError):
    """The response exceeded the injected acknowledgement-body bound."""


class CallbackRejected(CallbackClientError):
    """The Backend definitively rejected this unchanged receipt."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Callback receipt rejected with HTTP {status_code}.")
        self.status_code = status_code


class CallbackConflict(CallbackRejected):
    """The Backend reports a result-ID collision or stale receipt context."""


class CallbackDeadlineExceeded(CallbackClientError):
    """No further delivery attempt may start before the supplied retry deadline."""

    def __init__(
        self,
        *,
        attempts: int,
        last_failure: str | None,
        delivery_uncertain: bool,
    ) -> None:
        message = "Callback retry deadline elapsed before acceptance was confirmed."
        super().__init__(message)
        self.attempts = attempts
        self.last_failure = last_failure
        self.delivery_uncertain = delivery_uncertain


class CallbackRetryExhausted(CallbackClientError):
    """An explicitly injected attempt budget ended without confirmed acceptance."""

    def __init__(
        self,
        *,
        attempts: int,
        last_failure: str,
        delivery_uncertain: bool,
    ) -> None:
        super().__init__("Callback retry attempt budget exhausted without confirmed acceptance.")
        self.attempts = attempts
        self.last_failure = last_failure
        self.delivery_uncertain = delivery_uncertain


@dataclass(frozen=True, slots=True)
class FrozenCallbackReceipt:
    """One immutable raw callback envelope; this type never signs or serializes it."""

    result_id: str
    raw_envelope: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, str) or not _is_canonical_uuid4(self.result_id):
            raise InvalidFrozenReceipt("Receipt result_id must be a canonical UUIDv4.")
        if not isinstance(self.raw_envelope, bytes) or not self.raw_envelope:
            raise InvalidFrozenReceipt("Receipt envelope must be non-empty immutable bytes.")
        try:
            envelope = json.loads(
                self.raw_envelope.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
            raise InvalidFrozenReceipt("Receipt envelope is not strict UTF-8 JSON.") from error

        if not isinstance(envelope, dict) or set(envelope) != {
            "payload", "signature", "signature_encoding"
        }:
            raise InvalidFrozenReceipt("Receipt envelope has an invalid outer shape.")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or payload.get("result_id") != self.result_id:
            raise InvalidFrozenReceipt("Receipt result_id does not match the envelope payload.")
        if envelope.get("signature_encoding") != "base64url-no-padding":
            raise InvalidFrozenReceipt("Receipt signature encoding is unsupported.")
        signature = envelope.get("signature")
        if not isinstance(signature, str) or not _is_canonical_signature(signature):
            raise InvalidFrozenReceipt("Receipt signature has an invalid V1 representation.")


@dataclass(frozen=True, slots=True)
class CallbackRetryPolicy:
    """Approved network timings plus caller-supplied resource and optional attempt bounds."""

    max_request_bytes: int
    max_response_bytes: int
    connect_timeout_seconds: float = 2.0
    total_timeout_seconds: float = 5.0
    backoff_seconds: tuple[float, ...] = (2.0, 4.0, 8.0, 16.0, 30.0)
    auth_retry_seconds: float = 30.0
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        for name in ("max_request_bytes", "max_response_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise InvalidCallbackConfiguration(f"{name} must be a positive integer.")
        if self.max_attempts is not None and (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise InvalidCallbackConfiguration("max_attempts must be a positive integer or None.")
        if not isinstance(self.backoff_seconds, tuple):
            raise InvalidCallbackConfiguration("backoff_seconds must be an immutable tuple.")
        timings = (
            self.connect_timeout_seconds,
            self.total_timeout_seconds,
            self.auth_retry_seconds,
            *self.backoff_seconds,
        )
        if not self.backoff_seconds or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in timings
        ):
            raise InvalidCallbackConfiguration("Retry timings must be finite positive numbers.")
        if self.connect_timeout_seconds > self.total_timeout_seconds:
            raise InvalidCallbackConfiguration("Connect timeout cannot exceed total timeout.")

    def transient_delay(self, failure_number: int) -> float:
        index = min(failure_number - 1, len(self.backoff_seconds) - 1)
        return self.backoff_seconds[index]


@dataclass(frozen=True, slots=True)
class CallbackAccepted:
    result_id: str
    receipt_status: str
    attempts: int


@dataclass(frozen=True, slots=True)
class _InFlightDelivery:
    raw_envelope: bytes
    deadline: datetime
    task: asyncio.Task[CallbackAccepted]


def _is_canonical_uuid4(value: str) -> bool:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _is_canonical_signature(value: str) -> bool:
    if _SIGNATURE_PATTERN.fullmatch(value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except (ValueError, base64.binascii.Error):
        return False
    return len(decoded) == 64 and base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") == value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _validate_callback_url(value: str) -> str:
    try:
        url = httpx.URL(value)
    except (httpx.InvalidURL, TypeError, ValueError) as error:
        raise InvalidCallbackConfiguration("Callback URL is invalid.") from error
    if (
        url.scheme != "http"
        or not url.host
        or url.username
        or url.password
        or url.path != CALLBACK_PATH
        or url.query
        or url.fragment
    ):
        raise InvalidCallbackConfiguration("Callback URL must target the approved internal route.")
    return str(url)


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise InvalidCallbackConfiguration(f"{name} must be an aware UTC datetime.")
    return value.astimezone(timezone.utc)


class SimulatorCallbackClient:
    """Posts one frozen receipt and shares one retry owner among concurrent callers."""

    def __init__(
        self,
        *,
        callback_url: str,
        callback_token: SecretStr,
        policy: CallbackRetryPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not isinstance(callback_token, SecretStr) or not callback_token.get_secret_value():
            raise InvalidCallbackConfiguration("Simulator callback token is required.")
        if len(callback_token.get_secret_value().encode("utf-8")) < 32:
            raise InvalidCallbackConfiguration("Simulator callback token must contain 32 bytes.")
        if not isinstance(policy, CallbackRetryPolicy):
            raise InvalidCallbackConfiguration("A callback retry policy is required.")
        self._callback_url = _validate_callback_url(callback_url)
        self._callback_token = callback_token
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(
                policy.total_timeout_seconds,
                connect=policy.connect_timeout_seconds,
            ),
        )
        self._guard = asyncio.Lock()
        self._in_flight: dict[str, _InFlightDelivery] = {}
        self._closed = False

    async def deliver(
        self,
        receipt: FrozenCallbackReceipt,
        *,
        hard_deadline_at: datetime,
    ) -> CallbackAccepted:
        """Deliver/replay exact receipt bytes only while the supplied deadline allows."""
        if self._closed:
            raise InvalidCallbackConfiguration("Callback client is closed.")
        if not isinstance(receipt, FrozenCallbackReceipt):
            raise InvalidFrozenReceipt("deliver requires a FrozenCallbackReceipt.")
        if len(receipt.raw_envelope) > self._policy.max_request_bytes:
            raise InvalidFrozenReceipt("Receipt exceeds the injected request-size limit.")
        deadline = _utc(hard_deadline_at, "hard_deadline_at")
        now = _utc(self._clock(), "clock value")
        deadline_mono = self._monotonic() + max(0.0, (deadline - now).total_seconds())

        async with self._guard:
            if self._closed:
                raise InvalidCallbackConfiguration("Callback client is closed.")
            current = self._in_flight.get(receipt.result_id)
            if current is not None:
                if current.raw_envelope != receipt.raw_envelope or current.deadline != deadline:
                    raise InvalidFrozenReceipt(
                        "Concurrent delivery reused a result_id with different receipt context."
                    )
                task = current.task
            else:
                task = asyncio.create_task(self._deliver_owned(receipt, deadline, deadline_mono))
                self._in_flight[receipt.result_id] = _InFlightDelivery(
                    receipt.raw_envelope, deadline, task
                )
                task.add_done_callback(
                    lambda completed, result_id=receipt.result_id: self._discard_finished(
                        result_id, completed
                    )
                )
        return await asyncio.shield(task)

    async def aclose(self) -> None:
        """Stop new work and cancel in-flight transport; cancellation is never success."""
        async with self._guard:
            if self._closed:
                return
            self._closed = True
            tasks = [entry.task for entry in self._in_flight.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._client.aclose()

    def _discard_finished(self, result_id: str, task: asyncio.Task[CallbackAccepted]) -> None:
        current = self._in_flight.get(result_id)
        if current is not None and current.task is task:
            self._in_flight.pop(result_id, None)

    async def _deliver_owned(
        self,
        receipt: FrozenCallbackReceipt,
        deadline: datetime,
        deadline_mono: float,
    ) -> CallbackAccepted:
        attempts = 0
        transient_failures = 0
        last_failure: str | None = None
        delivery_uncertain = False
        headers = {
            "Authorization": f"Bearer {self._callback_token.get_secret_value()}",
            "Content-Type": "application/json",
        }

        while True:
            now = _utc(self._clock(), "clock value")
            if now >= deadline or self._monotonic() >= deadline_mono:
                raise CallbackDeadlineExceeded(
                    attempts=attempts,
                    last_failure=last_failure,
                    delivery_uncertain=delivery_uncertain,
                )
            if self._policy.max_attempts is not None and attempts >= self._policy.max_attempts:
                raise CallbackRetryExhausted(
                    attempts=attempts,
                    last_failure=last_failure or "attempt_budget",
                    delivery_uncertain=delivery_uncertain,
                )

            attempts += 1
            try:
                async with asyncio.timeout(self._policy.total_timeout_seconds):
                    async with self._client.stream(
                        "POST",
                        self._callback_url,
                        headers=headers,
                        content=receipt.raw_envelope,
                        timeout=httpx.Timeout(
                            self._policy.total_timeout_seconds,
                            connect=self._policy.connect_timeout_seconds,
                        ),
                    ) as response:
                        status = response.status_code
                        response_content_type = response.headers.get("content-type", "")
                        response_body = await self._read_bounded(response) if status == 202 else b""
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, TimeoutError):
                last_failure = "timeout"
                delivery_uncertain = True
                transient_failures += 1
                delay = self._policy.transient_delay(transient_failures)
            except httpx.RequestError:
                last_failure = "connection_failure"
                delivery_uncertain = True
                transient_failures += 1
                delay = self._policy.transient_delay(transient_failures)
            else:
                if status == 202:
                    return self._validate_ack(
                        receipt, response_content_type, response_body, attempts
                    )
                if status in (401, 403):
                    last_failure = f"http_{status}"
                    delivery_uncertain = False
                    delay = self._policy.auth_retry_seconds
                elif status in (408, 429) or 500 <= status <= 599:
                    last_failure = f"http_{status}"
                    delivery_uncertain = True
                    transient_failures += 1
                    delay = self._policy.transient_delay(transient_failures)
                elif status == 409:
                    raise CallbackConflict(status)
                elif status in (400, 404, 422):
                    raise CallbackRejected(status)
                else:
                    raise CallbackProtocolError(
                        f"Unexpected callback HTTP status {status}; acceptance was not confirmed."
                    )

            if self._policy.max_attempts is not None and attempts >= self._policy.max_attempts:
                raise CallbackRetryExhausted(
                    attempts=attempts,
                    last_failure=last_failure,
                    delivery_uncertain=delivery_uncertain,
                )
            retry_at = _utc(self._clock(), "clock value") + timedelta(seconds=delay)
            retry_mono = self._monotonic() + delay
            if retry_at >= deadline or retry_mono >= deadline_mono:
                raise CallbackDeadlineExceeded(
                    attempts=attempts,
                    last_failure=last_failure,
                    delivery_uncertain=delivery_uncertain,
                )
            await self._sleep(delay)

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._policy.max_response_bytes:
                raise CallbackResponseTooLarge("Callback response exceeded its configured bound.")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_ack(
        receipt: FrozenCallbackReceipt,
        content_type: str,
        body: bytes,
        attempts: int,
    ) -> CallbackAccepted:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise CallbackProtocolError("HTTP 202 did not contain the approved JSON acknowledgement.")
        try:
            acknowledgement = json.loads(
                body.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
            raise CallbackProtocolError("HTTP 202 acknowledgement is malformed.") from error
        if (
            not isinstance(acknowledgement, dict)
            or set(acknowledgement) != {"receipt_status", "result_id"}
            or acknowledgement.get("receipt_status") not in _RECEIPT_STATUSES
            or acknowledgement.get("result_id") != receipt.result_id
        ):
            raise CallbackProtocolError("HTTP 202 acknowledgement does not match this receipt.")
        return CallbackAccepted(
            result_id=receipt.result_id,
            receipt_status=acknowledgement["receipt_status"],
            attempts=attempts,
        )
