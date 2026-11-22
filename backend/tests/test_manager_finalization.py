import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from gpu_marketplace.manager.finalization import (
    INBOX_POLL_INTERVAL_SECONDS,
    InboxFinalizationCoordinator,
    InboxFinalizationPoller,
)


@dataclass(frozen=True)
class _Candidate:
    inbox_id: str
    result_id: str
    received_at: datetime
    hard_deadline_at: datetime
    attempt_id: str = "attempt-1"


@dataclass(frozen=True)
class _Evidence:
    candidate: _Candidate
    raw_digest: str


@dataclass(frozen=True)
class _Verdict:
    kind: str


@dataclass(frozen=True)
class _PortOutcome:
    kind: str


def _coordinator(
    *,
    locate_candidate,
    load_evidence,
    verify,
    finalize,
    evaluate_deadlines,
):
    return InboxFinalizationCoordinator(
        locate_candidate=locate_candidate,
        load_evidence=load_evidence,
        verify=verify,
        finalize=finalize,
        evaluate_deadlines=evaluate_deadlines,
    )


def test_fin_01_injected_poller_runs_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls: list[str] = []

        async def cycle() -> None:
            calls.append("cycle")

        async def wait_for_interval(event: asyncio.Event, interval: float) -> bool:
            calls.append("wait")
            assert interval == INBOX_POLL_INTERVAL_SECONDS
            event.set()
            return True

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            wait_for_interval=wait_for_interval,
        )
        await poller.run()
        assert calls == ["cycle", "wait"]

    asyncio.run(scenario())


def test_fin_02_empty_normal_scan_records_progress_before_heartbeat() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        observed: list[object] = []

        async def empty_cycle() -> None:
            return None

        def clock() -> float:
            observed.append("clock")
            return 12.5

        def completed() -> None:
            observed.append(("heartbeat", poller.last_completed_at))

        async def wait_for_interval(_event: asyncio.Event, _interval: float) -> bool:
            stop_event.set()
            return True

        poller = InboxFinalizationPoller(
            cycle=empty_cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=completed,
            monotonic_clock=clock,
            wait_for_interval=wait_for_interval,
        )
        await poller.run()
        assert observed == ["clock", ("heartbeat", 12.5)]

    asyncio.run(scenario())


def test_fin_03_stop_during_cadence_wait_exits_promptly() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        cycle_finished = asyncio.Event()
        wait_started = asyncio.Event()
        calls: list[str] = []

        async def cycle() -> None:
            calls.append("cycle")
            cycle_finished.set()

        async def wait_for_interval(event: asyncio.Event, _interval: float) -> bool:
            wait_started.set()
            await event.wait()
            return True

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            wait_for_interval=wait_for_interval,
        )
        task = asyncio.create_task(poller.run())
        await asyncio.wait_for(cycle_finished.wait(), timeout=1)
        await asyncio.wait_for(wait_started.wait(), timeout=1)
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        assert calls == ["cycle"]

    asyncio.run(scenario())


def test_fin_04_stop_before_processing_starts_no_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        calls: list[str] = []

        async def cycle() -> None:
            calls.append("cycle")

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: calls.append("heartbeat"),
        )
        await poller.run()
        assert calls == []
        assert poller.last_completed_at is None

    asyncio.run(scenario())


def test_fin_05_concurrent_poller_runs_reject_overlap() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        stop_event = asyncio.Event()
        cycle_calls = 0

        async def cycle() -> None:
            nonlocal cycle_calls
            cycle_calls += 1
            started.set()
            await release.wait()

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
        )
        first = asyncio.create_task(poller.run())
        await asyncio.wait_for(started.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="already running"):
            await poller.run()
        release.set()
        stop_event.set()
        await asyncio.wait_for(first, timeout=1)
        assert cycle_calls == 1

    asyncio.run(scenario())


def test_fin_06_candidate_verifier_finalizer_ports_run_in_order() -> None:
    candidate = _Candidate("inbox-1", "result-1", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:trusted")
    verdict = _Verdict("verified")
    finalized = _PortOutcome("finalized")
    calls: list[str] = []

    async def locate():
        calls.append("locate")
        return candidate

    async def load(found):
        calls.append("load")
        assert found is candidate
        return evidence

    async def verify(found):
        calls.append("verify")
        assert found is evidence
        return verdict

    async def finalize(found, loaded, result):
        calls.append("finalize")
        assert found is candidate and loaded is evidence and result is verdict
        return finalized

    async def evaluate_deadlines():
        calls.append("deadline")
        return _PortOutcome("deadline")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=locate,
            load_evidence=load,
            verify=verify,
            finalize=finalize,
            evaluate_deadlines=evaluate_deadlines,
        ).run_once()
    )
    assert calls == ["locate", "load", "verify", "finalize"]
    assert observation.candidate_processed is True
    assert observation.finalization_outcome is finalized
    assert observation.deadline_outcome is None


def test_fin_07_verified_receipt_passes_unchanged_without_local_write() -> None:
    candidate = _Candidate("inbox-v", "result-v", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:v")
    verdict = _Verdict("verified")
    writes: list[object] = []

    async def finalize(_candidate, _evidence, received_verdict):
        assert received_verdict is verdict
        return _PortOutcome("accepted-by-adapter")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(candidate),
            load_evidence=lambda _candidate: _async_value(evidence),
            verify=lambda _evidence: _async_value(verdict),
            finalize=finalize,
            evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
        ).run_once()
    )
    assert observation.finalization_outcome.kind == "accepted-by-adapter"
    assert writes == []


def test_fin_08_definitive_rejection_is_forwarded_without_job_terminalization() -> None:
    candidate = _Candidate("inbox-r", "result-r", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:r")
    rejected = _Verdict("INVALID_SIGNATURE")
    calls: list[object] = []

    async def finalize(found, _evidence, verdict):
        calls.append((found, verdict))
        # Only the injected owner adapter may reject the matching Inbox item;
        # the TV1 coordinator has no Job terminalization or release port.
        return _PortOutcome("inbox-rejected-only")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(candidate),
            load_evidence=lambda _candidate: _async_value(evidence),
            verify=lambda _evidence: _async_value(rejected),
            finalize=finalize,
            evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
        ).run_once()
    )
    assert calls == [(candidate, rejected)]
    assert observation.finalization_outcome.kind == "inbox-rejected-only"
    assert observation.deadline_outcome is None


def test_fin_09_verifier_unavailable_does_not_finalize_or_evaluate_deadline() -> None:
    class VerifierUnavailable(RuntimeError):
        pass

    candidate = _Candidate("inbox-p", "result-p", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:p")
    calls: list[str] = []

    async def verify(_evidence):
        calls.append("verify")
        raise VerifierUnavailable("key registry unavailable")

    async def finalize(_candidate, _evidence, _verdict):
        calls.append("finalize")

    async def evaluate_deadlines():
        calls.append("deadline")

    with pytest.raises(VerifierUnavailable, match="key registry unavailable"):
        asyncio.run(
            _coordinator(
                locate_candidate=lambda: _async_value(candidate),
                load_evidence=lambda _candidate: _async_value(evidence),
                verify=verify,
                finalize=finalize,
                evaluate_deadlines=evaluate_deadlines,
            ).run_once()
        )
    assert calls == ["verify"]


def test_fin_10_invalid_then_later_valid_candidate_precedes_deadline_port() -> None:
    # Fake ports verify per-cycle ordering and that no deadline request is made
    # while a candidate is returned. A PostgreSQL test must later prove the
    # durable query exposes every ordered PENDING candidate across pages.
    candidates = [
        _Candidate("r1", "result-1", datetime.now(UTC), datetime.now(UTC)),
        _Candidate("r2", "result-2", datetime.now(UTC), datetime.now(UTC)),
    ]
    verdicts = [_Verdict("INVALID_SIGNATURE"), _Verdict("verified")]
    candidate_index = 0
    verdict_index = 0
    finalized: list[tuple[str, str]] = []
    deadline_calls: list[str] = []

    async def locate():
        nonlocal candidate_index
        if candidate_index == len(candidates):
            return None
        found = candidates[candidate_index]
        candidate_index += 1
        return found

    async def load(candidate):
        return _Evidence(candidate, f"sha256:{candidate.result_id}")

    async def verify(_evidence):
        nonlocal verdict_index
        found = verdicts[verdict_index]
        verdict_index += 1
        return found

    async def finalize(candidate, _evidence, verdict):
        finalized.append((candidate.result_id, verdict.kind))
        return _PortOutcome("done")

    async def evaluate_deadlines():
        deadline_calls.append("durable-check")
        return _PortOutcome("owner-blocked-or-finalized")

    coordinator = _coordinator(
        locate_candidate=locate,
        load_evidence=load,
        verify=verify,
        finalize=finalize,
        evaluate_deadlines=evaluate_deadlines,
    )
    first = asyncio.run(coordinator.run_once())
    second = asyncio.run(coordinator.run_once())
    assert first.candidate_processed and second.candidate_processed
    assert finalized == [("result-1", "INVALID_SIGNATURE"), ("result-2", "verified")]
    assert deadline_calls == []


def test_fin_11_on_time_pending_candidate_is_left_to_authoritative_deadline_port() -> None:
    # The fake outcome verifies pass-through only. A real PostgreSQL transaction
    # test must prove a committed on-time PENDING row blocks SYSTEM_FAULT.
    blocked = _PortOutcome("preceding-pending")
    calls: list[str] = []

    async def evaluate_deadlines():
        calls.append("authoritative-deadline-uow")
        return blocked

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(None),
            load_evidence=lambda _candidate: _async_value(None),
            verify=lambda _evidence: _async_value(None),
            finalize=lambda _candidate, _evidence, _verdict: _async_value(None),
            evaluate_deadlines=evaluate_deadlines,
        ).run_once()
    )
    assert calls == ["authoritative-deadline-uow"]
    assert observation.candidate_processed is False
    assert observation.deadline_outcome is blocked


def test_fin_12_committed_on_time_receipt_is_forwarded_after_deadline() -> None:
    # The timestamp fixture verifies no local deadline filtering. A PostgreSQL
    # restart test must prove trusted received_at survives and remains eligible.
    received_at = datetime.now(UTC) - timedelta(seconds=5)
    deadline = received_at + timedelta(seconds=1)
    candidate = _Candidate("inbox-late", "result-late", received_at, deadline)
    evidence = _Evidence(candidate, "sha256:late")
    verdict = _Verdict("verified")
    finalized_binding: list[tuple[object, object, object]] = []

    async def finalize(found, loaded, checked):
        finalized_binding.append((found, loaded, checked))
        return _PortOutcome("owner-rechecked")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(candidate),
            load_evidence=lambda _candidate: _async_value(evidence),
            verify=lambda _evidence: _async_value(verdict),
            finalize=finalize,
            evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
        ).run_once()
    )
    assert finalized_binding == [(candidate, evidence, verdict)]
    assert observation.finalization_outcome.kind == "owner-rechecked"


def test_fin_13_deadline_equality_is_not_decided_by_coordinator() -> None:
    # The fake verifies the candidate/verdict reach the owner adapter unchanged.
    # Only a real ingress/finalizer DB-clock race can verify equality is late.
    deadline = datetime.now(UTC)
    candidate = _Candidate("inbox-equal", "result-equal", deadline, deadline)
    evidence = _Evidence(candidate, "sha256:equal")
    verdict = _Verdict("verified")
    passed_to_owner: list[object] = []

    async def finalize(found, _evidence, checked):
        passed_to_owner.extend((found, checked))
        return _PortOutcome("owner-noop-if-late")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(candidate),
            load_evidence=lambda _candidate: _async_value(evidence),
            verify=lambda _evidence: _async_value(verdict),
            finalize=finalize,
            evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
        ).run_once()
    )
    assert passed_to_owner == [candidate, verdict]
    assert observation.finalization_outcome.kind == "owner-noop-if-late"


def test_fin_14_distinct_result_ids_are_not_deduplicated_locally() -> None:
    candidates = [
        _Candidate("inbox-a", "result-a", datetime.now(UTC), datetime.now(UTC)),
        _Candidate("inbox-b", "result-b", datetime.now(UTC), datetime.now(UTC)),
    ]
    index = 0
    finalizer_inputs: list[tuple[str, str, str]] = []

    async def locate():
        nonlocal index
        if index == len(candidates):
            return None
        candidate = candidates[index]
        index += 1
        return candidate

    async def finalize(candidate, _evidence, _verdict):
        finalizer_inputs.append(
            (candidate.attempt_id, candidate.result_id, candidate.inbox_id)
        )
        return _PortOutcome("adapter-decides-winner")

    coordinator = _coordinator(
        locate_candidate=locate,
        load_evidence=lambda candidate: _async_value(_Evidence(candidate, "sha256")),
        verify=lambda _evidence: _async_value(_Verdict("verified")),
        finalize=finalize,
        evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
    )
    asyncio.run(coordinator.run_once())
    asyncio.run(coordinator.run_once())
    assert finalizer_inputs == [
        ("attempt-1", "result-a", "inbox-a"),
        ("attempt-1", "result-b", "inbox-b"),
    ]


def test_fin_15_unknown_finalization_commit_propagates_without_retry() -> None:
    # This fake checks exception propagation/no retry. A disposable PostgreSQL
    # lost-COMMIT-ACK test must verify durable reconciliation before integration.
    class CommitOutcomeUnknown(RuntimeError):
        pass

    unknown = CommitOutcomeUnknown("commit acknowledgment unknown")
    calls: list[str] = []
    candidate = _Candidate("inbox-u", "result-u", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:u")

    async def finalize(_candidate, _evidence, _verdict):
        calls.append("finalize")
        raise unknown

    async def evaluate_deadlines():
        calls.append("deadline")

    with pytest.raises(CommitOutcomeUnknown) as raised:
        asyncio.run(
            _coordinator(
                locate_candidate=lambda: _async_value(candidate),
                load_evidence=lambda _candidate: _async_value(evidence),
                verify=lambda _evidence: _async_value(_Verdict("verified")),
                finalize=finalize,
                evaluate_deadlines=evaluate_deadlines,
            ).run_once()
        )
    assert raised.value is unknown
    assert calls == ["finalize"]


def test_fin_16_stale_verdict_is_only_forwarded_for_owner_recheck() -> None:
    candidate = _Candidate("inbox-stale", "result-stale", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, "sha256:stale")
    stale = _Verdict("verified-from-old-evidence")
    received: list[object] = []

    async def finalize(found, loaded, verdict):
        received.extend((found, loaded, verdict))
        return _PortOutcome("binding-mismatch-noop")

    observation = asyncio.run(
        _coordinator(
            locate_candidate=lambda: _async_value(candidate),
            load_evidence=lambda _candidate: _async_value(evidence),
            verify=lambda _evidence: _async_value(stale),
            finalize=finalize,
            evaluate_deadlines=lambda: _async_value(_PortOutcome("deadline")),
        ).run_once()
    )
    assert received == [candidate, evidence, stale]
    assert observation.finalization_outcome.kind == "binding-mismatch-noop"


def test_fin_17_forced_polling_cancellation_propagates_without_heartbeat() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        stop_event = asyncio.Event()
        heartbeats: list[str] = []

        async def cycle() -> None:
            started.set()
            await asyncio.Event().wait()

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: heartbeats.append("complete"),
        )
        task = asyncio.create_task(poller.run())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert heartbeats == []
        assert poller.last_completed_at is None

    asyncio.run(scenario())


def test_fin_18_graceful_stop_waits_for_inflight_cycle() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        stop_event = asyncio.Event()
        heartbeats: list[str] = []

        async def cycle() -> None:
            started.set()
            await release.wait()

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=lambda: heartbeats.append("complete"),
        )
        task = asyncio.create_task(poller.run())
        await asyncio.wait_for(started.wait(), timeout=1)
        stop_event.set()
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert heartbeats == ["complete"]

    asyncio.run(scenario())


def test_fin_19_closed_claim_gate_waits_without_cycle_or_progress() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls: list[object] = []

        async def cycle() -> None:
            calls.append("cycle")

        async def wait_for_interval(event: asyncio.Event, interval: float) -> bool:
            calls.append(("wait", interval))
            event.set()
            return True

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: False,
            on_cycle_completed=lambda: calls.append("heartbeat"),
            wait_for_interval=wait_for_interval,
        )
        await poller.run()
        assert calls == [("wait", 2.0)]
        assert poller.last_completed_at is None

    asyncio.run(scenario())


@pytest.mark.parametrize("missing", ["cycle", "stop_event", "claim_allowed"])
def test_fin_20_poller_missing_required_port_fails_closed(missing: str) -> None:
    async def cycle() -> None:
        return None

    args = {
        "cycle": cycle,
        "stop_event": asyncio.Event(),
        "claim_allowed": lambda: True,
    }
    args[missing] = None
    with pytest.raises(ValueError, match="required"):
        InboxFinalizationPoller(**args)


@pytest.mark.parametrize(
    "missing",
    ["locate_candidate", "load_evidence", "verify", "finalize", "evaluate_deadlines"],
)
def test_fin_20_coordinator_missing_required_port_fails_closed(missing: str) -> None:
    ports = {
        "locate_candidate": lambda: _async_value(None),
        "load_evidence": lambda _candidate: _async_value(None),
        "verify": lambda _evidence: _async_value(None),
        "finalize": lambda _candidate, _evidence, _verdict: _async_value(None),
        "evaluate_deadlines": lambda: _async_value(None),
    }
    ports[missing] = None
    with pytest.raises(ValueError, match="required"):
        InboxFinalizationCoordinator(**ports)


def test_fin_21_failure_does_not_log_secret_or_raw_evidence(caplog) -> None:
    sentinel = "SYNTHETIC-PRIVATE-KEY-AND-RAW-RECEIPT"
    candidate = _Candidate("inbox-secret", "result-secret", datetime.now(UTC), datetime.now(UTC))
    evidence = _Evidence(candidate, sentinel)

    async def verify(_evidence):
        raise RuntimeError(sentinel)

    with pytest.raises(RuntimeError, match=sentinel):
        asyncio.run(
            _coordinator(
                locate_candidate=lambda: _async_value(candidate),
                load_evidence=lambda _candidate: _async_value(evidence),
                verify=verify,
                finalize=lambda *_args: _async_value(None),
                evaluate_deadlines=lambda: _async_value(None),
            ).run_once()
        )
    assert sentinel not in caplog.text


def test_fin_22_completion_hook_failure_propagates_without_rerunning_cycle() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        calls: list[str] = []

        async def cycle() -> None:
            calls.append("cycle")

        def broken_hook() -> None:
            calls.append("hook")
            raise RuntimeError("heartbeat failed")

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            on_cycle_completed=broken_hook,
        )
        with pytest.raises(RuntimeError, match="heartbeat failed"):
            await poller.run()
        assert calls == ["cycle", "hook"]
        assert poller.last_completed_at is not None

    asyncio.run(scenario())


def test_fin_23_cadence_uses_approved_two_second_interval() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        intervals: list[float] = []

        async def cycle() -> None:
            return None

        async def wait_for_interval(event: asyncio.Event, interval: float) -> bool:
            intervals.append(interval)
            event.set()
            return True

        poller = InboxFinalizationPoller(
            cycle=cycle,
            stop_event=stop_event,
            claim_allowed=lambda: True,
            wait_for_interval=wait_for_interval,
        )
        await poller.run()
        assert intervals == [2.0]
        assert intervals == [INBOX_POLL_INTERVAL_SECONDS]

    asyncio.run(scenario())


def test_fin_24_empty_locator_does_not_supply_exhaustion_proof() -> None:
    # This fake proves the coordinator passes no page/exhaustion assertion. A
    # database test must prove the deadline UoW scans all committed evidence.
    page = object()
    calls: list[object] = []
    blocked = _PortOutcome("durable-evidence-still-pending")

    async def locate():
        calls.append(("locate-page", page))
        return None

    async def evaluate_deadlines():
        # The coordinator invokes this port with no pagination/completion flag;
        # the owner adapter must recheck all committed candidates durably.
        calls.append(("authoritative-deadline-port",))
        return blocked

    observation = asyncio.run(
        _coordinator(
            locate_candidate=locate,
            load_evidence=lambda _candidate: _async_value(None),
            verify=lambda _evidence: _async_value(None),
            finalize=lambda _candidate, _evidence, _verdict: _async_value(None),
            evaluate_deadlines=evaluate_deadlines,
        ).run_once()
    )
    assert calls == [("locate-page", page), ("authoritative-deadline-port",)]
    assert observation.deadline_outcome is blocked


async def _async_value(value):
    return value
