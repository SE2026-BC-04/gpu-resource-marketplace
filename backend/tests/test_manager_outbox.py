import asyncio
from dataclasses import dataclass

import pytest

from gpu_marketplace.manager.outbox import (
    DISPATCH_POLL_INTERVAL_SECONDS,
    OutboxDispatchCoordinator,
    OutboxPoller,
    _wait_for_stop_or_interval,
)


@dataclass(frozen=True)
class _FakeTransportObservation:
    """Test-local stand-in; not a proposed shared TV2/TV5 transport DTO."""

    category: str
    accepted: bool = False
    http_status: int | None = None


async def _deliver_fake_transport_observation(observation):
    claim = object()
    calls: list[str] = []
    settled: list[tuple[object, object]] = []

    async def claim_one_committed():
        calls.append("claim")
        return claim

    async def dispatch(received_claim):
        assert received_claim is claim
        calls.append("dispatch")
        return observation

    async def settle(received_claim, received_observation) -> None:
        calls.append("settle")
        settled.append((received_claim, received_observation))

    coordinator = OutboxDispatchCoordinator(
        claim_one_committed=claim_one_committed,
        dispatch=dispatch,
        settle=settle,
    )
    await coordinator.run_once()
    return claim, calls, settled


def test_out_01_poller_starts_with_injected_cycle_port() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            stop_event.set()

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
        )
        await poller.run()
        assert cycle_calls == 1

    asyncio.run(scenario())


def test_out_02_empty_due_scan_records_progress_and_heartbeat() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        heartbeats: list[None] = []

        async def claim_no_due_work():
            return None

        async def unexpected_dispatch(_claim):
            pytest.fail("no dispatch is expected when no due claim exists")

        async def unexpected_settlement(_claim, _outcome) -> None:
            pytest.fail("no settlement is expected when no due claim exists")

        def on_completed() -> None:
            heartbeats.append(None)
            stop_event.set()

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_no_due_work,
            dispatch=unexpected_dispatch,
            settle=unexpected_settlement,
        )
        poller = OutboxPoller(
            cycle=coordinator.run_once,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            monotonic_clock=lambda: 12.5,
            on_cycle_completed=on_completed,
        )
        assert poller.last_completed_monotonic is None
        await poller.run()
        assert poller.last_completed_monotonic == 12.5
        assert heartbeats == [None]

    asyncio.run(scenario())


def test_out_03_stop_interrupts_cadence_wait_promptly() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        async def wait_for_stop(event: asyncio.Event, interval: float) -> bool:
            assert interval == 2.0
            wait_started.set()
            return await _wait_for_stop_or_interval(event, interval)

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            wait_for_interval=wait_for_stop,
        )
        task = asyncio.create_task(poller.run())
        await wait_started.wait()
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        assert cycle_calls == 1

    asyncio.run(scenario())


def test_out_04_stop_before_first_claim_starts_no_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
        )
        await poller.run()
        assert cycle_calls == 0

    asyncio.run(scenario())


def test_out_05_concurrent_run_attempts_do_not_overlap() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            cycle_started.set()
            await release_cycle.wait()

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
        )
        first_run = asyncio.create_task(poller.run())
        await cycle_started.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await poller.run()

        stop_event.set()
        release_cycle.set()
        await asyncio.wait_for(first_run, timeout=1)
        assert cycle_calls == 1

    asyncio.run(scenario())


def test_out_06_claim_dispatch_settlement_order_is_preserved() -> None:
    async def scenario() -> None:
        events: list[str] = []
        claim = object()
        outcome = object()

        async def claim_one_committed():
            events.append("claim_committed")
            return claim

        async def dispatch(received_claim):
            assert received_claim is claim
            events.append("dispatch")
            return outcome

        async def settle(received_claim, received_outcome) -> None:
            assert received_claim is claim
            assert received_outcome is outcome
            events.append("settlement")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        await coordinator.run_once()
        assert events == ["claim_committed", "dispatch", "settlement"]

    asyncio.run(scenario())


def test_out_07_claim_failure_never_starts_http_dispatch() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def claim_one_committed():
            calls.append("claim")
            raise RuntimeError("claim failed")

        async def dispatch(_claim):
            calls.append("dispatch")
            return object()

        async def settle(_claim, _outcome) -> None:
            calls.append("settlement")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(RuntimeError, match="claim failed"):
            await coordinator.run_once()
        assert calls == ["claim"]

    asyncio.run(scenario())


def test_out_08_accepted_transport_outcome_is_settled_without_finalization() -> None:
    async def scenario() -> None:
        accepted_outcome = object()
        claim = object()
        calls: list[str] = []

        async def claim_one_committed():
            calls.append("claim")
            return claim

        async def dispatch(received_claim):
            assert received_claim is claim
            calls.append("dispatch")
            return accepted_outcome

        async def settle(received_claim, received_outcome) -> None:
            assert received_claim is claim
            assert received_outcome is accepted_outcome
            calls.append("settlement")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        await coordinator.run_once()
        assert calls == ["claim", "dispatch", "settlement"]

    asyncio.run(scenario())


def test_out_09_transport_failure_outcome_is_not_rewritten_as_success() -> None:
    async def scenario() -> None:
        claim = object()
        transport_failure = object()
        settled: list[object] = []

        async def claim_one_committed():
            return claim

        async def dispatch(_claim):
            return transport_failure

        async def settle(received_claim, outcome) -> None:
            assert received_claim is claim
            settled.append(outcome)

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        await coordinator.run_once()
        assert settled == [transport_failure]

    asyncio.run(scenario())


def test_out_10_unknown_claim_commit_outcome_is_not_blindly_dispatched() -> None:
    class CommitOutcomeUnknown(Exception):
        pass

    async def scenario() -> None:
        calls: list[str] = []

        async def claim_one_committed():
            calls.append("claim")
            raise CommitOutcomeUnknown("commit outcome unknown")

        async def dispatch(_claim):
            calls.append("dispatch")
            return object()

        async def settle(_claim, _outcome) -> None:
            calls.append("settlement")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(CommitOutcomeUnknown):
            await coordinator.run_once()
        assert calls == ["claim"]

    asyncio.run(scenario())


def test_out_11_cancellation_during_cycle_does_not_heartbeat_or_claim_again() -> None:
    async def scenario() -> None:
        cycle_started = asyncio.Event()
        heartbeats: list[None] = []
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            cycle_started.set()
            await asyncio.Event().wait()

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: heartbeats.append(None),
        )
        task = asyncio.create_task(poller.run())
        await cycle_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cycle_calls == 1
        assert heartbeats == []

    asyncio.run(scenario())


def test_out_12_concurrent_coordinator_calls_reject_unbounded_submissions() -> None:
    async def scenario() -> None:
        claim_started = asyncio.Event()
        release_claim = asyncio.Event()
        claim_calls = 0
        claim = object()

        async def claim_one_committed():
            nonlocal claim_calls
            claim_calls += 1
            claim_started.set()
            await release_claim.wait()
            return claim

        async def dispatch(_claim):
            return object()

        async def settle(_claim, _outcome) -> None:
            return None

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        first_run = asyncio.create_task(coordinator.run_once())
        await claim_started.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await coordinator.run_once()
        release_claim.set()
        await asyncio.wait_for(first_run, timeout=1)
        assert claim_calls == 1

    asyncio.run(scenario())


def test_out_13_settlement_failure_propagates_without_retrying_claim() -> None:
    async def scenario() -> None:
        claim_calls = 0
        dispatch_calls = 0
        settlement_calls = 0

        async def claim_one_committed():
            nonlocal claim_calls
            claim_calls += 1
            return object()

        async def dispatch(_claim):
            nonlocal dispatch_calls
            dispatch_calls += 1
            return object()

        async def settle(_claim, _outcome) -> None:
            nonlocal settlement_calls
            settlement_calls += 1
            raise RuntimeError("settlement failed")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(RuntimeError, match="settlement failed"):
            await coordinator.run_once()
        assert (claim_calls, dispatch_calls, settlement_calls) == (1, 1, 1)

    asyncio.run(scenario())


def test_out_14_dispatch_poll_cadence_is_two_seconds() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        intervals: list[float] = []
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        async def stop_at_next_wait(event: asyncio.Event, interval: float) -> bool:
            intervals.append(interval)
            event.set()
            return True

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            wait_for_interval=stop_at_next_wait,
        )
        await poller.run()
        assert cycle_calls == 1
        assert intervals == [2.0]
        assert DISPATCH_POLL_INTERVAL_SECONDS == 2.0

    asyncio.run(scenario())


def test_out_15_completion_hook_runs_once_for_each_normal_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        completed: list[int] = []
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        def on_completed() -> None:
            completed.append(cycle_calls)

        async def stop_after_three(event: asyncio.Event, _interval: float) -> bool:
            if len(completed) == 3:
                event.set()
                return True
            return False

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=on_completed,
            wait_for_interval=stop_after_three,
        )
        await poller.run()
        assert completed == [1, 2, 3]

    asyncio.run(scenario())


def test_out_16_failed_cycle_does_not_call_completion_hook() -> None:
    async def scenario() -> None:
        heartbeats: list[None] = []

        async def failed_cycle() -> None:
            raise RuntimeError("cycle failed")

        poller = OutboxPoller(
            cycle=failed_cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: heartbeats.append(None),
        )
        with pytest.raises(RuntimeError, match="cycle failed"):
            await poller.run()
        assert heartbeats == []
        assert poller.last_completed_monotonic is None

    asyncio.run(scenario())


def test_out_21_completion_hook_failure_propagates_after_progress_without_retry() -> None:
    async def scenario() -> None:
        cycle_calls = 0
        hook_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        def fail_hook() -> None:
            nonlocal hook_calls
            hook_calls += 1
            raise RuntimeError("heartbeat failed")

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            monotonic_clock=lambda: 51.0,
            on_cycle_completed=fail_hook,
        )
        with pytest.raises(RuntimeError, match="heartbeat failed"):
            await poller.run()
        assert cycle_calls == 1
        assert hook_calls == 1
        assert poller.last_completed_monotonic == 51.0

    asyncio.run(scenario())


def test_out_17_missing_required_ports_fail_closed() -> None:
    with pytest.raises(ValueError, match="cycle port is required"):
        OutboxPoller(
            cycle=None,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
        )
    with pytest.raises(ValueError, match="stop event is required"):
        OutboxPoller(
            cycle=lambda: None,
            stop_event=None,
            claim_allowed=lambda: True,
        )
    with pytest.raises(ValueError, match="claim-permission gate is required"):
        OutboxPoller(
            cycle=lambda: None,
            stop_event=asyncio.Event(),
            claim_allowed=None,
        )
    for missing_port in ("claim", "dispatch", "settle"):
        ports = {
            "claim_one_committed": lambda: asyncio.sleep(0),
            "dispatch": lambda _claim: asyncio.sleep(0, result=object()),
            "settle": lambda _claim, _outcome: asyncio.sleep(0),
        }
        ports[
            {
                "claim": "claim_one_committed",
                "dispatch": "dispatch",
                "settle": "settle",
            }[missing_port]
        ] = None
        with pytest.raises(ValueError, match="port is required"):
            OutboxDispatchCoordinator(**ports)


def test_out_18_secret_or_payload_exception_text_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        secret_text = "SYNTHETIC-SENSITIVE-LOG-SENTINEL"

        async def claim_one_committed():
            raise RuntimeError(secret_text)

        async def dispatch(_claim):
            return object()

        async def settle(_claim, _outcome) -> None:
            return None

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(RuntimeError, match="SYNTHETIC-SENSITIVE-LOG-SENTINEL"):
            await coordinator.run_once()

    asyncio.run(scenario())
    assert "SYNTHETIC-SENSITIVE-LOG-SENTINEL" not in caplog.text


def test_out_19_duplicate_delivery_keeps_opaque_claim_handle_unchanged() -> None:
    async def scenario() -> None:
        claim = object()
        observed_dispatch: list[object] = []
        observed_settlement: list[object] = []

        async def claim_one_committed():
            return claim

        async def dispatch(received_claim):
            observed_dispatch.append(received_claim)
            return object()

        async def settle(received_claim, _outcome) -> None:
            observed_settlement.append(received_claim)

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        await coordinator.run_once()
        await coordinator.run_once()
        # Mock-port identity only; this does not verify DB CAS or fencing.
        assert observed_dispatch == [claim, claim]
        assert observed_settlement == [claim, claim]

    asyncio.run(scenario())


def test_out_20_graceful_stop_waits_for_inflight_cycle_to_finish() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()
        heartbeats: list[None] = []
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            cycle_started.set()
            await release_cycle.wait()

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: heartbeats.append(None),
        )
        task = asyncio.create_task(poller.run())
        await cycle_started.wait()
        stop_event.set()
        assert not task.done()
        release_cycle.set()
        await asyncio.wait_for(task, timeout=1)
        assert cycle_calls == 1
        assert heartbeats == [None]

    asyncio.run(scenario())


def test_claim_gate_closed_waits_without_busy_spin_or_heartbeat() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        wait_started = asyncio.Event()
        cycle_calls = 0
        heartbeats: list[None] = []
        waits = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1

        async def stop_on_gate_wait(event: asyncio.Event, interval: float) -> bool:
            nonlocal waits
            waits += 1
            assert interval == 2.0
            wait_started.set()
            event.set()
            return True

        poller = OutboxPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: False,
            on_cycle_completed=lambda: heartbeats.append(None),
            wait_for_interval=stop_on_gate_wait,
        )
        await poller.run()
        assert wait_started.is_set()
        assert waits == 1
        assert cycle_calls == 0
        assert heartbeats == []

    asyncio.run(scenario())


def test_out_p2_01_typed_timeout_observation_reaches_settlement_unchanged() -> None:
    observation = _FakeTransportObservation("timeout")
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert len(settled) == 1
    assert settled[0][0] is claim
    assert settled[0][1] is observation


def test_out_p2_02_typed_connection_failure_settles_once() -> None:
    observation = _FakeTransportObservation("connection_failure")
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert len(settled) == 1
    assert settled[0][0] is claim
    assert settled[0][1] is observation


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_out_p2_03_retryable_http_observation_reaches_settlement(status: int) -> None:
    observation = _FakeTransportObservation("http_response", http_status=status)
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert len(settled) == 1
    assert settled[0][0] is claim
    assert settled[0][1] is observation
    assert settled[0][1].http_status == status


@pytest.mark.parametrize("status", [401, 403])
def test_out_p2_04_auth_failure_observation_is_not_reclassified_as_success(
    status: int,
) -> None:
    observation = _FakeTransportObservation("http_response", http_status=status)
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert len(settled) == 1
    assert settled[0][0] is claim
    assert settled[0][1] is observation
    assert settled[0][1].accepted is False


def test_out_p2_05_http_202_is_settled_without_job_finalization() -> None:
    observation = _FakeTransportObservation(
        "http_response", accepted=True, http_status=202
    )
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert len(settled) == 1
    assert settled[0][0] is claim
    assert settled[0][1] is observation
    # The coordinator exposes no Job-finalization port.


def test_out_p2_06_escaped_expected_timeout_propagates_without_settlement() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        claim = object()
        timeout = TimeoutError("read timeout")

        async def claim_one_committed():
            calls.append("claim")
            return claim

        async def dispatch(_claim):
            calls.append("dispatch")
            raise timeout

        async def settle(_claim, _observation) -> None:
            calls.append("settle")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(TimeoutError) as raised:
            await coordinator.run_once()
        assert raised.value is timeout
        assert calls == ["claim", "dispatch"]

    asyncio.run(scenario())


def test_out_p2_07_cancelled_dispatch_propagates_without_completion_callback() -> None:
    async def scenario() -> None:
        dispatch_started = asyncio.Event()
        settled: list[object] = []
        completions: list[None] = []

        async def claim_one_committed():
            return object()

        async def dispatch(_claim):
            dispatch_started.set()
            await asyncio.Event().wait()

        async def settle(_claim, observation) -> None:
            settled.append(observation)

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        poller = OutboxPoller(
            cycle=coordinator.run_once,
            stop_event=asyncio.Event(),
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: completions.append(None),
        )
        task = asyncio.create_task(poller.run())
        await dispatch_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled == []
        assert completions == []

    asyncio.run(scenario())


def test_out_p2_08_unknown_claim_commit_outcome_never_dispatches() -> None:
    class CommitOutcomeUnknown(Exception):
        pass

    async def scenario() -> None:
        calls: list[str] = []

        async def claim_one_committed():
            calls.append("claim")
            raise CommitOutcomeUnknown("claim commit unknown")

        async def dispatch(_claim):
            calls.append("dispatch")
            return _FakeTransportObservation("http_response", accepted=True, http_status=202)

        async def settle(_claim, _observation) -> None:
            calls.append("settle")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(CommitOutcomeUnknown):
            await coordinator.run_once()
        assert calls == ["claim"]

    asyncio.run(scenario())


def test_out_p2_09_unknown_settlement_commit_propagates_without_local_retry() -> None:
    class SettlementCommitUnknown(Exception):
        pass

    async def scenario() -> None:
        claim_calls = 0
        dispatch_calls = 0
        settlement_calls = 0
        claim = object()
        observation = _FakeTransportObservation("http_response", accepted=True, http_status=202)
        unknown = SettlementCommitUnknown("settlement commit unknown")

        async def claim_one_committed():
            nonlocal claim_calls
            claim_calls += 1
            return claim

        async def dispatch(_claim):
            nonlocal dispatch_calls
            dispatch_calls += 1
            return observation

        async def settle(_claim, _observation) -> None:
            nonlocal settlement_calls
            settlement_calls += 1
            raise unknown

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(SettlementCommitUnknown) as raised:
            await coordinator.run_once()
        assert raised.value is unknown
        assert (claim_calls, dispatch_calls, settlement_calls) == (1, 1, 1)

    asyncio.run(scenario())


def test_out_p2_10_claim_and_observation_identity_are_preserved() -> None:
    observation = _FakeTransportObservation("connection_failure")
    claim, calls, settled = asyncio.run(_deliver_fake_transport_observation(observation))

    assert calls == ["claim", "dispatch", "settle"]
    assert settled[0][0] is claim
    assert settled[0][1] is observation


def test_out_p2_11_repeated_invocations_settle_once_each() -> None:
    async def scenario() -> None:
        claim = object()
        observation = _FakeTransportObservation("http_response", accepted=True, http_status=202)
        claim_calls = 0
        dispatch_calls = 0
        settled: list[tuple[object, object]] = []

        async def claim_one_committed():
            nonlocal claim_calls
            claim_calls += 1
            return claim

        async def dispatch(received_claim):
            nonlocal dispatch_calls
            dispatch_calls += 1
            assert received_claim is claim
            return observation

        async def settle(received_claim, received_observation) -> None:
            settled.append((received_claim, received_observation))

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        await coordinator.run_once()
        await coordinator.run_once()
        assert (claim_calls, dispatch_calls) == (2, 2)
        assert len(settled) == 2
        assert all(received_claim is claim for received_claim, _ in settled)
        assert all(received_observation is observation for _, received_observation in settled)

    asyncio.run(scenario())


def test_out_p2_12_port_exception_details_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        sensitive_text = "SYNTHETIC-TOKEN-AND-PAYLOAD-SENTINEL"

        async def claim_one_committed():
            return object()

        async def dispatch(_claim):
            raise RuntimeError(sensitive_text)

        async def settle(_claim, _observation) -> None:
            pytest.fail("settlement must not receive a fabricated outcome")

        coordinator = OutboxDispatchCoordinator(
            claim_one_committed=claim_one_committed,
            dispatch=dispatch,
            settle=settle,
        )
        with pytest.raises(RuntimeError, match=sensitive_text):
            await coordinator.run_once()

    asyncio.run(scenario())
    assert "SYNTHETIC-TOKEN-AND-PAYLOAD-SENTINEL" not in caplog.text
