"""Real PostgreSQL tests for the production Jobs read adapter and SQL visibility."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4
from uuid import UUID

import pytest
from db_safety import TestDatabase
from gpu_marketplace.jobs.cursor import HmacCursorCodec
from gpu_marketplace.jobs.models import JobRole, JobStatus
from gpu_marketplace.jobs.service import JobsReadService
from gpu_marketplace.repositories.jobs import PostgresJobReader
from jobs_cancel_pg_support import seed_committed_job
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str


@pytest.fixture
def jobs_reader(
    migrated_database_with_teardown: Engine,
    test_database: TestDatabase,
) -> Iterator[tuple[Engine, PostgresJobReader]]:
    engine = migrated_database_with_teardown
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def bind_runtime_group(session: Session, transaction, connection) -> None:
        connection.execute(text('SET LOCAL ROLE "gpm_api_rw"'))

    event.listen(factory, "after_begin", bind_runtime_group)
    reader = PostgresJobReader(
        factory,
        allowed_session_users=frozenset({make_url(test_database.url).username or ""}),
    )
    try:
        yield engine, reader
    finally:
        event.remove(factory, "after_begin", bind_runtime_group)


def test_postgres_job_reader_enforces_client_worker_and_admin_visibility(
    jobs_reader: tuple[Engine, PostgresJobReader],
) -> None:
    engine, reader = jobs_reader
    first = seed_committed_job(engine)
    second = seed_committed_job(engine)

    first_client = reader.list_visible(
        principal=Principal(UUID(first.client_user_id), JobRole.CLIENT),
        status=None,
        after=None,
        limit=20,
    )
    second_client = reader.list_visible(
        principal=Principal(UUID(second.client_user_id), JobRole.CLIENT),
        status=None,
        after=None,
        limit=20,
    )
    first_worker = reader.list_visible(
        principal=Principal(UUID(first.worker_user_id), JobRole.WORKER),
        status=None,
        after=None,
        limit=20,
    )
    second_worker = reader.list_visible(
        principal=Principal(UUID(second.worker_user_id), JobRole.WORKER),
        status=None,
        after=None,
        limit=20,
    )
    admin = reader.list_visible(
        principal=Principal(UUID(first.client_user_id), JobRole.ADMIN),
        status=None,
        after=None,
        limit=20,
    )

    assert [str(record.id) for record in first_client.items] == [first.job_id]
    assert [str(record.id) for record in second_client.items] == [second.job_id]
    assert [str(record.id) for record in first_worker.items] == [first.job_id]
    assert [str(record.id) for record in second_worker.items] == [second.job_id]
    assert {str(record.id) for record in admin.items} == {first.job_id, second.job_id}
    assert reader.get_visible(
        principal=Principal(UUID(first.client_user_id), JobRole.CLIENT),
        job_id=UUID(second.job_id),
    ) is None
    assert reader.get_visible(
        principal=Principal(UUID(first.worker_user_id), JobRole.WORKER),
        job_id=UUID(second.job_id),
    ) is None


def test_postgres_job_reader_keyset_uses_submitted_at_then_uuid_and_status(
    jobs_reader: tuple[Engine, PostgresJobReader],
) -> None:
    engine, reader = jobs_reader
    from test_schema_constraints import add_listing, add_user, add_worker

    with engine.begin() as connection:
        _worker_user_id, worker_id = add_worker(connection)
        listing_id = add_listing(connection, worker_id, total=8)
        submitted_at = connection.execute(
            text("SELECT TIMESTAMPTZ '2026-11-06 12:00:00+00'")
        ).scalar_one()
        fixtures: list[tuple[str, str]] = []
        for status in ("QUEUED", "CANCELLED", "QUEUED"):
            client_id = add_user(connection, "CLIENT")
            job_id = str(uuid4())
            terminal = submitted_at if status == "CANCELLED" else None
            connection.execute(
                text(
                    "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, "
                    "duration_seconds, submitted_at, correlation_id, status, terminal_at) "
                    "VALUES (:id, :client_id, :listing_id, :worker_id, 1, 60, :submitted_at, "
                    ":correlation_id, :status, :terminal_at)"
                ),
                {
                    "id": job_id,
                    "client_id": client_id,
                    "listing_id": listing_id,
                    "worker_id": worker_id,
                    "submitted_at": submitted_at,
                    "correlation_id": str(uuid4()),
                    "status": status,
                    "terminal_at": terminal,
                },
            )
            fixtures.append((client_id, job_id))

    principal = Principal(UUID(fixtures[0][0]), JobRole.ADMIN)
    first_page = reader.list_visible(principal=principal, status=None, after=None, limit=2)
    assert len(first_page.items) == 2
    assert first_page.next_position is not None
    assert [str(record.id) for record in first_page.items] == sorted(
        [fixture[1] for fixture in fixtures], reverse=True
    )[:2]
    second_page = reader.list_visible(
        principal=principal,
        status=None,
        after=first_page.next_position,
        limit=2,
    )
    assert len(second_page.items) == 1
    assert second_page.next_position is None
    assert str(second_page.items[0].id) == sorted(
        [fixture[1] for fixture in fixtures], reverse=True
    )[2]

    cancelled = reader.list_visible(
        principal=principal,
        status=JobStatus.CANCELLED,
        after=None,
        limit=10,
    )
    assert [str(record.id) for record in cancelled.items] == [fixtures[1][1]]


def test_jobs_read_service_projects_no_client_identity_or_protected_reference(
    jobs_reader: tuple[Engine, PostgresJobReader],
) -> None:
    engine, reader = jobs_reader
    fixture = seed_committed_job(engine)
    service = JobsReadService(
        reader=reader,
        cursor_codec=HmacCursorCodec(b"test-only-jobs-read-cursor-key-012345"),
    )

    worker_view = service.get_job(
        principal=Principal(UUID(fixture.worker_user_id), JobRole.WORKER),
        job_id=UUID(fixture.job_id),
    )
    client_view = service.get_job(
        principal=Principal(UUID(fixture.client_user_id), JobRole.CLIENT),
        job_id=UUID(fixture.job_id),
    )

    assert "client_id" not in worker_view.model_dump()
    assert "simulation_reference" not in worker_view.model_dump()
    assert "simulation_reference" not in client_view.model_dump()
    assert client_view.model_dump()["worker_id"] == UUID(fixture.worker_id)
