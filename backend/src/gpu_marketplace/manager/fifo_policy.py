"""Pure FIFO and capacity assessment for one Listing.

This module consumes immutable scalar snapshots only. It does not query or
mutate the database and does not claim that an allocation has committed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID


ListingStatus = Literal["ACTIVE", "PAUSED"]
JobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]


def _require_int(value: object, *, minimum: int, maximum: int, field: str) -> None:
    # bool subclasses int, but is never a valid persisted sequence or count.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid {field}")


@dataclass(frozen=True, slots=True)
class ListingSnapshot:
    listing_id: UUID
    status: ListingStatus
    total_gpu_count: int
    allocated_gpu_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, UUID):
            raise ValueError("Invalid listing_id")
        if self.status not in ("ACTIVE", "PAUSED"):
            raise ValueError("Invalid Listing status")
        _require_int(self.total_gpu_count, minimum=1, maximum=2**31 - 1, field="total_gpu_count")
        _require_int(
            self.allocated_gpu_count,
            minimum=0,
            maximum=self.total_gpu_count,
            field="allocated_gpu_count",
        )


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: UUID
    listing_id: UUID
    status: JobStatus
    enqueue_seq: int
    requested_gpu_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, UUID) or not isinstance(self.listing_id, UUID):
            raise ValueError("Invalid Job identity")
        if self.status not in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
            raise ValueError("Invalid Job status")
        _require_int(self.enqueue_seq, minimum=-(2**63), maximum=2**63 - 1, field="enqueue_seq")
        _require_int(
            self.requested_gpu_count,
            minimum=1,
            maximum=2**31 - 1,
            field="requested_gpu_count",
        )


class PolicyAssessment(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EMPTY = "EMPTY"
    HEAD_DOES_NOT_FIT = "HEAD_DOES_NOT_FIT"
    LISTING_NOT_ACTIVE = "LISTING_NOT_ACTIVE"


@dataclass(frozen=True, slots=True)
class FifoDecision:
    assessment: PolicyAssessment
    listing_id: UUID
    available_gpu_count: int
    head: JobSnapshot | None


def assess_fifo(
    listing: ListingSnapshot, jobs: Iterable[JobSnapshot]
) -> FifoDecision:
    """Pure multi-row oracle for unit tests; runtime should pass one locked head.

    This helper can find the minimum queued ``enqueue_seq`` in the supplied
    iterable, but cannot detect an omitted earlier row. Do not traverse a queue
    from the runtime transaction; use :func:`assess_fifo_head` with the one
    authoritative queued head TV2 selected under the agreed locks, or ``None``.
    """
    head: JobSnapshot | None = None
    seen_ids: set[UUID] = set()
    seen_sequences: set[int] = set()
    for job in jobs:
        if not isinstance(job, JobSnapshot):
            raise ValueError("jobs must contain JobSnapshot values")
        if job.listing_id != listing.listing_id:
            raise ValueError("Job belongs to another Listing")
        if job.job_id in seen_ids or job.enqueue_seq in seen_sequences:
            raise ValueError("Duplicate Job identity or enqueue_seq")
        seen_ids.add(job.job_id)
        seen_sequences.add(job.enqueue_seq)
        if job.status == "QUEUED" and (head is None or job.enqueue_seq < head.enqueue_seq):
            head = job

    return assess_fifo_head(listing, head)


def assess_fifo_head(
    listing: ListingSnapshot, head: JobSnapshot | None
) -> FifoDecision:
    """Assess one authoritative QUEUED head (or an authoritative empty queue).

    Runtime callers must have TV2 select the actual head by ``enqueue_seq``
    under Listing → Job locks (Worker advisory lock first where applicable),
    without Job ``SKIP LOCKED``. This function accepts no ORM/session and does
    not make database or allocation decisions.
    """
    available = listing.total_gpu_count - listing.allocated_gpu_count
    if head is not None:
        if not isinstance(head, JobSnapshot):
            raise ValueError("head must be a JobSnapshot or None")
        if head.listing_id != listing.listing_id:
            raise ValueError("Job belongs to another Listing")
        if head.status != "QUEUED":
            raise ValueError("head must be QUEUED")
    if listing.status == "PAUSED":
        return FifoDecision(PolicyAssessment.LISTING_NOT_ACTIVE, listing.listing_id, available, None)
    if head is None:
        return FifoDecision(PolicyAssessment.EMPTY, listing.listing_id, available, None)
    if head.requested_gpu_count > available:
        return FifoDecision(PolicyAssessment.HEAD_DOES_NOT_FIT, listing.listing_id, available, head)
    return FifoDecision(PolicyAssessment.ELIGIBLE, listing.listing_id, available, head)
