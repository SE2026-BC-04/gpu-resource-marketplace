"""DB-free FIFO/capacity oracle for Phase 2D; not an allocation transaction.

These local snapshots/results are not the unacknowledged TX-ALLOCATE port.
TV2 must obtain current rows under Listing -> Job locks, confirm signer readiness,
and commit all allocation effects atomically before reporting an allocation.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import UUID


ListingStatus = Literal["ACTIVE", "PAUSED"]
JobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]


def _integer_in_range(value: int, minimum: int, maximum: int, field: str) -> None:
    # bool is an int subclass, but is not a valid persisted GPU count/sequence.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Invalid {field}")


@dataclass(frozen=True)
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
        _integer_in_range(self.total_gpu_count, 1, 2**31 - 1, "total_gpu_count")
        _integer_in_range(
            self.allocated_gpu_count, 0, self.total_gpu_count, "allocated_gpu_count"
        )


@dataclass(frozen=True)
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
        _integer_in_range(self.enqueue_seq, -(2**63), 2**63 - 1, "enqueue_seq")
        _integer_in_range(self.requested_gpu_count, 1, 2**31 - 1, "requested_gpu_count")


class FifoDisposition(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EMPTY_QUEUE = "EMPTY_QUEUE"
    BLOCKED_CAPACITY = "BLOCKED_CAPACITY"
    INACTIVE_LISTING = "INACTIVE_LISTING"


@dataclass(frozen=True)
class FifoAssessment:
    disposition: FifoDisposition
    listing_id: UUID
    free_gpu_count: int
    head: JobSnapshot | None


def assess_fifo(
    listing: ListingSnapshot, jobs: Iterable[JobSnapshot]
) -> FifoAssessment:
    """Assess at most one QUEUED head without changing any state.

    Input order, UUID order and timestamps never determine FIFO. The supplied
    snapshots must include the true queued head; an omitted earlier Job cannot
    be detected here. An empty QUEUED set is authoritative only if its source is.
    The future DB adapter must select ORDER BY enqueue_seq LIMIT 1 FOR UPDATE
    after locking the Listing, without Job SKIP LOCKED. It need not load the
    whole queue to use this oracle; unit tests may supply a model queue.

    ELIGIBLE means only that FIFO/capacity allow this head. It does not establish
    signer readiness, reserve GPUs, prove lock ownership or authorize dispatch.
    """
    free_gpu_count = listing.total_gpu_count - listing.allocated_gpu_count
    if listing.status == "PAUSED":
        return FifoAssessment(
            FifoDisposition.INACTIVE_LISTING, listing.listing_id, free_gpu_count, None
        )

    head: JobSnapshot | None = None
    job_ids: set[UUID] = set()
    sequences: set[int] = set()
    for job in jobs:
        if job.listing_id != listing.listing_id:
            raise ValueError("Job belongs to another Listing")
        if job.job_id in job_ids or job.enqueue_seq in sequences:
            raise ValueError("Duplicate Job identity or enqueue_seq")
        job_ids.add(job.job_id)
        sequences.add(job.enqueue_seq)
        if job.status == "QUEUED" and (
            head is None or job.enqueue_seq < head.enqueue_seq
        ):
            head = job

    if head is None:
        disposition = FifoDisposition.EMPTY_QUEUE
    elif head.requested_gpu_count > free_gpu_count:
        disposition = FifoDisposition.BLOCKED_CAPACITY
    else:
        disposition = FifoDisposition.ELIGIBLE
    return FifoAssessment(disposition, listing.listing_id, free_gpu_count, head)
