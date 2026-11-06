"""Required GPU-002 consumption ports; no alternate ORM/schema is defined here.

The adapter must use one PostgreSQL READ COMMITTED transaction per UoW.
get_for_update must acquire the Listing row lock before any Job constraint read.
An uncommitted UoW must roll back on exit, including commit failures.
Create uses DB-owned defaults; update writes only supplied allowlisted fields.
All reads return public-safe Worker/reputation projections, never ORM objects.
"""

from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Protocol
from uuid import UUID

from .models import (
    ListingChanges,
    ListingPosition,
    ListingQuery,
    ListingRecord,
    ListingStatus,
    WorkerProfile,
)


class WorkerReader(Protocol):
    def find_by_user_id(self, user_id: UUID) -> WorkerProfile | None: ...


class ListingRepository(Protocol):
    def page(
        self,
        query: ListingQuery,
        before: ListingPosition | None,
        limit: int,
    ) -> Sequence[ListingRecord]:
        """Filter in SQL; order created_at DESC, id DESC; strict keyset < before."""
        ...

    def get(self, listing_id: UUID) -> ListingRecord | None: ...

    def get_for_update(self, listing_id: UUID) -> ListingRecord | None:
        """Return a fresh row after SELECT FOR UPDATE, not a cached ORM snapshot."""
        ...

    def create(self, worker_id: UUID, values: ListingChanges) -> ListingRecord:
        """Omit id/status/allocated/timestamps; DB defaults set ACTIVE/0 and times."""
        ...

    def update(self, listing_id: UUID, changes: ListingChanges) -> ListingRecord:
        """Write metadata only; use GPU-002's approved DB-clock mechanism."""
        ...

    def set_status(self, listing_id: UUID, status: ListingStatus) -> ListingRecord: ...


class JobConstraintReader(Protocol):
    def has_nonterminal_jobs(self, listing_id: UUID) -> bool: ...

    def max_queued_gpu_count(self, listing_id: UUID) -> int:
        """Return MAX(requested_gpu_count) for QUEUED Jobs, or 0."""
        ...


class ListingUnitOfWork(Protocol):
    workers: WorkerReader
    listings: ListingRepository
    jobs: JobConstraintReader

    def __enter__(self) -> "ListingUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], ListingUnitOfWork]
