"""Deterministic properties of the Phase 2D FIFO policy."""

from dataclasses import replace
from itertools import permutations
from uuid import UUID

import pytest

from gpu_marketplace.manager.fifo_policy import (
    JobSnapshot,
    ListingSnapshot,
    PolicyAssessment,
    assess_fifo,
    assess_fifo_head,
)


LISTING = UUID(int=100)
# The newest Job deliberately has the smallest UUID. The queue sequence has gaps.
FIRST = JobSnapshot(UUID(int=9), LISTING, "QUEUED", 10, 4)
SECOND = JobSnapshot(UUID(int=4), LISTING, "QUEUED", 40, 1)
THIRD = JobSnapshot(UUID(int=1), LISTING, "QUEUED", 90, 2)
JOB_ORDERS = tuple(permutations((FIRST, SECOND, THIRD)))


@pytest.mark.parametrize("jobs", JOB_ORDERS, ids=lambda jobs: "-".join(str(j.enqueue_seq) for j in jobs))
@pytest.mark.parametrize("free", range(7))
def test_permutation_and_capacity_cannot_change_the_fifo_head(
    jobs: tuple[JobSnapshot, ...], free: int,
) -> None:
    listing = ListingSnapshot(LISTING, "ACTIVE", 6, 6 - free)
    decision = assess_fifo(listing, jobs)

    assert decision.head is FIRST
    assert decision.available_gpu_count == free
    assert decision == assess_fifo_head(listing, FIRST)
    if free < 4:
        assert decision.assessment is PolicyAssessment.HEAD_DOES_NOT_FIT
    else:
        assert decision.assessment is PolicyAssessment.ELIGIBLE


@pytest.mark.parametrize("jobs", JOB_ORDERS, ids=lambda jobs: "-".join(str(j.enqueue_seq) for j in jobs))
@pytest.mark.parametrize("cancelled_count", range(4))
def test_cancelling_a_prefix_advances_to_the_first_remaining_head(
    jobs: tuple[JobSnapshot, ...], cancelled_count: int,
) -> None:
    ordered = (FIRST, SECOND, THIRD)
    cancelled_ids = {job.job_id for job in ordered[:cancelled_count]}
    snapshots = tuple(replace(job, status="CANCELLED") if job.job_id in cancelled_ids else job
                      for job in jobs)
    listing = ListingSnapshot(LISTING, "ACTIVE", 6, 0)

    result = assess_fifo(listing, snapshots)

    if cancelled_count == len(ordered):
        assert result.head is None
        assert result.assessment is PolicyAssessment.EMPTY
    else:
        assert result.head is ordered[cancelled_count]
        assert result.assessment is PolicyAssessment.ELIGIBLE


@pytest.mark.parametrize("free", range(7))
def test_pausing_overrides_both_empty_and_fitting_fifo_cases(free: int) -> None:
    listing = ListingSnapshot(LISTING, "PAUSED", 6, 6 - free)

    for jobs in ((), (SECOND, FIRST, THIRD)):
        result = assess_fifo(listing, jobs)
        assert result.assessment is PolicyAssessment.LISTING_NOT_ACTIVE
        assert result.head is None
        assert result.available_gpu_count == free
