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
    """Return the FIFO/capacity assessment for the true queued head.

    The caller must supply authoritative snapshots and, for runtime use, obtain
    the queued head under the transaction's agreed locks. This function cannot
    detect an omitted earlier queued Job. Non-queued Jobs (including CANCELLED)
    are excluded before choosing the minimum ``enqueue_seq``.
    """
    available = listing.total_gpu_count - listing.allocated_gpu_count
    if listing.status == "PAUSED":
        return FifoDecision(PolicyAssessment.LISTING_NOT_ACTIVE, listing.listing_id, available, None)

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

    if head is None:
        return FifoDecision(PolicyAssessment.EMPTY, listing.listing_id, available, None)
    if head.requested_gpu_count > available:
        return FifoDecision(PolicyAssessment.HEAD_DOES_NOT_FIT, listing.listing_id, available, head)
    return FifoDecision(PolicyAssessment.ELIGIBLE, listing.listing_id, available, head)
