"""Simulator-local cache/dispatch composition; injected producer only."""
from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread
import time
import json
from uuid import UUID

from fastapi import FastAPI
import httpx
import pytest
from pydantic import SecretStr, ValidationError

from gpu_marketplace_simulator.app import create_app
from gpu_marketplace_simulator.attempt_cache import (
    Admission,
    AttemptCache,
    AttemptState,
    Receipt,
)
from gpu_marketplace_simulator.attempt_cache_adapter import (
    AttemptCacheAdmissionAdapter,
    ProducerLifecycle,
    ProducerRegistrationUncertain,
)
from gpu_marketplace_simulator.admission_executor import BoundedAdmissionExecutor
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.dispatch import (
    AttemptAdmissionConflict,
    AttemptAdmissionOutcome,
    AttemptAdmissionUnavailable,
    DispatchRequest,
)


MANAGER_TOKEN = "manager-test-token-0123456789abcdef"
ATTEMPT = "44444444-4444-4444-8444-444444444444"
RESULT = UUID("77777777-7777-4777-8777-777777777777")


class LocalASGIClient:
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def post(self, path: str, *, body: dict[str, object] | None = None,
             token: str | None = MANAGER_TOKEN) -> httpx.Response:
        async def send() -> httpx.Response:
            headers = {"Content-Type": "application/json"}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://simulator.test",
            ) as client:
                return await client.post(
                    path, headers=headers, json=dispatch() if body is None else body
                )
        return asyncio.run(send())


def dispatch(attempt_id: str = ATTEMPT) -> dict[str, object]:
    return {
        "outbox_event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "job_id": "33333333-3333-4333-8333-333333333333",
        "attempt_id": attempt_id,
        "worker_id": "11111111-1111-4111-8111-111111111111",
        "listing_id": "22222222-2222-4222-8222-222222222222",
        "gpu_count": 2,
        "duration_seconds": 60,
        "simulation_input": {"workload_profile": "demo-v1"},
        "finish_due_at": "2026-10-18T08:01:00.000000Z",
        "hard_deadline_at": "2026-10-18T08:03:00.000000Z",
    }


def signed_result_envelope(
    *, attempt_id: str = ATTEMPT, result_id: UUID = RESULT,
    payload_overrides: dict[str, object] | None = None,
) -> bytes:
    """Structural ADR-004 V1 fixture; signature shape only, never verified here."""
    fields = dispatch(attempt_id)
    payload = {
        "schema_version": "1",
        "result_id": str(result_id),
        "job_id": fields["job_id"],
        "attempt_id": attempt_id,
        "worker_id": fields["worker_id"],
        "listing_id": fields["listing_id"],
        "outcome": "SUCCESS",
        "failure_reason": None,
        "result_digest": "sha256:" + "0" * 64,
        "finished_at": "2026-10-18T08:01:00.000000Z",
        "key_id": "88888888-8888-4888-8888-888888888888",
    }
    if payload_overrides:
        payload.update(payload_overrides)
    signature = urlsafe_b64encode(bytes(64)).rstrip(b"=").decode("ascii")
    return json.dumps(
        {"payload": payload, "signature": signature,
         "signature_encoding": "base64url-no-padding"},
        separators=(",", ":"),
    ).encode("utf-8")


def make_receipt(
    *, attempt_id: str = ATTEMPT, result_id: UUID = RESULT,
    payload_overrides: dict[str, object] | None = None,
) -> Receipt:
    return Receipt(result_id, signed_result_envelope(
        attempt_id=attempt_id, result_id=result_id,
        payload_overrides=payload_overrides,
    ))


def terminate_producer(lifecycle: ProducerLifecycle) -> None:
    execution = Future()
    execution.set_exception(RuntimeError("test producer terminated"))
    lifecycle.bind_execution_future(execution)


class FakeProducerRegistrar:
    """Test handoff boundary; stores tickets but performs no execution."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.calls = 0
        self.reject_next = False
        self.raise_next = False
        self.tickets: dict[str, tuple[DispatchRequest, Admission, ProducerLifecycle]] = {}

    def register(
        self, request: DispatchRequest, admission: Admission,
        lifecycle: ProducerLifecycle,
    ) -> bool:
        with self.lock:
            self.calls += 1
            if self.raise_next:
                self.raise_next = False
                raise RuntimeError("private producer detail")
            if self.reject_next:
                self.reject_next = False
                return False
            self.tickets[request.attempt_id] = (request, admission, lifecycle)
            return True

    def simulate_failure_after_acceptance(self, attempt_id: str) -> None:
        if attempt_id not in self.tickets:
            raise AssertionError("producer was not registered")
        raise RuntimeError("post-accept producer failure")


def make_app(*, max_entries: int = 32, concurrency: int = 32,
             ttl: float = 60.0, registrar: FakeProducerRegistrar | None = None,
             executor_workers: int = 4, max_outstanding: int = 16):
    producer = registrar or FakeProducerRegistrar()
    settings = Settings(
        manager_dispatch_token=SecretStr(MANAGER_TOKEN),
        dispatch_max_body_bytes=4096,
        attempt_cache_max_entries=max_entries,
        attempt_cache_ttl_seconds=ttl,
        producer_concurrency_limit=concurrency,
        admission_executor_workers=executor_workers,
        admission_max_outstanding=max_outstanding,
        shutdown_drain_timeout_seconds=0.05,
    )
    app = create_app(settings, producer_registrar=producer)
    return app, producer, LocalASGIClient(app)


def test_first_admission_registers_one_producer_before_202_and_preserves_ten_fields() -> None:
    app, producer, client = make_app()
    response = client.post("/internal/v1/executions")
    assert response.status_code == 202
    assert response.json() == {"attempt_id": ATTEMPT, "accepted": True}
    assert producer.calls == 1
    request, admission, _lifecycle = producer.tickets[ATTEMPT]
    assert set(request.model_dump(mode="json")) == set(dispatch())
    assert request.attempt_id == ATTEMPT
    assert request.simulation_input.model_dump(mode="json") == {"workload_profile": "demo-v1"}
    assert admission.state is AttemptState.IN_FLIGHT
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).fingerprint == admission.fingerprint


def test_identical_inflight_duplicate_returns_202_only_after_registered_handoff() -> None:
    _, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    repeated = client.post("/internal/v1/executions")
    assert repeated.status_code == 202
    assert producer.calls == 1


def test_route_never_returns_202_for_an_unregistered_producer_outcome() -> None:
    class UnregisteredPort:
        def admit(self, request: DispatchRequest) -> AttemptAdmissionOutcome:
            return AttemptAdmissionOutcome(
                attempt_id=request.attempt_id,
                state="IN_FLIGHT",
                newly_admitted=True,
                producer_registered=False,
                receipt=None,
                cache_admission=None,
            )

    settings = Settings(manager_dispatch_token=SecretStr(MANAGER_TOKEN),
                        dispatch_max_body_bytes=4096,
                        admission_executor_workers=2,
                        admission_max_outstanding=4)
    app = create_app(settings, admission_port=UnregisteredPort())
    response = LocalASGIClient(app).post("/internal/v1/executions")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_finished_duplicate_reuses_retained_receipt_without_registering_again() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    _, original, _lifecycle = producer.tickets[ATTEMPT]
    original_receipt = make_receipt()
    outcome = adapter.complete(original, original_receipt)
    assert outcome.state == "FINISHED"
    repeated = client.post("/internal/v1/executions")
    assert repeated.status_code == 202
    assert original_receipt.raw_envelope.decode() not in repeated.text
    assert str(original_receipt.result_id) not in repeated.text
    assert producer.calls == 1
    retained = adapter.admit(DispatchRequest.model_validate(dispatch()))
    assert retained.state == "FINISHED"
    assert retained.receipt is original_receipt
    assert retained.receipt.raw_envelope == original_receipt.raw_envelope


def test_conflicting_retained_dispatch_maps_to_409_without_second_producer() -> None:
    _, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    changed = dispatch()
    changed["gpu_count"] = 3
    response = client.post("/internal/v1/executions", body=changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_CONFLICT"
    assert response.headers["cache-control"] == "no-store"
    assert UUID(response.headers["x-request-id"]).version == 4
    assert producer.calls == 1


def test_failed_handoff_returns_503_and_token_guarded_rollback_allows_safe_retry() -> None:
    app, producer, client = make_app()
    producer.reject_next = True
    response = client.post("/internal/v1/executions")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)) is None
    assert client.post("/internal/v1/executions").status_code == 202
    assert producer.calls == 2


def test_rejected_handoff_reports_proven_prestart_rollback_without_leaking_details() -> None:
    app, producer, _client = make_app()
    producer.reject_next = True
    with pytest.raises(AttemptAdmissionUnavailable, match="producer rejected handoff"):
        app.state.admission_port.admit(DispatchRequest.model_validate(dispatch()))
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)) is None
    assert app.state.admission_port.active_producer_count == 0


def test_rejected_handoff_reports_uncertain_rollback_and_keeps_capacity() -> None:
    app, producer, _client = make_app()
    producer.reject_next = True
    app.state.attempt_cache.abort_before_start = lambda _admission: False
    with pytest.raises(
        AttemptAdmissionUnavailable, match="pre-start rollback could not be proven"
    ):
        app.state.admission_port.admit(DispatchRequest.model_validate(dispatch()))
    assert producer.calls == 1
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    assert app.state.admission_port.active_producer_count == 1


def test_handoff_exception_is_redacted_and_prestart_admission_is_removed() -> None:
    app, producer, client = make_app()
    producer.raise_next = True
    response = client.post("/internal/v1/executions")
    assert response.status_code == 503
    assert "private producer detail" not in response.text
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)) is None


def test_abort_before_start_token_fence_cannot_remove_a_newer_admission() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=10)
    old = cache.admit(dispatch())
    assert cache.abort_before_start(old)
    current = cache.admit(dispatch())
    assert current.newly_admitted
    assert not cache.abort_before_start(old)
    retained = cache.snapshot(UUID(ATTEMPT))
    assert retained.state is AttemptState.IN_FLIGHT
    assert retained.fingerprint == current.fingerprint


def test_sixteen_concurrent_identical_requests_register_exactly_one_producer() -> None:
    app, producer, _ = make_app()
    barrier = Barrier(16)

    def send(_: int) -> int:
        barrier.wait(timeout=5)
        return LocalASGIClient(app).post("/internal/v1/executions").status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(send, range(16)))
    assert statuses == [202] * 16
    assert producer.calls == 1


def test_slow_sync_registrar_does_not_block_unrelated_asgi_health_request() -> None:
    class BlockingRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.entered.set()
            if not self.release.wait(timeout=3):
                return False
            return super().register(request, admission, lifecycle)

    producer = BlockingRegistrar()
    app, _, _ = make_app(registrar=producer)
    async def event_loop_probe() -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route("/test/event-loop-probe", event_loop_probe, methods=["GET"])
    health_finished = Event()
    observations: dict[str, bool] = {}

    def watchdog() -> None:
        if not producer.entered.wait(timeout=2):
            producer.release.set()
            return
        observations["health_completed_before_release"] = health_finished.wait(timeout=0.5)
        producer.release.set()

    release_controller = Thread(target=watchdog, daemon=True)
    release_controller.start()

    async def requests() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            dispatch_task = asyncio.create_task(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            ))
            health_task = asyncio.create_task(client.get("/test/event-loop-probe"))
            health_response = await asyncio.wait_for(health_task, timeout=2)
            health_finished.set()
            dispatch_response = await asyncio.wait_for(dispatch_task, timeout=2)
            return dispatch_response, health_response

    dispatch_response, health_response = asyncio.run(requests())
    release_controller.join(timeout=2)
    assert not release_controller.is_alive()
    assert dispatch_response.status_code == 202
    assert health_response.status_code == 200
    assert observations.get("health_completed_before_release") is True


def test_dispatch_waits_for_registered_handoff_before_returning_202() -> None:
    class HeldRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.entered.set()
            if not self.release.wait(timeout=3):
                return False
            return super().register(request, admission, lifecycle)

    producer = HeldRegistrar()
    app, _, _ = make_app(registrar=producer)

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            return await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            )

    async def exercise() -> httpx.Response:
        task = asyncio.create_task(request())
        assert await asyncio.to_thread(producer.entered.wait, 1)
        assert not task.done()
        producer.release.set()
        return await asyncio.wait_for(task, timeout=2)

    response = asyncio.run(exercise())
    assert response.status_code == 202
    assert producer.calls == 1


def test_cancelled_http_wait_does_not_cancel_or_rollback_registered_admission() -> None:
    class HeldRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()
            self.registered = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.entered.set()
            if not self.release.wait(timeout=3):
                return False
            result = super().register(request, admission, lifecycle)
            self.registered.set()
            return result

    producer = HeldRegistrar()
    app, _, _ = make_app(registrar=producer)

    async def exercise() -> tuple[httpx.Response, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            request = asyncio.create_task(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            ))
            assert await asyncio.to_thread(producer.entered.wait, 1)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            producer.release.set()
            assert await asyncio.to_thread(producer.registered.wait, 1)
            retry = await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            )
            return retry, producer.calls

    response, calls = asyncio.run(exercise())
    assert response.status_code == 202
    assert calls == 1


def test_bounded_admission_executor_returns_503_when_outstanding_limit_is_full() -> None:
    class HeldRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.entered.set()
            if not self.release.wait(timeout=3):
                return False
            return super().register(request, admission, lifecycle)

    producer = HeldRegistrar()
    app, _, _ = make_app(registrar=producer, executor_workers=1, max_outstanding=1)

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            first = asyncio.create_task(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            ))
            assert await asyncio.to_thread(producer.entered.wait, 1)
            overloaded = await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch("55555555-5555-4555-8555-555555555555"),
            )
            producer.release.set()
            accepted = await asyncio.wait_for(first, timeout=2)
            return accepted, overloaded

    accepted, overloaded = asyncio.run(exercise())
    assert accepted.status_code == 202
    assert overloaded.status_code == 503
    assert overloaded.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert producer.calls == 1


def test_concurrent_identical_and_conflicting_requests_have_one_producer() -> None:
    app, producer, _ = make_app()
    barrier = Barrier(16)

    def send(index: int) -> int:
        body = dispatch()
        if index >= 8:
            body["duration_seconds"] = 61
        barrier.wait(timeout=5)
        return LocalASGIClient(app).post("/internal/v1/executions", body=body).status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(send, range(16)))
    assert statuses.count(202) == 8
    assert statuses.count(409) == 8
    assert producer.calls == 1


def test_completion_racing_with_duplicate_never_registers_second_producer() -> None:
    app, producer, _ = make_app()
    assert LocalASGIClient(app).post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    _, admission, _lifecycle = producer.tickets[ATTEMPT]
    barrier = Barrier(2)

    def finish() -> None:
        barrier.wait(timeout=5)
        adapter.complete(admission, make_receipt())

    def repeat() -> int:
        barrier.wait(timeout=5)
        return LocalASGIClient(app).post("/internal/v1/executions").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(finish)
        status = pool.submit(repeat).result(timeout=5)
        future.result(timeout=5)
    assert status == 202
    assert producer.calls == 1
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.FINISHED


def test_producer_concurrency_limit_rejects_new_attempt_without_side_effect() -> None:
    app, producer, client = make_app(max_entries=8, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    second_id = "55555555-5555-4555-8555-555555555555"
    response = client.post("/internal/v1/executions", body=dispatch(second_id))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert producer.calls == 1
    assert app.state.attempt_cache.snapshot(UUID(second_id)) is None
    # A valid duplicate does not consume a second producer slot.
    assert client.post("/internal/v1/executions").status_code == 202


def test_confirmed_terminal_failure_releases_slot_and_retained_replay_never_reruns() -> None:
    app, producer, client = make_app(max_entries=3, concurrency=2)
    assert client.post("/internal/v1/executions").status_code == 202
    second_id = "55555555-5555-4555-8555-555555555555"
    assert client.post("/internal/v1/executions", body=dispatch(second_id)).status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    first_admission = producer.tickets[ATTEMPT][1]
    second_admission = producer.tickets[second_id][1]

    first_lifecycle = producer.tickets[ATTEMPT][2]
    second_lifecycle = producer.tickets[second_id][2]
    terminate_producer(first_lifecycle)
    terminate_producer(second_lifecycle)
    first_lifecycle.fail_after_start()
    second_lifecycle.fail_after_start()
    assert adapter.active_producer_count == 0
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.FAILED_NO_RECEIPT
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).receipt is None

    identical = client.post("/internal/v1/executions")
    assert identical.status_code == 503
    assert identical.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    altered = dispatch()
    altered["duration_seconds"] = 61
    assert client.post("/internal/v1/executions", body=altered).status_code == 409
    assert producer.calls == 2

    third_id = "66666666-6666-4666-8666-666666666666"
    assert client.post("/internal/v1/executions", body=dispatch(third_id)).status_code == 202
    assert producer.calls == 3


def test_slow_registration_does_not_hold_global_lock_or_ack_pending_duplicate() -> None:
    class SelectivelyBlockedRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.first_entered = Event()
            self.release_first = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            if request.attempt_id == ATTEMPT:
                self.first_entered.set()
                if not self.release_first.wait(timeout=3):
                    return False
            return super().register(request, admission, lifecycle)

    producer = SelectivelyBlockedRegistrar()
    app, _, _ = make_app(registrar=producer, executor_workers=2, max_outstanding=4)

    async def exercise() -> tuple[int, int, int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            first = asyncio.create_task(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            ))
            assert await asyncio.to_thread(producer.first_entered.wait, 1)
            # A duplicate while the original handoff is pending gets a retryable
            # failure, never a premature 202.
            duplicate = await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            )
            # A different Attempt can enter and complete registration meanwhile.
            other_id = "55555555-5555-4555-8555-555555555555"
            other = await asyncio.wait_for(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(other_id),
            ), timeout=1)
            assert not first.done()
            producer.release_first.set()
            accepted = await asyncio.wait_for(first, timeout=2)
            replay = await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            )
            return (duplicate.status_code, other.status_code,
                    accepted.status_code, replay.status_code)

    duplicate_status, other_status, accepted_status, replay_status = asyncio.run(exercise())
    assert duplicate_status == 503
    assert other_status == 202
    assert accepted_status == 202
    assert replay_status == 202
    assert producer.calls == 2


def test_uncertain_registration_keeps_owner_slot_and_never_relaunches() -> None:
    class UncertainRegistrar(FakeProducerRegistrar):
        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.calls += 1
            raise ProducerRegistrationUncertain("private uncertainty details")

    app, producer, client = make_app(registrar=UncertainRegistrar(), concurrency=1)
    first = client.post("/internal/v1/executions")
    assert first.status_code == 503
    assert "private uncertainty details" not in first.text
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    assert adapter.active_producer_count == 1
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT

    repeated = client.post("/internal/v1/executions")
    other = client.post(
        "/internal/v1/executions",
        body=dispatch("55555555-5555-4555-8555-555555555555"),
    )
    assert repeated.status_code == 503
    assert other.status_code == 503
    assert producer.calls == 1
    assert app.state.attempt_cache.snapshot(
        UUID("55555555-5555-4555-8555-555555555555")
    ) is None


def test_invalid_or_mismatched_receipt_is_rejected_without_cache_mutation() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    admission = producer.tickets[ATTEMPT][1]
    wrong_attempt = make_receipt(
        attempt_id="55555555-5555-4555-8555-555555555555"
    )
    with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound"):
        adapter.complete(admission, wrong_attempt)
    wrong_outer = Receipt(
        UUID("99999999-9999-4999-8999-999999999999"),
        signed_result_envelope(result_id=RESULT),
    )
    with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound"):
        adapter.complete(admission, wrong_outer)
    wrong_payload_result = make_receipt(
        payload_overrides={"result_id": "99999999-9999-4999-8999-999999999999"}
    )
    with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound"):
        adapter.complete(admission, wrong_payload_result)
    mismatched_identities = {
        "job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "worker_id": "99999999-9999-4999-8999-999999999999",
        "listing_id": "99999999-9999-4999-8999-999999999998",
    }
    for field, value in mismatched_identities.items():
        with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound"):
            adapter.complete(
                admission, make_receipt(payload_overrides={field: value})
            )
    retained = app.state.attempt_cache.snapshot(UUID(ATTEMPT))
    assert retained.state is AttemptState.IN_FLIGHT
    assert retained.receipt is None
    assert adapter.active_producer_count == 1


def test_swallowed_completion_rejection_is_not_treated_as_producer_failure(capsys) -> None:
    app, producer, client = make_app(max_entries=2, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    _, admission, lifecycle = producer.tickets[ATTEMPT]
    execution = Future()
    lifecycle.bind_execution_future(execution)

    with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound"):
        lifecycle.complete(make_receipt(payload_overrides={
            "job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        }))
    # Reproduce a producer swallowing the rejection and falsely succeeding.
    execution.set_result(None)
    with pytest.raises(AttemptAdmissionUnavailable, match="not confirmed"):
        lifecycle.fail_after_start()
    logs = capsys.readouterr().out
    assert "attempt_producer_succeeded_without_receipt" in logs
    assert "receipt is not bound" not in logs

    retained = app.state.attempt_cache.snapshot(UUID(ATTEMPT))
    assert retained.state is AttemptState.IN_FLIGHT
    assert retained.receipt is None
    assert app.state.admission_port.active_producer_count == 1
    assert producer.calls == 1


def test_propagated_completion_rejection_becomes_failure_only_after_future_terminates() -> None:
    app, producer, client = make_app(max_entries=2, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    _, _admission, lifecycle = producer.tickets[ATTEMPT]
    execution = Future()
    lifecycle.bind_execution_future(execution)
    with pytest.raises(AttemptAdmissionUnavailable, match="receipt is not bound") as rejected:
        lifecycle.complete(make_receipt(payload_overrides={
            "job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        }))

    with pytest.raises(AttemptAdmissionUnavailable, match="not confirmed"):
        lifecycle.fail_after_start()
    assert app.state.admission_port.active_producer_count == 1
    execution.set_exception(rejected.value)
    failure = lifecycle.fail_after_start()
    assert failure.state is AttemptState.FAILED_NO_RECEIPT
    assert failure.receipt is None
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).receipt is None
    assert app.state.admission_port.active_producer_count == 0
    assert producer.calls == 1
    replay = client.post("/internal/v1/executions")
    assert replay.status_code == 503
    assert producer.calls == 1


def test_completion_and_failure_race_releases_the_slot_exactly_once() -> None:
    app, producer, client = make_app(max_entries=2, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    _, admission, lifecycle = producer.tickets[ATTEMPT]
    terminate_producer(lifecycle)
    barrier = Barrier(3)

    def complete():
        barrier.wait(timeout=3)
        try:
            return app.state.admission_port.complete(admission, make_receipt()).state
        except Exception:
            return "LOST"

    def fail():
        barrier.wait(timeout=3)
        try:
            return lifecycle.fail_after_start().state
        except Exception:
            return "LOST"

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(complete)
        failure = pool.submit(fail)
        barrier.wait(timeout=3)
        outcomes = completion.result(timeout=3), failure.result(timeout=3)
    winners = [item for item in outcomes if item != "LOST"]
    assert len(winners) == 1
    assert app.state.admission_port.active_producer_count == 0
    retained = app.state.attempt_cache.snapshot(UUID(ATTEMPT))
    assert retained.state in {AttemptState.FINISHED, AttemptState.FAILED_NO_RECEIPT}
    assert (retained.receipt is not None) is (retained.state is AttemptState.FINISHED)


def test_duplicate_failure_signal_does_not_release_capacity_twice() -> None:
    app, producer, client = make_app(max_entries=2, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    _, admission, lifecycle = producer.tickets[ATTEMPT]
    terminate_producer(lifecycle)
    lifecycle.fail_after_start()
    assert app.state.admission_port.active_producer_count == 0
    with pytest.raises(AttemptAdmissionUnavailable):
        lifecycle.fail_after_start()
    assert app.state.admission_port.active_producer_count == 0
    next_id = "55555555-5555-4555-8555-555555555555"
    assert client.post("/internal/v1/executions", body=dispatch(next_id)).status_code == 202
    assert app.state.admission_port.active_producer_count == 1
    assert producer.calls == 2


def test_failure_signal_requires_the_bound_execution_future_to_terminate() -> None:
    app, producer, client = make_app(max_entries=2, concurrency=1)
    assert client.post("/internal/v1/executions").status_code == 202
    _, _admission, lifecycle = producer.tickets[ATTEMPT]
    execution = Future()
    lifecycle.bind_execution_future(execution)

    with pytest.raises(AttemptAdmissionUnavailable, match="not confirmed"):
        lifecycle.fail_after_start()
    assert app.state.admission_port.active_producer_count == 1
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT

    unrelated = Future()
    unrelated.set_exception(RuntimeError("unrelated future"))
    with pytest.raises(AttemptAdmissionUnavailable, match="already bound"):
        lifecycle.bind_execution_future(unrelated)
    assert app.state.admission_port.active_producer_count == 1

    execution.set_exception(RuntimeError("actual producer terminated"))
    lifecycle.fail_after_start()
    assert app.state.admission_port.active_producer_count == 0
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.FAILED_NO_RECEIPT


def test_shutdown_racing_registration_keeps_confirmed_producer_owned_until_terminal() -> None:
    class HeldRegistrar(FakeProducerRegistrar):
        def __init__(self) -> None:
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def register(
            self, request: DispatchRequest, admission: Admission,
            lifecycle: ProducerLifecycle,
        ) -> bool:
            self.entered.set()
            if not self.release.wait(timeout=3):
                return False
            return super().register(request, admission, lifecycle)

    producer = HeldRegistrar()
    app, _, _ = make_app(registrar=producer)
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port

    async def exercise() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            task = asyncio.create_task(client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch(),
            ))
            assert await asyncio.to_thread(producer.entered.wait, 1)
            adapter.close()
            producer.release.set()
            response = await asyncio.wait_for(task, timeout=2)
            return response.status_code

    assert asyncio.run(exercise()) == 503
    assert producer.calls == 1
    assert adapter.active_producer_count == 1
    assert not adapter.drain(0)
    admission = producer.tickets[ATTEMPT][1]
    adapter.complete(admission, make_receipt())
    assert adapter.active_producer_count == 0
    assert adapter.drain(0)


def test_completed_receipt_survives_callback_transport_failure_byte_exactly() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    admission = producer.tickets[ATTEMPT][1]
    raw = signed_result_envelope()
    retained_receipt = Receipt(RESULT, raw)
    adapter.complete(admission, retained_receipt)
    # Simulate only transport failure after the immutable receipt was retained.
    with pytest.raises(ConnectionError, match="callback transport"):
        raise ConnectionError("callback transport unavailable")
    replay = client.post("/internal/v1/executions")
    assert replay.status_code == 202
    retained = app.state.attempt_cache.snapshot(UUID(ATTEMPT))
    assert retained.state is AttemptState.FINISHED
    assert retained.receipt.raw_envelope is raw
    assert retained.receipt.raw_envelope == raw
    assert producer.calls == 1


def test_cache_full_and_cache_closed_map_to_503_without_new_producer() -> None:
    app, producer, client = make_app(max_entries=1, concurrency=4)
    first = client.post("/internal/v1/executions")
    assert first.status_code == 202
    second_id = "55555555-5555-4555-8555-555555555555"
    full = client.post("/internal/v1/executions", body=dispatch(second_id))
    assert full.status_code == 503
    assert full.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert producer.calls == 1

    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    adapter.close()
    closed = client.post("/internal/v1/executions", body=dispatch(
        "66666666-6666-4666-8666-666666666666"
    ))
    assert closed.status_code == 503
    assert producer.calls == 1


def test_post_202_failure_remains_inflight_and_shutdown_drain_is_bounded() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    # No failure callback or cleanup policy is invented after HTTP 202.
    with pytest.raises(RuntimeError, match="post-accept producer failure"):
        producer.simulate_failure_after_acceptance(ATTEMPT)
    adapter.close()
    started = time.monotonic()
    assert adapter.drain(0.01) is False
    assert time.monotonic() - started < 0.25
    retained = app.state.attempt_cache.snapshot(UUID(ATTEMPT))
    assert retained.state is AttemptState.IN_FLIGHT
    assert client.post("/internal/v1/executions").status_code == 503


def test_shutdown_drain_completes_when_registered_producer_finishes() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    _, admission, _lifecycle = producer.tickets[ATTEMPT]
    adapter.close()
    worker = Thread(
        target=lambda: adapter.complete(admission, make_receipt()),
        daemon=True,
    )
    worker.start()
    assert adapter.drain(0.5) is True
    worker.join(timeout=0.5)
    assert not worker.is_alive()
    assert app.state.attempt_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.FINISHED


def test_fastapi_lifespan_closes_injected_cache_on_shutdown() -> None:
    app, producer, _ = make_app()

    async def exercise_lifespan() -> tuple[int, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://simulator.test") as client:
            async with app.router.lifespan_context(app):
                accepted = await client.post(
                    "/internal/v1/executions",
                    headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                    json=dispatch(),
                )
            after_close = await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
                json=dispatch("55555555-5555-4555-8555-555555555555"),
            )
            return accepted.status_code, after_close.status_code

    assert asyncio.run(exercise_lifespan()) == (202, 503)
    assert producer.calls == 1


def test_invalid_cache_runtime_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(attempt_cache_max_entries=True)
    with pytest.raises(ValidationError):
        Settings(attempt_cache_ttl_seconds=float("inf"))
    with pytest.raises(ValidationError):
        Settings(attempt_cache_ttl_seconds=True)
    with pytest.raises(ValidationError):
        Settings(admission_executor_workers=True)
    with pytest.raises(ValueError, match="max_outstanding"):
        BoundedAdmissionExecutor(workers=2, max_outstanding=1)
    with pytest.raises(ValueError, match="explicit finite limits"):
        create_app(Settings(manager_dispatch_token=SecretStr(MANAGER_TOKEN)),
                   producer_registrar=FakeProducerRegistrar())


def test_d16_conflict_detection_is_retained_process_only() -> None:
    clock_value = [10.0]
    cache = AttemptCache(max_entries=2, ttl_seconds=5, clock=lambda: clock_value[0])
    producer = FakeProducerRegistrar()
    adapter = AttemptCacheAdmissionAdapter(
        cache=cache, producer=producer, max_concurrent_producers=2
    )
    original = DispatchRequest.model_validate(dispatch())
    initial = adapter.admit(original)
    adapter.complete(initial.cache_admission, make_receipt())
    changed_payload = dispatch()
    changed_payload["gpu_count"] = 3
    changed = DispatchRequest.model_validate(changed_payload)
    with pytest.raises(AttemptAdmissionConflict):
        adapter.admit(changed)

    clock_value[0] += 6
    # After eviction the cache has no history; a new cache instance has the same limitation.
    accepted_after_expiry = adapter.admit(changed)
    assert accepted_after_expiry.newly_admitted
    cold = AttemptCache(max_entries=2, ttl_seconds=5, clock=lambda: clock_value[0])
    cold_adapter = AttemptCacheAdmissionAdapter(
        cache=cold, producer=FakeProducerRegistrar(), max_concurrent_producers=2
    )
    assert cold_adapter.admit(changed).newly_admitted
