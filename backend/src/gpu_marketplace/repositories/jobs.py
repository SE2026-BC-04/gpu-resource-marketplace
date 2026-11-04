"""PostgreSQL adapter for the ACKed TX-CANCEL ports (GPU-005-D / GPU-002).

Implements ``JobLocatorReader`` and ``JobCancelUnitOfWork`` from
``gpu_marketplace.jobs.cancel_ports``. Only QUEUED -> CANCELLED is performed.
Lock order is Listing then Job (database-design section 11); the cancel UPDATE
samples PostgreSQL ``clock_timestamp()`` after both locks and never touches
allocation, Listing counters, simulation references or reputation rows.

Errors never carry driver text, SQL or bound parameters: storage failures are
translated to ``DependencyUnavailable`` (``from None``) and only the exception
type and SQLSTATE are logged. A COMMIT whose result cannot be established
raises ``CommitOutcomeUnknown`` and must not be retried by callers.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from enum import StrEnum
from types import TracebackType
from typing import Any, Literal, Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from gpu_marketplace.jobs.cancel_ports import (
    CancelGuardReason,
    CancelGuardRejected,
    CommitOutcomeUnknown,
    JobLocator,
)
from gpu_marketplace.jobs.errors import DependencyUnavailable
from gpu_marketplace.jobs.models import FailureReason, JobStatus
from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord

logger = logging.getLogger(__name__)

ALLOWED_RUNTIME_ROLES = frozenset({"gpm_api_app", "gpm_api_rw"})
# The login (``session_user``) the runtime must connect with. ``current_user`` alone can be
# changed by ``SET ROLE`` / a ``role`` connection option on an owner login, so production
# also requires the native API login. Tests that deliberately use an owner login plus
# ``SET ROLE`` must pass ``allowed_session_users`` explicitly.
ALLOWED_RUNTIME_LOGINS = frozenset({"gpm_api_app"})

# SQLSTATE classes after which PostgreSQL has definitely aborted the transaction
# (class 23 = integrity violation incl. deferred checks at COMMIT; 40 = rollback).
_KNOWN_ABORT_SQLSTATE_CLASSES = frozenset({"23", "40"})

_JOB_COLUMNS = (
    "id, client_id, worker_id, listing_id, requested_gpu_count, duration_seconds, "
    "status, failure_reason, submitted_at, started_at, terminal_at"
)

_LOCATOR_SQL = text("SELECT listing_id FROM jobs WHERE id = :job_id")
_LOCK_LISTING_SQL = text(
    "SELECT id FROM gpu_listings WHERE id = :listing_id FOR UPDATE OF gpu_listings"
)
_LOCK_JOB_SQL = text(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = :job_id FOR UPDATE")
# status/terminal_at are the only mutated columns; the QUEUED/owner/listing guard
# is part of the statement so a stale caller can never cancel another state.
_CANCEL_SQL = text(
    "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() "
    "WHERE id = :job_id AND listing_id = :listing_id AND client_id = :client_id "
    f"AND status = 'QUEUED' RETURNING {_JOB_COLUMNS}"
)
_CLASSIFY_SQL = text("SELECT client_id, listing_id FROM jobs WHERE id = :job_id")
_ROLE_CHECK_SQL = text("SELECT current_user, session_user")
_SESSION_CHECK_SQL = text(
    "SELECT current_user, session_user, current_setting('transaction_isolation')"
)
_SET_TIMEOUT_SQL = text("SELECT set_config(:name, :value, true)")


class TransactionOutcome(StrEnum):
    """Internal evidence only; never a public API error or a retry instruction."""

    NOT_COMMITTED = "NOT_COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    COMMITTED = "COMMITTED"
    COMMIT_OUTCOME_UNKNOWN = "COMMIT_OUTCOME_UNKNOWN"


def _sqlstate(error: BaseException) -> str | None:
    original = error.orig if isinstance(error, DBAPIError) else None
    value = getattr(original, "sqlstate", None)
    return value if isinstance(value, str) else None


def _log_store_failure(event: str, error: BaseException, outcome: TransactionOutcome | None) -> None:
    # Exception text can contain SQL, parameters or DSN fragments: log type only.
    extra: dict[str, Any] = {"error_type": type(error).__name__, "sqlstate": _sqlstate(error)}
    if outcome is not None:
        extra["transaction_outcome"] = outcome.value
    logger.error(event, extra=extra)


def _to_record(row: Any) -> JobRecord:
    return JobRecord(
        id=row.id,
        client_id=row.client_id,
        worker_id=row.worker_id,
        listing_id=row.listing_id,
        requested_gpu_count=row.requested_gpu_count,
        duration_seconds=row.duration_seconds,
        status=JobStatus(row.status),
        failure_reason=None if row.failure_reason is None else FailureReason(row.failure_reason),
        submitted_at=row.submitted_at,
        started_at=row.started_at,
        terminal_at=row.terminal_at,
    )


class PostgresJobLocatorReader:
    """Unlocked, single-statement read of ``jobs.listing_id`` in a short Session."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        allowed_session_users: frozenset[str] = ALLOWED_RUNTIME_LOGINS,
    ) -> None:
        self._sessions = sessions
        self._allowed_session_users = allowed_session_users

    def get_locator(self, *, job_id: UUID) -> JobLocator | None:
        try:
            with self._sessions() as session:
                # Fail closed on the effective DB role before reading any Job identity, so a
                # misconfigured privileged session cannot act as an existence oracle.
                role, login = session.execute(_ROLE_CHECK_SQL).one()
                if role not in ALLOWED_RUNTIME_ROLES or login not in self._allowed_session_users:
                    logger.error("job_locator_session_misconfigured")
                    raise DependencyUnavailable()
                listing_id = session.execute(_LOCATOR_SQL, {"job_id": job_id}).scalar_one_or_none()
        except SQLAlchemyError as error:
            _log_store_failure("job_locator_read_failed", error, None)
            raise DependencyUnavailable() from None
        return None if listing_id is None else JobLocator(listing_id=listing_id)


class PostgresJobCancelUnitOfWork:
    """Factory of single-use READ COMMITTED cancel transactions.

    ``sessions`` must create Sessions connected as ``gpm_api_app`` (or the
    ``gpm_api_rw`` group), never an owner/superuser DSN; the transaction verifies
    ``current_user``, the native login (``session_user``) and isolation on entry and
    fails closed otherwise.
    """

    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        lock_timeout_ms: int = 5_000,
        statement_timeout_ms: int = 10_000,
        allowed_session_users: frozenset[str] = ALLOWED_RUNTIME_LOGINS,
    ) -> None:
        for value in (lock_timeout_ms, statement_timeout_ms):
            if type(value) is not int or not 1 <= value <= 120_000:
                raise ValueError("timeouts must be integer milliseconds in [1, 120000]")
        self._sessions = sessions
        self._lock_timeout_ms = lock_timeout_ms
        self._statement_timeout_ms = statement_timeout_ms
        self._allowed_session_users = allowed_session_users

    def transaction(self, *, principal: JobPrincipal) -> PostgresJobCancelTransaction:
        # Authorization is decided by the service and by predicates in the UPDATE;
        # the principal is deliberately not copied into SQL, logs or session state.
        return PostgresJobCancelTransaction(
            self._sessions,
            lock_timeout_ms=self._lock_timeout_ms,
            statement_timeout_ms=self._statement_timeout_ms,
            allowed_session_users=self._allowed_session_users,
        )


class PostgresJobCancelTransaction:
    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        allowed_session_users: frozenset[str] = ALLOWED_RUNTIME_LOGINS,
    ) -> None:
        self._sessions = sessions
        self._lock_timeout_ms = lock_timeout_ms
        self._statement_timeout_ms = statement_timeout_ms
        self._allowed_session_users = allowed_session_users
        self._session: Session | None = None
        self._entered = False
        self._committed = False
        self._failed = False
        self._outcome = TransactionOutcome.NOT_COMMITTED
        self._locked_listing: UUID | None = None
        self._locked_job: UUID | None = None

    @property
    def outcome(self) -> TransactionOutcome:
        """Retained after exit; cleanup cannot resolve an indeterminate COMMIT."""
        return self._outcome

    # -- lifecycle -----------------------------------------------------------------
    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError("Job cancel transaction is single-use")
        self._entered = True
        try:
            self._session = self._sessions()
            self._session.autoflush = False
            self._session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            role, login, isolation = self._session.execute(_SESSION_CHECK_SQL).one()
            if (
                role not in ALLOWED_RUNTIME_ROLES
                or login not in self._allowed_session_users
                or isolation != "read committed"
            ):
                logger.error("job_cancel_session_misconfigured")
                raise DependencyUnavailable()
            for name, value in (
                ("lock_timeout", self._lock_timeout_ms),
                ("statement_timeout", self._statement_timeout_ms),
            ):
                self._session.execute(_SET_TIMEOUT_SQL, {"name": name, "value": f"{value}ms"})
            return self
        except SQLAlchemyError as error:
            _log_store_failure("job_cancel_begin_failed", error, self._outcome)
            self.__exit__(*sys.exc_info())
            raise DependencyUnavailable() from None
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        session, self._session = self._session, None
        if session is None:
            return False
        cleanup_failed = False
        unexpected: Exception | None = None
        try:
            if not self._committed:
                session.rollback()
                if self._outcome is TransactionOutcome.NOT_COMMITTED:
                    self._outcome = TransactionOutcome.ROLLED_BACK
        except SQLAlchemyError as error:
            cleanup_failed = True
            _log_store_failure("job_cancel_rollback_failed", error, self._outcome)
        except Exception as error:  # noqa: BLE001 - must never replace an in-flight exception
            cleanup_failed = True
            unexpected = error
            _log_store_failure("job_cancel_rollback_failed", error, self._outcome)
        finally:
            try:
                session.close()
            except SQLAlchemyError as error:
                cleanup_failed = True
                _log_store_failure("job_cancel_close_failed", error, self._outcome)
            except Exception as error:  # noqa: BLE001 - same priority rule as rollback
                cleanup_failed = True
                unexpected = unexpected or error
                _log_store_failure("job_cancel_close_failed", error, self._outcome)
        if exc_type is None:
            # An exception already in flight always wins (it was ignored above after being
            # logged by type only). On a clean body, unexpected programming faults propagate
            # unchanged, as the port requires, even after a confirmed COMMIT; the retained
            # ``outcome`` still records COMMITTED. A storage fault during cleanup becomes the
            # sanitized outage error only before COMMIT; after COMMIT it is logged, because
            # the mutation is durable and reporting an outage would be a false failure.
            if unexpected is not None:
                raise unexpected
            if cleanup_failed and not self._committed:
                raise DependencyUnavailable() from None
        return False

    def _active(self) -> Session:
        if self._session is None or self._committed:
            raise RuntimeError("Job cancel transaction is not active")
        if self._failed:
            raise DependencyUnavailable() from None
        return self._session

    def _execute(self, statement: Any, params: dict[str, Any]) -> Any:
        session = self._active()
        try:
            return session.execute(statement, params)
        except SQLAlchemyError as error:
            self._failed = True
            _log_store_failure("job_cancel_statement_failed", error, self._outcome)
            raise DependencyUnavailable() from None

    # -- operations ----------------------------------------------------------------
    def lock_listing(self, *, listing_id: UUID) -> None:
        if self._locked_listing is not None:
            raise RuntimeError("Listing lock was already requested")
        self._execute(_LOCK_LISTING_SQL, {"listing_id": listing_id}).scalar_one_or_none()
        # A vanished Listing cannot own a Job (RESTRICT FK); lock_job then returns
        # None/mismatch and the service reports the uniform 404.
        self._locked_listing = listing_id

    def lock_job(self, *, job_id: UUID) -> JobRecord | None:
        if self._locked_listing is None:
            raise RuntimeError("Listing lock is required before locking a Job")
        if self._locked_job is not None:
            raise RuntimeError("Job lock was already requested")
        row = self._execute(_LOCK_JOB_SQL, {"job_id": job_id}).one_or_none()
        self._locked_job = job_id
        return None if row is None else _to_record(row)

    def cancel_queued(self, *, job_id: UUID, listing_id: UUID, client_id: UUID) -> JobRecord:
        if self._locked_listing != listing_id or self._locked_job != job_id:
            raise RuntimeError("Listing and Job locks are required before cancelling")
        params = {"job_id": job_id, "listing_id": listing_id, "client_id": client_id}
        row = self._execute(_CANCEL_SQL, params).one_or_none()
        if row is not None:
            return _to_record(row)
        # Zero rows: classify from the row still locked by this transaction.
        current = self._execute(_CLASSIFY_SQL, {"job_id": job_id}).one_or_none()
        if current is None:
            reason = CancelGuardReason.MISSING
        elif current.client_id != client_id or current.listing_id != listing_id:
            reason = CancelGuardReason.NOT_OWNER
        else:
            reason = CancelGuardReason.NOT_QUEUED
        raise CancelGuardRejected(reason)

    def commit(self) -> None:
        session = self._active()
        # An exception can follow a durable COMMIT with a lost acknowledgement, so
        # the outcome stays unknown unless PostgreSQL reports a definite abort.
        self._outcome = TransactionOutcome.COMMIT_OUTCOME_UNKNOWN
        try:
            session.commit()
        except SQLAlchemyError as error:
            self._failed = True
            sqlstate = _sqlstate(error)
            if sqlstate is not None and sqlstate[:2] in _KNOWN_ABORT_SQLSTATE_CLASSES:
                self._outcome = TransactionOutcome.ROLLED_BACK
                _log_store_failure("job_cancel_commit_aborted", error, self._outcome)
                raise DependencyUnavailable() from None
            _log_store_failure("job_cancel_commit_unknown", error, self._outcome)
            raise CommitOutcomeUnknown() from None
        except BaseException:
            self._failed = True
            raise
        self._committed = True
        self._outcome = TransactionOutcome.COMMITTED
