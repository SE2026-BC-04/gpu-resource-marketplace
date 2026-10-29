"""Delegated R1 repository tests; HTTP/Jobs/Manager acceptance is separate.

Setup uses the vetted disposable owner fixture. Every adapter statement executes
as gpm_api_rw, with a new Session/connection and real PostgreSQL transactions.
SQL UPDATEs used as lock stimuli/grant probes are not HTTP/Manager acceptance.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from db_safety import verify_cluster

from gpu_marketplace.domain.identity import (
    User,
    UserRole,
    Worker,
    WorkerReputationAggregate,
)
from gpu_marketplace.domain.jobs import Job
from gpu_marketplace.domain.listings import GpuListing
from gpu_marketplace.repositories.listings import PostgresListingUnitOfWork


class StoreUnavailable(Exception):
    pass


@dataclass(frozen=True)
class WorkerRecord:
    id: UUID
    display_name: str


@dataclass(frozen=True)
class ListingRecord:
    id: UUID
    worker: WorkerRecord
    gpu_model: str
    vram_gb: int
    total_gpu_count: int
    allocated_gpu_count: int
    status: str
    mock_price_per_hour: Decimal | None
    created_at: datetime
    updated_at: datetime
    successful_jobs: int
    worker_fault_jobs: int


VALUES = {"gpu_model": "R1 simulated GPU", "vram_gb": 24, "total_gpu_count": 8}


def make_uow(sessions):
    return PostgresListingUnitOfWork(
        sessions,
        worker_record=WorkerRecord,
        listing_record=ListingRecord,
        unavailable_error=StoreUnavailable,
    )


@pytest.fixture
def sessions(baseline_database: Engine):
    factory = sessionmaker(bind=baseline_database)

    def restrict(session, transaction, connection):
        connection.execute(text("SET LOCAL ROLE gpm_api_rw"))

    event.listen(factory, "after_begin", restrict)
    try:
        yield factory
    finally:
        event.remove(factory, "after_begin", restrict)


@pytest.fixture
def data(baseline_database: Engine):
    values = SimpleNamespace(
        worker=uuid4(),
        other_worker=uuid4(),
        user=uuid4(),
        other_user=uuid4(),
        client=uuid4(),
        listing=uuid4(),
        paused=uuid4(),
        other_listing=uuid4(),
    )
    with baseline_database.begin() as connection:
        for user_id, role in (
            (values.user, "WORKER"),
            (values.other_user, "WORKER"),
            (values.client, "CLIENT"),
        ):
            connection.execute(
                insert(User).values(
                    id=user_id, login_name=str(user_id), password_hash="synthetic"
                )
            )
            connection.execute(insert(UserRole).values(user_id=user_id, role_code=role))
        connection.execute(
            insert(Worker),
            [
                {
                    "id": values.worker,
                    "user_id": values.user,
                    "display_name": "Worker A",
                },
                {
                    "id": values.other_worker,
                    "user_id": values.other_user,
                    "display_name": "Worker B",
                },
            ],
        )
        connection.execute(
            insert(WorkerReputationAggregate).values(
                worker_id=values.worker,
                successful_jobs=9,
                worker_fault_jobs=1,
            )
        )
        same_time = datetime(2026, 1, 1, tzinfo=UTC)
        for listing_id, worker_id, status in (
            (values.listing, values.worker, "ACTIVE"),
            (values.paused, values.worker, "PAUSED"),
            (values.other_listing, values.other_worker, "ACTIVE"),
        ):
            connection.execute(
                insert(GpuListing).values(
                    id=listing_id,
                    worker_id=worker_id,
                    status=status,
                    created_at=same_time,
                    **VALUES,
                )
            )
    return values


def add_job(engine, data, count, status="QUEUED"):
    with engine.begin() as connection:
        connection.execute(
            insert(Job).values(
                client_id=data.client,
                listing_id=data.listing,
                worker_id=data.worker,
                requested_gpu_count=count,
                duration_seconds=30,
                status=status,
                submitted_at=datetime.now(UTC),
                correlation_id=uuid4(),
                started_at=datetime.now(UTC)
                if status not in {"QUEUED", "CANCELLED"}
                else None,
                terminal_at=datetime.now(UTC)
                if status in {"COMPLETED", "FAILED", "CANCELLED"}
                else None,
                failure_reason="JOB_FAULT" if status == "FAILED" else None,
            )
        )


def test_effective_role_is_restricted_and_read_committed(sessions):
    with make_uow(sessions) as uow:
        role, isolation = uow._execute(
            text("SELECT current_user, current_setting('transaction_isolation')")
        ).one()
        assert (role, isolation) == ("gpm_api_rw", "read committed")


def test_owner_session_is_rejected_and_closed(baseline_database):
    factory = sessionmaker(bind=baseline_database)
    with pytest.raises(StoreUnavailable):
        with make_uow(factory):
            pytest.fail("Owner session must never enter a Listing UoW")


def test_worker_lookup_and_public_frozen_projection(sessions, data):
    with make_uow(sessions) as uow:
        worker = uow.workers.find_by_user_id(data.user)
        assert worker == WorkerRecord(data.worker, "Worker A")
        assert uow.workers.find_by_user_id(data.client) is None
        assert uow.workers.find_by_user_id(uuid4()) is None
        record = uow.listings.get(data.listing)
        assert record.worker == worker
        assert (record.successful_jobs, record.worker_fault_jobs) == (9, 1)
        assert set(record.__dict__) == set(ListingRecord.__dataclass_fields__)
    assert record.gpu_model == VALUES["gpu_model"]
    with pytest.raises(FrozenInstanceError):
        record.gpu_model = "mutated"


def test_missing_reputation_defaults_to_zero(sessions, data):
    with make_uow(sessions) as uow:
        record = uow.listings.get(data.other_listing)
        assert (record.successful_jobs, record.worker_fault_jobs) == (0, 0)
        assert uow.listings.get(uuid4()) is None


def test_keyset_tie_breaker_filters_in_sql(sessions, data):
    query = SimpleNamespace(status=None, worker_id=data.worker)
    with make_uow(sessions) as uow:
        rows = uow.listings.page(query, None, 101)
        assert [row.id for row in rows] == sorted(
            (data.listing, data.paused), reverse=True
        )
        first = uow.listings.page(query, None, 1)[0]
        after = SimpleNamespace(created_at=first.created_at, id=first.id)
        assert [row.id for row in uow.listings.page(query, after, 1)] == [rows[1].id]
        active = uow.listings.page(
            SimpleNamespace(status="ACTIVE", worker_id=data.worker), None, 101
        )
        assert [row.id for row in active] == [data.listing]
        assert (
            uow.listings.page(
                SimpleNamespace(status=None, worker_id=uuid4()), None, 101
            )
            == ()
        )


def test_create_uses_db_defaults_and_commit(sessions, data):
    with make_uow(sessions) as uow:
        record = uow.listings.create(
            data.worker, {**VALUES, "mock_price_per_hour": Decimal("1.20")}
        )
        assert record.id.version == 4
        assert (record.status, record.allocated_gpu_count, record.worker.id) == (
            "ACTIVE",
            0,
            data.worker,
        )
        assert record.created_at.utcoffset().total_seconds() == 0
        assert record.updated_at >= record.created_at
        uow.commit()
    with make_uow(sessions) as uow:
        assert uow.listings.get(record.id) == record


@pytest.mark.parametrize(
    "field",
    ["id", "worker_id", "status", "allocated_gpu_count", "created_at", "updated_at"],
)
def test_managed_create_fields_rejected_before_sql(sessions, data, field):
    with make_uow(sessions) as uow:
        with pytest.raises(ValueError):
            uow.listings.create(data.worker, {**VALUES, field: None})


def test_exit_without_commit_rolls_back(sessions, data):
    with make_uow(sessions) as uow:
        record = uow.listings.create(data.worker, VALUES)
    with make_uow(sessions) as uow:
        assert uow.listings.get(record.id) is None


def test_exception_rolls_back_all_prior_writes(sessions, data):
    with pytest.raises(StoreUnavailable):
        with make_uow(sessions) as uow:
            record = uow.listings.create(data.worker, VALUES)
            uow.listings.create(data.worker, {**VALUES, "total_gpu_count": 0})
    with make_uow(sessions) as uow:
        assert uow.listings.get(record.id) is None


def test_commit_failure_rolls_back_and_is_sanitized(
    sessions, data, monkeypatch, caplog
):
    with caplog.at_level(logging.ERROR), pytest.raises(StoreUnavailable) as error:
        with make_uow(sessions) as uow:
            record = uow.listings.create(data.worker, VALUES)

            def fail():
                raise OperationalError("secret SQL", {}, Exception("secret DSN"))

            monkeypatch.setattr(uow._active(), "commit", fail)
            uow.commit()
    assert str(error.value) == "" and error.value.__suppress_context__
    assert "secret" not in caplog.text
    with make_uow(sessions) as uow:
        assert uow.listings.get(record.id) is None


@pytest.mark.parametrize("method", ["has_nonterminal_jobs", "max_queued_gpu_count"])
def test_constraint_read_requires_matching_listing_lock(sessions, data, method):
    with make_uow(sessions) as uow:
        with pytest.raises(RuntimeError):
            getattr(uow.jobs, method)(data.listing)
        uow.listings.get_for_update(data.other_listing)
        with pytest.raises(RuntimeError):
            getattr(uow.jobs, method)(data.listing)


@pytest.mark.parametrize(
    "status,expected",
    [
        ("QUEUED", True),
        ("RUNNING", True),
        ("COMPLETED", False),
        ("FAILED", False),
        ("CANCELLED", False),
    ],
)
def test_nonterminal_guard_reads_real_job_statuses(
    baseline_database, sessions, data, status, expected
):
    add_job(baseline_database, data, 3, status)
    with make_uow(sessions) as uow:
        uow.listings.get_for_update(data.listing)
        assert uow.jobs.has_nonterminal_jobs(data.listing) is expected


def test_queued_capacity_is_max_not_sum(baseline_database, sessions, data):
    for count, status in [
        (7, "QUEUED"),
        (4, "QUEUED"),
        (99, "RUNNING"),
        (999, "COMPLETED"),
    ]:
        add_job(baseline_database, data, count, status)
    with make_uow(sessions) as uow:
        uow.listings.get_for_update(data.listing)
        assert uow.jobs.max_queued_gpu_count(data.listing) == 7
        uow.listings.get_for_update(data.other_listing)
        assert uow.jobs.max_queued_gpu_count(data.other_listing) == 0


def test_outer_reputation_join_does_not_lock_nullable_side(sessions, data):
    with make_uow(sessions) as uow:
        record = uow.listings.get_for_update(data.other_listing)
        assert record.id == data.other_listing
        assert uow.jobs.max_queued_gpu_count(data.other_listing) == 0
        assert uow.listings.get_for_update(uuid4()) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("allocated_gpu_count", 1),
        ("worker_id", None),
        ("created_at", datetime(2020, 1, 1, tzinfo=UTC)),
        ("updated_at", datetime(2020, 1, 1, tzinfo=UTC)),
    ],
)
def test_actual_api_role_cannot_update_managed_columns(sessions, data, field, value):
    with pytest.raises(StoreUnavailable):
        with make_uow(sessions) as uow:
            uow._execute(
                update(GpuListing)
                .where(GpuListing.id == data.listing)
                .values(**{field: value})
            )


@pytest.mark.parametrize("operation", ["patch", "pause", "resume"])
def test_effective_writes_fail_closed_when_d7_disabled(
    baseline_database, test_database, sessions, data, operation
):
    listing_id = data.paused if operation == "resume" else data.listing
    with baseline_database.begin() as owner:
        verify_cluster(owner, test_database)
        owner.execute(
            text(
                "ALTER TABLE public.gpu_listings DISABLE TRIGGER trg_gpu_listings_guard_update"
            )
        )
    try:
        with make_uow(sessions) as uow:
            before = uow.listings.get(listing_id)
        with pytest.raises(StoreUnavailable):
            with make_uow(sessions) as uow:
                extra = uow.listings.create(data.worker, VALUES)
                uow.listings.get_for_update(listing_id)
                if operation == "patch":
                    uow.listings.update(listing_id, {"total_gpu_count": 9})
                else:
                    uow.listings.set_status(
                        listing_id, "PAUSED" if operation == "pause" else "ACTIVE"
                    )
        with make_uow(sessions) as uow:
            assert uow.listings.get(listing_id) == before
            assert uow.listings.get(extra.id) is None
    finally:
        with baseline_database.begin() as owner:
            verify_cluster(owner, test_database)
            owner.execute(
                text(
                    "ALTER TABLE public.gpu_listings ENABLE TRIGGER trg_gpu_listings_guard_update"
                )
            )


def test_noop_does_not_write_or_require_d7(sessions, data):
    with make_uow(sessions) as uow:
        record = uow.listings.get_for_update(data.listing)
        assert uow.listings.update(data.listing, {}) == record
        assert uow.listings.set_status(data.listing, "ACTIVE") == record
        uow.commit()


def test_single_use_and_no_access_after_commit_or_exit(sessions, data):
    uow = make_uow(sessions)
    with uow:
        uow.commit()
        with pytest.raises(RuntimeError):
            uow.listings.get(data.listing)
    with pytest.raises(RuntimeError):
        uow.listings.get(data.listing)
    with pytest.raises(RuntimeError):
        with uow:
            pass


def test_two_sessions_wait_then_read_fresh_listing_and_job_guard(
    baseline_database, sessions, data
):
    ready = Event()
    observed = {}

    def contender():
        with make_uow(sessions) as second:
            assert second.listings.get(data.listing).total_gpu_count == 8
            observed["pid"] = second._execute(
                text("SELECT pg_backend_pid()")
            ).scalar_one()
            ready.set()
            record = second.listings.get_for_update(data.listing)
            return (
                record.total_gpu_count,
                second.jobs.max_queued_gpu_count(data.listing),
                record.updated_at,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with make_uow(sessions) as first:
            first.listings.get_for_update(data.listing)
            pending = pool.submit(contender)
            assert ready.wait(5), "Contender did not start"
            blocked = False
            for _ in range(150):
                with baseline_database.connect() as observer:
                    blocked = observer.execute(
                        text(
                            "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": observed["pid"]},
                    ).scalar_one_or_none()
                if blocked:
                    break
                Event().wait(0.02)
            assert blocked, "No real PostgreSQL lock wait was observed"
            changed = first.listings.update(data.listing, {"total_gpu_count": 12})
            # Raw Job insert is a protocol stimulus, not implemented TX-SUBMIT.
            first._execute(
                insert(Job).values(
                    client_id=data.client,
                    listing_id=data.listing,
                    worker_id=data.worker,
                    requested_gpu_count=10,
                    duration_seconds=30,
                    submitted_at=datetime.now(UTC),
                    correlation_id=uuid4(),
                )
            )
            first.commit()
        assert pending.result(timeout=5) == (12, 10, changed.updated_at)


def test_unreachable_db_is_sanitized_without_sql_or_dsn(caplog):
    from gpu_marketplace.common.database import create_engine

    engine = create_engine(
        "postgresql+psycopg://probe:secret-in-dsn@127.0.0.1:1/gpu_marketplace_probe"
    )
    try:
        with caplog.at_level(logging.ERROR), pytest.raises(StoreUnavailable) as raised:
            with make_uow(sessionmaker(bind=engine)):
                pytest.fail("Unreachable DB cannot enter")
        assert str(raised.value) == "" and raised.value.__suppress_context__
        for sensitive in ("secret-in-dsn", "127.0.0.1", "SELECT", "probe"):
            assert sensitive not in caplog.text
            assert sensitive not in repr(raised.value)
    finally:
        engine.dispose()
