"""Unit tests for TV4-P2D-07; these are not PostgreSQL acceptance evidence."""

from dataclasses import replace
from itertools import permutations
from uuid import UUID

import pytest

from gpu_marketplace.manager.fifo_policy import (
    FifoDecision,
    JobSnapshot,
    ListingSnapshot,
    PolicyAssessment,
    assess_fifo,
    assess_fifo_head,
)


LISTING_ID = UUID(int=10)
LISTING = ListingSnapshot(LISTING_ID, "ACTIVE", total_gpu_count=4, allocated_gpu_count=0)


def job(
    seq: int,
    requested: int = 1,
    *,
    job_id: int | None = None,
    status: str = "QUEUED",
    listing_id: UUID = LISTING_ID,
) -> JobSnapshot:
    return JobSnapshot(
        job_id=UUID(int=seq if job_id is None else job_id),
        listing_id=listing_id,
        status=status,  # type: ignore[arg-type]
        enqueue_seq=seq,
        requested_gpu_count=requested,
    )


def test_fifo_uses_enqueue_seq_independent_of_input_and_uuid_order() -> None:
    head = job(3, job_id=999)
    jobs = (head, job(10, job_id=1), job(1000, job_id=2))

    for order in permutations(jobs):
        decision = assess_fifo(LISTING, iter(order))
        assert decision == FifoDecision(PolicyAssessment.ELIGIBLE, LISTING_ID, 4, head)


def test_runtime_boundary_assesses_exact_authoritative_queued_head() -> None:
    head = job(1, 2)
    decision = assess_fifo_head(replace(LISTING, allocated_gpu_count=2), head)
    assert decision == FifoDecision(PolicyAssessment.ELIGIBLE, LISTING_ID, 2, head)


def test_runtime_boundary_accepts_authoritative_no_head() -> None:
    decision = assess_fifo_head(LISTING, None)
    assert decision == FifoDecision(PolicyAssessment.EMPTY, LISTING_ID, 4, None)


def test_runtime_boundary_rejects_nonqueued_or_foreign_head() -> None:
    with pytest.raises(ValueError, match="QUEUED"):
        assess_fifo_head(LISTING, job(1, status="CANCELLED"))
    with pytest.raises(ValueError, match="another Listing"):
        assess_fifo_head(LISTING, job(1, listing_id=UUID(int=11)))


def test_unfittable_head_blocks_smaller_later_job_without_backfill() -> None:
    listing = replace(LISTING, allocated_gpu_count=2)
    head, later = job(1, 4), job(2, 1)

    decision = assess_fifo(listing, [later, head])

    assert decision.assessment is PolicyAssessment.HEAD_DOES_NOT_FIT
    assert decision.head == head
    assert decision.available_gpu_count == 2


def test_paused_listing_is_ineligible_even_with_fitting_queued_job() -> None:
    listing = replace(LISTING, status="PAUSED")
    decision = assess_fifo(listing, [job(1)])
    assert decision.assessment is PolicyAssessment.LISTING_NOT_ACTIVE
    assert decision.head is None


def test_cancelled_head_is_skipped_and_next_queued_job_is_assessed() -> None:
    cancelled = job(1, status="CANCELLED")
    queued = job(2, 2)
    decision = assess_fifo(LISTING, [queued, cancelled])
    assert decision.assessment is PolicyAssessment.ELIGIBLE
    assert decision.head == queued


def test_running_and_terminal_jobs_do_not_count_as_queued_head() -> None:
    jobs = [job(1, status="RUNNING"), job(2, status="COMPLETED"), job(3, status="FAILED")]
    decision = assess_fifo(LISTING, jobs)
    assert decision.assessment is PolicyAssessment.EMPTY
    assert decision.head is None


def test_capacity_exact_fit_is_eligible_and_zero_free_blocks_positive_request() -> None:
    exact_fit = replace(LISTING, allocated_gpu_count=2)
    no_free = replace(LISTING, allocated_gpu_count=4)
    assert assess_fifo(exact_fit, [job(1, 2)]).assessment is PolicyAssessment.ELIGIBLE
    assert assess_fifo(no_free, [job(1)]).assessment is PolicyAssessment.HEAD_DOES_NOT_FIT


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ListingSnapshot(LISTING_ID, "ACTIVE", True, 0),
        lambda: ListingSnapshot(LISTING_ID, "ACTIVE", 2, False),
        lambda: job(True),
        lambda: job(1, True),
    ],
)
def test_boolean_values_are_not_accepted_as_integer_counts_or_sequence(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_listing_mismatch_and_duplicate_job_identity_or_sequence_are_rejected() -> None:
    with pytest.raises(ValueError, match="another Listing"):
        assess_fifo(LISTING, [job(1, listing_id=UUID(int=11))])
    with pytest.raises(ValueError, match="Duplicate"):
        assess_fifo(LISTING, [job(1, job_id=20), job(2, job_id=20)])
    with pytest.raises(ValueError, match="Duplicate"):
        assess_fifo(LISTING, [job(1, job_id=20), job(1, job_id=21)])


def test_snapshot_is_immutable_and_decision_never_claims_allocation_commit() -> None:
    decision = assess_fifo(LISTING, [job(1)])
    with pytest.raises((AttributeError, TypeError)):
        decision.assessment = PolicyAssessment.EMPTY  # type: ignore[misc]
    assert {item.value for item in PolicyAssessment} == {
        "ELIGIBLE",
        "EMPTY",
        "HEAD_DOES_NOT_FIT",
        "LISTING_NOT_ACTIVE",
    }
