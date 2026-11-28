"""Assertions on committed snapshots for TV4-P2D-12 test fixtures.

The fixture owns a fresh Listing and its test Jobs. A future adapter supplies
snapshots from a fresh read after both real transactions have finished.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


HeadStatus = Literal["QUEUED", "CANCELLED", "RUNNING"]


@dataclass(frozen=True, slots=True)
class AllocationRow:
    job_id: UUID
    listing_id: UUID
    gpu_count: int
    state: str


@dataclass(frozen=True, slots=True)
class AttemptRow:
    job_id: UUID
    attempt_id: UUID


@dataclass(frozen=True, slots=True)
class OutboxRow:
    attempt_id: UUID
    event_id: UUID
    event_type: str


@dataclass(frozen=True, slots=True)
class JobRaceSnapshot:
    listing_id: UUID
    total_gpu_count: int
    allocated_gpu_count: int
    job_statuses: Mapping[UUID, str]
    allocations: tuple[AllocationRow, ...] = ()
    attempts: tuple[AttemptRow, ...] = ()
    outbox: tuple[OutboxRow, ...] = ()


def assert_head_race_snapshot(
    snapshot: JobRaceSnapshot,
    *,
    head_id: UUID,
    head_status: HeadStatus,
    requested_gpu_count: int,
    later_job_ids: Sequence[UUID] = (),
) -> None:
    """Check zero effects or one linked graph for the original FIFO head."""
    assert head_id not in later_job_ids, "fixture must identify the original head separately"
    expected_statuses = {job_id: "QUEUED" for job_id in later_job_ids}
    expected_statuses[head_id] = head_status
    assert snapshot.job_statuses == expected_statuses, "unexpected Job state or FIFO bypass"
    assert (
        0 <= snapshot.allocated_gpu_count <= snapshot.total_gpu_count
    ), "Listing capacity is out of bounds"
    active_total = sum(row.gpu_count for row in snapshot.allocations if row.state == "ACTIVE")
    assert snapshot.allocated_gpu_count == active_total, "Listing counter and ACTIVE rows differ"

    if head_status != "RUNNING":
        assert not snapshot.allocations and not snapshot.attempts and not snapshot.outbox, (
            "unexpected Allocation, Attempt or Outbox rows"
        )
        return

    assert len(snapshot.allocations) == len(snapshot.attempts) == len(snapshot.outbox) == 1, (
        "expected exactly one Allocation, Attempt and Outbox row"
    )
    (allocation,) = snapshot.allocations
    (attempt,) = snapshot.attempts
    (event,) = snapshot.outbox
    assert allocation == AllocationRow(head_id, snapshot.listing_id, requested_gpu_count, "ACTIVE"), (
        "reservation is not bound to the expected Job, Listing and GPU count"
    )
    assert attempt.job_id == head_id, "Attempt belongs to another Job"
    assert event.attempt_id == attempt.attempt_id, "Outbox belongs to another Attempt"
    assert event.event_type == "EXECUTE_JOB", "unexpected Outbox event type"
