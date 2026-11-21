"""TV4-P2D-07/15 policy tests, not PostgreSQL P2D-TX/RACE/SCHED evidence."""

from dataclasses import replace
from itertools import permutations
from uuid import UUID

import pytest

from gpu_marketplace.manager.fifo_policy import (
    FifoDisposition,
    JobSnapshot,
    ListingSnapshot,
    assess_fifo,
)


LISTING = ListingSnapshot(UUID(int=10), "ACTIVE", 4, 0)


def queued(seq: int, gpus: int = 1, *, job_id: int | None = None) -> JobSnapshot:
    return JobSnapshot(
        UUID(int=job_id if job_id is not None else seq),
        LISTING.listing_id,
        "QUEUED",
        seq,
        gpus,
    )


def test_fifo_is_independent_of_input_order_uuid_order_and_sequence_gaps() -> None:
    head = queued(3, job_id=999)
    jobs = [head, queued(10, job_id=1), queued(1000, job_id=2)]
    # No timestamp input exists: tied submitted_at values cannot break FIFO.
    for order in permutations(jobs):
        result = assess_fifo(LISTING, iter(order))
        assert result.disposition is FifoDisposition.ELIGIBLE
        assert result.head == head
        assert result.listing_id == LISTING.listing_id


def test_unfittable_head_blocks_a_smaller_later_job() -> None:
    listing = replace(LISTING, allocated_gpu_count=2)
    head, tail = queued(1, 4), queued(2, 1)
    result = assess_fifo(listing, [tail, head])
    assert result.disposition is FifoDisposition.BLOCKED_CAPACITY
    assert result.head == head
    assert result.free_gpu_count == 2


@pytest.mark.parametrize(
    ("free", "requested"), [(free, n) for free in range(5) for n in range(1, 5)]
)
def test_capacity_boundary_uses_total_minus_current_allocated(
    free: int, requested: int
) -> None:
    listing = replace(LISTING, allocated_gpu_count=4 - free)
    head = queued(1, requested)
    result = assess_fifo(listing, [head])
    expected = (
        FifoDisposition.ELIGIBLE
        if requested <= free
        else FifoDisposition.BLOCKED_CAPACITY
    )
    assert result.disposition is expected
    assert result.head == head
    assert result.free_gpu_count == free


def test_cancelled_head_exposes_next_queued_job_and_ignores_other_states() -> None:
    jobs = [
        replace(queued(1), status="CANCELLED"),
        replace(queued(2), status="RUNNING"),
        replace(queued(3), status="COMPLETED"),
        replace(queued(4), status="FAILED"),
        queued(5),
        queued(6),
    ]
    result = assess_fifo(LISTING, jobs)
    assert result.disposition is FifoDisposition.ELIGIBLE
    assert result.head == jobs[4]


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_only_nonqueued_jobs_mean_empty_queue(status: str) -> None:
    result = assess_fifo(LISTING, [replace(queued(1), status=status)])
    assert result.disposition is FifoDisposition.EMPTY_QUEUE
    assert result.head is None


def test_empty_queue_remains_empty_even_when_capacity_is_fully_allocated() -> None:
    result = assess_fifo(replace(LISTING, allocated_gpu_count=4), [])
    assert result.disposition is FifoDisposition.EMPTY_QUEUE
    assert result.free_gpu_count == 0
    assert result.head is None


def test_pause_skips_job_read_and_resume_allows_later_assessment() -> None:
    def unavailable_jobs():
        raise AssertionError("PAUSED must not inspect Jobs for new allocation")
        yield

    paused = replace(LISTING, status="PAUSED", allocated_gpu_count=1)
    result = assess_fifo(paused, unavailable_jobs())
    assert result.disposition is FifoDisposition.INACTIVE_LISTING
    assert result.head is None
    assert result.free_gpu_count == 3
    assert (
        assess_fifo(replace(paused, status="ACTIVE"), [queued(1)]).disposition
        is FifoDisposition.ELIGIBLE
    )


def test_blocked_listing_does_not_affect_assessment_of_another_listing() -> None:
    blocked = assess_fifo(replace(LISTING, allocated_gpu_count=3), [queued(1, 4)])
    other = replace(LISTING, listing_id=UUID(int=11))
    other_head = replace(queued(2), listing_id=other.listing_id)
    eligible = assess_fifo(other, [other_head])
    assert blocked.disposition is FifoDisposition.BLOCKED_CAPACITY
    assert eligible.disposition is FifoDisposition.ELIGIBLE
    assert eligible.head == other_head


def test_reassessment_uses_new_capacity_and_does_not_reserve_or_mutate_inputs() -> None:
    listing = replace(LISTING, allocated_gpu_count=3)
    jobs = [queued(1, 2), queued(2)]
    before = (listing, tuple(jobs))
    first = assess_fifo(listing, jobs)
    assert assess_fifo(listing, jobs) == first
    assert (listing, tuple(jobs)) == before
    assert first.disposition is FifoDisposition.BLOCKED_CAPACITY
    assert (
        assess_fifo(replace(listing, allocated_gpu_count=2), jobs).disposition
        is FifoDisposition.ELIGIBLE
    )


def test_two_successive_allocations_require_new_committed_state_snapshots() -> None:
    head, tail = queued(1, 2), queued(2, 3)
    assert assess_fifo(LISTING, [head, tail]).head == head
    # Model the state TV2 would commit; the oracle itself performs no writes.
    after = replace(LISTING, allocated_gpu_count=2)
    jobs_after = [replace(head, status="RUNNING"), tail]
    result = assess_fifo(after, jobs_after)
    assert result.head == tail
    assert result.disposition is FifoDisposition.BLOCKED_CAPACITY


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_gpu_count", 0),
        ("total_gpu_count", 2**31),
        ("total_gpu_count", True),
        ("allocated_gpu_count", -1),
        ("allocated_gpu_count", 5),
        ("allocated_gpu_count", False),
        ("allocated_gpu_count", 1.5),
        ("status", "DELETED"),
        ("listing_id", "not-a-uuid"),
    ],
)
def test_invalid_listing_snapshot_fails_closed(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        assess_fifo(replace(LISTING, **{field: value}), [])


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested_gpu_count", 0),
        ("requested_gpu_count", -1),
        ("requested_gpu_count", 2**31),
        ("requested_gpu_count", True),
        ("enqueue_seq", True),
        ("enqueue_seq", 1.5),
        ("enqueue_seq", -(2**63) - 1),
        ("enqueue_seq", 2**63),
        ("status", "UNKNOWN"),
        ("job_id", "not-a-uuid"),
    ],
)
def test_invalid_job_snapshot_fails_closed(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        assess_fifo(LISTING, [replace(queued(1), **{field: value})])


@pytest.mark.parametrize("seq", [-(2**63), 0, 2**63 - 1])
def test_policy_uses_database_bigint_order_without_inventing_positive_sequence_check(
    seq: int,
) -> None:
    head = replace(queued(1), enqueue_seq=seq)
    assert assess_fifo(LISTING, [head]).head == head


def test_wrong_listing_and_duplicate_database_identities_fail_closed() -> None:
    head = queued(1)
    invalid_queues = [
        [replace(head, listing_id=UUID(int=999))],
        [head, replace(queued(2), job_id=head.job_id)],
        [head, replace(queued(2), enqueue_seq=head.enqueue_seq)],
    ]
    for jobs in invalid_queues:
        with pytest.raises(ValueError):
            assess_fifo(LISTING, jobs)
