"""G2-A / TV5-P2E-08: process-local admission, replay, concurrency and D-16 B."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread
from uuid import UUID
import copy

import pytest

from gpu_marketplace_simulator.attempt_cache import (
    AttemptCache, AttemptState, CacheClosed, CacheFull, ExecutionConflict,
    InvalidDispatch, InvalidTransition, Receipt, dispatch_fingerprint,
)


ATTEMPT = "44444444-4444-4444-8444-444444444444"
ANOTHER = "55555555-5555-4555-8555-555555555555"
THIRD = "66666666-6666-4666-8666-666666666666"
RESULT = UUID("77777777-7777-4777-8777-777777777777")


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


def receipt() -> Receipt:
    return Receipt(RESULT, b'{"signed_result":"frozen-original"}')


def test_admission_duplicate_inflight_and_finished_replay() -> None:
    cache = AttemptCache(max_entries=2, ttl_seconds=15)
    request = dispatch()
    first = cache.admit(request)
    assert first.newly_admitted
    assert first.state is AttemptState.IN_FLIGHT
    duplicate = cache.admit(dict(reversed(list(request.items()))))
    assert duplicate.state is AttemptState.IN_FLIGHT
    assert not duplicate.newly_admitted
    assert duplicate.receipt is None
    completed = cache.finish(first, receipt())
    assert completed.state is AttemptState.FINISHED
    repeated = cache.admit(request)
    assert not repeated.newly_admitted
    assert repeated.receipt is completed.receipt
    assert repeated.receipt.result_id == RESULT
    assert repeated.receipt.raw_envelope == receipt().raw_envelope
    with pytest.raises(InvalidTransition):
        cache.finish(first, receipt())
    with pytest.raises(InvalidTransition):
        cache.finish(duplicate, receipt())


def test_retained_conflicting_request_cannot_replace_original() -> None:
    cache = AttemptCache(max_entries=2, ttl_seconds=30)
    first = cache.admit(dispatch())
    changed = dispatch()
    changed["duration_seconds"] = 61
    with pytest.raises(ExecutionConflict, match="EXECUTION_CONFLICT"):
        cache.admit(changed)
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    cache.finish(first, receipt())
    with pytest.raises(ExecutionConflict):
        cache.admit(changed)
    assert cache.admit(dispatch()).receipt.result_id == RESULT


def test_atomic_admission_one_producer_for_64_simultaneous_requests() -> None:
    cache = AttemptCache(max_entries=2, ttl_seconds=30)
    gate = Barrier(64)
    def work(_: int):
        gate.wait(timeout=10)
        return cache.admit(dispatch())
    with ThreadPoolExecutor(max_workers=64) as pool:
        results = list(pool.map(work, range(64)))
    assert sum(item.newly_admitted for item in results) == 1
    assert len({item.fingerprint for item in results}) == 1
    assert all(item.state is AttemptState.IN_FLIGHT for item in results)


def test_simultaneous_conflicting_request_cannot_create_second_producer() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    gate = Barrier(2)
    altered = dispatch()
    altered["gpu_count"] = 3
    def attempt(request):
        gate.wait(timeout=5)
        try:
            return cache.admit(request)
        except ExecutionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (dispatch(), altered)))
    assert sum(isinstance(item, str) and item == "conflict" for item in outcomes) == 1
    assert sum(not isinstance(item, str) and item.newly_admitted for item in outcomes) == 1


def test_inflight_is_not_evicted_under_capacity_pressure() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    first = cache.admit(dispatch())
    with pytest.raises(CacheFull):
        cache.admit(dispatch(ANOTHER))
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    cache.finish(first, receipt())
    replacement = cache.admit(dispatch(ANOTHER))
    assert replacement.newly_admitted
    assert cache.snapshot(UUID(ATTEMPT)) is None


def test_expiry_and_eviction_do_not_claim_cross_restart_identity_guarantees() -> None:
    now = [100.0]
    cache = AttemptCache(max_entries=2, ttl_seconds=5, clock=lambda: now[0])
    first = cache.admit(dispatch())
    cache.finish(first, receipt())
    now[0] = 104.999
    assert not cache.admit(dispatch()).newly_admitted
    now[0] = 105.0
    changed = dispatch()
    changed["gpu_count"] = 5
    assert cache.admit(changed).newly_admitted

    # Cold restart loses the in-memory fingerprint. The Manager must resend
    # only its immutable trusted Outbox payload; no historical 409 guarantee.
    restarted = AttemptCache(max_entries=2, ttl_seconds=5, clock=lambda: now[0])
    assert restarted.admit(dispatch()).newly_admitted


def test_finished_ttl_never_expires_inflight_entries() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=1, clock=lambda: now[0])
    first = cache.admit(dispatch())
    now[0] = 10000.0
    with pytest.raises(CacheFull):
        cache.admit(dispatch(ANOTHER))
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    cache.finish(first, receipt())
    now[0] = 10001.0
    assert cache.admit(dispatch(ANOTHER)).newly_admitted


def test_close_disallows_new_admission_and_drain_waits_for_completion() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=5)
    first = cache.admit(dispatch())
    cache.close()
    with pytest.raises(CacheClosed):
        cache.admit(dispatch())
    assert not cache.drain(0)
    signal = Event()
    def complete() -> None:
        cache.finish(first, receipt())
        signal.set()
    worker = Thread(target=complete)
    worker.start()
    assert cache.drain(2)
    worker.join(timeout=2)
    assert signal.is_set()


@pytest.mark.parametrize("bad", (0, -1, True, 1.2))
def test_invalid_cache_capacity(bad: object) -> None:
    with pytest.raises(ValueError):
        AttemptCache(max_entries=bad, ttl_seconds=5)


@pytest.mark.parametrize("bad", (0, -1, True, float("inf"), float("nan")))
def test_invalid_ttl(bad: object) -> None:
    with pytest.raises(ValueError):
        AttemptCache(max_entries=1, ttl_seconds=bad)


@pytest.mark.parametrize("field", ("gpu_count", "duration_seconds"))
@pytest.mark.parametrize("bad", (0, -1, True, "2", 2**31))
def test_invalid_int32_rejected(field: str, bad: object) -> None:
    item = dispatch()
    item[field] = bad
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)


@pytest.mark.parametrize("field", ("outbox_event_id", "job_id", "attempt_id", "worker_id", "listing_id"))
def test_invalid_uuid_rejected(field: str) -> None:
    item = dispatch()
    item[field] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)


@pytest.mark.parametrize("field", ("finish_due_at", "hard_deadline_at"))
def test_invalid_timestamp_rejected(field: str) -> None:
    item = dispatch()
    item[field] = "2026-10-18T08:01:00Z"
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)


def test_invalid_profile_or_extra_field_fails_closed() -> None:
    item = dispatch()
    item["simulation_input"] = {"workload_profile": "demo-v2"}
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)
    item = dispatch()
    item["unexpected"] = "secret"
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)
    item = dispatch()
    item["simulation_input"] = {"workload_profile": "demo-v1", "command": "rm -rf"}
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)


def test_receipt_is_exact_bytes_and_strict_uuid() -> None:
    with pytest.raises(ValueError):
        Receipt(RESULT, b"")
    with pytest.raises(ValueError):
        Receipt(RESULT, "not bytes")
    with pytest.raises(ValueError):
        Receipt(UUID("11111111-1111-1111-8111-111111111111"), b"data")


def test_fingerprint_is_key_order_independent_but_full_request_bound() -> None:
    item = dispatch()
    assert dispatch_fingerprint(item) == dispatch_fingerprint(
        dict(reversed(list(item.items())))
    )
    different = copy.deepcopy(item)
    different["outbox_event_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    assert dispatch_fingerprint(item) != dispatch_fingerprint(different)
