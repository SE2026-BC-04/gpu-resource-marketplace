"""Unit checks for TV4's side of the proposed TX-ALLOCATE boundary."""

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from gpu_marketplace.manager.fifo_policy import (
    JobSnapshot,
    ListingSnapshot,
    ListingStatus,
    PolicyAssessment,
    assess_fifo_head,
)


LISTING_ID = UUID(int=1)
HEAD_ID = UUID(int=2)


def queued_head(listing_id: UUID, requested: int) -> JobSnapshot:
    return JobSnapshot(HEAD_ID, listing_id, "QUEUED", 100, requested)


@pytest.mark.parametrize(
    ("listing_status", "requested", "assessment", "returns_head"),
    [
        pytest.param("ACTIVE", 2, PolicyAssessment.ELIGIBLE, True, id="exact-fit"),
        pytest.param("ACTIVE", 4, PolicyAssessment.HEAD_DOES_NOT_FIT, True, id="oversized-head"),
        pytest.param("ACTIVE", None, PolicyAssessment.EMPTY, False, id="empty"),
        pytest.param("PAUSED", 1, PolicyAssessment.LISTING_NOT_ACTIVE, False, id="paused"),
        pytest.param("PAUSED", None, PolicyAssessment.LISTING_NOT_ACTIVE, False, id="paused-empty"),
    ],
)
def test_assesses_the_supplied_transaction_snapshot(
    listing_status: ListingStatus,
    requested: int | None,
    assessment: PolicyAssessment,
    returns_head: bool,
) -> None:
    listing = ListingSnapshot(LISTING_ID, listing_status, 6, 4)
    head = None if requested is None else queued_head(LISTING_ID, requested)

    result = assess_fifo_head(listing, head)

    assert result.assessment is assessment
    assert result.listing_id == LISTING_ID
    assert result.available_gpu_count == 2
    assert result.head is (head if returns_head else None)


def test_blocked_head_does_not_affect_an_independent_listing() -> None:
    other_id = UUID(int=3)
    blocked = assess_fifo_head(
        ListingSnapshot(LISTING_ID, "ACTIVE", 6, 4), queued_head(LISTING_ID, 4),
    )
    other = assess_fifo_head(
        ListingSnapshot(other_id, "ACTIVE", 6, 4),
        JobSnapshot(UUID(int=4), other_id, "QUEUED", 101, 2),
    )

    assert blocked.assessment is PolicyAssessment.HEAD_DOES_NOT_FIT
    assert blocked.head is not None and blocked.head.job_id == HEAD_ID
    assert other.assessment is PolicyAssessment.ELIGIBLE
    assert other.listing_id == other_id


@pytest.mark.parametrize(
    "head",
    [
        pytest.param(queued_head(UUID(int=3), 1), id="wrong-listing"),
        pytest.param(JobSnapshot(HEAD_ID, LISTING_ID, "RUNNING", 100, 1), id="nonqueued"),
    ],
)
def test_invalid_authoritative_head_is_rejected(head: JobSnapshot) -> None:
    listing = ListingSnapshot(LISTING_ID, "ACTIVE", 6, 4)

    with pytest.raises(ValueError):
        assess_fifo_head(listing, head)


def test_snapshot_does_not_allow_policy_to_mutate_capacity_or_job_state() -> None:
    listing = ListingSnapshot(LISTING_ID, "ACTIVE", 6, 4)
    head = queued_head(LISTING_ID, 1)

    with pytest.raises(FrozenInstanceError):
        setattr(listing, "allocated_gpu_count", 5)
    with pytest.raises(FrozenInstanceError):
        setattr(head, "status", "RUNNING")

    assert assess_fifo_head(listing, head).assessment is PolicyAssessment.ELIGIBLE
