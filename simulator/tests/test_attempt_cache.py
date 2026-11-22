"""G2-A / TV5-P2E-08: process-local admission, replay, concurrency and D-16 B."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from concurrent.futures import Future, ThreadPoolExecutor
import copy
from threading import Barrier, Event, Thread
from types import MappingProxyType
from uuid import UUID

import pytest

from gpu_marketplace_simulator.attempt_cache import (
    AttemptCache, AttemptState, CacheClosed, CacheFull, ExecutionConflict,
    InvalidDispatch, InvalidTransition, ProducerFailureEvidence, Receipt,
    dispatch_fingerprint,
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


def terminal_failure_evidence() -> ProducerFailureEvidence:
    execution = Future()
    execution.set_exception(RuntimeError("simulated producer termination"))
    return ProducerFailureEvidence.from_terminated_execution(execution)


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
        cache.finish(first, Receipt(UUID("88888888-8888-4888-8888-888888888888"), b"changed"))
    assert cache.snapshot(UUID(ATTEMPT)).receipt == completed.receipt
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


def test_many_finished_replays_reuse_exact_original_receipt() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    producer = cache.admit(dispatch())
    original = receipt()
    cache.finish(producer, original)
    gate = Barrier(32)

    def replay(_):
        gate.wait(timeout=5)
        return cache.admit(dispatch())

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(replay, range(32)))
    assert all(not item.newly_admitted for item in results)
    assert all(item.receipt is original for item in results)
    assert {item.receipt.result_id for item in results} == {original.result_id}
    assert {item.receipt.raw_envelope for item in results} == {original.raw_envelope}


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


def test_64_simultaneous_identical_and_conflicting_dispatches_have_one_owner() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    gate = Barrier(64)
    changed = dispatch()
    changed["duration_seconds"] = 61

    def work(index: int):
        gate.wait(timeout=10)
        request = dispatch() if index < 32 else changed
        try:
            return cache.admit(request)
        except ExecutionConflict:
            return None

    with ThreadPoolExecutor(max_workers=64) as pool:
        results = list(pool.map(work, range(64)))
    accepted = [item for item in results if item is not None]
    conflicts = [item for item in results if item is None]
    assert len(accepted) + len(conflicts) == 64
    assert sum(item.newly_admitted for item in accepted) == 1
    assert len({item.fingerprint for item in accepted}) == 1
    assert len(conflicts) == 32


def test_completion_racing_with_identical_duplicate_never_creates_second_owner() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    first = cache.admit(dispatch())
    gate = Barrier(2)

    def duplicate():
        gate.wait(timeout=5)
        return cache.admit(dispatch())

    def complete():
        gate.wait(timeout=5)
        return cache.finish(first, receipt())

    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicate_future = pool.submit(duplicate)
        finish_future = pool.submit(complete)
        duplicate_admission = duplicate_future.result(timeout=5)
        completed = finish_future.result(timeout=5)
    assert duplicate_admission.newly_admitted is False
    assert duplicate_admission.state in (AttemptState.IN_FLIGHT, AttemptState.FINISHED)
    assert completed.state is AttemptState.FINISHED
    snapshot = cache.snapshot(UUID(ATTEMPT))
    assert snapshot.state is AttemptState.FINISHED
    assert snapshot.receipt.raw_envelope == receipt().raw_envelope


def test_completion_racing_with_capacity_never_evicts_inflight_entry() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    first = cache.admit(dispatch())
    gate = Barrier(2)

    def complete():
        gate.wait(timeout=5)
        return cache.finish(first, receipt())

    def fill_capacity():
        gate.wait(timeout=5)
        try:
            return cache.admit(dispatch(ANOTHER))
        except CacheFull:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(complete)
        admission = pool.submit(fill_capacity)
        completed = completion.result(timeout=5)
        replacement = admission.result(timeout=5)

    assert completed.state is AttemptState.FINISHED
    if replacement is None:
        assert cache.snapshot(UUID(ATTEMPT)).receipt == completed.receipt
    else:
        assert replacement.newly_admitted
        assert cache.snapshot(UUID(ATTEMPT)) is None
        assert cache.snapshot(UUID(ANOTHER)).state is AttemptState.IN_FLIGHT


def test_concurrent_completions_allow_exactly_one_receipt() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    first = cache.admit(dispatch())
    gate = Barrier(16)

    def complete(index: int):
        gate.wait(timeout=5)
        item = Receipt(
            UUID(f"88888888-8888-4888-8888-{index:012d}"),
            f"receipt-{index}".encode(),
        )
        try:
            return cache.finish(first, item)
        except InvalidTransition:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(complete, range(16)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert cache.snapshot(UUID(ATTEMPT)).receipt == winners[0].receipt


def test_unrelated_attempts_can_all_be_admitted_concurrently() -> None:
    count = 64
    cache = AttemptCache(max_entries=count, ttl_seconds=30)
    gate = Barrier(count)

    def admit(index: int):
        gate.wait(timeout=10)
        attempt_id = str(UUID(int=(index + 1), version=4))
        return cache.admit(dispatch(attempt_id))

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(admit, range(count)))
    assert all(result.newly_admitted for result in results)
    assert len({result.attempt_id for result in results}) == count


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
    changed_after_restart = dispatch()
    changed_after_restart["gpu_count"] = 5
    assert restarted.admit(changed_after_restart).newly_admitted


def test_stale_producer_cannot_finish_same_attempt_after_ttl_re_admission() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: now[0])
    old_producer = cache.admit(dispatch())
    cache.finish(old_producer, receipt())
    now[0] = 5.0
    new_producer = cache.admit(dispatch())
    assert new_producer.newly_admitted

    with pytest.raises(InvalidTransition):
        cache.finish(
            old_producer,
            Receipt(UUID("88888888-8888-4888-8888-888888888888"), b"stale"),
        )
    current = cache.snapshot(UUID(ATTEMPT))
    assert current.state is AttemptState.IN_FLIGHT
    assert current.receipt is None
    cache.finish(new_producer, receipt())


def test_stale_producer_from_replaced_cache_cannot_finish_new_cache_entry() -> None:
    previous_cache = AttemptCache(max_entries=1, ttl_seconds=5)
    old_producer = previous_cache.admit(dispatch())
    replacement_cache = AttemptCache(max_entries=1, ttl_seconds=5)
    new_producer = replacement_cache.admit(dispatch())
    with pytest.raises(InvalidTransition):
        replacement_cache.finish(
            old_producer,
            Receipt(UUID("88888888-8888-4888-8888-888888888888"), b"stale"),
        )
    assert replacement_cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    replacement_cache.finish(new_producer, receipt())


def test_oldest_finished_entry_is_evicted_fifo_with_insertion_order_tie_break() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=2, ttl_seconds=100, clock=lambda: now[0])
    first = cache.admit(dispatch())
    cache.finish(first, receipt())
    second = cache.admit(dispatch(ANOTHER))
    cache.finish(second, receipt())

    replacement = cache.admit(dispatch(THIRD))
    assert replacement.newly_admitted
    assert cache.snapshot(UUID(ATTEMPT)) is None
    assert cache.snapshot(UUID(ANOTHER)).state is AttemptState.FINISHED
    assert cache.snapshot(UUID(THIRD)).state is AttemptState.IN_FLIGHT


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


def test_confirmed_failure_transitions_inflight_to_retained_tombstone_without_receipt() -> None:
    cache = AttemptCache(max_entries=2, ttl_seconds=30)
    original = cache.admit(dispatch())

    failed = cache.fail_after_start(original, terminal_failure_evidence())
    retained = cache.snapshot(UUID(ATTEMPT))

    assert failed.state is AttemptState.FAILED_NO_RECEIPT
    assert failed.receipt is None
    assert retained is not None
    assert retained.state is AttemptState.FAILED_NO_RECEIPT
    assert retained.fingerprint == original.fingerprint
    assert retained.receipt is None
    assert not cache.admit(dispatch()).newly_admitted
    with pytest.raises(ExecutionConflict):
        changed = dispatch()
        changed["gpu_count"] = 3
        cache.admit(changed)


def test_failure_requires_future_exception_or_completed_cancellation() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    original = cache.admit(dispatch())
    pending = Future()
    with pytest.raises(ValueError, match="not positively terminated"):
        ProducerFailureEvidence.from_terminated_execution(pending)
    successful = Future()
    successful.set_result(None)
    with pytest.raises(ValueError, match="not failure evidence"):
        ProducerFailureEvidence.from_terminated_execution(successful)
    with pytest.raises(InvalidTransition):
        cache.fail_after_start(original, object())
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT

    cancelled = Future()
    assert cancelled.cancel()
    evidence = ProducerFailureEvidence.from_terminated_execution(cancelled)
    assert cache.fail_after_start(original, evidence).state is AttemptState.FAILED_NO_RECEIPT


def test_completion_and_confirmed_failure_are_mutually_exclusive_terminal_winners() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    first = cache.admit(dispatch())
    finished = cache.finish(first, receipt())
    with pytest.raises(InvalidTransition):
        cache.fail_after_start(first, terminal_failure_evidence())
    assert cache.snapshot(UUID(ATTEMPT)).receipt is finished.receipt

    second_cache = AttemptCache(max_entries=1, ttl_seconds=30)
    second = second_cache.admit(dispatch())
    failed = second_cache.fail_after_start(second, terminal_failure_evidence())
    with pytest.raises(InvalidTransition):
        second_cache.finish(second, receipt())
    assert second_cache.snapshot(UUID(ATTEMPT)).state is failed.state
    assert second_cache.snapshot(UUID(ATTEMPT)).receipt is None


def test_duplicate_failure_and_stale_token_cannot_mutate_new_admission() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: now[0])
    old = cache.admit(dispatch())
    evidence = terminal_failure_evidence()
    cache.fail_after_start(old, evidence)
    with pytest.raises(InvalidTransition):
        cache.fail_after_start(old, evidence)
    now[0] = 5
    current = cache.admit(dispatch())
    assert current.newly_admitted
    with pytest.raises(InvalidTransition):
        cache.fail_after_start(old, evidence)
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT
    assert cache.snapshot(UUID(ATTEMPT)).fingerprint == current.fingerprint


def test_failed_tombstone_expires_and_cold_restart_has_no_history() -> None:
    now = [10.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: now[0])
    failed = cache.admit(dispatch())
    cache.fail_after_start(failed, terminal_failure_evidence())
    now[0] = 14.999
    assert cache.admit(dispatch()).state is AttemptState.FAILED_NO_RECEIPT
    now[0] = 15
    changed = dispatch()
    changed["gpu_count"] = 4
    assert cache.admit(changed).newly_admitted

    cold_cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: now[0])
    assert cold_cache.admit(changed).newly_admitted


def test_failed_tombstones_are_oldest_first_pressure_eviction_candidates() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=2, ttl_seconds=100, clock=lambda: now[0])
    first = cache.admit(dispatch())
    cache.fail_after_start(first, terminal_failure_evidence())
    now[0] = 1
    second = cache.admit(dispatch(ANOTHER))
    cache.fail_after_start(second, terminal_failure_evidence())

    replacement = cache.admit(dispatch(THIRD))
    assert replacement.newly_admitted
    assert cache.snapshot(UUID(ATTEMPT)) is None
    assert cache.snapshot(UUID(ANOTHER)).state is AttemptState.FAILED_NO_RECEIPT
    assert cache.snapshot(UUID(THIRD)).state is AttemptState.IN_FLIGHT


def test_uncertain_inflight_is_never_expired_evicted_or_drained_as_terminal() -> None:
    now = [0.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=1, clock=lambda: now[0])
    cache.admit(dispatch())
    now[0] = 100
    assert not cache.drain(0)
    with pytest.raises(CacheFull):
        cache.admit(dispatch(ANOTHER))
    assert cache.snapshot(UUID(ATTEMPT)).state is AttemptState.IN_FLIGHT


def test_close_disallows_new_admission_and_drain_waits_for_completion() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=5)
    first = cache.admit(dispatch())
    cache.close()
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


@pytest.mark.parametrize("bad", (True, float("inf"), float("nan"), "1"))
def test_cache_clock_must_return_finite_monotonic_number(bad: object) -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: bad)
    with pytest.raises(ValueError, match="finite monotonic"):
        cache.admit(dispatch())


def test_cache_clock_moving_backwards_fails_without_state_transition() -> None:
    now = [10.0]
    cache = AttemptCache(max_entries=1, ttl_seconds=5, clock=lambda: now[0])
    producer = cache.admit(dispatch())
    now[0] = 9.0
    with pytest.raises(ValueError, match="moved backwards"):
        cache.finish(producer, receipt())
    now[0] = 10.0
    snapshot = cache.snapshot(UUID(ATTEMPT))
    assert snapshot.state is AttemptState.IN_FLIGHT
    assert snapshot.receipt is None
    cache.finish(producer, receipt())


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
    item = dispatch()
    item["simulation_input"] = {"workload_profile": True}
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)
    item = dispatch()
    del item["hard_deadline_at"]
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(item)


def test_custom_mapping_inputs_are_rejected_before_serialization() -> None:
    item = dispatch()
    with pytest.raises(InvalidDispatch):
        dispatch_fingerprint(MappingProxyType(item))
    item = dispatch()
    item["simulation_input"] = MappingProxyType(item["simulation_input"])
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outbox_event_id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ("job_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("attempt_id", ANOTHER),
        ("worker_id", "99999999-9999-4999-8999-999999999999"),
        ("listing_id", "99999999-9999-4999-8999-999999999998"),
        ("gpu_count", 3),
        ("duration_seconds", 61),
        ("finish_due_at", "2026-10-18T08:01:01.000000Z"),
        ("hard_deadline_at", "2026-10-18T08:03:01.000000Z"),
    ],
)
def test_each_approved_immutable_dispatch_field_changes_fingerprint(field, value) -> None:
    original = dispatch()
    changed = dict(original)
    changed[field] = value
    assert dispatch_fingerprint(original) != dispatch_fingerprint(changed)


def test_receipt_value_and_raw_bytes_are_immutable_after_cache_binding() -> None:
    cache = AttemptCache(max_entries=1, ttl_seconds=30)
    producer = cache.admit(dispatch())
    original = receipt()
    cache.finish(producer, original)
    replay = cache.admit(dispatch())
    assert replay.receipt is original
    assert replay.receipt.raw_envelope == b'{"signed_result":"frozen-original"}'
    with pytest.raises(FrozenInstanceError):
        original.result_id = UUID("88888888-8888-4888-8888-888888888888")
    with pytest.raises(TypeError):
        original.raw_envelope[0] = 0
