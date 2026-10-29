"""Narrow persistence ports for the queued Job cancellation transaction.

The production adapter is owned by GPU-002. These protocols describe its
required ordering and effects; they do not implement PostgreSQL behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord


@dataclass(frozen=True)
class JobLocator:
    """Unlocked, minimal locator read before acquiring domain locks."""

    listing_id: UUID


class JobLocatorReader(Protocol):
    def get_locator(self, *, job_id: UUID) -> JobLocator | None:
        """Read only the immutable Listing key; do not lock the Job row."""
        ...


class JobCancelTransaction(Protocol):
    def lock_listing(self, *, listing_id: UUID) -> None:
        """Acquire the Listing row lock before any Job row lock."""
        ...

    def lock_job(self, *, job_id: UUID) -> JobRecord | None:
        """Lock and return a fresh Job row, or None if it no longer exists."""
        ...

    def cancel_queued(
        self,
        *,
        job_id: UUID,
        listing_id: UUID,
        client_id: UUID,
    ) -> JobRecord:
        """Guard QUEUED/identity predicates and return the DB-timestamped row.

        The adapter must perform QUEUED -> CANCELLED and sample PostgreSQL
        ``clock_timestamp()`` after locks. It sets ``terminal_at`` from that
        trusted clock, leaves ``failure_reason`` and ``started_at`` NULL, and
        changes no allocation, Listing counter, result, reputation, or
        simulation-reference data. A failed guard must raise and roll back.
        """
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class JobCancelUnitOfWork(Protocol):
    def begin(self, *, principal: JobPrincipal) -> JobCancelTransaction:
        """Begin the single TX-CANCEL unit after locator lookup succeeds."""
        ...
