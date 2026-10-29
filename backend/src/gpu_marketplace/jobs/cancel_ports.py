"""Narrow persistence ports for the queued Job cancellation transaction.

The production adapter is owned by GPU-002. These protocols specify the
transaction/error contract but do not implement PostgreSQL behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord


@dataclass(frozen=True)
class JobLocator:
    """Unlocked, minimal locator read before acquiring domain locks."""

    listing_id: UUID


class JobLocatorReader(Protocol):
    def get_locator(self, *, job_id: UUID) -> JobLocator | None:
        """Read only the immutable Listing key; do not lock the Job row.

        Raise the existing ``DependencyUnavailable`` domain error for a known
        database outage. Unexpected programming errors must remain unexpected.
        """
        ...


class CancelGuardReason(StrEnum):
    MISSING = "MISSING"
    NOT_OWNER = "NOT_OWNER"
    NOT_QUEUED = "NOT_QUEUED"


class CancelGuardRejected(Exception):
    """A conditional cancel UPDATE returned no row, classified by the adapter."""

    def __init__(self, reason: CancelGuardReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class CommitOutcomeUnknown(Exception):
    """Commit could not be confirmed; callers must not retry the mutation."""


class JobCancelTransaction(Protocol):
    """Single-use context-managed transaction, including resource cleanup.

    ``__enter__`` begins the transaction. If begin fails after acquiring any
    resource, the adapter must release it before propagating the original
    exception. ``__exit__`` rolls back an uncommitted, known-active transaction
    and closes/releases the Session/connection exactly once on every path.
    Cleanup failures must not replace an exception already in flight. A commit
    attempt with unknown outcome is not safely retryable; cleanup may be
    best-effort, but the adapter must not claim rollback undid a possibly
    committed transaction. Every storage operation translates known database
    connectivity/unavailability failures to the existing ``DependencyUnavailable``
    domain error; unexpected programming exceptions propagate unchanged.
    """

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

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

        The adapter performs QUEUED -> CANCELLED and samples PostgreSQL
        ``clock_timestamp()`` after locks. It leaves ``failure_reason`` and
        ``started_at`` NULL and changes no allocation, Listing counter, result,
        reputation, or simulation-reference data. If conditional UPDATE
        ``RETURNING`` yields zero rows, raise ``CancelGuardRejected`` classified
        as MISSING, NOT_OWNER, or NOT_QUEUED after the locked recheck; never
        return a fabricated/success row. Translate known database outages to
        the existing ``DependencyUnavailable`` error and do not expose driver
        messages. Unexpected programming exceptions propagate unchanged.
        """
        ...

    def commit(self) -> None:
        """Commit once; use DependencyUnavailable or CommitOutcomeUnknown as appropriate.

        Never retry automatically when the commit outcome is uncertain.
        """
        ...


class JobCancelUnitOfWork(Protocol):
    def transaction(self, *, principal: JobPrincipal) -> JobCancelTransaction:
        """Create a lazy context manager; acquire resources only on ``__enter__``.

        Known DB unavailability is reported as ``DependencyUnavailable``. If
        creation or ``__enter__`` fails, any resource already acquired must be
        cleaned up before the original exception propagates.
        """
        ...
