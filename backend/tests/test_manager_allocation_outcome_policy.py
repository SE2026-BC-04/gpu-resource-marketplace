from unittest.mock import Mock, sentinel
from uuid import UUID

import pytest

from gpu_marketplace.manager.allocation_outcome_policy import map_fifo_no_write
from gpu_marketplace.manager.fifo_policy import (
    JobSnapshot,
    ListingSnapshot,
    ListingStatus,
    assess_fifo_head,
)


@pytest.mark.parametrize(
    ("status", "requested", "target", "reason"),
    [
        pytest.param("ACTIVE", None, "noop", "NO_QUEUED_HEAD", id="empty"),
        pytest.param("ACTIVE", 3, "blocked", "HEAD_DOES_NOT_FIT", id="oversized"),
        pytest.param("PAUSED", 1, "blocked", "LISTING_NOT_ACTIVE", id="paused"),
        pytest.param("ACTIVE", 2, None, None, id="eligible"),
    ],
)
def test_maps_fifo_assessment_through_only_its_owner_constructor(
    status: ListingStatus,
    requested: int | None,
    target: str | None,
    reason: str | None,
) -> None:
    listing = ListingSnapshot(UUID(int=1), status, 4, 2)
    head = (
        None
        if requested is None
        else JobSnapshot(UUID(int=2), listing.listing_id, "QUEUED", 1, requested)
    )
    assessment = assess_fifo_head(listing, head).assessment
    blocked = Mock(return_value=sentinel.blocked)
    noop = Mock(return_value=sentinel.noop)

    result = map_fifo_no_write(assessment, blocked=blocked, noop=noop)

    if target == "blocked":
        assert result is sentinel.blocked
        blocked.assert_called_once_with(reason)
        noop.assert_not_called()
    elif target == "noop":
        assert result is sentinel.noop
        noop.assert_called_once_with(reason)
        blocked.assert_not_called()
    else:
        assert result is None
        blocked.assert_not_called()
        noop.assert_not_called()


@pytest.mark.parametrize("assessment", ["EMPTY", "LOCK_BUSY", "ALLOCATED", None])
def test_rejects_non_policy_outcomes(assessment: object) -> None:
    blocked, noop = Mock(), Mock()

    with pytest.raises(ValueError, match="Unknown FIFO policy assessment"):
        map_fifo_no_write(assessment, blocked=blocked, noop=noop)  # type: ignore[arg-type]

    blocked.assert_not_called()
    noop.assert_not_called()


def test_constructor_failure_propagates_without_fallback_or_retry() -> None:
    listing = ListingSnapshot(UUID(int=1), "ACTIVE", 4, 2)
    assessment = assess_fifo_head(listing, None).assessment
    error = RuntimeError("constructor failed")
    blocked = Mock()
    noop = Mock(side_effect=error)

    with pytest.raises(RuntimeError) as caught:
        map_fifo_no_write(assessment, blocked=blocked, noop=noop)

    assert caught.value is error
    noop.assert_called_once_with("NO_QUEUED_HEAD")
    blocked.assert_not_called()
