"""Simulator-local cache/dispatch composition; injected producer only."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, Thread
import time
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
from gpu_marketplace_simulator.attempt_cache_adapter import AttemptCacheAdmissionAdapter
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.dispatch import (
    AttemptAdmissionConflict,
    AttemptAdmissionOutcome,
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


class FakeProducerRegistrar:
    """Test handoff boundary; stores tickets but performs no execution."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.calls = 0
        self.reject_next = False
        self.raise_next = False
        self.tickets: dict[str, tuple[DispatchRequest, Admission]] = {}

    def register(self, request: DispatchRequest, admission: Admission) -> bool:
        with self.lock:
            self.calls += 1
            if self.raise_next:
                self.raise_next = False
                raise RuntimeError("private producer detail")
            if self.reject_next:
                self.reject_next = False
                return False
            self.tickets[request.attempt_id] = (request, admission)
            return True

    def simulate_failure_after_acceptance(self, attempt_id: str) -> None:
        if attempt_id not in self.tickets:
            raise AssertionError("producer was not registered")
        raise RuntimeError("post-accept producer failure")


def make_app(*, max_entries: int = 32, concurrency: int = 32,
             ttl: float = 60.0, registrar: FakeProducerRegistrar | None = None):
    producer = registrar or FakeProducerRegistrar()
    settings = Settings(
        manager_dispatch_token=SecretStr(MANAGER_TOKEN),
        dispatch_max_body_bytes=4096,
        attempt_cache_max_entries=max_entries,
        attempt_cache_ttl_seconds=ttl,
        producer_concurrency_limit=concurrency,
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
    request, admission = producer.tickets[ATTEMPT]
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
                        dispatch_max_body_bytes=4096)
    app = create_app(settings, admission_port=UnregisteredPort())
    response = LocalASGIClient(app).post("/internal/v1/executions")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_finished_duplicate_reuses_retained_receipt_without_registering_again() -> None:
    app, producer, client = make_app()
    assert client.post("/internal/v1/executions").status_code == 202
    adapter: AttemptCacheAdmissionAdapter = app.state.admission_port
    _, original = producer.tickets[ATTEMPT]
    original_receipt = Receipt(RESULT, b'{"same":"raw signed bytes"}')
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
    assert retained.receipt.raw_envelope == b'{"same":"raw signed bytes"}'


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
    _, admission = producer.tickets[ATTEMPT]
    barrier = Barrier(2)

    def finish() -> None:
        barrier.wait(timeout=5)
        adapter.complete(admission, Receipt(RESULT, b"receipt"))

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
    _, admission = producer.tickets[ATTEMPT]
    adapter.close()
    worker = Thread(
        target=lambda: adapter.complete(admission, Receipt(RESULT, b"finished")),
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
    adapter.complete(initial.cache_admission, Receipt(RESULT, b"original"))
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
