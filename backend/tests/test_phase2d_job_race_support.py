"""Prove the snapshot assertion rejects broken fixtures without invoking SQL."""

from dataclasses import replace
from uuid import UUID

import pytest

from phase2d_job_race_support import (
    AllocationRow,
    AttemptRow,
    HeadStatus,
    JobRaceSnapshot,
    OutboxRow,
    assert_head_race_snapshot,
)


LISTING, HEAD, LATER, ATTEMPT, EVENT = (UUID(int=value) for value in range(1, 6))


def snapshot() -> JobRaceSnapshot:
    return JobRaceSnapshot(
        listing_id=LISTING,
        total_gpu_count=4,
        allocated_gpu_count=3,
        job_statuses={HEAD: "RUNNING", LATER: "QUEUED"},
        allocations=(AllocationRow(HEAD, LISTING, 3, "ACTIVE"),),
        attempts=(AttemptRow(HEAD, ATTEMPT),),
        outbox=(OutboxRow(ATTEMPT, EVENT, "EXECUTE_JOB"),),
    )


def check(state: JobRaceSnapshot, head_status: HeadStatus = "RUNNING") -> None:
    assert_head_race_snapshot(
        state,
        head_id=HEAD,
        head_status=head_status,
        requested_gpu_count=3,
        later_job_ids=(LATER,),
    )


def test_accepts_one_graph_for_the_original_head() -> None:
    check(snapshot())


@pytest.mark.parametrize("head_status", ["QUEUED", "CANCELLED"])
def test_no_write_paths_require_empty_graph(head_status: HeadStatus) -> None:
    settled = JobRaceSnapshot(LISTING, 4, 0, {HEAD: head_status, LATER: "QUEUED"})

    check(settled, head_status)

    leaked_attempt = replace(settled, attempts=(AttemptRow(HEAD, ATTEMPT),))
    with pytest.raises(AssertionError, match="unexpected Allocation, Attempt or Outbox"):
        check(leaked_attempt, head_status)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        pytest.param({"job_statuses": {HEAD: "RUNNING", LATER: "RUNNING"}}, "FIFO bypass", id="later-started"),
        pytest.param({"allocated_gpu_count": 2}, "ACTIVE rows differ", id="counter-drift"),
        pytest.param({"total_gpu_count": 2}, "out of bounds", id="overcommit"),
        pytest.param({"outbox": ()}, "exactly one", id="missing-outbox"),
        pytest.param(
            {
                "total_gpu_count": 8,
                "allocated_gpu_count": 6,
                "allocations": (AllocationRow(HEAD, LISTING, 3, "ACTIVE"),) * 2,
            },
            "exactly one",
            id="duplicate-allocation",
        ),
        pytest.param(
            {"attempts": (AttemptRow(HEAD, ATTEMPT), AttemptRow(HEAD, UUID(int=6)))},
            "exactly one",
            id="duplicate-attempt",
        ),
        pytest.param(
            {"allocations": (AllocationRow(HEAD, UUID(int=6), 3, "ACTIVE"),)},
            "not bound",
            id="wrong-listing",
        ),
        pytest.param({"attempts": (AttemptRow(LATER, ATTEMPT),)}, "another Job", id="wrong-job"),
        pytest.param(
            {"outbox": (OutboxRow(UUID(int=6), EVENT, "EXECUTE_JOB"),)},
            "another Attempt",
            id="wrong-attempt",
        ),
        pytest.param(
            {"outbox": (OutboxRow(ATTEMPT, EVENT, "OTHER"),)},
            "unexpected Outbox event type",
            id="wrong-event-type",
        ),
    ],
)
def test_rejects_invalid_committed_snapshots(changes: dict[str, object], message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        check(replace(snapshot(), **changes))
