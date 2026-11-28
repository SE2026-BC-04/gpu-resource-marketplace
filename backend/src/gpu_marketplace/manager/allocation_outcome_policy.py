"""TV4's provisional adapter from FIFO assessment to no-write outcomes."""

from collections.abc import Callable
from typing import Literal, TypeVar

from gpu_marketplace.manager.fifo_policy import PolicyAssessment


_BlockedT = TypeVar("_BlockedT")
_NoopT = TypeVar("_NoopT")


def map_fifo_no_write(
    assessment: PolicyAssessment,
    *,
    blocked: Callable[[Literal["HEAD_DOES_NOT_FIT", "LISTING_NOT_ACTIVE"]], _BlockedT],
    noop: Callable[[Literal["NO_QUEUED_HEAD"]], _NoopT],
) -> _BlockedT | _NoopT | None:
    """Use the caller's outcome constructors for policy-only no-write paths.

    None means the FIFO check found no reason to block. It is not a
    transaction outcome. The caller owns all remaining guards and publishes
    its outcome only after transaction cleanup.
    """
    if assessment is PolicyAssessment.HEAD_DOES_NOT_FIT:
        return blocked("HEAD_DOES_NOT_FIT")
    if assessment is PolicyAssessment.LISTING_NOT_ACTIVE:
        return blocked("LISTING_NOT_ACTIVE")
    if assessment is PolicyAssessment.EMPTY:
        return noop("NO_QUEUED_HEAD")
    if assessment is PolicyAssessment.ELIGIBLE:
        return None
    raise ValueError("Unknown FIFO policy assessment")
