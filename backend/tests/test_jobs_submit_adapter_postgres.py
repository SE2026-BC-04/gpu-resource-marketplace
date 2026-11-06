"""Production TX-SUBMIT adapter tests against a safety-marked PostgreSQL fixture."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from db_safety import TestDatabase
from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    IdempotencyKeyReused,
    JobGpuExceedsListingTotal,
    ListingPaused,
)
from gpu_marketplace.jobs.models import SubmitJobRequest
from gpu_marketplace.jobs.submit import JobSubmitService
from gpu_marketplace.jobs.submit_ports import SimulationReference
from gpu_marketplace.repositories.job_submit import PostgresJobSubmissionStore
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from test_schema_constraints import add_listing, add_user, add_worker


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str = "CLIENT"


@dataclass(frozen=True)
class ListingFixture:
    client_id: UUID
    worker_id: UUID
    listing_id: UUID


@pytest.fixture
def submit_service(
    migrated_database_with_teardown: Engine,
    test_database: TestDatabase,
) -> Iterator[tuple[Engine, JobSubmitService]]:
    engine = migrated_database_with_teardown
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def bind_runtime_group(session: Session, transaction, connection) -> None:
        connection.execute(text('SET LOCAL ROLE "gpm_api_rw"'))

    event.listen(sessions, "after_begin", bind_runtime_group)
    store = PostgresJobSubmissionStore(
        sessions,
        allowed_session_users=frozenset({make_url(test_database.url).username or ""}),
    )
    try:
        yield engine, JobSubmitService(store=store)
    finally:
        event.remove(sessions, "after_begin", bind_runtime_group)


def seed_listing(
    engine: Engine, *, total: int = 4, client_id: UUID | None = None
) -> ListingFixture:
    with engine.begin() as connection:
        stored_client_id = str(client_id) if client_id is not None else add_user(connection, "CLIENT")
        _worker_user_id, worker_id = add_worker(connection)
        listing_id = add_listing(connection, worker_id, total=total)
    return ListingFixture(UUID(stored_client_id), UUID(worker_id), UUID(listing_id))


def make_request(listing_id: UUID, *, gpu_count: int = 2, duration: int = 60) -> SubmitJobRequest:
    return SubmitJobRequest(
        listing_id=listing_id,
        gpu_count=gpu_count,
        duration_seconds=duration,
    )


def submit(service: JobSubmitService, fixture: ListingFixture, *, key: str, duration: int = 60):
    return service.submit(
        principal=Principal(fixture.client_id),
        idempotency_key=key,
        request=make_request(fixture.listing_id, duration=duration),
        correlation_id=uuid4(),
    )


def test_postgres_submit_commits_job_and_protected_reference_together(
    submit_service: tuple[Engine, JobSubmitService],
) -> None:
    engine, service = submit_service
    fixture = seed_listing(engine)

    result = submit(service, fixture, key="postgres-submit-key-01")

    assert not result.replayed
    assert result.job.status.value == "QUEUED"
    assert result.job.client_id == fixture.client_id
    assert result.job.worker_id == fixture.worker_id
    assert result.job.listing_id == fixture.listing_id
    with engine.connect() as connection:
        jobs = connection.execute(
            text(
                "SELECT id, status, requested_gpu_count, duration_seconds, submitted_at, "
                "enqueue_seq, idempotency_key, request_sha256 FROM jobs WHERE id = :id"
            ),
            {"id": result.job.id},
        ).mappings().one()
        references = connection.execute(
            text(
                "SELECT seed_value, algorithm_version, expected_outcome, "
                "expected_failure_reason, expected_digest FROM simulation_references "
                "WHERE job_id = :id"
            ),
            {"id": result.job.id},
        ).mappings().all()
    assert jobs["status"] == "QUEUED"
    assert jobs["requested_gpu_count"] == 2
    assert jobs["duration_seconds"] == 60
    assert jobs["submitted_at"] is not None
    assert jobs["enqueue_seq"] > 0
    assert jobs["idempotency_key"] == "postgres-submit-key-01"
    assert len(jobs["request_sha256"]) == 32
    assert len(references) == 1
    assert references[0]["algorithm_version"] == "demo-v1-public1"
    assert references[0]["seed_value"] == 3035342533442321017
    assert references[0]["expected_outcome"] == "SUCCESS"
    assert references[0]["expected_failure_reason"] is None
    assert references[0]["expected_digest"] == (
        "sha256:a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c"
    )


def test_postgres_same_key_same_body_replays_after_listing_is_paused(
    submit_service: tuple[Engine, JobSubmitService],
) -> None:
    engine, service = submit_service
    fixture = seed_listing(engine)
    first = submit(service, fixture, key="postgres-submit-key-02")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE gpu_listings SET status = 'PAUSED' WHERE id = :id"),
            {"id": fixture.listing_id},
        )

    replay = submit(service, fixture, key="postgres-submit-key-02")

    assert replay.replayed
    assert replay.job.id == first.job.id
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM simulation_references")
        ).scalar_one() == 1


def test_postgres_paused_new_key_and_over_capacity_create_nothing(
    submit_service: tuple[Engine, JobSubmitService],
) -> None:
    engine, service = submit_service
    paused = seed_listing(engine)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE gpu_listings SET status = 'PAUSED' WHERE id = :id"),
            {"id": paused.listing_id},
        )
    with pytest.raises(ListingPaused):
        submit(service, paused, key="postgres-submit-key-03")

    over = seed_listing(engine, total=1)
    with pytest.raises(JobGpuExceedsListingTotal):
        submit(service, over, key="postgres-submit-key-04")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM simulation_references")
        ).scalar_one() == 0


def test_postgres_reference_constraint_failure_rolls_back_job(
    submit_service: tuple[Engine, JobSubmitService], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, service = submit_service
    fixture = seed_listing(engine)
    import gpu_marketplace.jobs.submit as submit_module

    monkeypatch.setattr(
        submit_module,
        "create_simulation_reference",
        lambda **_: SimulationReference(
            seed_value=1,
            algorithm_version="demo-v1-public1",
            expected_outcome="SUCCESS",
            expected_failure_reason=None,
            expected_digest="not-a-valid-digest",
        ),
    )

    with pytest.raises(DependencyUnavailable):
        submit(service, fixture, key="postgres-submit-key-05")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM simulation_references")
        ).scalar_one() == 0


def test_postgres_concurrent_different_listing_same_key_has_one_winner(
    submit_service: tuple[Engine, JobSubmitService],
) -> None:
    engine, service = submit_service
    first_listing = seed_listing(engine)
    second_listing = seed_listing(engine, client_id=first_listing.client_id)
    barrier = threading.Barrier(2)
    store = service._store  # noqa: SLF001 - test the public use case over the production store
    original_find = store.find_existing
    initial_lookups = 0
    lock = threading.Lock()

    def synchronized_find(*, client_id: UUID, idempotency_key: str):
        nonlocal initial_lookups
        result = original_find(client_id=client_id, idempotency_key=idempotency_key)
        with lock:
            initial_lookups += 1
            should_wait = initial_lookups <= 2
        if should_wait:
            barrier.wait(timeout=10)
        return result

    store.find_existing = synchronized_find
    outcomes: list[object] = []
    errors: list[BaseException] = []

    def worker(fixture: ListingFixture) -> None:
        try:
            outcomes.append(submit(service, fixture, key="postgres-submit-key-race"))
        except BaseException as error:  # noqa: BLE001 - recorded for concurrent assertion
            errors.append(error)

    threads = [
        threading.Thread(target=worker, args=(first_listing,), daemon=True),
        threading.Thread(target=worker, args=(second_listing,), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) == 1
    assert len(errors) == 1 and isinstance(errors[0], IdempotencyKeyReused)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM simulation_references")
        ).scalar_one() == 1
