"""PostgreSQL persistence for idempotent TX-SUBMIT and protected references."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from types import TracebackType
from typing import Any, Literal, Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gpu_marketplace.jobs.cancel_ports import CommitOutcomeUnknown
from gpu_marketplace.jobs.errors import DependencyUnavailable
from gpu_marketplace.jobs.models import FailureReason, JobStatus, SubmitJobRequest
from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord
from gpu_marketplace.jobs.submit_ports import (
    IdempotencyCollision,
    JobSubmissionTransaction,
    ListingAdmission,
    SimulationReference,
    StoredSubmission,
)
from gpu_marketplace.repositories.commit_outcome import is_definite_commit_rollback

logger = logging.getLogger(__name__)

_ALLOWED_RUNTIME_ROLES = frozenset({"gpm_api_app", "gpm_api_rw"})
_ALLOWED_RUNTIME_LOGINS = frozenset({"gpm_api_app"})
_IDEMPOTENCY_CONSTRAINT = "uq_jobs_client_idempotency"
_ROLE_CHECK_SQL = text("SELECT current_user, session_user, current_setting('transaction_isolation')")
_SET_TIMEOUT_SQL = text("SELECT set_config(:name, :value, true)")
_FIND_EXISTING_SQL = text(
    "SELECT id, client_id, worker_id, listing_id, requested_gpu_count, duration_seconds, "
    "status, failure_reason, submitted_at, started_at, terminal_at, request_sha256 "
    "FROM jobs WHERE client_id = :client_id AND idempotency_key = :idempotency_key"
)
_LOCK_LISTING_SQL = text(
    "SELECT id, worker_id, status, total_gpu_count FROM gpu_listings "
    "WHERE id = :listing_id FOR UPDATE OF gpu_listings"
)
_INSERT_JOB_SQL = text(
    "INSERT INTO jobs (client_id, listing_id, worker_id, requested_gpu_count, "
    "duration_seconds, submitted_at, idempotency_key, request_sha256, correlation_id) "
    "VALUES (:client_id, :listing_id, :worker_id, :requested_gpu_count, "
    ":duration_seconds, clock_timestamp(), :idempotency_key, :request_sha256, :correlation_id) "
    "RETURNING id, client_id, worker_id, listing_id, requested_gpu_count, duration_seconds, "
    "status, failure_reason, submitted_at, started_at, terminal_at"
)
_INSERT_REFERENCE_SQL = text(
    "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, "
    "expected_outcome, expected_failure_reason, expected_digest) "
    "VALUES (:job_id, :seed_value, :algorithm_version, :expected_outcome, "
    ":expected_failure_reason, :expected_digest)"
)


def _sqlstate(error: BaseException) -> str | None:
    original = getattr(error, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _constraint_name(error: BaseException) -> str | None:
    original = getattr(error, "orig", None)
    diagnostic = getattr(original, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _log_failure(event: str, error: BaseException, *, sqlstate: str | None = None) -> None:
    # Never include exception text, query parameters, SQL, or DSN in logs.
    logger.error(
        event,
        extra={"exception_type": type(error).__name__, "sqlstate": sqlstate},
    )


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


def _to_submission(row: Any) -> StoredSubmission:
    return StoredSubmission(job=_to_record(row), request_sha256=bytes(row.request_sha256))


class PostgresJobSubmissionStore:
    """Short native-role lookup and factory for restricted READ COMMITTED UoWs."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        lock_timeout_ms: int = 5_000,
        statement_timeout_ms: int = 10_000,
        allowed_session_users: frozenset[str] = _ALLOWED_RUNTIME_LOGINS,
    ) -> None:
        for value in (lock_timeout_ms, statement_timeout_ms):
            if type(value) is not int or not 1 <= value <= 120_000:
                raise ValueError("timeouts must be integer milliseconds in [1, 120000]")
        self._sessions = sessions
        self._lock_timeout_ms = lock_timeout_ms
        self._statement_timeout_ms = statement_timeout_ms
        self._allowed_session_users = allowed_session_users

    def find_existing(
        self, *, client_id: UUID, idempotency_key: str
    ) -> StoredSubmission | None:
        try:
            with self._sessions() as session:
                role, login = session.execute(
                    text("SELECT current_user, session_user")
                ).one()
                if role not in _ALLOWED_RUNTIME_ROLES or login not in self._allowed_session_users:
                    logger.error("job_submit_reader_session_misconfigured")
                    raise DependencyUnavailable()
                row = session.execute(
                    _FIND_EXISTING_SQL,
                    {"client_id": client_id, "idempotency_key": idempotency_key},
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            _log_failure("job_submit_idempotency_read_failed", error, sqlstate=_sqlstate(error))
            raise DependencyUnavailable() from None
        return None if row is None else _to_submission(row)

    def transaction(self, *, principal: JobPrincipal) -> JobSubmissionTransaction:
        # The principal is checked by the application service. It is intentionally
        # not interpolated into SQL, logs, or mutable session state.
        return PostgresJobSubmissionTransaction(
            self._sessions,
            lock_timeout_ms=self._lock_timeout_ms,
            statement_timeout_ms=self._statement_timeout_ms,
            allowed_session_users=self._allowed_session_users,
        )


class PostgresJobSubmissionTransaction:
    """Single-use transaction with Listing-first locking and atomic oracle insert."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        *,
        lock_timeout_ms: int,
        statement_timeout_ms: int,
        allowed_session_users: frozenset[str],
    ) -> None:
        self._sessions = sessions
        self._lock_timeout_ms = lock_timeout_ms
        self._statement_timeout_ms = statement_timeout_ms
        self._allowed_session_users = allowed_session_users
        self._session: Session | None = None
        self._entered = False
        self._committed = False
        self._failed = False
        self._inserted_job_id: UUID | None = None
        self._reference_inserted = False
        self._locked_listing: UUID | None = None

    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError("Job submission transaction is single-use")
        self._entered = True
        try:
            self._session = self._sessions()
            self._session.autoflush = False
            self._session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            role, login, isolation = self._session.execute(_ROLE_CHECK_SQL).one()
            if (
                role not in _ALLOWED_RUNTIME_ROLES
                or login not in self._allowed_session_users
                or isolation != "read committed"
            ):
                logger.error("job_submit_session_misconfigured")
                raise DependencyUnavailable()
            for name, value in (
                ("lock_timeout", self._lock_timeout_ms),
                ("statement_timeout", self._statement_timeout_ms),
            ):
                self._session.execute(
                    _SET_TIMEOUT_SQL, {"name": name, "value": f"{value}ms"}
                )
            return self
        except SQLAlchemyError as error:
            _log_failure("job_submit_begin_failed", error, sqlstate=_sqlstate(error))
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
        except SQLAlchemyError as error:
            cleanup_failed = True
            _log_failure("job_submit_rollback_failed", error, sqlstate=_sqlstate(error))
        except Exception as error:  # noqa: BLE001 - preserve the in-flight failure
            cleanup_failed = True
            unexpected = error
            _log_failure("job_submit_rollback_failed", error)
        finally:
            try:
                session.close()
            except SQLAlchemyError as error:
                cleanup_failed = True
                _log_failure("job_submit_close_failed", error, sqlstate=_sqlstate(error))
            except Exception as error:  # noqa: BLE001 - preserve the in-flight failure
                cleanup_failed = True
                unexpected = unexpected or error
                _log_failure("job_submit_close_failed", error)
        if exc_type is None:
            if unexpected is not None:
                raise unexpected
            if cleanup_failed and not self._committed:
                raise DependencyUnavailable() from None
        return False

    def _active(self) -> Session:
        if self._session is None or self._committed:
            raise RuntimeError("Job submission transaction is not active")
        if self._failed:
            raise DependencyUnavailable() from None
        return self._session

    def _execute(self, event: str, statement: Any, params: dict[str, Any]) -> Any:
        try:
            return self._active().execute(statement, params)
        except SQLAlchemyError as error:
            self._failed = True
            if _constraint_name(error) == _IDEMPOTENCY_CONSTRAINT:
                raise IdempotencyCollision() from None
            _log_failure(event, error, sqlstate=_sqlstate(error))
            raise DependencyUnavailable() from None

    def lock_listing(self, *, listing_id: UUID) -> ListingAdmission | None:
        if self._locked_listing is not None:
            raise RuntimeError("Listing lock was already requested")
        row = self._execute(
            "job_submit_listing_lock_failed",
            _LOCK_LISTING_SQL,
            {"listing_id": listing_id},
        ).mappings().one_or_none()
        self._locked_listing = listing_id
        if row is None:
            return None
        return ListingAdmission(
            listing_id=row.id,
            worker_id=row.worker_id,
            status=row.status,
            total_gpu_count=row.total_gpu_count,
        )

    def find_existing(
        self, *, client_id: UUID, idempotency_key: str
    ) -> StoredSubmission | None:
        if self._locked_listing is None:
            raise RuntimeError("Listing lock is required before the idempotency recheck")
        row = self._execute(
            "job_submit_idempotency_recheck_failed",
            _FIND_EXISTING_SQL,
            {"client_id": client_id, "idempotency_key": idempotency_key},
        ).mappings().one_or_none()
        return None if row is None else _to_submission(row)

    def insert_job(
        self,
        *,
        client_id: UUID,
        listing: ListingAdmission,
        request: SubmitJobRequest,
        idempotency_key: str,
        request_sha256: bytes,
        correlation_id: UUID,
    ) -> JobRecord:
        if self._locked_listing != listing.listing_id or self._inserted_job_id is not None:
            raise RuntimeError("The locked Listing is required before creating one Job")
        row = self._execute(
            "job_submit_insert_job_failed",
            _INSERT_JOB_SQL,
            {
                "client_id": client_id,
                "listing_id": listing.listing_id,
                "worker_id": listing.worker_id,
                "requested_gpu_count": request.gpu_count,
                "duration_seconds": request.duration_seconds,
                "idempotency_key": idempotency_key,
                "request_sha256": request_sha256,
                "correlation_id": correlation_id,
            },
        ).mappings().one()
        self._inserted_job_id = row.id
        return _to_record(row)

    def insert_reference(
        self, *, job_id: UUID, reference: SimulationReference
    ) -> None:
        if self._inserted_job_id != job_id or self._reference_inserted:
            raise RuntimeError("The Job insert is required before its single reference")
        self._execute(
            "job_submit_insert_reference_failed",
            _INSERT_REFERENCE_SQL,
            {
                "job_id": job_id,
                "seed_value": reference.seed_value,
                "algorithm_version": reference.algorithm_version,
                "expected_outcome": reference.expected_outcome,
                "expected_failure_reason": reference.expected_failure_reason,
                "expected_digest": reference.expected_digest,
            },
        )
        self._reference_inserted = True

    def commit(self) -> None:
        if self._inserted_job_id is None or not self._reference_inserted:
            raise RuntimeError("TX-SUBMIT must insert one Job and one reference before commit")
        session = self._active()
        try:
            session.commit()
        except SQLAlchemyError as error:
            self._failed = True
            if _constraint_name(error) == _IDEMPOTENCY_CONSTRAINT:
                raise IdempotencyCollision() from None
            sqlstate = _sqlstate(error)
            if is_definite_commit_rollback(sqlstate):
                _log_failure("job_submit_commit_aborted", error, sqlstate=sqlstate)
                raise DependencyUnavailable() from None
            _log_failure("job_submit_commit_unknown", error, sqlstate=sqlstate)
            raise CommitOutcomeUnknown() from None
        except BaseException:
            self._failed = True
            raise
        self._committed = True
