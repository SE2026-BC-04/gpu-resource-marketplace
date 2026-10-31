"""Safe PostgreSQL support for future TX-CANCEL integration tests.

Call these helpers only with the repository's ``baseline_database`` Engine
fixture. That fixture depends on ``test_database``/``db_engine`` and therefore
the disposable-cluster opt-in and verification guards in ``db_safety.py``.
Seed helpers commit on purpose so independent PostgreSQL connections can see
the fixtures; teardown removes only the generated rows.
"""

from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from test_schema_constraints import add_job, add_listing, add_user, add_worker


JOB_STATES = frozenset({"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"})
LISTING_STATES = frozenset({"ACTIVE", "PAUSED"})


@dataclass(frozen=True)
class CommittedJobFixture:
    client_user_id: str
    worker_user_id: str
    worker_id: str
    listing_id: str
    job_id: str


@dataclass(frozen=True)
class PersistedJobSnapshot:
    job_row: tuple[object, ...]
    listing_allocated_gpu_count: int
    simulation_reference_fingerprint: str | None
    worker_reputation: tuple[int, int] | None


def job_state_fields(status: str, database_time: datetime) -> dict[str, object]:
    """Return only the lifecycle fields needed to seed a valid existing-schema Job."""
    if status not in JOB_STATES:
        raise ValueError(f"Unsupported Job fixture status: {status}")
    if status == "QUEUED":
        return {}
    if status == "RUNNING":
        return {"status": status, "started_at": database_time}
    if status == "COMPLETED":
        return {"status": status, "started_at": database_time, "terminal_at": database_time}
    if status == "FAILED":
        return {
            "status": status,
            "started_at": database_time,
            "terminal_at": database_time,
            "failure_reason": "JOB_FAULT",
        }
    return {"status": status, "terminal_at": database_time}


def seed_committed_job(
    engine: Engine,
    *,
    status: str = "QUEUED",
    listing_status: str = "ACTIVE",
    total_gpu_count: int = 4,
) -> CommittedJobFixture:
    """Seed a committed Client/Worker/Listing/Job using existing schema helpers.

    ``engine`` must come from ``baseline_database``. The database-clock read and
    all rows are in one committed setup unit. Independent test connections can
    therefore observe these fixtures (unlike seeds made through rollback-only
    ``conn``).
    """
    if listing_status not in LISTING_STATES:
        raise ValueError(f"Unsupported Listing fixture status: {listing_status}")
    if type(total_gpu_count) is not int or total_gpu_count <= 0:
        raise ValueError("total_gpu_count must be a positive integer")

    with engine.begin() as connection:
        database_time = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        client_user_id = add_user(connection, "CLIENT")
        worker_user_id, worker_id = add_worker(connection)
        listing_id = add_listing(connection, worker_id, total=total_gpu_count)
        if listing_status == "PAUSED":
            connection.execute(
                text("UPDATE gpu_listings SET status = 'PAUSED' WHERE id = :id"),
                {"id": listing_id},
            )
        job_id = add_job(
            connection,
            client_user_id,
            listing_id,
            worker_id,
            job_state_fields(status, database_time),
        )
    return CommittedJobFixture(
        client_user_id=client_user_id,
        worker_user_id=worker_user_id,
        worker_id=worker_id,
        listing_id=listing_id,
        job_id=job_id,
    )


def delete_committed_job_fixture(engine: Engine, fixture: CommittedJobFixture) -> None:
    """Delete only this fixture, in FK-safe order, using a verified test Engine."""
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM simulation_references WHERE job_id = :id"),
            {"id": fixture.job_id},
        )
        connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": fixture.job_id})
        connection.execute(
            text("DELETE FROM gpu_listings WHERE id = :id"),
            {"id": fixture.listing_id},
        )
        connection.execute(
            text("DELETE FROM worker_reputation_aggregates WHERE worker_id = :id"),
            {"id": fixture.worker_id},
        )
        connection.execute(text("DELETE FROM workers WHERE id = :id"), {"id": fixture.worker_id})
        connection.execute(
            text("DELETE FROM user_roles WHERE user_id IN (:client, :worker)"),
            {"client": fixture.client_user_id, "worker": fixture.worker_user_id},
        )
        connection.execute(
            text("DELETE FROM users WHERE id IN (:client, :worker)"),
            {"client": fixture.client_user_id, "worker": fixture.worker_user_id},
        )


@contextmanager
def committed_job_fixture(
    engine: Engine,
    *,
    status: str = "QUEUED",
    listing_status: str = "ACTIVE",
    total_gpu_count: int = 4,
) -> Iterator[CommittedJobFixture]:
    """Commit setup rows for cross-connection tests and always clean them in finally."""
    fixture = seed_committed_job(
        engine,
        status=status,
        listing_status=listing_status,
        total_gpu_count=total_gpu_count,
    )
    try:
        yield fixture
    finally:
        delete_committed_job_fixture(engine, fixture)


def _reference_fingerprint(values: tuple[object, ...] | None) -> str | None:
    if values is None:
        return None
    material = "\x1f".join(str(value) for value in values).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def read_persisted_snapshot(engine: Engine, fixture: CommittedJobFixture) -> PersistedJobSnapshot:
    """Read state through a fresh connection; never query Phase 2-only tables.

    The existing Phase 1B schema has Jobs, Listings, simulation references and
    Worker reputation aggregates. Allocations, Signed Results and contribution
    rows are intentionally not queried here because those tables are absent on
    the PR #33 baseline; tests must wait for their schema owner/phase.
    """
    with engine.connect() as connection:
        job = connection.execute(
            text(
                "SELECT id::text, client_id::text, listing_id::text, worker_id::text, "
                "requested_gpu_count, duration_seconds, status, submitted_at, started_at, "
                "terminal_at, failure_reason FROM jobs WHERE id = :id"
            ),
            {"id": fixture.job_id},
        ).one_or_none()
        if job is None:
            job_row: tuple[object, ...] = ()
        else:
            job_row = tuple(job)

        listing = connection.execute(
            text("SELECT allocated_gpu_count FROM gpu_listings WHERE id = :id"),
            {"id": fixture.listing_id},
        ).scalar_one_or_none()
        if listing is None:
            raise AssertionError("test Listing disappeared while reading its snapshot")

        reference = connection.execute(
            text(
                "SELECT seed_value, algorithm_version, expected_outcome, "
                "expected_failure_reason, expected_digest FROM simulation_references "
                "WHERE job_id = :id"
            ),
            {"id": fixture.job_id},
        ).one_or_none()
        reference_values = None if reference is None else tuple(reference)

        reputation = connection.execute(
            text(
                "SELECT successful_jobs, worker_fault_jobs FROM worker_reputation_aggregates "
                "WHERE worker_id = :id"
            ),
            {"id": fixture.worker_id},
        ).one_or_none()
    return PersistedJobSnapshot(
        job_row=job_row,
        listing_allocated_gpu_count=listing,
        simulation_reference_fingerprint=_reference_fingerprint(reference_values),
        worker_reputation=None if reputation is None else tuple(reputation),
    )


def assert_snapshot_unchanged(
    before: PersistedJobSnapshot,
    after: PersistedJobSnapshot,
) -> None:
    """Assert existing-schema state did not change; diagnostics contain no oracle values."""
    assert after == before


def read_database_clock(engine: Engine) -> datetime:
    """Read PostgreSQL's clock on a fresh connection for trusted-time assertions."""
    with engine.connect() as connection:
        return connection.execute(text("SELECT clock_timestamp()")).scalar_one()


class ListingLockAttempt:
    """Bounded second-connection Listing-lock attempt for PostgreSQL race tests.

    The caller must hold the first transaction's Listing lock before ``start``;
    after observing the wait it commits/rolls back that first transaction, then
    joins this worker. The worker always rolls back and closes its connection.
    """

    def __init__(self, engine: Engine, listing_id: str) -> None:
        self.engine = engine
        self.listing_id = listing_id
        self.pid: int | None = None
        self.result: str | None = None
        self.error_type: str | None = None
        self.sqlstate: str | None = None
        self.started = threading.Event()
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        connection = None
        transaction = None
        operation_error: BaseException | None = None
        try:
            connection = self.engine.connect()
            transaction = connection.begin()
            connection.execute(text("SET LOCAL lock_timeout = '8s'"))
            connection.execute(text("SET LOCAL statement_timeout = '12s'"))
            self.pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            self.started.set()
            connection.execute(
                text("SELECT id FROM gpu_listings WHERE id = :id FOR UPDATE"),
                {"id": self.listing_id},
            ).scalar_one_or_none()
            self.result = "lock_acquired"
        except DBAPIError as error:
            original = error.orig
            self.error_type = type(original).__name__
            self.sqlstate = getattr(original, "sqlstate", None)
            operation_error = error
        except BaseException as error:
            self.error_type = type(error).__name__
            operation_error = error
        finally:
            self.started.set()
            try:
                if transaction is not None and transaction.is_active:
                    transaction.rollback()
            except BaseException as error:
                if operation_error is None:
                    self.error_type = type(error).__name__
            finally:
                try:
                    if connection is not None:
                        connection.close()
                except BaseException as error:
                    if operation_error is None and self.error_type is None:
                        self.error_type = type(error).__name__
                finally:
                    self.finished.set()

    def wait_until_blocked(self, *, timeout: float = 5.0) -> None:
        """Wait for PostgreSQL to report this backend blocked by a row lock."""
        deadline = time.monotonic() + timeout
        if not self.started.wait(timeout):
            raise TimeoutError("second lock connection did not start before timeout")
        if self.pid is None:
            raise AssertionError("second lock connection failed before publishing its backend PID")
        while time.monotonic() < deadline:
            with self.engine.connect() as watcher:
                row = watcher.execute(
                    text(
                        "SELECT wait_event_type, pg_blocking_pids(pid) "
                        "FROM pg_stat_activity WHERE pid = :pid AND datname = current_database()"
                    ),
                    {"pid": self.pid},
                ).one_or_none()
            if row is not None and row.wait_event_type == "Lock" and row[1]:
                return
            if self.finished.is_set():
                raise AssertionError(
                    f"second lock attempt finished before a lock wait (result={self.result!r}, "
                    f"error_type={self.error_type!r}, sqlstate={self.sqlstate!r})"
                )
            self.finished.wait(min(0.05, max(0.0, deadline - time.monotonic())))
        raise TimeoutError("PostgreSQL did not report the second connection waiting on a lock")

    def join(self, *, timeout: float = 15.0) -> None:
        """Bound the worker join; never leave an unbounded test thread."""
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("second PostgreSQL transaction did not finish within join timeout")
