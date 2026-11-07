"""Deterministic PostgreSQL races between TX-SUBMIT and Listing mutations.

Every command opens an independent SQLAlchemy Session/connection. Events hold the
winning transaction at a known point; no sleep is used to select commit order.
The inherited database fixtures refuse to run without the disposable-cluster
safety markers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from db_safety import TestDatabase
from gpu_marketplace.jobs.errors import JobGpuExceedsListingTotal, ListingPaused
from gpu_marketplace.jobs.models import SubmitJobRequest
from gpu_marketplace.jobs.submit import JobSubmitService
from gpu_marketplace.listings.cursors import ListingCursorCodec
from gpu_marketplace.listings.errors import ListingDependencyUnavailable, ListingError
from gpu_marketplace.listings.models import ListingRecord, WorkerProfile
from gpu_marketplace.listings.service import ListingService
from gpu_marketplace.repositories.audit import PostgresAuditWriter
from gpu_marketplace.repositories.job_submit import PostgresJobSubmissionStore
from gpu_marketplace.repositories.listings import PostgresListingUnitOfWork
from test_schema_constraints import add_listing, add_user, add_worker


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str
    status: str = "ACTIVE"


@dataclass(frozen=True)
class FixtureIds:
    client_id: UUID
    worker_user_id: UUID
    worker_id: UUID
    listing_id: UUID


@pytest.fixture
def integration_services(
    baseline_database: Engine, test_database: TestDatabase
) -> Iterator[
    tuple[
        Engine,
        Callable[[], sessionmaker[Session]],
        ListingService,
        JobSubmitService,
        FixtureIds,
    ]
]:
    engine = baseline_database
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def restrict_to_runtime_group(
        _session: Session, _transaction: object, connection
    ) -> None:
        connection.execute(text('SET LOCAL ROLE "gpm_api_rw"'))

    event.listen(sessions, "after_begin", restrict_to_runtime_group)
    try:
        owner_login = make_url(test_database.url).username or ""
        audit_writer = PostgresAuditWriter(sessions)
        listing_service = ListingService(
            lambda: PostgresListingUnitOfWork(
                sessions,
                worker_record=WorkerProfile,
                listing_record=ListingRecord,
                unavailable_error=ListingDependencyUnavailable,
            ),
            ListingCursorCodec(b"concurrency-test-listing-cursor-key-0123456789"),
            audit_writer=audit_writer,
        )
        job_service = JobSubmitService(
            store=PostgresJobSubmissionStore(
                sessions, allowed_session_users=frozenset({owner_login})
            ),
            audit_writer=audit_writer,
        )
        with engine.begin() as connection:
            client_id = UUID(add_user(connection, "CLIENT"))
            worker_user_id, worker_id = add_worker(connection)
            listing_id = UUID(add_listing(connection, worker_id, total=4))
        ids = FixtureIds(client_id, UUID(worker_user_id), UUID(worker_id), listing_id)
        yield engine, lambda: sessions, listing_service, job_service, ids
    finally:
        event.remove(sessions, "after_begin", restrict_to_runtime_group)


class _SubmissionGate:
    def __init__(
        self,
        delegate,
        *,
        before_lock: Event | None = None,
        locked: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self._delegate = delegate
        self._before_lock = before_lock
        self._locked = locked
        self._release = release

    def __enter__(self):
        self._delegate.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._delegate.__exit__(*exc_info)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def lock_listing(self, *, listing_id: UUID):
        if self._before_lock is not None:
            self._before_lock.set()
        result = self._delegate.lock_listing(listing_id=listing_id)
        if self._locked is not None:
            self._locked.set()
        if self._release is not None and not self._release.wait(20):
            raise TimeoutError("submit synchronization gate timed out")
        return result


class _SubmissionStoreGate:
    def __init__(self, delegate, **gate_options) -> None:
        self._delegate = delegate
        self._gate_options = gate_options

    def find_existing(self, **kwargs):
        return self._delegate.find_existing(**kwargs)

    def transaction(self, **kwargs):
        return _SubmissionGate(
            self._delegate.transaction(**kwargs), **self._gate_options
        )


class _ListingRepositoryGate:
    def __init__(
        self,
        delegate,
        *,
        before_lock: Event | None = None,
        locked: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self._delegate = delegate
        self._before_lock = before_lock
        self._locked = locked
        self._release = release

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def get_for_update(self, listing_id: UUID):
        if self._before_lock is not None:
            self._before_lock.set()
        result = self._delegate.get_for_update(listing_id)
        if self._locked is not None:
            self._locked.set()
        if self._release is not None and not self._release.wait(20):
            raise TimeoutError("Listing synchronization gate timed out")
        return result


class _ListingUnitOfWorkGate:
    def __init__(self, delegate, **gate_options) -> None:
        self._delegate = delegate
        self.workers = delegate.workers
        self.listings = _ListingRepositoryGate(delegate.listings, **gate_options)
        self.jobs = delegate.jobs

    def __enter__(self):
        self._delegate.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._delegate.__exit__(*exc_info)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


def _submit(
    service: JobSubmitService,
    ids: FixtureIds,
    *,
    key: str,
) -> object:
    return service.submit(
        principal=Principal(ids.client_id, "CLIENT"),
        idempotency_key=key,
        request=SubmitJobRequest(
            listing_id=ids.listing_id,
            gpu_count=2,
            duration_seconds=60,
        ),
        correlation_id=uuid4(),
    )


def _listing_service_with_gate(
    sessions: Callable[[], sessionmaker[Session]],
    audit_writer: PostgresAuditWriter,
    **gate_options,
) -> ListingService:
    return ListingService(
        lambda: _ListingUnitOfWorkGate(
            PostgresListingUnitOfWork(
                sessions(),
                worker_record=WorkerProfile,
                listing_record=ListingRecord,
                unavailable_error=ListingDependencyUnavailable,
            ),
            **gate_options,
        ),
        ListingCursorCodec(b"concurrency-test-listing-cursor-key-0123456789"),
        audit_writer=audit_writer,
    )


def _audit_writer(sessions: Callable[[], sessionmaker[Session]]) -> PostgresAuditWriter:
    return PostgresAuditWriter(sessions())


def _counts(engine: Engine, listing_id: UUID) -> tuple[int, int, int]:
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT count(*) FROM jobs WHERE listing_id = :id"), {"id": listing_id}
            ).scalar_one(),
            connection.execute(
                text(
                    "SELECT count(*) FROM simulation_references sr "
                    "JOIN jobs j ON j.id = sr.job_id WHERE j.listing_id = :id"
                ),
                {"id": listing_id},
            ).scalar_one(),
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE subject_type = 'JOB' "
                    "AND subject_id IN (SELECT id FROM jobs WHERE listing_id = :id) "
                    "AND event_type = 'JOB_SUBMIT' AND outcome = 'SUCCESS'"
                ),
                {"id": listing_id},
            ).scalar_one(),
        )


def test_submit_holds_listing_lock_before_pause_and_both_commit_once(
    integration_services,
) -> None:
    engine, sessions, _listing_service, job_service, ids = integration_services
    locked, allow_submit, pause_attempt = Event(), Event(), Event()
    writer = _audit_writer(sessions)
    gated_submit = JobSubmitService(
        store=_SubmissionStoreGate(
            job_service._store, locked=locked, release=allow_submit
        ),
        audit_writer=writer,
    )
    gated_listing = _listing_service_with_gate(
        sessions, writer, before_lock=pause_attempt
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        submit_future = pool.submit(_submit, gated_submit, ids, key="race-submit-pause-a")
        assert locked.wait(15), "Submit did not acquire its Listing lock"
        pause_future = pool.submit(
            gated_listing.set_status,
            Principal(ids.worker_user_id, "WORKER"),
            ids.listing_id,
            "PAUSED",
            correlation_id=uuid4(),
        )
        try:
            assert pause_attempt.wait(15), "Pause did not reach its Listing lock"
        finally:
            allow_submit.set()
        result = submit_future.result(timeout=20)
        paused = pause_future.result(timeout=20)

    assert result.job.status.value == "QUEUED"
    assert paused.status == "PAUSED"
    assert _counts(engine, ids.listing_id) == (1, 1, 1)


def test_pause_commits_before_new_key_submit_and_creates_no_job_or_reference(
    integration_services,
) -> None:
    engine, sessions, _listing_service, job_service, ids = integration_services
    locked, allow_pause, submit_attempt = Event(), Event(), Event()
    writer = _audit_writer(sessions)
    gated_listing = _listing_service_with_gate(
        sessions, writer, locked=locked, release=allow_pause
    )
    gated_submit = JobSubmitService(
        store=_SubmissionStoreGate(job_service._store, before_lock=submit_attempt),
        audit_writer=writer,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        pause_future = pool.submit(
            gated_listing.set_status,
            Principal(ids.worker_user_id, "WORKER"),
            ids.listing_id,
            "PAUSED",
            correlation_id=uuid4(),
        )
        assert locked.wait(15), "Pause did not acquire its Listing lock"
        submit_future = pool.submit(_submit, gated_submit, ids, key="race-submit-pause-b")
        try:
            assert submit_attempt.wait(15), "Submit did not reach its Listing lock"
        finally:
            allow_pause.set()
        assert pause_future.result(timeout=20).status == "PAUSED"
        with pytest.raises(ListingPaused):
            submit_future.result(timeout=20)

    assert _counts(engine, ids.listing_id) == (0, 0, 0)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM audit_events WHERE subject_type='LISTING' "
                 "AND subject_id=:id AND event_type='JOB_SUBMIT' AND outcome='REJECTED'"),
            {"id": ids.listing_id},
        ).scalar_one() == 1


def test_submit_wins_resize_down_rechecks_queued_capacity_under_listing_lock(
    integration_services,
) -> None:
    engine, sessions, _listing_service, job_service, ids = integration_services
    locked, allow_submit, resize_attempt = Event(), Event(), Event()
    writer = _audit_writer(sessions)
    gated_submit = JobSubmitService(
        store=_SubmissionStoreGate(
            job_service._store, locked=locked, release=allow_submit
        ),
        audit_writer=writer,
    )
    gated_listing = _listing_service_with_gate(
        sessions, writer, before_lock=resize_attempt
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        submit_future = pool.submit(_submit, gated_submit, ids, key="race-submit-resize-a")
        assert locked.wait(15), "Submit did not acquire its Listing lock"
        resize_future = pool.submit(
            gated_listing.patch,
            Principal(ids.worker_user_id, "WORKER"),
            ids.listing_id,
            {"total_gpu_count": 1},
            correlation_id=uuid4(),
        )
        try:
            assert resize_attempt.wait(15), "Resize did not reach its Listing lock"
        finally:
            allow_submit.set()
        result = submit_future.result(timeout=20)
        with pytest.raises(ListingError) as raised:
            resize_future.result(timeout=20)

    assert raised.value.code == "LISTING_CAPACITY_BELOW_QUEUED_MAX"
    assert result.job.status.value == "QUEUED"
    assert _counts(engine, ids.listing_id) == (1, 1, 1)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT total_gpu_count FROM gpu_listings WHERE id=:id"),
            {"id": ids.listing_id},
        ).scalar_one() == 4


def test_resize_commits_before_submit_and_fresh_capacity_check_rejects(
    integration_services,
) -> None:
    engine, sessions, _listing_service, job_service, ids = integration_services
    locked, allow_resize, submit_attempt = Event(), Event(), Event()
    writer = _audit_writer(sessions)
    gated_listing = _listing_service_with_gate(
        sessions, writer, locked=locked, release=allow_resize
    )
    gated_submit = JobSubmitService(
        store=_SubmissionStoreGate(job_service._store, before_lock=submit_attempt),
        audit_writer=writer,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        resize_future = pool.submit(
            gated_listing.patch,
            Principal(ids.worker_user_id, "WORKER"),
            ids.listing_id,
            {"total_gpu_count": 1},
            correlation_id=uuid4(),
        )
        assert locked.wait(15), "Resize did not acquire its Listing lock"
        submit_future = pool.submit(_submit, gated_submit, ids, key="race-submit-resize-b")
        try:
            assert submit_attempt.wait(15), "Submit did not reach its Listing lock"
        finally:
            allow_resize.set()
        assert resize_future.result(timeout=20).total_gpu_count == 1
        with pytest.raises(JobGpuExceedsListingTotal):
            submit_future.result(timeout=20)

    assert _counts(engine, ids.listing_id) == (0, 0, 0)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT total_gpu_count FROM gpu_listings WHERE id=:id"),
            {"id": ids.listing_id},
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM audit_events WHERE subject_type='LISTING' "
                 "AND subject_id=:id AND event_type='JOB_SUBMIT' AND outcome='REJECTED'"),
            {"id": ids.listing_id},
        ).scalar_one() == 1
