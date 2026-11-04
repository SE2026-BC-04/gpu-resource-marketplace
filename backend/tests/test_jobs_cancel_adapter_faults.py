"""Database-free fault tests for the TX-CANCEL adapter (``repositories/jobs.py``).

They use a fake Session so they always run (no PostgreSQL opt-in needed) and cover
review items P2-01 (role check before the locator read) and P2-02 (cleanup must
never replace an exception already in flight).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from gpu_marketplace.jobs.cancel_ports import CommitOutcomeUnknown
from gpu_marketplace.jobs.errors import DependencyUnavailable, JobNotFound
from gpu_marketplace.repositories.jobs import (
    PostgresJobCancelTransaction,
    PostgresJobLocatorReader,
)
from sqlalchemy.exc import OperationalError

API_ROLE = "gpm_api_app"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def one(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Minimal Session double; statements are recognised by their SQL text."""

    def __init__(
        self,
        *,
        role: str = API_ROLE,
        listing_id: uuid.UUID | None = None,
        rollback_error: Exception | None = None,
        close_error: Exception | None = None,
        commit_error: Exception | None = None,
    ) -> None:
        self.role = role
        self.listing_id = listing_id
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.commit_error = commit_error
        self.executed: list[str] = []
        self.closed = False
        self.autoflush = True

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connection(self, **_kwargs: Any) -> None:
        return None

    def execute(self, statement: Any, _params: Any = None) -> _Result:
        sql = str(statement)
        self.executed.append(sql)
        if "current_setting('transaction_isolation')" in sql:
            return _Result((self.role, "read committed"))
        if sql.strip() == "SELECT current_user":
            return _Result(self.role)
        if "FROM jobs WHERE id" in sql:
            return _Result(self.listing_id)
        return _Result(None)

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _transaction(session: _FakeSession) -> PostgresJobCancelTransaction:
    return PostgresJobCancelTransaction(
        lambda: session,  # type: ignore[arg-type,return-value]
        lock_timeout_ms=1_000,
        statement_timeout_ms=1_000,
    )


# -- P2-01: the locator fails closed on the effective DB role ---------------------------


@pytest.mark.parametrize("listing_id", [uuid.uuid4(), None], ids=["existing-job", "absent-job"])
def test_locator_rejects_privileged_role_before_reading_jobs(listing_id: uuid.UUID | None) -> None:
    session = _FakeSession(role="gpm_owner", listing_id=listing_id)
    reader = PostgresJobLocatorReader(lambda: session)  # type: ignore[arg-type,return-value]

    with pytest.raises(DependencyUnavailable):
        reader.get_locator(job_id=uuid.uuid4())

    # Identical safe failure whether or not the Job exists, and no Job identity was read.
    assert not any("FROM jobs" in sql for sql in session.executed)
    assert session.closed


@pytest.mark.parametrize("role", ["gpm_api_app", "gpm_api_rw"])
def test_locator_reads_for_approved_api_roles(role: str) -> None:
    listing = uuid.uuid4()
    reader = PostgresJobLocatorReader(lambda: _FakeSession(role=role, listing_id=listing))  # type: ignore[arg-type,return-value]

    locator = reader.get_locator(job_id=uuid.uuid4())

    assert locator is not None and locator.listing_id == listing


def test_locator_returns_none_for_absent_job_under_api_role() -> None:
    reader = PostgresJobLocatorReader(lambda: _FakeSession(listing_id=None))  # type: ignore[arg-type,return-value]

    assert reader.get_locator(job_id=uuid.uuid4()) is None


# -- P2-02: cleanup never replaces an in-flight exception -------------------------------


@pytest.mark.parametrize("failing", ["rollback", "close", "both"])
def test_cleanup_runtime_error_does_not_mask_body_exception(failing: str) -> None:
    session = _FakeSession(
        rollback_error=RuntimeError("rollback boom") if failing in ("rollback", "both") else None,
        close_error=RuntimeError("close boom") if failing in ("close", "both") else None,
    )

    with pytest.raises(JobNotFound):
        with _transaction(session):
            raise JobNotFound()

    assert session.closed  # close is still attempted after a failed rollback


def test_cleanup_runtime_error_does_not_mask_unknown_commit() -> None:
    session = _FakeSession(
        commit_error=OperationalError("stmt", {}, Exception("driver text must never escape")),
        rollback_error=RuntimeError("rollback boom"),
        close_error=RuntimeError("close boom"),
    )

    with pytest.raises(CommitOutcomeUnknown):
        with _transaction(session) as tx:
            tx.commit()

    assert session.closed


def test_cleanup_runtime_error_without_body_exception_is_not_swallowed() -> None:
    session = _FakeSession(rollback_error=RuntimeError("rollback boom"))

    with pytest.raises(RuntimeError, match="rollback boom"):
        with _transaction(session):
            pass

    assert session.closed


def test_close_runtime_error_without_body_exception_is_not_swallowed() -> None:
    session = _FakeSession(close_error=RuntimeError("close boom"))

    with pytest.raises(RuntimeError, match="close boom"):
        with _transaction(session):
            pass


def test_close_programming_fault_after_successful_commit_propagates_and_keeps_outcome() -> None:
    session = _FakeSession(close_error=RuntimeError("close boom"))
    transaction = _transaction(session)

    with pytest.raises(RuntimeError, match="close boom"):
        with transaction as tx:
            tx.commit()

    # The write is durable: the outcome evidence must still say so.
    assert transaction.outcome.value == "COMMITTED"


def test_close_storage_fault_after_successful_commit_is_logged_not_raised() -> None:
    session = _FakeSession(close_error=OperationalError("stmt", {}, Exception("secret dsn")))

    with _transaction(session) as tx:
        tx.commit()

    assert tx.outcome.value == "COMMITTED"


def test_programming_fault_after_commit_does_not_mask_a_later_body_exception() -> None:
    session = _FakeSession(close_error=RuntimeError("close boom"))

    with pytest.raises(JobNotFound):
        with _transaction(session) as tx:
            tx.commit()
            raise JobNotFound()


def test_storage_cleanup_failure_on_clean_body_is_sanitized_outage() -> None:
    session = _FakeSession(rollback_error=OperationalError("stmt", {}, Exception("secret dsn")))

    with pytest.raises(DependencyUnavailable) as caught:
        with _transaction(session):
            pass

    assert "secret" not in str(caught.value)
