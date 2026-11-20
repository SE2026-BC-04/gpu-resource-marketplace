"""Callback sender tests against HTTPX's fake transport, never a live Backend."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Awaitable, Callable

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from gpu_marketplace_simulator.callback_client import (
    CALLBACK_PATH,
    CallbackAccepted,
    CallbackClientError,
    CallbackConflict,
    CallbackDeadlineExceeded,
    CallbackProtocolError,
    CallbackRejected,
    CallbackResponseTooLarge,
    CallbackRetryExhausted,
    CallbackRetryPolicy,
    FrozenCallbackReceipt,
    InvalidCallbackConfiguration,
    InvalidFrozenReceipt,
    SimulatorCallbackClient,
)
from gpu_marketplace_simulator.config import Settings


RESULT_ID = "77777777-7777-4777-8777-777777777777"
CALLBACK_TOKEN = "callback-direction-test-token-0123456789"
MANAGER_TOKEN = "manager-direction-test-token-0123456789"
START = datetime(2026, 11, 1, tzinfo=timezone.utc)


def envelope_bytes(*, result_id: str = RESULT_ID, whitespace: bool = False) -> bytes:
    body = {
        "payload": {
            "schema_version": "1",
            "result_id": result_id,
            "job_id": "33333333-3333-4333-8333-333333333333",
            "attempt_id": "44444444-4444-4444-8444-444444444444",
            "worker_id": "11111111-1111-4111-8111-111111111111",
            "listing_id": "22222222-2222-4222-8222-222222222222",
            "outcome": "SUCCESS",
            "failure_reason": None,
            "result_digest": "sha256:" + "a" * 64,
            "finished_at": "2026-11-01T00:00:59.000000Z",
            "key_id": "66666666-6666-4666-8666-666666666666",
        },
        "signature": "A" * 86,
        "signature_encoding": "base64url-no-padding",
    }
    if whitespace:
        return json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8")
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def receipt(raw: bytes | None = None, *, result_id: str = RESULT_ID) -> FrozenCallbackReceipt:
    return FrozenCallbackReceipt(result_id=result_id, raw_envelope=raw or envelope_bytes(result_id=result_id))


class FakeTime:
    def __init__(self) -> None:
        self.now = START
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.elapsed

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += timedelta(seconds=delay)
        self.elapsed += delay


def policy(**overrides: object) -> CallbackRetryPolicy:
    values: dict[str, object] = {
        "max_request_bytes": 4096,
        "max_response_bytes": 2048,
    }
    values.update(overrides)
    return CallbackRetryPolicy(**values)  # type: ignore[arg-type]


def make_client(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]
    | httpx.AsyncBaseTransport,
    *,
    fake_time: FakeTime | None = None,
    retry_policy: CallbackRetryPolicy | None = None,
    token: str = CALLBACK_TOKEN,
) -> SimulatorCallbackClient:
    time_source = fake_time or FakeTime()
    transport = handler if isinstance(handler, httpx.AsyncBaseTransport) else httpx.MockTransport(handler)
    return SimulatorCallbackClient(
        callback_url=f"http://backend.internal{CALLBACK_PATH}",
        callback_token=SecretStr(token),
        policy=retry_policy or policy(),
        transport=transport,
        clock=time_source.clock,
        monotonic=time_source.monotonic,
        sleep=time_source.sleep,
    )


def run(coroutine):
    return asyncio.run(coroutine)


def success_response(request: httpx.Request, result_id: str = RESULT_ID, status: str = "STORED"):
    return httpx.Response(
        202,
        json={"receipt_status": status, "result_id": result_id},
        request=request,
    )


def test_success_posts_exact_frozen_bytes_and_uses_callback_token_only() -> None:
    raw = envelope_bytes(whitespace=True)
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            result = await client.deliver(receipt(raw), hard_deadline_at=START + timedelta(minutes=2))
            assert result == CallbackAccepted(RESULT_ID, "STORED", 1)
        finally:
            await client.aclose()

    run(scenario())
    assert len(observed) == 1
    assert observed[0].content == raw
    assert observed[0].headers["authorization"] == f"Bearer {CALLBACK_TOKEN}"
    assert MANAGER_TOKEN not in observed[0].headers["authorization"]
    assert observed[0].headers["content-type"] == "application/json"
    assert "idempotency-key" not in observed[0].headers


@pytest.mark.parametrize("ack_status", ["STORED", "DUPLICATE"])
def test_approved_stored_or_duplicate_ack_stops_retries(ack_status: str) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return success_response(request, status=ack_status)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            result = await client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
            assert result.receipt_status == ack_status
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize("failure", ["timeout", "connect", 503, 429])
def test_transient_failure_retries_same_body_and_result_id(failure: str | int) -> None:
    raw = envelope_bytes(whitespace=True)
    seen: list[bytes] = []
    ids: list[str] = []
    fake_time = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        ids.append(json.loads(request.content)["payload"]["result_id"])
        if len(seen) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("test timeout", request=request)
            if failure == "connect":
                raise httpx.ConnectError("test connection failure", request=request)
            return httpx.Response(failure, request=request)
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler, fake_time=fake_time)
        try:
            result = await client.deliver(receipt(raw), hard_deadline_at=START + timedelta(minutes=1))
            assert result.attempts == 2
        finally:
            await client.aclose()

    run(scenario())
    assert seen == [raw, raw]
    assert ids == [RESULT_ID, RESULT_ID]
    assert fake_time.sleeps == [2.0]


def test_total_request_timeout_retries_the_same_frozen_body() -> None:
    calls = 0
    seen: list[bytes] = []
    fake_time = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        seen.append(request.content)
        if calls == 1:
            await asyncio.Event().wait()
        return success_response(request)

    async def scenario() -> None:
        client = make_client(
            handler,
            fake_time=fake_time,
            retry_policy=policy(connect_timeout_seconds=0.01, total_timeout_seconds=0.02),
        )
        try:
            result = await client.deliver(
                receipt(), hard_deadline_at=START + timedelta(minutes=1)
            )
            assert result.attempts == 2
        finally:
            await client.aclose()

    run(scenario())
    assert seen == [envelope_bytes(), envelope_bytes()]
    assert fake_time.sleeps == [2.0]


def test_retry_schedule_is_capped_and_deterministic() -> None:
    calls = 0
    fake_time = FakeTime()
    observed_bodies: list[bytes] = []
    raw = envelope_bytes(whitespace=True)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        observed_bodies.append(request.content)
        if calls <= 6:
            return httpx.Response(503, request=request)
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler, fake_time=fake_time)
        try:
            result = await client.deliver(receipt(raw), hard_deadline_at=START + timedelta(minutes=2))
            assert result.attempts == 7
        finally:
            await client.aclose()

    run(scenario())
    assert fake_time.sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert observed_bodies == [raw] * 7


def test_401_and_403_recovery_retries_at_most_once_per_30_seconds() -> None:
    calls = 0
    fake_time = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(401, request=request)
        if calls == 2:
            return httpx.Response(403, request=request)
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler, fake_time=fake_time)
        try:
            result = await client.deliver(receipt(), hard_deadline_at=START + timedelta(seconds=61))
            assert result.attempts == 3
        finally:
            await client.aclose()

    run(scenario())
    assert fake_time.sleeps == [30.0, 30.0]


def test_deadline_prevents_scheduling_a_retry_at_or_after_boundary() -> None:
    calls = 0
    fake_time = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    async def scenario() -> None:
        client = make_client(handler, fake_time=fake_time)
        try:
            with pytest.raises(CallbackDeadlineExceeded) as caught:
                await client.deliver(receipt(), hard_deadline_at=START + timedelta(seconds=2))
            assert caught.value.attempts == 1
            assert caught.value.delivery_uncertain
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1
    assert fake_time.sleeps == []


@pytest.mark.parametrize("status", [400, 404, 409, 422, 301, 302, 307, 200, 201, 204])
def test_permanent_redirect_and_unapproved_success_statuses_are_not_retried(status: int) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Location": "http://elsewhere.invalid"}, request=request)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            expected = CallbackConflict if status == 409 else CallbackRejected if status in (400, 404, 422) else CallbackProtocolError
            with pytest.raises(expected):
                await client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"not-json", "application/json"),
        (b'{"receipt_status":"STORED","result_id":"wrong"}', "application/json"),
        (b'{"receipt_status":"OTHER","result_id":"' + RESULT_ID.encode() + b'"}', "application/json"),
        (
            b'{"receipt_status":"STORED","result_id":"' + RESULT_ID.encode()
            + b'","extra":true}',
            "application/json",
        ),
        (
            b'{"receipt_status":"STORED","receipt_status":"DUPLICATE","result_id":"'
            + RESULT_ID.encode() + b'"}',
            "application/json",
        ),
        (b'{"receipt_status":"STORED","result_id":"' + RESULT_ID.encode() + b'"}', "text/plain"),
    ],
)
def test_invalid_or_contradictory_202_ack_is_not_success(
    body: bytes, content_type: str
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            202,
            content=body,
            headers={"content-type": content_type},
            request=request,
        )

    async def scenario() -> None:
        client = make_client(handler)
        try:
            with pytest.raises(CallbackProtocolError):
                await client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1


def test_oversized_ack_body_is_rejected_with_injected_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=b"x" * 40, request=request)

    async def scenario() -> None:
        client = make_client(handler, retry_policy=policy(max_response_bytes=16))
        try:
            with pytest.raises(CallbackResponseTooLarge):
                await client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
        finally:
            await client.aclose()

    run(scenario())


@pytest.mark.parametrize(
    "result_id,raw",
    [
        ("not-a-uuid", envelope_bytes()),
        (RESULT_ID, bytearray(envelope_bytes())),
        (RESULT_ID, b""),
        (RESULT_ID, b"\xff"),
        (RESULT_ID, b"{"),
        ("33333333-3333-1333-8333-333333333333", envelope_bytes()),
        (RESULT_ID, envelope_bytes(result_id="33333333-3333-4333-8333-333333333333")),
    ],
)
def test_invalid_frozen_receipt_is_rejected_before_transport(result_id: str, raw: object) -> None:
    with pytest.raises(InvalidFrozenReceipt):
        FrozenCallbackReceipt(result_id=result_id, raw_envelope=raw)  # type: ignore[arg-type]


def test_duplicate_json_property_in_receipt_is_rejected() -> None:
    raw = envelope_bytes().replace(
        b'{"payload":', b'{"payload":{},"payload":', 1
    )
    with pytest.raises(InvalidFrozenReceipt):
        FrozenCallbackReceipt(result_id=RESULT_ID, raw_envelope=raw)


def test_noncanonical_base64url_signature_is_rejected() -> None:
    raw = envelope_bytes().replace(
        b'"signature":"' + b"A" * 86,
        b'"signature":"' + b"A" * 85 + b"B",
    )
    with pytest.raises(InvalidFrozenReceipt):
        FrozenCallbackReceipt(result_id=RESULT_ID, raw_envelope=raw)


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://backend.internal" + CALLBACK_PATH,
        "http://user:password@backend.internal" + CALLBACK_PATH,
        "http://backend.internal/internal/other",
        "http://backend.internal" + CALLBACK_PATH + "?debug=1",
        "http://backend.internal" + CALLBACK_PATH + "#fragment",
    ],
)
def test_unsupported_callback_url_fails_closed(url: str) -> None:
    with pytest.raises(InvalidCallbackConfiguration):
        SimulatorCallbackClient(
            callback_url=url,
            callback_token=SecretStr(CALLBACK_TOKEN),
            policy=policy(),
            transport=httpx.MockTransport(lambda request: httpx.Response(202, request=request)),
        )


def test_config_reads_callback_direction_credentials_and_rejects_short_secret() -> None:
    configured = Settings(
        callback_url=f"http://backend.internal{CALLBACK_PATH}",
        callback_token=SecretStr(CALLBACK_TOKEN),
    )
    assert configured.callback_url == f"http://backend.internal{CALLBACK_PATH}"
    assert configured.callback_token is not None
    with pytest.raises(ValidationError):
        Settings(callback_token=SecretStr("short"))


def test_concurrent_calls_for_same_receipt_share_one_delivery_owner() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            deadline = START + timedelta(minutes=1)
            first = asyncio.create_task(client.deliver(receipt(), hard_deadline_at=deadline))
            await started.wait()
            second = asyncio.create_task(client.deliver(receipt(), hard_deadline_at=deadline))
            release.set()
            results = await asyncio.gather(first, second)
            assert results[0] == results[1]
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1


def test_different_receipts_can_be_delivered_concurrently() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        result_id = json.loads(request.content)["payload"]["result_id"]
        started.add(result_id)
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return success_response(request, result_id)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            deadline = START + timedelta(minutes=1)
            first = asyncio.create_task(client.deliver(receipt(), hard_deadline_at=deadline))
            second_id = "88888888-8888-4888-8888-888888888888"
            second = asyncio.create_task(
                client.deliver(receipt(result_id=second_id), hard_deadline_at=deadline)
            )
            await both_started.wait()
            release.set()
            results = await asyncio.gather(first, second)
            assert {result.result_id for result in results} == {RESULT_ID, second_id}
        finally:
            await client.aclose()

    run(scenario())
    assert len(started) == 2


def test_same_active_result_id_with_changed_bytes_is_rejected_locally() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler)
        try:
            deadline = START + timedelta(minutes=1)
            first = asyncio.create_task(client.deliver(receipt(), hard_deadline_at=deadline))
            await started.wait()
            with pytest.raises(InvalidFrozenReceipt):
                await client.deliver(
                    receipt(envelope_bytes(whitespace=True)), hard_deadline_at=deadline
                )
            release.set()
            await first
        finally:
            await client.aclose()

    run(scenario())
    assert calls == 1


def test_shutdown_cancels_uncertain_request_without_reporting_success() -> None:
    started = asyncio.Event()
    never = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await never.wait()
        return success_response(request)

    async def scenario() -> None:
        client = make_client(handler)
        delivery = asyncio.create_task(
            client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
        )
        await started.wait()
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await delivery

    run(scenario())


def test_injected_attempt_budget_exhaustion_is_typed_and_uncertain() -> None:
    fake_time = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    async def scenario() -> None:
        client = make_client(handler, fake_time=fake_time, retry_policy=policy(max_attempts=2))
        try:
            with pytest.raises(CallbackRetryExhausted) as caught:
                await client.deliver(receipt(), hard_deadline_at=START + timedelta(minutes=1))
            assert caught.value.attempts == 2
            assert caught.value.delivery_uncertain
        finally:
            await client.aclose()

    run(scenario())
    assert fake_time.sleeps == [2.0]


def test_retry_policy_rejects_mutable_or_invalid_bounds() -> None:
    with pytest.raises(InvalidCallbackConfiguration):
        policy(backoff_seconds=[1.0, 2.0])
    with pytest.raises(InvalidCallbackConfiguration):
        policy(max_request_bytes=0)
    with pytest.raises(InvalidCallbackConfiguration):
        policy(connect_timeout_seconds=6.0, total_timeout_seconds=5.0)


def test_client_does_not_use_network_until_deliver_is_called() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"receipt_status": "STORED", "result_id": RESULT_ID}, request=request)

    client = make_client(handler)
    assert requests == []
    run(client.aclose())
    assert requests == []
