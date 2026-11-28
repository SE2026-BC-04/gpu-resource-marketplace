"""Stage A test-only composition of the real Simulator-local components."""
from __future__ import annotations

import asyncio
import base64
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from threading import Event, Lock, Thread
from typing import Iterator
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gpu_marketplace_simulator.attempt_cache import AttemptState, Receipt
from gpu_marketplace_simulator.attempt_cache_adapter import AttemptAdmissionUnavailable
from gpu_marketplace_simulator.callback_client import CallbackAccepted, CallbackRetryPolicy
from gpu_marketplace_simulator.deterministic import (
    SimulationInput,
    _derive_seed_value,
    simulate,
)
from gpu_marketplace_simulator.dispatch import DispatchRequest
from gpu_marketplace_simulator.runtime_composition import TestOnlyRuntimeComposition
from gpu_marketplace_simulator.signed_v1 import envelope_from_json


DISPATCH_TOKEN = base64.urlsafe_b64encode(b"D" * 32).decode().rstrip("=")
CALLBACK_TOKEN = base64.urlsafe_b64encode(b"C" * 32).decode().rstrip("=")
KEY_ID = UUID("66666666-6666-4666-8666-666666666666")
JOB_ID = "33333333-3333-4333-8333-333333333333"
ATTEMPT_ID = "44444444-4444-4444-8444-444444444444"
WORKER_ID = "11111111-1111-4111-8111-111111111111"
LISTING_ID = "22222222-2222-4222-8222-222222222222"
OUTBOX_ID = "55555555-5555-4555-8555-555555555555"
START = datetime(2030, 1, 1, tzinfo=timezone.utc)


class FixedSigner:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key
        self.calls: list[tuple[str, str, bytes]] = []
        self.fail = False

    def sign(self, *, worker_id: str, key_id: str, message: bytes) -> bytes:
        self.calls.append((worker_id, key_id, message))
        if self.fail:
            raise RuntimeError("synthetic signer failure detail")
        return self.private_key.sign(message)


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 100.0
        self.lock = Lock()

    def __call__(self) -> float:
        with self.lock:
            return self.value

    def advance(self, amount: float) -> None:
        with self.lock:
            self.value += amount


class LocalASGIClient:
    """Synchronous test facade over one persistent asyncio ASGI event loop."""

    def __init__(self, app: FastAPI, runtime: TestOnlyRuntimeComposition) -> None:
        self.app = app
        self.runtime = runtime
        self.runner = asyncio.Runner()
        self.lifespan = app.router.lifespan_context(app)
        self.client: httpx.AsyncClient | None = None
        self.shutdown_task: asyncio.Task[object] | None = None

    def __enter__(self) -> LocalASGIClient:
        self.runner.__enter__()
        self.runner.run(self.lifespan.__aenter__())
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://simulator.test",
        )
        return self

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        assert self.client is not None
        return self.runner.run(self.client.post(path, **kwargs))

    def get(self, path: str) -> httpx.Response:
        assert self.client is not None
        return self.runner.run(self.client.get(path))

    def wait_for_attempt(self, attempt_id: str, timeout: float = 5.0) -> bool:
        return self.runner.run(asyncio.to_thread(self.runtime.wait_for_attempt, attempt_id, timeout))

    def post_many(self, bodies: list[dict[str, object]]) -> list[httpx.Response]:
        assert self.client is not None

        async def send_all() -> list[httpx.Response]:
            return list(await asyncio.gather(*(
                self.client.post(
                    "/internal/v1/executions",
                    headers={"Authorization": f"Bearer {DISPATCH_TOKEN}"},
                    json=body,
                )
                for body in bodies
            )))

        return self.runner.run(send_all())

    def begin_shutdown(self) -> None:
        async def begin() -> None:
            if self.client is not None:
                await self.client.aclose()
            self.shutdown_task = asyncio.create_task(self.lifespan.__aexit__(None, None, None))
            await self.runtime.wait_for_shutdown_start()

        self.runner.run(begin())

    def finish_shutdown(self) -> None:
        if self.shutdown_task is not None:
            async def await_shutdown() -> None:
                await self.shutdown_task

            self.runner.run(await_shutdown())

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.shutdown_task is None:
            assert self.client is not None
            self.runner.run(self.client.aclose())
            self.runner.run(self.lifespan.__aexit__(exc_type, exc, tb))
        else:
            self.finish_shutdown()
        self.runner.__exit__(exc_type, exc, tb)


class ThreadedASGIClient:
    """ASGI test client whose loop keeps running while barriers are held."""

    def __init__(self, app: FastAPI, runtime: TestOnlyRuntimeComposition) -> None:
        self.app = app
        self.runtime = runtime
        self.loop = asyncio.new_event_loop()
        self.ready = Event()
        self.thread = Thread(target=self._run_loop, name="stage-a-test-loop", daemon=True)
        self.client: httpx.AsyncClient | None = None
        self.lifespan = app.router.lifespan_context(app)
        self.shutdown_future = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()

    def __enter__(self) -> ThreadedASGIClient:
        self.thread.start()
        assert self.ready.wait(2)

        async def startup() -> None:
            await self.lifespan.__aenter__()
            self.client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://simulator.test",
            )

        asyncio.run_coroutine_threadsafe(startup(), self.loop).result(timeout=2)
        return self

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        assert self.client is not None
        return asyncio.run_coroutine_threadsafe(
            self.client.post(path, **kwargs), self.loop
        ).result(timeout=3)

    def wait_for_attempt(self, attempt_id: str, timeout: float = 5.0) -> bool:
        return self.runtime.wait_for_attempt(attempt_id, timeout)

    def begin_shutdown(self, *, close_client: bool = True) -> None:
        async def begin() -> None:
            if close_client and self.client is not None:
                await self.client.aclose()
            self.shutdown_future = asyncio.create_task(
                self.lifespan.__aexit__(None, None, None)
            )
            await self.runtime.wait_for_shutdown_start()

        asyncio.run_coroutine_threadsafe(begin(), self.loop).result(timeout=2)

    def post_async(self, path: str, **kwargs: object):
        assert self.client is not None
        return asyncio.run_coroutine_threadsafe(self.client.post(path, **kwargs), self.loop)

    def wait_shutdown(self, timeout: float = 2) -> None:
        assert self.shutdown_future is not None
        asyncio.run_coroutine_threadsafe(
            _await_task(self.shutdown_future), self.loop
        ).result(timeout=timeout)

    def __exit__(self, exc_type, exc, tb) -> None:
        async def shutdown() -> None:
            if self.client is not None:
                await self.client.aclose()
            if self.shutdown_future is None:
                await self.lifespan.__aexit__(exc_type, exc, tb)
            else:
                await self.shutdown_future

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=4)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        self.loop.close()


async def _await_task(task: asyncio.Task[object]) -> None:
    await task


class HeldCallbackStream(httpx.AsyncByteStream):
    def __init__(
        self,
        entered: Event,
        release: asyncio.Event,
        *,
        cancellation_seen: Event | None = None,
        resist_cancellation: bool = False,
    ) -> None:
        self.entered = entered
        self.release = release
        self.cancellation_seen = cancellation_seen
        self.resist_cancellation = resist_cancellation

    async def __aiter__(self):
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if self.cancellation_seen is not None:
                self.cancellation_seen.set()
            if self.resist_cancellation:
                await self.release.wait()
            raise
        yield b'{"receipt_status":"STORED","result_id":"77777777-7777-4777-8777-777777777777"}'


def valid_dispatch(attempt_id: str = ATTEMPT_ID) -> dict[str, object]:
    due = START + timedelta(minutes=1)
    hard = due + timedelta(seconds=120)
    return {
        "outbox_event_id": OUTBOX_ID,
        "job_id": JOB_ID,
        "attempt_id": attempt_id,
        "worker_id": WORKER_ID,
        "listing_id": LISTING_ID,
        "gpu_count": 2,
        "duration_seconds": 60,
        "simulation_input": {"workload_profile": "demo-v1"},
        "finish_due_at": due.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "hard_deadline_at": hard.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }


def retry_policy(**updates: object) -> CallbackRetryPolicy:
    config: dict[str, object] = {
        "max_request_bytes": 16_384,
        "max_response_bytes": 1024,
        "connect_timeout_seconds": 0.05,
        "total_timeout_seconds": 0.1,
        "backoff_seconds": (0.001,),
        "auth_retry_seconds": 0.001,
        "max_attempts": 3,
    }
    config.update(updates)
    return CallbackRetryPolicy(**config)  # type: ignore[arg-type]


@contextmanager
def runtime_context(
    *,
    callback_handler=None,
    before_produce=None,
    signer: FixedSigner | None = None,
    cache_clock: FakeMonotonic | None = None,
    cache_max_entries: int = 16,
    cache_ttl_seconds: float = 30,
    producer_concurrency_limit: int = 8,
    worker_count: int = 2,
    max_in_flight: int = 8,
    callback_policy: CallbackRetryPolicy | None = None,
    before_callback_schedule=None,
    clock: datetime = START,
    result_ids: tuple[str, ...] | None = None,
    threaded_client: bool = False,
    bind_execution_future=None,
    on_worker_waiting_gate=None,
    on_bind_failure=None,
) -> Iterator[tuple[TestOnlyRuntimeComposition, LocalASGIClient, list[httpx.Request], FixedSigner]]:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signer = signer or FixedSigner(private_key)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    requests: list[httpx.Request] = []
    next_result = iter(result_ids or ("77777777-7777-4777-8777-777777777777",))

    def callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if callback_handler is not None:
            return callback_handler(request)
        result_id = json.loads(request.content)["payload"]["result_id"]
        return httpx.Response(
            202,
            json={"receipt_status": "STORED", "result_id": result_id},
            request=request,
        )

    composition = TestOnlyRuntimeComposition(
        dispatch_token=DISPATCH_TOKEN,
        callback_token=CALLBACK_TOKEN,
        signer=signer,
        test_public_key=public_key,
        key_id=KEY_ID,
        callback_transport=httpx.MockTransport(callback),
        callback_policy=callback_policy or retry_policy(),
        clock=lambda: clock,
        result_id_factory=lambda: UUID(next(next_result)),
        before_produce=before_produce,
        before_callback_schedule=before_callback_schedule,
        bind_execution_future=bind_execution_future,
        on_worker_waiting_gate=on_worker_waiting_gate,
        on_bind_failure=on_bind_failure,
        cache_clock=cache_clock,
        cache_max_entries=cache_max_entries,
        cache_ttl_seconds=cache_ttl_seconds,
        producer_concurrency_limit=producer_concurrency_limit,
        worker_count=worker_count,
        max_in_flight=max_in_flight,
        shutdown_timeout_seconds=0.2,
    )
    client_type = ThreadedASGIClient if threaded_client else LocalASGIClient
    with client_type(composition.create_app(), composition) as client:
        yield composition, client, requests, signer


def post(client: LocalASGIClient, body: dict[str, object] | None = None, *, token: str = DISPATCH_TOKEN):
    return client.post(
        "/internal/v1/executions",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_dispatch() if body is None else body,
    )


def test_01_authenticated_dispatch_creates_and_callbacks_frozen_receipt_before_ack() -> None:
    entered, release = Event(), Event()

    def hold_producer(_dispatch) -> None:
        entered.set()
        assert release.wait(2)

    with runtime_context(before_produce=hold_producer) as (runtime, client, requests, signer):
        response = post(client)
        assert response.status_code == 202
        assert runtime.registration_count == 1
        assert entered.wait(1)
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.IN_FLIGHT
        release.set()
        assert client.wait_for_attempt(ATTEMPT_ID)
        entry = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert entry.state is AttemptState.FINISHED
        assert entry.receipt is not None
        assert len(requests) == 1
        assert requests[0].content == entry.receipt.raw_envelope
        parsed = envelope_from_json(entry.receipt.raw_envelope)
        signer.private_key.public_key().verify(
            base64.urlsafe_b64decode(parsed.envelope.signature + "=="),
            signer.calls[0][2],
        )


def test_02_identical_retained_duplicate_reuses_one_producer_and_receipt() -> None:
    entered, release = Event(), Event()

    def hold_producer(_dispatch) -> None:
        entered.set()
        assert release.wait(2)

    with runtime_context(before_produce=hold_producer) as (runtime, client, requests, _):
        assert post(client).status_code == 202
        assert entered.wait(1)
        # Identical duplicate while the same Attempt is still IN_FLIGHT.
        assert post(client).status_code == 202
        assert runtime.registration_count == 1
        release.set()
        assert client.wait_for_attempt(ATTEMPT_ID)
        first = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt
        second = post(client)
        retained = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt
        assert second.status_code == 202
        assert runtime.registration_count == 1
        assert len(requests) == 1
        assert retained == first
        assert post(client).status_code == 202
        assert runtime.registration_count == 1


def test_03_altered_retained_duplicate_is_409_without_mutation() -> None:
    with runtime_context() as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        before = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        altered = valid_dispatch()
        altered["duration_seconds"] = 61
        response = post(client, altered)
        after = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert response.status_code == 409
        assert after == before
        assert runtime.registration_count == 1


def test_04_bounded_admission_rejects_without_202_or_inflight_eviction() -> None:
    entered, release = Event(), Event()

    def block_first(_dispatch) -> None:
        entered.set()
        assert release.wait(2)

    with runtime_context(
        before_produce=block_first, producer_concurrency_limit=1, worker_count=1,
        max_in_flight=1, cache_max_entries=1,
    ) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert entered.wait(1)
        other = valid_dispatch("88888888-8888-4888-8888-888888888888")
        rejected = post(client, other)
        assert rejected.status_code == 503
        assert runtime.registration_count == 1
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.IN_FLIGHT
        assert client.app.state.attempt_cache.snapshot(UUID(other["attempt_id"])) is None
        release.set()


def test_05_deterministic_v1_to_v4_vectors_and_nonvector_are_stable() -> None:
    cases = (
        ("33333333-3333-4333-8333-333333333333", 60, 3035342533442321017,
         "sha256:a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c"),
        ("33333333-3333-4333-8333-333333333333", 2, 8887054454783268118,
         "sha256:9baaaaa338423c75753ecbd00da615a1f88a006eeb0a512d432635664754b7bf"),
        ("33333333-3333-4333-8333-333333333333", 1, 2063102514678027846,
         "sha256:f1c9d8e371bd4e6876a73b2414c285c6362fe01bca4d8d432169f4d484b3d749"),
        ("33333333-3333-4333-8333-000000000c02", 60, 2240287873181493078,
         "sha256:ad2212d44fef948b303afb1e5d5d8e9435eeab64f6701c54cafc3c6f3fd77aa7"),
    )
    for job_id, duration, seed, digest in cases:
        data = SimulationInput(UUID(job_id), UUID(LISTING_ID), UUID(WORKER_ID), 2, duration)
        assert _derive_seed_value(data) == seed
        assert simulate(data).result_digest == digest
    sample = SimulationInput(UUID(JOB_ID), UUID(LISTING_ID), UUID(WORKER_ID), 3, 17)
    assert simulate(sample) == simulate(sample)


def test_06_malformed_signed_payload_json_and_duplicate_members_fail_closed() -> None:
    with runtime_context() as (runtime, client, _, signer):
        headers = {
            "Authorization": f"Bearer {DISPATCH_TOKEN}",
            "Content-Type": "application/json",
        }
        malformed = client.post(
            "/internal/v1/executions", headers=headers, content=b"{"
        )
        duplicate = client.post(
            "/internal/v1/executions",
            headers=headers,
            content=(
                b'{"outbox_event_id":"' + OUTBOX_ID.encode()
                + b'","outbox_event_id":"' + OUTBOX_ID.encode() + b'"}'
            ),
        )
        assert malformed.status_code == duplicate.status_code == 422
        assert runtime.registration_count == 0
        # The canonical parser rejects an invalid signed payload before signer use.
        from gpu_marketplace_simulator.signed_v1 import (
            PayloadValidationError,
            SignedResultV1Payload,
            sign_payload,
        )
        valid = {
            "schema_version": "1", "result_id": RESULT_ID, "job_id": JOB_ID,
            "attempt_id": ATTEMPT_ID, "worker_id": WORKER_ID,
            "listing_id": LISTING_ID, "outcome": "SUCCESS", "failure_reason": None,
            "result_digest": "sha256:" + "a" * 64,
            "finished_at": START.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "key_id": str(KEY_ID),
        }
        forged = SignedResultV1Payload.model_construct(**{**valid, "outcome": "INVALID"})
        before = len(signer.calls)
        with pytest.raises(PayloadValidationError):
            sign_payload(forged, signer)
        assert len(signer.calls) == before
        # A raw duplicate-key Signed Result envelope is rejected at the
        # callback boundary without replacing or forwarding its bytes.
        from gpu_marketplace_simulator.callback_client import FrozenCallbackReceipt, InvalidFrozenReceipt
        with pytest.raises(InvalidFrozenReceipt):
            FrozenCallbackReceipt(RESULT_ID, b'{"payload":{},"payload":{},"signature":"x","signature_encoding":"base64url-no-padding"}')


RESULT_ID = "77777777-7777-4777-8777-777777777777"


def test_07_injected_signer_failure_is_tombstoned_after_actual_future_terminates() -> None:
    signer = FixedSigner(Ed25519PrivateKey.from_private_bytes(bytes(range(32))))
    signer.fail = True
    with runtime_context(signer=signer) as (runtime, client, requests, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.FAILED_NO_RECEIPT
        assert requests == []
        assert post(client).status_code == 503
        assert runtime.registration_count == 1


def test_08_post_202_producer_exception_and_queued_cancellation_use_real_future_evidence() -> None:
    started, release = Event(), Event()

    def block_first(dispatch) -> None:
        if dispatch.attempt_id == ATTEMPT_ID:
            started.set()
            assert release.wait(2)
        else:
            raise RuntimeError("synthetic producer failure")

    with runtime_context(before_produce=block_first, worker_count=1, max_in_flight=4) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert started.wait(1)
        second_id = "88888888-8888-4888-8888-888888888888"
        assert post(client, valid_dispatch(second_id)).status_code == 202
        queued_id = "99999999-9999-4999-8999-999999999999"
        assert post(client, valid_dispatch(queued_id)).status_code == 202
        queued_future = runtime.execution_futures[queued_id]
        assert queued_future.cancel()
        release.set()
        assert client.wait_for_attempt(ATTEMPT_ID)
        assert client.wait_for_attempt(second_id)
        assert client.wait_for_attempt(queued_id)
        assert client.app.state.attempt_cache.snapshot(UUID(second_id)).state is AttemptState.FAILED_NO_RECEIPT
        assert client.app.state.attempt_cache.snapshot(UUID(queued_id)).state is AttemptState.FAILED_NO_RECEIPT


def test_09_all_five_receipt_identity_mismatches_are_rejected() -> None:
    from gpu_marketplace_simulator.signed_v1 import SignedResultV1Payload, sign_payload
    from rfc8785 import dumps

    entered, release = Event(), Event()

    def hold(_dispatch) -> None:
        entered.set()
        assert release.wait(2)

    with runtime_context(before_produce=hold) as (runtime, client, _, signer):
        assert post(client).status_code == 202
        assert entered.wait(1)
        lifecycle = runtime.lifecycle_for(ATTEMPT_ID)
        admission = runtime.admission_for(ATTEMPT_ID)
        variants = (
            {"result_id": "88888888-8888-4888-8888-888888888888"},
            {"attempt_id": "88888888-8888-4888-8888-888888888888"},
            {"job_id": "88888888-8888-4888-8888-888888888888"},
            {"worker_id": "88888888-8888-4888-8888-888888888888"},
            {"listing_id": "88888888-8888-4888-8888-888888888888"},
        )
        for overrides in variants:
            base = {
                "schema_version": "1", "result_id": RESULT_ID, "job_id": JOB_ID,
                "attempt_id": ATTEMPT_ID, "worker_id": WORKER_ID, "listing_id": LISTING_ID,
                "outcome": "SUCCESS", "failure_reason": None,
                "result_digest": "sha256:" + "a" * 64,
                "finished_at": START.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "key_id": str(KEY_ID),
            }
            base.update(overrides)
            signed = sign_payload(SignedResultV1Payload(**base), signer)
            raw = dumps(signed.envelope().model_dump(mode="json"))
            with pytest.raises(Exception):
                # Keep the outer receipt ID fixed. The result_id variant then
                # intentionally disagrees with the signed payload identity.
                lifecycle.complete(Receipt(UUID(RESULT_ID), raw))
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.IN_FLIGHT
        release.set()
        assert client.wait_for_attempt(ATTEMPT_ID)


def test_10_lost_callback_response_retries_after_fake_persistence_without_reproduction() -> None:
    persisted: list[bytes] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        persisted.append(request.content)
        if attempts == 1:
            raise httpx.ReadTimeout("response lost after fake persistence", request=request)
        result_id = json.loads(request.content)["payload"]["result_id"]
        return httpx.Response(202, json={"receipt_status": "DUPLICATE", "result_id": result_id}, request=request)

    with runtime_context(callback_handler=handler) as (runtime, client, _, signer):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        assert attempts == 2
        assert persisted[0] == persisted[1]
        assert runtime.registration_count == 1
        assert len(signer.calls) == 1
        result_id = json.loads(persisted[0])["payload"]["result_id"]
        assert runtime.callback_results[result_id].receipt_status == "DUPLICATE"


def test_11_stored_and_duplicate_ack_bind_the_result_id_only() -> None:
    with runtime_context() as (runtime, client, requests, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        envelope = json.loads(requests[0].content)
        result_id = envelope["payload"]["result_id"]
        accepted = runtime.callback_results[result_id]
        assert accepted.receipt_status == "STORED"
        assert accepted.result_id == result_id
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.FINISHED


def test_12_callback_retries_use_same_receipt_bytes_and_result_id() -> None:
    sent: list[tuple[bytes, str]] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payload = json.loads(request.content)["payload"]
        sent.append((request.content, payload["result_id"]))
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(202, json={"receipt_status": "STORED", "result_id": payload["result_id"]}, request=request)

    with runtime_context(callback_handler=handler) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        assert len(sent) == 3
        assert len({body for body, _ in sent}) == 1
        assert len({result for _, result in sent}) == 1
        assert runtime.registration_count == 1


def test_13_callback_retry_exhaustion_keeps_finished_receipt_and_no_rerun() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with runtime_context(callback_handler=handler, callback_policy=retry_policy(max_attempts=2)) as (runtime, client, requests, signer):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        assert len(requests) == 2
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.FINISHED
        assert post(client).status_code == 202
        assert runtime.registration_count == 1
        assert len(signer.calls) == 1

    with runtime_context(clock=START + timedelta(minutes=3)) as (deadline_runtime, deadline_client, deadline_requests, _):
        assert post(deadline_client).status_code == 202
        assert deadline_client.wait_for_attempt(ATTEMPT_ID)
        assert deadline_requests == []
        assert deadline_runtime.registration_count == 1
        assert deadline_client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.FINISHED


def test_14_concurrent_identical_dispatches_and_completion_race_register_once() -> None:
    with runtime_context(
        result_ids=(RESULT_ID, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    ) as (runtime, client, _, _):
        # A duplicate observed while registration is still pending may
        # correctly receive 503. First establish a confirmed retained Attempt,
        # then exercise concurrent replay and conflict behavior.
        assert post(client).status_code == 202
        statuses = [response.status_code for response in client.post_many(
            [valid_dispatch() for _ in range(12)]
        )]
        assert statuses == [202] * 12
        assert runtime.registration_count == 1
        assert client.wait_for_attempt(ATTEMPT_ID)

        conflict_id = "88888888-8888-4888-8888-888888888888"
        accepted_body = valid_dispatch(conflict_id)
        assert post(client, accepted_body).status_code == 202
        assert client.wait_for_attempt(conflict_id)
        bodies = [valid_dispatch(conflict_id) for _ in range(12)]
        for index, body in enumerate(bodies):
            if index % 2:
                body["duration_seconds"] = 61
        mixed = [response.status_code for response in client.post_many(bodies)]
        assert mixed.count(202) == 6
        assert mixed.count(409) == 6
        assert runtime.registration_count == 2


def test_15_shutdown_drains_active_producer_without_releasing_inflight_early() -> None:
    started, release = Event(), Event()

    def block(_dispatch) -> None:
        started.set()
        assert release.wait(3)

    composition_private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signer = FixedSigner(composition_private)
    public_key = composition_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    composition = TestOnlyRuntimeComposition(
        dispatch_token=DISPATCH_TOKEN, callback_token=CALLBACK_TOKEN,
        signer=signer, test_public_key=public_key, key_id=KEY_ID,
        callback_transport=httpx.MockTransport(lambda request: httpx.Response(
            202, json={"receipt_status": "STORED", "result_id": RESULT_ID}, request=request
        )), callback_policy=retry_policy(), clock=lambda: START,
        before_produce=block, shutdown_timeout_seconds=1,
    )
    client = LocalASGIClient(composition.create_app(), composition)
    client.__enter__()
    assert post(client).status_code == 202
    assert started.wait(1)
    client.begin_shutdown()
    cache = client.app.state.attempt_cache
    assert cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.IN_FLIGHT
    release.set()
    client.__exit__(None, None, None)
    assert cache.snapshot(UUID(ATTEMPT_ID)).state is AttemptState.FINISHED
    assert composition.shutdown_drained is True
    assert composition.shutdown_cleanup_complete is True


def test_24_shutdown_timeout_cancels_callback_and_preserves_finished_receipt() -> None:
    callback_entered = Event()
    cancellation_seen = Event()
    callback_release = asyncio.Event()

    def hold_callback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"content-type": "application/json"},
            stream=HeldCallbackStream(
                callback_entered, callback_release, cancellation_seen=cancellation_seen
            ),
            request=request,
        )

    with runtime_context(
        callback_handler=hold_callback,
        callback_policy=retry_policy(total_timeout_seconds=5, max_attempts=1),
        threaded_client=True,
    ) as (
        runtime, client, requests, _
    ):
        response = post(client)
        assert response.status_code == 202
        assert callback_entered.wait(2)

        cache = client.app.state.attempt_cache
        finished = cache.snapshot(UUID(ATTEMPT_ID))
        assert finished.state is AttemptState.FINISHED
        assert finished.receipt is not None
        original_receipt = finished.receipt
        producer_future = runtime.execution_futures[ATTEMPT_ID]
        available_before_shutdown = runtime.available_execution_capacity

        client.begin_shutdown()
        client.wait_shutdown()

        try:
            producer_future.result(timeout=2)
            assert runtime.shutdown_drained is False
            assert runtime.callback_close_started is True
            assert cancellation_seen.wait(1)
            assert runtime.shutdown_cleanup_complete is True
            assert runtime._callback_client._client.is_closed is True
            assert producer_future.done()
            assert runtime.available_execution_capacity == available_before_shutdown + 1
            after_shutdown = cache.snapshot(UUID(ATTEMPT_ID))
            assert after_shutdown.state is AttemptState.FINISHED
            assert after_shutdown.receipt.result_id == original_receipt.result_id
            assert after_shutdown.receipt.raw_envelope is original_receipt.raw_envelope
            assert len(requests) == 1
            assert not isinstance(
                runtime.callback_results.get(str(original_receipt.result_id)), CallbackAccepted
            )
        finally:
            # Baseline cleanup: release the stream so pytest never leaves an
            # unresolved producer or loop task, even when the red assertion fires.
            client.loop.call_soon_threadsafe(callback_release.set)
            producer_future.result(timeout=2)
            asyncio.run_coroutine_threadsafe(runtime._callback_client.aclose(), client.loop).result(
                timeout=2
            )


def test_25_shutdown_cancels_one_owned_same_receipt_retry() -> None:
    first_attempt = Event()
    requests: list[httpx.Request] = []

    def transient_callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        first_attempt.set()
        return httpx.Response(503, request=request)

    with runtime_context(
        callback_handler=transient_callback,
        callback_policy=retry_policy(
            total_timeout_seconds=6, backoff_seconds=(5,), max_attempts=3
        ),
        threaded_client=True,
    ) as (runtime, client, _, signer):
        assert post(client).status_code == 202
        assert first_attempt.wait(2)
        cached = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert cached.state is AttemptState.FINISHED
        assert cached.receipt is not None

        # A retained duplicate reuses the same receipt and never starts another
        # producer or callback owner while the first callback is in backoff.
        assert post(client).status_code == 202
        assert runtime.registration_count == 1
        assert len(signer.calls) == 1

        producer_future = runtime.execution_futures[ATTEMPT_ID]
        client.begin_shutdown()
        client.wait_shutdown()
        producer_future.result(timeout=2)

        assert runtime.shutdown_drained is False
        assert len(requests) == 1
        assert requests[0].content is cached.receipt.raw_envelope
        assert runtime.callback_results.get(str(cached.receipt.result_id)) is not None
        assert not isinstance(
            runtime.callback_results[str(cached.receipt.result_id)], CallbackAccepted
        )
        current = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert current.state is AttemptState.FINISHED
        assert current.receipt.result_id == cached.receipt.result_id
        assert current.receipt.raw_envelope is cached.receipt.raw_envelope


def test_26_cancellation_resistant_transport_keeps_close_owner_until_released() -> None:
    callback_entered, cancellation_seen = Event(), Event()
    callback_release = asyncio.Event()

    def resistant_callback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"content-type": "application/json"},
            stream=HeldCallbackStream(
                callback_entered,
                callback_release,
                cancellation_seen=cancellation_seen,
                resist_cancellation=True,
            ),
            request=request,
        )

    with runtime_context(
        callback_handler=resistant_callback,
        callback_policy=retry_policy(total_timeout_seconds=5, max_attempts=1),
        threaded_client=True,
    ) as (runtime, client, requests, signer):
        assert post(client).status_code == 202
        assert callback_entered.wait(2)
        cached = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert cached.state is AttemptState.FINISHED
        assert cached.receipt is not None
        producer_future = runtime.execution_futures[ATTEMPT_ID]

        client.begin_shutdown()
        client.wait_shutdown()
        try:
            producer_future.result(timeout=2)
            assert cancellation_seen.wait(1)
            assert runtime.shutdown_drained is False
            assert runtime.shutdown_cleanup_complete is False
            assert runtime.callback_close_started is True
            assert runtime._callback_client._client.is_closed is False
            assert runtime.active_execution_count == 0
            assert runtime.available_execution_capacity == 8
            assert len(requests) == 1
            assert len(signer.calls) == 1
            assert not isinstance(
                runtime.callback_results.get(str(cached.receipt.result_id)), CallbackAccepted
            )
            current = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
            assert current.state is AttemptState.FINISHED
            assert current.receipt.raw_envelope is cached.receipt.raw_envelope
        finally:
            client.loop.call_soon_threadsafe(callback_release.set)

        async def finish_cleanup() -> None:
            assert runtime._callback_close_task is not None
            await asyncio.wait_for(asyncio.shield(runtime._callback_close_task), timeout=2)

        asyncio.run_coroutine_threadsafe(finish_cleanup(), client.loop).result(timeout=3)
        assert runtime.shutdown_cleanup_complete is True
        assert runtime._callback_client._client.is_closed is True

        async def remaining_deliveries() -> int:
            return len(runtime._callback_client._in_flight)

        assert asyncio.run_coroutine_threadsafe(remaining_deliveries(), client.loop).result() == 0
        for worker in tuple(runtime._executor._threads):
            worker.join(timeout=2)
            assert not worker.is_alive()


def test_27_shutdown_cancels_queued_future_but_retains_running_capacity() -> None:
    running_started, release_running = Event(), Event()
    second_attempt_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    def block_first(dispatch: DispatchRequest) -> None:
        if dispatch.attempt_id == ATTEMPT_ID:
            running_started.set()
            assert release_running.wait(3)

    with runtime_context(
        before_produce=block_first,
        worker_count=1,
        max_in_flight=2,
        threaded_client=True,
    ) as (runtime, client, requests, signer):
        assert post(client).status_code == 202
        assert running_started.wait(1)
        assert post(client, valid_dispatch(second_attempt_id)).status_code == 202
        running_future = runtime.execution_futures[ATTEMPT_ID]
        queued_future = runtime.execution_futures[second_attempt_id]
        assert not running_future.done()
        assert not queued_future.running()

        client.begin_shutdown()
        client.wait_shutdown()
        try:
            assert queued_future.cancelled()
            assert runtime.active_execution_count == 1
            assert runtime.available_execution_capacity == 1
            second_state = client.app.state.attempt_cache.snapshot(UUID(second_attempt_id))
            assert second_state.state.value == "FAILED_NO_RECEIPT"
            assert not running_future.done()
        finally:
            release_running.set()

        running_future.result(timeout=2)
        first_state = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert first_state.state is AttemptState.FINISHED
        assert runtime.active_execution_count == 0
        assert runtime.available_execution_capacity == 2
        assert runtime.registration_count == 2
        assert len(signer.calls) == 1
        assert requests == []


def test_28_callback_scheduled_after_close_is_rejected_without_unowned_task() -> None:
    before_schedule, release_schedule = Event(), Event()

    def pause_before_schedule(_dispatch: DispatchRequest) -> None:
        before_schedule.set()
        assert release_schedule.wait(3)

    with runtime_context(
        before_callback_schedule=pause_before_schedule,
        threaded_client=True,
    ) as (runtime, client, requests, signer):
        assert post(client).status_code == 202
        assert before_schedule.wait(1)
        cached = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert cached.state is AttemptState.FINISHED
        assert cached.receipt is not None
        producer_future = runtime.execution_futures[ATTEMPT_ID]

        client.begin_shutdown()
        client.wait_shutdown()
        try:
            assert runtime.callback_close_started is True
            assert not producer_future.done()
            assert runtime.available_execution_capacity == 7
        finally:
            release_schedule.set()

        producer_future.result(timeout=2)
        assert runtime.active_execution_count == 0
        assert runtime.available_execution_capacity == 8
        assert len(signer.calls) == 1
        assert requests == []
        current = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert current.state is AttemptState.FINISHED
        assert current.receipt.result_id == cached.receipt.result_id
        assert current.receipt.raw_envelope is cached.receipt.raw_envelope
        assert runtime.callback_results.get(str(cached.receipt.result_id)) is not None
        assert not isinstance(
            runtime.callback_results[str(cached.receipt.result_id)], CallbackAccepted
        )

        async def deliveries() -> int:
            return len(runtime._callback_client._in_flight)

        assert asyncio.run_coroutine_threadsafe(deliveries(), client.loop).result() == 0


def test_29_repeated_concurrent_shutdown_uses_one_cleanup_owner() -> None:
    with runtime_context(threaded_client=True) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)

        async def shutdown_twice() -> None:
            await asyncio.gather(runtime.shutdown(), runtime.shutdown())
            task = runtime._callback_close_task
            deadline = runtime._shutdown_deadline
            assert task is not None
            await asyncio.gather(runtime.shutdown(), runtime.shutdown())
            assert runtime._callback_close_task is task
            assert runtime._shutdown_deadline == deadline

        asyncio.run_coroutine_threadsafe(shutdown_twice(), client.loop).result(timeout=3)
        assert runtime.shutdown_drained is True
        assert runtime.shutdown_cleanup_complete is True
        assert runtime._callback_client._client.is_closed is True
        assert runtime.available_execution_capacity == 8


def test_30_shutdown_during_registration_rejects_without_untracked_execution() -> None:
    bind_entered, release_bind = Event(), Event()
    bound_futures: list[Future[object]] = []

    def delayed_bind(lifecycle, future) -> None:
        bound_futures.append(future)
        bind_entered.set()
        assert release_bind.wait(3)
        lifecycle.bind_execution_future(future)

    with runtime_context(
        bind_execution_future=delayed_bind,
        threaded_client=True,
    ) as (runtime, client, requests, signer):
        response_future = client.post_async(
            "/internal/v1/executions",
            headers={"Authorization": f"Bearer {DISPATCH_TOKEN}"},
            json=valid_dispatch(),
        )
        assert bind_entered.wait(1)
        producer_future = bound_futures[0]
        client.begin_shutdown(close_client=False)
        client.wait_shutdown()

        try:
            assert runtime.shutdown_drained is False
            assert runtime.active_execution_count == 1
            assert runtime.available_execution_capacity == 7
            assert runtime.registration_count == 0
        finally:
            release_bind.set()

        response = response_future.result(timeout=2)
        assert response.status_code == 503
        producer_future.result(timeout=2)
        assert runtime.active_execution_count == 0
        assert runtime.available_execution_capacity == 8
        assert runtime.registration_count == 0
        assert signer.calls == []
        assert requests == []


def test_16_d16_conflicts_only_while_fingerprint_retained_and_cold_start_is_new_cache() -> None:
    monotonic = FakeMonotonic()
    with runtime_context(cache_clock=monotonic, cache_ttl_seconds=5,
                         result_ids=(RESULT_ID, "88888888-8888-4888-8888-888888888888")) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        first_result_id = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt.result_id
        altered = valid_dispatch()
        altered["duration_seconds"] = 61
        assert post(client, altered).status_code == 409
        monotonic.advance(5)
        assert post(client, altered).status_code == 202
        assert runtime.registration_count == 2
        assert client.wait_for_attempt(ATTEMPT_ID)
        retained_result_id = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt.result_id
        assert retained_result_id != first_result_id

    # A fresh process-local cache has no historical fingerprint guarantee.
    with runtime_context(result_ids=("99999999-9999-4999-8999-999999999999",)) as (cold, cold_client, _, _):
        assert post(cold_client).status_code == 202
        assert cold_client.wait_for_attempt(ATTEMPT_ID)
        assert cold.registration_count == 1
        cold_result_id = cold_client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt.result_id
        assert cold_result_id != retained_result_id


def test_21_expired_same_attempt_old_callback_cannot_signal_new_registration() -> None:
    monotonic = FakeMonotonic()
    first_producer_entered, release_first_producer = Event(), Event()
    old_callback_entered, release_old_callback = Event(), Event()
    new_producer_entered, release_new_producer = Event(), Event()
    callback_lock, produce_lock = Lock(), Lock()
    callback_count = produce_count = 0

    def callback_handler(request: httpx.Request) -> httpx.Response:
        nonlocal callback_count
        with callback_lock:
            callback_count += 1
            current = callback_count
        if current == 1:
            old_callback_entered.set()
            assert release_old_callback.wait(3)
        result_id = json.loads(request.content)["payload"]["result_id"]
        return httpx.Response(202, json={"receipt_status": "STORED", "result_id": result_id}, request=request)

    def hold_second_producer(_dispatch) -> None:
        nonlocal produce_count
        with produce_lock:
            produce_count += 1
            current = produce_count
        if current == 1:
            first_producer_entered.set()
            assert release_first_producer.wait(3)
        elif current == 2:
            new_producer_entered.set()
            assert release_new_producer.wait(3)

    with runtime_context(
        threaded_client=True,
        callback_handler=callback_handler,
        before_produce=hold_second_producer,
        cache_clock=monotonic,
        cache_ttl_seconds=5,
        result_ids=(RESULT_ID, "88888888-8888-4888-8888-888888888888"),
    ) as (runtime, client, _, _):
        try:
            assert post(client).status_code == 202
            assert first_producer_entered.wait(2)
            release_first_producer.set()
            assert old_callback_entered.wait(2)
            first_entry = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
            assert first_entry.state is AttemptState.FINISHED
            first_result_id = first_entry.receipt.result_id
            old_future = runtime.execution_futures[ATTEMPT_ID]
            monotonic.advance(5)
            outcome = client.app.state.admission_port.admit(
                DispatchRequest.model_validate(valid_dispatch())
            )
            assert outcome.newly_admitted is True
            assert runtime.registration_count == 2
            assert new_producer_entered.wait(2)
            new_future = runtime.execution_futures[ATTEMPT_ID]
            assert new_future is not old_future
            assert runtime.wait_for_attempt(ATTEMPT_ID, timeout=0) is False

            old_done = Event()
            old_future.add_done_callback(lambda _: old_done.set())
            release_old_callback.set()
            assert old_done.wait(2)
            assert runtime.wait_for_attempt(ATTEMPT_ID, timeout=0) is False
            assert not new_future.done()

            release_new_producer.set()
            assert runtime.wait_for_attempt(ATTEMPT_ID, timeout=2)
            second_entry = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
            assert second_entry.state is AttemptState.FINISHED
            assert second_entry.receipt.result_id != first_result_id
        finally:
            release_first_producer.set()
            release_old_callback.set()
            release_new_producer.set()


def test_22_queued_future_bind_failure_cancels_before_execution_and_releases_once() -> None:
    first_started, release_first = Event(), Event()
    binder_calls = 0
    binder_lock = Lock()
    failures: list[tuple[Future[object], bool]] = []
    executed: list[str] = []

    def binder(lifecycle, future) -> None:
        nonlocal binder_calls
        with binder_lock:
            binder_calls += 1
            current = binder_calls
        if current != 2:
            lifecycle.bind_execution_future(future)
            return
        raise RuntimeError("injected bind failure")

    def before_produce(dispatch) -> None:
        executed.append(dispatch.attempt_id)
        if dispatch.attempt_id == ATTEMPT_ID:
            first_started.set()
            assert release_first.wait(3)

    with runtime_context(
        bind_execution_future=binder,
        on_bind_failure=lambda future, cancelled: failures.append((future, cancelled)),
        before_produce=before_produce,
        worker_count=1,
        max_in_flight=2,
    ) as (runtime, client, _, _):
        try:
            assert post(client).status_code == 202
            assert first_started.wait(2)
            failed_id = "88888888-8888-4888-8888-888888888888"
            assert post(client, valid_dispatch(failed_id)).status_code == 503
            assert len(failures) == 1
            failed_future, cancelled = failures[0]
            assert cancelled is True and failed_future.cancelled()
            assert runtime.active_execution_count == 1
            assert runtime.available_execution_capacity == 1
            assert failed_id not in executed
            assert runtime.registration_count == 1

            third_id = "99999999-9999-4999-8999-999999999999"
            assert post(client, valid_dispatch(third_id)).status_code == 202
            release_first.set()
            assert client.wait_for_attempt(ATTEMPT_ID)
            assert client.wait_for_attempt(third_id)
            assert runtime.active_execution_count == 0
            assert runtime.available_execution_capacity == 2
        finally:
            release_first.set()


def test_23_running_future_bind_failure_keeps_capacity_until_gated_worker_terminates() -> None:
    worker_waiting, terminated = Event(), Event()
    observed: list[tuple[bool, int, int, bool]] = []
    executed: list[str] = []
    runtime_holder: dict[str, TestOnlyRuntimeComposition] = {}
    client_holder: dict[str, ThreadedASGIClient] = {}

    def binder(_lifecycle, _future) -> None:
        assert worker_waiting.wait(2)
        raise RuntimeError("injected running Future bind failure")

    def on_bind_failure(future, cancelled) -> None:
        runtime = runtime_holder["runtime"]
        observed.append((cancelled, runtime.active_execution_count,
                         runtime.available_execution_capacity, future.done()))
        future.add_done_callback(lambda _: terminated.set())
        client = client_holder["client"]
        with pytest.raises(AttemptAdmissionUnavailable):
            client.app.state.admission_port.admit(DispatchRequest.model_validate(
                valid_dispatch("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            ))

    with runtime_context(
        threaded_client=True,
        bind_execution_future=binder,
        on_worker_waiting_gate=lambda _dispatch: worker_waiting.set(),
        on_bind_failure=on_bind_failure,
        before_produce=lambda dispatch: executed.append(dispatch.attempt_id),
        worker_count=1,
        max_in_flight=1,
    ) as (runtime, client, requests, signer):
        runtime_holder["runtime"] = runtime
        client_holder["client"] = client
        failed_id = "88888888-8888-4888-8888-888888888888"
        assert post(client, valid_dispatch(failed_id)).status_code == 503
        assert observed == [(False, 1, 0, False)]
        assert terminated.wait(2)
        assert runtime.active_execution_count == 0
        assert runtime.available_execution_capacity == 1
        assert runtime.registration_count == 0
        assert client.app.state.attempt_cache.snapshot(UUID(failed_id)) is None
        assert executed == []
        assert requests == [] and signer.calls == []


def test_17_direction_credentials_are_distinct_and_wrong_token_is_rejected() -> None:
    with runtime_context() as (runtime, client, _, _):
        assert post(client, token=CALLBACK_TOKEN).status_code == 401
        assert runtime.registration_count == 0
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    with pytest.raises(ValueError, match="distinct"):
        TestOnlyRuntimeComposition(
            dispatch_token=DISPATCH_TOKEN, callback_token=DISPATCH_TOKEN,
            signer=FixedSigner(private_key), test_public_key=public, key_id=KEY_ID,
            callback_transport=httpx.MockTransport(lambda request: httpx.Response(202, request=request)),
            callback_policy=retry_policy(),
        )


def test_18_oversized_and_unauthenticated_requests_have_no_admission_side_effects() -> None:
    with runtime_context() as (runtime, client, _, _):
        unauthorized = client.post(
            "/internal/v1/executions",
            headers={"Authorization": "Bearer invalid", "Content-Type": "application/json"},
            content=b"{" + b"x" * 20_000,
        )
        oversized = client.post(
            "/internal/v1/executions",
            headers={"Authorization": f"Bearer {DISPATCH_TOKEN}", "Content-Type": "application/json"},
            content=b"{" + b"x" * 20_000,
        )
        assert unauthorized.status_code == 401
        assert oversized.status_code == 422
        assert runtime.registration_count == 0
        assert "Bearer " not in unauthorized.text
        assert "x" * 128 not in oversized.text


def test_19_stale_lifecycle_cannot_complete_or_release_a_replacement_owner() -> None:
    monotonic = FakeMonotonic()
    with runtime_context(
        cache_clock=monotonic,
        cache_ttl_seconds=5,
        result_ids=(RESULT_ID, "88888888-8888-4888-8888-888888888888"),
    ) as (runtime, client, _, _):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        stale_lifecycle = runtime.lifecycle_for(ATTEMPT_ID)
        stale_admission = runtime.admission_for(ATTEMPT_ID)
        monotonic.advance(5)
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        current = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID))
        assert current.state is AttemptState.FINISHED
        with pytest.raises(Exception, match="stale"):
            stale_lifecycle.complete(current.receipt)
        assert client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt == current.receipt
        assert runtime.registration_count == 2
        assert stale_admission.fingerprint != runtime.admission_for(ATTEMPT_ID).fingerprint or (
            stale_admission._producer_token is not runtime.admission_for(ATTEMPT_ID)._producer_token
        )


def test_20_canonical_signed_v1_bytes_verify_across_producer_cache_and_callback() -> None:
    with runtime_context() as (runtime, client, sent, signer):
        assert post(client).status_code == 202
        assert client.wait_for_attempt(ATTEMPT_ID)
        receipt = client.app.state.attempt_cache.snapshot(UUID(ATTEMPT_ID)).receipt
        parsed = envelope_from_json(receipt.raw_envelope)
        assert receipt.raw_envelope == sent[0].content
        assert parsed.raw_envelope is receipt.raw_envelope
        signer.private_key.public_key().verify(
            base64.urlsafe_b64decode(parsed.envelope.signature + "=="),
            signer.calls[0][2],
        )
        assert parsed.envelope.payload.key_id == str(KEY_ID)
        assert parsed.envelope.payload.attempt_id == ATTEMPT_ID
