"""Test assertions for committed snapshots of a PAUSED dispatch retry."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrySnapshot:
    listing_status: str
    job_status: str
    listing_id: UUID
    job_id: UUID
    allocation_ids: tuple[UUID, ...]
    attempt_id: UUID
    event_id: UUID
    dispatch_payload: bytes
    finish_due_at: datetime
    hard_deadline_at: datetime
    allocated_gpu_count: int


@dataclass(frozen=True, slots=True)
class LeaseSnapshot:
    event_id: UUID
    owner: str | None
    version: int
    state: str
    lease_until: datetime | None
    next_retry_at: datetime
    delivery_attempts: int


def assert_paused_retry_preserves_execution(before: RetrySnapshot, after: RetrySnapshot) -> None:
    """Compare after PAUSE and before any authorized finalization or release."""
    assert before.listing_status == "PAUSED" and before.job_status == "RUNNING"
    assert len(before.allocation_ids) == 1 and before.allocated_gpu_count > 0
    assert after == before, "dispatch retry changed the PAUSED Listing's execution snapshot"


def assert_stale_settlement_is_inert(
    current_lease: LeaseSnapshot, observed: LeaseSnapshot, *, affected_rows: int,
) -> None:
    """A stale owner cannot ACK or reschedule a replacement lease."""
    assert affected_rows == 0, "stale settlement was allowed to write"
    assert observed == current_lease, "stale settlement changed the replacement lease"
