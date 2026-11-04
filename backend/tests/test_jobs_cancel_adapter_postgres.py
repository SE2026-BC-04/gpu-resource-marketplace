"""Real PostgreSQL tests for the TX-CANCEL adapter (``repositories/jobs.py``).

They run the production ``JobCancelService`` against ``PostgresJobLocatorReader`` and
``PostgresJobCancelUnitOfWork`` under the restricted ``gpm_api_app`` role on the
disposable cluster only (same guards as ``test_jobs_cancel_d2_postgres.py``).
PG-CANCEL IDs refer to docs/development/handoffs/GPU-005-D_postgres_cancel_test_plan.md.
PG-CANCEL-15 (real Manager allocation) stays BLOCKED on Phase 2 and is not covered.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from conftest import reset_schema
from db_safety import TestDatabase
from gpu_marketplace.jobs.cancel import JobCancelService
from gpu_marketplace.jobs.cancel_ports import (
    CancelGuardReason,
    CancelGuardRejected,
    CommitOutcomeUnknown,
)
from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    JobNotCancellable,
    JobNotFound,
)
from gpu_marketplace.jobs.models import JobStatus
from gpu_marketplace.repositories.jobs import (
    PostgresJobCancelUnitOfWork,
    PostgresJobLocatorReader,
    TransactionOutcome,
)
from jobs_cancel_pg_support import (
    CommittedJobFixture,
    assert_non_job_side_effects_unchanged,
    assert_snapshot_unchanged,
    read_database_clock,
    read_persisted_snapshot,
    seed_cancel_side_effect_rows,
    seed_committed_job,
)
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from test_schema_constraints import add_user

API_ROLE = "gpm_api_app"


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    role: str = "CLIENT"


class _Fake(Exception):
    pass


class _FakeDriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("driver text must never escape")
        self.sqlstate = sqlstate


@dataclass
class Stack:
    engine: Engine  # role-bound runtime engine
    sessions: sessionmaker[Session]
    uow: PostgresJobCancelUnitOfWork
    service: JobCancelService


def _runtime_engine(url: str, *, role: str = API_ROLE, application_name: str = "gpm-cancel-adapter") -> Engine:
    engine = create_engine(url, connect_args={"application_name": application_name, "connect_timeout": 5})

    @event.listens_for(engine, "connect")
    def _bind_role(dbapi_connection: Any, _record: Any) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f'SET ROLE "{role}"')
        dbapi_connection.commit()

    return engine


def _stack(url: str, *, application_name: str = "gpm-cancel-adapter", **uow_options: int) -> Stack:
    engine = _runtime_engine(url, application_name=application_name)
    sessions = sessionmaker(engine, expire_on_commit=False)
    # These tests use the disposable cluster's owner login plus SET ROLE, so the native login
    # (session_user) is allowed explicitly; production defaults to the gpm_api_app login only.
    test_logins = frozenset({make_url(url).username or ""})
    uow = PostgresJobCancelUnitOfWork(sessions, allowed_session_users=test_logins, **uow_options)
    return Stack(
        engine,
        sessions,
        uow,
        JobCancelService(
            locator_reader=PostgresJobLocatorReader(sessions, allowed_session_users=test_logins), uow=uow
        ),
    )


@pytest.fixture
def cancel_postgres(migrated_database: Engine, test_database: TestDatabase) -> Iterator[Engine]:
    try:
        yield migrated_database
    finally:
        reset_schema(migrated_database, test_database)


@pytest.fixture
def stack(cancel_postgres: Engine, test_database: TestDatabase) -> Iterator[Stack]:
    built = _stack(test_database.url)
    try:
        yield built
    finally:
        built.engine.dispose()


def _owner(fixture: CommittedJobFixture) -> Principal:
    return Principal(uuid.UUID(fixture.client_user_id))


def _seed(engine: Engine, **kwargs: Any) -> CommittedJobFixture:
    fixture = seed_committed_job(engine, **kwargs)
    seed_cancel_side_effect_rows(engine, fixture)
    return fixture


def _assert_no_leaked_connections(stack: Stack) -> None:
    assert stack.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def _wait_until_blocked_on_lock(observer: Engine, application_name: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with observer.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = :name "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                ),
                {"name": application_name},
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("adapter transaction never blocked on a PostgreSQL lock")


def _in_thread(function: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = function()
        except BaseException as error:  # noqa: BLE001 - re-raised/inspected by the test
            box["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


# -- PG-CANCEL-01 / 05 / 06 ----------------------------------------------------------


def test_cancel_queued_job_uses_database_clock_and_changes_nothing_else(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    clock_before = read_database_clock(cancel_postgres)

    response = stack.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))

    clock_after = read_database_clock(cancel_postgres)
    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert response.status is JobStatus.CANCELLED
    assert before.job_row[6] == "QUEUED" and after.job_row[6] == "CANCELLED"
    assert after.job_row[8] is None  # started_at
    assert after.job_row[10] is None  # failure_reason
    assert clock_before < after.job_row[9] < clock_after  # DB-generated terminal_at
    assert_non_job_side_effects_unchanged(before, after)
    _assert_no_leaked_connections(stack)


def test_cancel_succeeds_for_paused_listing_and_keeps_it_paused(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres, listing_status="PAUSED")
    before = read_persisted_snapshot(cancel_postgres, fixture)

    stack.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))

    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after.job_row[6] == "CANCELLED"
    assert_non_job_side_effects_unchanged(before, after)
    with cancel_postgres.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM gpu_listings WHERE id = :id"), {"id": fixture.listing_id}
        ).scalar_one()
    assert status == "PAUSED"


def test_second_cancel_by_same_owner_is_not_cancellable_and_changes_nothing(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    principal, job_id = _owner(fixture), uuid.UUID(fixture.job_id)
    stack.service.cancel(principal=principal, job_id=job_id)
    first = read_persisted_snapshot(cancel_postgres, fixture)

    with pytest.raises(JobNotCancellable):
        stack.service.cancel(principal=principal, job_id=job_id)

    assert_snapshot_unchanged(first, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


# -- PG-CANCEL-02 / 03 / 04 / 08 -----------------------------------------------------


def test_foreign_client_gets_uniform_not_found_and_state_is_unchanged(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    with cancel_postgres.begin() as connection:
        other_client = add_user(connection, "CLIENT")
    before = read_persisted_snapshot(cancel_postgres, fixture)

    with pytest.raises(JobNotFound):
        stack.service.cancel(principal=Principal(uuid.UUID(other_client)), job_id=uuid.UUID(fixture.job_id))

    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


def test_absent_job_is_not_found(cancel_postgres: Engine, stack: Stack) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)

    with pytest.raises(JobNotFound):
        stack.service.cancel(principal=_owner(fixture), job_id=uuid.uuid4())

    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_non_queued_job_is_not_cancellable_and_row_is_untouched(
    cancel_postgres: Engine, stack: Stack, status: str
) -> None:
    fixture = _seed(cancel_postgres, status=status)
    before = read_persisted_snapshot(cancel_postgres, fixture)

    with pytest.raises(JobNotCancellable):
        stack.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))

    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


def test_zero_row_update_is_classified_missing_not_owner_not_queued(
    cancel_postgres: Engine, stack: Stack
) -> None:
    queued = _seed(cancel_postgres)
    running = _seed(cancel_postgres, status="RUNNING")
    owner = uuid.UUID(queued.client_user_id)
    cases = [
        # (fixture, job_id, listing_id, client_id, expected reason)
        (queued, uuid.uuid4(), queued.listing_id, owner, CancelGuardReason.MISSING),
        (queued, queued.job_id, queued.listing_id, uuid.uuid4(), CancelGuardReason.NOT_OWNER),
        (queued, queued.job_id, running.listing_id, owner, CancelGuardReason.NOT_OWNER),
        (running, running.job_id, running.listing_id, uuid.UUID(running.client_user_id), CancelGuardReason.NOT_QUEUED),
    ]
    for fixture, job_id, listing_id, client_id, expected in cases:
        before = read_persisted_snapshot(cancel_postgres, fixture)
        with pytest.raises(CancelGuardRejected) as rejected:
            with stack.uow.transaction(principal=Principal(client_id)) as tx:
                tx.lock_listing(listing_id=uuid.UUID(str(listing_id)))
                tx.lock_job(job_id=uuid.UUID(str(job_id)))
                tx.cancel_queued(
                    job_id=uuid.UUID(str(job_id)),
                    listing_id=uuid.UUID(str(listing_id)),
                    client_id=client_id,
                )
        assert rejected.value.reason is expected
        assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


# -- PG-CANCEL-07: failure before commit rolls back ------------------------------------


def test_failure_after_guarded_update_before_commit_rolls_back(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    job_id, listing_id = uuid.UUID(fixture.job_id), uuid.UUID(fixture.listing_id)
    transaction = stack.uow.transaction(principal=_owner(fixture))

    with pytest.raises(_Fake):
        with transaction as tx:
            tx.lock_listing(listing_id=listing_id)
            tx.lock_job(job_id=job_id)
            tx.cancel_queued(job_id=job_id, listing_id=listing_id, client_id=uuid.UUID(fixture.client_user_id))
            raise _Fake()  # staged UPDATE must not survive

    assert transaction.outcome is TransactionOutcome.ROLLED_BACK
    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


# -- PG-CANCEL-09: restricted runtime role ---------------------------------------------


def test_transaction_runs_as_api_role_in_read_committed_and_rejects_owner_role(
    cancel_postgres: Engine, test_database: TestDatabase, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    with stack.uow.transaction(principal=_owner(fixture)) as tx:
        role, isolation = tx._session.execute(  # type: ignore[union-attr]
            text("SELECT current_user, current_setting('transaction_isolation')")
        ).one()
    assert (role, isolation) == (API_ROLE, "read committed")

    owner_engine = create_engine(test_database.url)  # superuser DSN must be refused
    try:
        unsafe = PostgresJobCancelUnitOfWork(sessionmaker(owner_engine, expire_on_commit=False))
        with pytest.raises(DependencyUnavailable):
            with unsafe.transaction(principal=_owner(fixture)):
                raise AssertionError("body must not run for a non-runtime role")
        assert owner_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        owner_engine.dispose()


def test_locator_with_owner_role_fails_identically_for_existing_and_absent_jobs(
    cancel_postgres: Engine, test_database: TestDatabase
) -> None:
    """P2-01: no existence oracle and no Job read when the session is a privileged login.

    Boundary: the restricted ``stack`` binds ``gpm_api_app`` with ``SET ROLE`` over the
    owner DSN and opts that owner login in explicitly, so the functional tests prove
    *effective* role behaviour. The native ``session_user`` default is covered by
    ``test_owner_login_with_api_role_is_rejected_by_default_for_locator_and_transaction``;
    a real ``gpm_api_app`` login is exercised by the Compose smoke, not by this module.
    """
    fixture = _seed(cancel_postgres)
    owner_engine = create_engine(test_database.url)
    try:
        reader = PostgresJobLocatorReader(sessionmaker(owner_engine, expire_on_commit=False))
        for job_id in (uuid.UUID(fixture.job_id), uuid.uuid4()):
            with pytest.raises(DependencyUnavailable):
                reader.get_locator(job_id=job_id)
        assert owner_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        owner_engine.dispose()


def test_owner_login_with_api_role_is_rejected_by_default_for_locator_and_transaction(
    cancel_postgres: Engine, test_database: TestDatabase
) -> None:
    """session_user guard: an owner login that runs SET ROLE gpm_api_app is not the API login.

    This is the scenario of the post-#31 bot finding. The production default allows only
    the native ``gpm_api_app`` login; the other tests in this module opt in explicitly.
    """
    fixture = _seed(cancel_postgres)
    engine = _runtime_engine(test_database.url, application_name="gpm-cancel-session-user")
    sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        with pytest.raises(DependencyUnavailable):
            PostgresJobLocatorReader(sessions).get_locator(job_id=uuid.UUID(fixture.job_id))
        with pytest.raises(DependencyUnavailable):
            with PostgresJobCancelUnitOfWork(sessions).transaction(principal=_owner(fixture)):
                raise AssertionError("body must not run for a non-API login")
        assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        engine.dispose()


# -- PG-CANCEL-10 / 11 / 12: DB clock and concurrency ----------------------------------


def test_cancel_waits_for_listing_lock_then_stamps_database_time_after_release(
    cancel_postgres: Engine, test_database: TestDatabase
) -> None:
    fixture = _seed(cancel_postgres)
    contender = _stack(test_database.url, application_name="gpm-cancel-contender")
    holder = cancel_postgres.connect()
    try:
        transaction = holder.begin()
        holder.execute(text("SELECT id FROM gpu_listings WHERE id = :id FOR UPDATE"), {"id": fixture.listing_id})
        thread, box = _in_thread(
            lambda: contender.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))
        )
        _wait_until_blocked_on_lock(cancel_postgres, "gpm-cancel-contender")
        # Lock order proof (PG-CANCEL-12): the waiter holds no Job row lock yet.
        holder.execute(text("SELECT id FROM jobs WHERE id = :id FOR UPDATE NOWAIT"), {"id": fixture.job_id})
        released_at = holder.execute(text("SELECT clock_timestamp()")).scalar_one()
        transaction.commit()
        thread.join(15)
        assert not thread.is_alive()
        assert "error" not in box, box.get("error")
    finally:
        holder.close()
        contender.engine.dispose()

    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after.job_row[6] == "CANCELLED"
    assert after.job_row[9] > released_at  # sampled after the lock was obtained


def test_two_concurrent_cancels_exactly_one_succeeds(
    cancel_postgres: Engine, test_database: TestDatabase, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    job_id, listing_id = uuid.UUID(fixture.job_id), uuid.UUID(fixture.listing_id)
    owner = _owner(fixture)
    contender = _stack(test_database.url, application_name="gpm-cancel-second")
    try:
        with stack.uow.transaction(principal=owner) as first:
            first.lock_listing(listing_id=listing_id)
            first.lock_job(job_id=job_id)
            winner = first.cancel_queued(job_id=job_id, listing_id=listing_id, client_id=owner.user_id)
            thread, box = _in_thread(lambda: contender.service.cancel(principal=owner, job_id=job_id))
            _wait_until_blocked_on_lock(cancel_postgres, "gpm-cancel-second")
            first.commit()
        thread.join(15)
        assert not thread.is_alive()
    finally:
        contender.engine.dispose()

    assert isinstance(box.get("error"), JobNotCancellable)
    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after.job_row[9] == winner.terminal_at  # only the first transition happened
    assert_non_job_side_effects_unchanged(before, after)


def test_lock_timeout_maps_to_dependency_unavailable_without_mutation(
    cancel_postgres: Engine, test_database: TestDatabase
) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    impatient = _stack(test_database.url, lock_timeout_ms=300)
    holder = cancel_postgres.connect()
    try:
        transaction = holder.begin()
        holder.execute(text("SELECT id FROM gpu_listings WHERE id = :id FOR UPDATE"), {"id": fixture.listing_id})
        with pytest.raises(DependencyUnavailable) as raised:
            impatient.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))
        transaction.rollback()
        assert raised.value.__cause__ is None and raised.value.__suppress_context__
        assert impatient.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        holder.close()
        impatient.engine.dispose()
    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))


# -- PG-CANCEL-13: outage ---------------------------------------------------------------


def test_locator_and_transaction_report_outage_without_driver_text(
    cancel_postgres: Engine, test_database: TestDatabase
) -> None:
    fixture = _seed(cancel_postgres)
    dead = _stack(test_database.url.replace(":55433/", ":1/") if ":55433/" in test_database.url else "postgresql+psycopg://x@127.0.0.1:1/x")
    try:
        with pytest.raises(DependencyUnavailable) as locator_error:
            PostgresJobLocatorReader(dead.sessions).get_locator(job_id=uuid.UUID(fixture.job_id))
        with pytest.raises(DependencyUnavailable) as begin_error:
            with dead.uow.transaction(principal=_owner(fixture)):
                raise AssertionError("body must not run when begin fails")
        for error in (locator_error.value, begin_error.value):
            assert error.__cause__ is None and error.__suppress_context__
            assert str(error) == "DEPENDENCY_UNAVAILABLE"
        assert dead.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        dead.engine.dispose()


def test_backend_terminated_mid_transaction_is_dependency_unavailable_and_cleans_up(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    transaction = stack.uow.transaction(principal=_owner(fixture))

    with pytest.raises(DependencyUnavailable):
        with transaction as tx:
            pid = tx._session.execute(text("SELECT pg_backend_pid()")).scalar_one()  # type: ignore[union-attr]
            with cancel_postgres.connect() as admin:
                admin.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            time.sleep(0.2)
            tx.lock_listing(listing_id=uuid.UUID(fixture.listing_id))

    assert transaction.outcome is TransactionOutcome.ROLLED_BACK
    assert_snapshot_unchanged(before, read_persisted_snapshot(cancel_postgres, fixture))
    _assert_no_leaked_connections(stack)


# -- PG-CANCEL-14: commit outcome -------------------------------------------------------


def _staged_cancel(stack: Stack, fixture: CommittedJobFixture):
    job_id, listing_id = uuid.UUID(fixture.job_id), uuid.UUID(fixture.listing_id)
    transaction = stack.uow.transaction(principal=_owner(fixture))
    tx = transaction.__enter__()
    tx.lock_listing(listing_id=listing_id)
    tx.lock_job(job_id=job_id)
    tx.cancel_queued(job_id=job_id, listing_id=listing_id, client_id=uuid.UUID(fixture.client_user_id))
    return transaction


def test_commit_with_lost_acknowledgement_is_unknown_and_never_rolled_back_by_adapter(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    transaction = _staged_cancel(stack, fixture)
    session = transaction._session
    assert session is not None
    real_commit = session.commit

    def commit_then_lose_ack() -> None:
        real_commit()  # durable COMMIT ...
        raise OperationalError("stmt", {}, _FakeDriverError("08006"))  # ... but the ack is lost

    session.commit = commit_then_lose_ack  # type: ignore[method-assign]
    try:
        with pytest.raises(CommitOutcomeUnknown) as raised:
            transaction.commit()
    finally:
        transaction.__exit__(None, None, None)

    assert raised.value.__cause__ is None
    assert transaction.outcome is TransactionOutcome.COMMIT_OUTCOME_UNKNOWN
    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after.job_row[6] == "CANCELLED"  # durable although reported unknown
    _assert_no_leaked_connections(stack)


def test_commit_connection_loss_is_unknown_and_state_stays_queued(
    cancel_postgres: Engine, stack: Stack
) -> None:
    fixture = _seed(cancel_postgres)
    transaction = _staged_cancel(stack, fixture)
    session = transaction._session
    assert session is not None
    pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
    with cancel_postgres.connect() as admin:
        admin.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
    time.sleep(0.2)

    try:
        with pytest.raises(CommitOutcomeUnknown):
            transaction.commit()
    finally:
        transaction.__exit__(None, None, None)

    assert transaction.outcome is TransactionOutcome.COMMIT_OUTCOME_UNKNOWN
    assert read_persisted_snapshot(cancel_postgres, fixture).job_row[6] == "QUEUED"
    _assert_no_leaked_connections(stack)


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "23514"])
def test_commit_aborted_by_server_is_known_rollback_dependency_unavailable(
    cancel_postgres: Engine, stack: Stack, sqlstate: str
) -> None:
    fixture = _seed(cancel_postgres)
    transaction = _staged_cancel(stack, fixture)
    session = transaction._session
    assert session is not None

    def aborted() -> None:
        session.rollback()
        raise DBAPIError("stmt", {}, _FakeDriverError(sqlstate))

    session.commit = aborted  # type: ignore[method-assign]
    try:
        with pytest.raises(DependencyUnavailable):
            transaction.commit()
    finally:
        transaction.__exit__(None, None, None)

    assert transaction.outcome is TransactionOutcome.ROLLED_BACK
    assert read_persisted_snapshot(cancel_postgres, fixture).job_row[6] == "QUEUED"


def test_service_does_not_swallow_or_retry_unknown_commit(
    cancel_postgres: Engine, stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _seed(cancel_postgres)
    calls = {"commit": 0}
    original = Session.commit

    def failing_commit(self: Session) -> None:
        calls["commit"] += 1
        raise OperationalError("stmt", {}, _FakeDriverError("08006"))

    monkeypatch.setattr(Session, "commit", failing_commit)
    with pytest.raises(CommitOutcomeUnknown):
        stack.service.cancel(principal=_owner(fixture), job_id=uuid.UUID(fixture.job_id))
    monkeypatch.setattr(Session, "commit", original)

    assert calls["commit"] == 1  # no automatic retry
    assert read_persisted_snapshot(cancel_postgres, fixture).job_row[6] == "QUEUED"
    _assert_no_leaked_connections(stack)


# -- misuse guards ---------------------------------------------------------------------


def test_transaction_is_single_use_and_requires_lock_order(cancel_postgres: Engine, stack: Stack) -> None:
    fixture = _seed(cancel_postgres)
    job_id, listing_id = uuid.UUID(fixture.job_id), uuid.UUID(fixture.listing_id)
    transaction = stack.uow.transaction(principal=_owner(fixture))
    with transaction as tx:
        with pytest.raises(RuntimeError):
            tx.lock_job(job_id=job_id)  # Job before Listing is a programming error
        with pytest.raises(RuntimeError):
            tx.cancel_queued(job_id=job_id, listing_id=listing_id, client_id=uuid.UUID(fixture.client_user_id))
    with pytest.raises(RuntimeError):
        transaction.__enter__()
    assert read_persisted_snapshot(cancel_postgres, fixture).job_row[6] == "QUEUED"
    _assert_no_leaked_connections(stack)
