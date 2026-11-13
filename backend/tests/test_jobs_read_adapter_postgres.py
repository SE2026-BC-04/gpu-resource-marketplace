"""Real PostgreSQL tests for the production Jobs read adapter and SQL visibility."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4
from uuid import UUID

import pytest
from db_safety import TestDatabase
from gpu_marketplace.jobs.cursor import HmacCursorCodec
from gpu_marketplace.jobs.errors import DependencyUnavailable
from gpu_marketplace.jobs.models import JobRole, JobStatus
from gpu_marketplace.jobs.service import JobsReadService
from gpu_marketplace.repositories.jobs import PostgresJobReader
from jobs_cancel_pg_support import seed_committed_job
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str


class _RowsResult:
    def one(self) -> tuple[str, str]:
        return "gpm_api_app", "test_login"

    def mappings(self) -> _RowsResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> _RecordingSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement, params=None) -> _RowsResult:
        parameters = dict(params or {})
        sql = str(statement)
        if sql != "SELECT current_user, session_user":
            self.statements.append((sql, parameters))
        return _RowsResult()


def _recording_reader(session: _RecordingSession) -> PostgresJobReader:
    return PostgresJobReader(
        lambda: session,
        allowed_session_users=frozenset({"test_login"}),
    )


def test_vt089_unfiltered_reader_sql_and_parameters_match_baseline_contract() -> None:
    session = _RecordingSession()
    reader = _recording_reader(session)
    principal = Principal(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), JobRole.CLIENT)

    reader.list_visible(principal=principal, status=None, after=None, limit=20)

    assert session.statements == [
        (
            "SELECT j.id, j.client_id, j.worker_id, j.listing_id, "
            "j.requested_gpu_count, j.duration_seconds, j.status, j.failure_reason, "
            "j.submitted_at, j.started_at, j.terminal_at FROM jobs AS j "
            "WHERE j.client_id = :principal_id "
            "ORDER BY j.submitted_at DESC, j.id DESC LIMIT :limit",
            {
                "principal_id": principal.user_id,
                "limit": 21,
            },
        )
    ]


def test_vt089_listing_filter_is_bound_native_uuid_before_order_and_limit() -> None:
    session = _RecordingSession()
    reader = _recording_reader(session)
    principal = Principal(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), JobRole.CLIENT)
    listing_id = UUID("22222222-2222-4222-8222-222222222222")

    reader.list_visible(
        principal=principal,
        status=JobStatus.QUEUED,
        after=None,
        limit=20,
        listing_id=listing_id,
    )

    sql, params = session.statements[0]
    assert "j.client_id = :principal_id AND j.status = :status AND j.listing_id = :listing_id" in sql
    assert sql.index("j.listing_id = :listing_id") < sql.index("ORDER BY") < sql.index("LIMIT")
    assert params == {
        "principal_id": principal.user_id,
        "status": "QUEUED",
        "listing_id": listing_id,
        "limit": 21,
    }
    assert isinstance(params["listing_id"], UUID)
    assert "gpu_listings" not in sql


def test_vt089_filtered_reader_outage_is_sanitized_without_database() -> None:
    class FailingSession(_RecordingSession):
        def execute(self, statement, params=None) -> _RowsResult:
            if str(statement) == "SELECT current_user, session_user":
                return super().execute(statement, params)
            raise SQLAlchemyError("private database password and query detail")

    reader = _recording_reader(FailingSession())
    principal = Principal(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), JobRole.CLIENT)

    with pytest.raises(DependencyUnavailable) as raised:
        reader.list_visible(
            principal=principal,
            status=None,
            after=None,
            limit=20,
            listing_id=UUID("22222222-2222-4222-8222-222222222222"),
        )

    assert "private database" not in str(raised.value).lower()
    assert "password" not in str(raised.value).lower()


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


def test_vt089_pg_listing_filter_status_roles_cursor_ties_and_before_limit(
    jobs_reader: tuple[Engine, PostgresJobReader],
) -> None:
    engine, reader = jobs_reader
    from test_schema_constraints import add_listing, add_user, add_worker

    with engine.begin() as connection:
        _worker1_user, worker1_id = add_worker(connection)
        worker2_user, worker2_id = add_worker(connection)
        listing1 = add_listing(connection, worker1_id, total=8)
        listing2 = add_listing(connection, worker2_id, total=32)
        client1 = add_user(connection, "CLIENT")
        client2 = add_user(connection, "CLIENT")
        admin_id = add_user(connection, "ADMIN")
        base_time = connection.execute(
            text("SELECT TIMESTAMPTZ '2026-11-06 12:00:00+00'")
        ).scalar_one()
        matching_ids: list[str] = []

        # Three matching QUEUED rows tie on timestamp and span two pages.
        for client_id in (client1, client2, client1):
            job_id = str(uuid4())
            connection.execute(
                text(
                    "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, "
                    "duration_seconds, submitted_at, correlation_id, status) "
                    "VALUES (:id, :client, :listing, :worker, 1, 60, :submitted, :corr, 'QUEUED')"
                ),
                {
                    "id": job_id,
                    "client": client_id,
                    "listing": listing1,
                    "worker": worker1_id,
                    "submitted": base_time,
                    "corr": str(uuid4()),
                },
            )
            matching_ids.append(job_id)

        # A matching Listing row with another status proves AND semantics.
        connection.execute(
            text(
                "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, "
                "duration_seconds, submitted_at, correlation_id, status, terminal_at) "
                "VALUES (:id, :client, :listing, :worker, 1, 60, :submitted, :corr, 'CANCELLED', :terminal)"
            ),
            {
                "id": str(uuid4()),
                "client": client1,
                "listing": listing1,
                "worker": worker1_id,
                "submitted": base_time,
                "corr": str(uuid4()),
                "terminal": base_time,
            },
        )

        # More recent decoys would consume the whole page if filtering happened
        # after LIMIT. They belong to another Listing and another Worker owner.
        for _ in range(21):
            connection.execute(
                text(
                    "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, "
                    "duration_seconds, submitted_at, correlation_id, status) "
                    "VALUES (:id, :client, :listing, :worker, 1, 60, :submitted, :corr, 'QUEUED')"
                ),
                {
                    "id": str(uuid4()),
                    "client": client2,
                    "listing": listing2,
                    "worker": worker2_id,
                    "submitted": base_time,
                    "corr": str(uuid4()),
                },
            )

    listing_uuid = UUID(listing1)
    admin = Principal(UUID(admin_id), JobRole.ADMIN)
    expected_ids = sorted(matching_ids, reverse=True)
    first_page = reader.list_visible(
        principal=admin,
        status=JobStatus.QUEUED,
        after=None,
        limit=2,
        listing_id=listing_uuid,
    )
    assert [str(record.id) for record in first_page.items] == expected_ids[:2]
    assert first_page.next_position is not None
    second_page = reader.list_visible(
        principal=admin,
        status=JobStatus.QUEUED,
        after=first_page.next_position,
        limit=2,
        listing_id=listing_uuid,
    )
    assert [str(record.id) for record in second_page.items] == expected_ids[2:]
    assert second_page.next_position is None
    assert len(set(expected_ids[:2] + [str(record.id) for record in second_page.items])) == 3

    client1_page = reader.list_visible(
        principal=Principal(UUID(client1), JobRole.CLIENT),
        status=JobStatus.QUEUED,
        after=None,
        limit=10,
        listing_id=listing_uuid,
    )
    client2_page = reader.list_visible(
        principal=Principal(UUID(client2), JobRole.CLIENT),
        status=JobStatus.QUEUED,
        after=None,
        limit=10,
        listing_id=listing_uuid,
    )
    worker1_page = reader.list_visible(
        principal=Principal(UUID(worker1_user), JobRole.WORKER),
        status=JobStatus.QUEUED,
        after=None,
        limit=10,
        listing_id=listing_uuid,
    )
    worker2_page = reader.list_visible(
        principal=Principal(UUID(worker2_user), JobRole.WORKER),
        status=JobStatus.QUEUED,
        after=None,
        limit=10,
        listing_id=listing_uuid,
    )
    unknown_listing_page = reader.list_visible(
        principal=Principal(UUID(worker2_user), JobRole.WORKER),
        status=None,
        after=None,
        limit=10,
        listing_id=UUID("55555555-5555-4555-8555-555555555555"),
    )
    assert {str(record.id) for record in client1_page.items} == {
        matching_ids[0], matching_ids[2]
    }
    assert [str(record.id) for record in client2_page.items] == [matching_ids[1]]
    assert {str(record.id) for record in worker1_page.items} == set(matching_ids)
    assert worker2_page.items == unknown_listing_page.items == ()


def test_vt089_pg_listing_filter_page_boundaries_19_20_21(
    jobs_reader: tuple[Engine, PostgresJobReader],
) -> None:
    engine, reader = jobs_reader
    from test_schema_constraints import add_listing, add_user, add_worker

    principal_id = None
    listing_rows: list[tuple[UUID, list[str]]] = []
    with engine.begin() as connection:
        _worker_user, worker_id = add_worker(connection)
        principal_id = UUID(add_user(connection, "ADMIN"))
        client_id = add_user(connection, "CLIENT")
        base_time = connection.execute(
            text("SELECT TIMESTAMPTZ '2026-11-07 09:00:00+00'")
        ).scalar_one()
        for row_count in (19, 20, 21):
            listing_id = UUID(add_listing(connection, worker_id, total=32))
            ids: list[str] = []
            for _ in range(row_count):
                job_id = str(uuid4())
                connection.execute(
                    text(
                        "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, "
                        "duration_seconds, submitted_at, correlation_id, status) "
                        "VALUES (:id, :client, :listing, :worker, 1, 60, :submitted, :corr, 'QUEUED')"
                    ),
                    {
                        "id": job_id,
                        "client": client_id,
                        "listing": str(listing_id),
                        "worker": worker_id,
                        "submitted": base_time,
                        "corr": str(uuid4()),
                    },
                )
                ids.append(job_id)
            listing_rows.append((listing_id, ids))

    assert principal_id is not None
    for listing_id, ids in listing_rows:
        expected = sorted(ids, reverse=True)
        first = reader.list_visible(
            principal=Principal(principal_id, JobRole.ADMIN),
            status=JobStatus.QUEUED,
            after=None,
            limit=20,
            listing_id=listing_id,
        )
        assert [str(record.id) for record in first.items] == expected[:20]
        if len(ids) <= 20:
            assert first.next_position is None
            continue
        assert first.next_position is not None
        second = reader.list_visible(
            principal=Principal(principal_id, JobRole.ADMIN),
            status=JobStatus.QUEUED,
            after=first.next_position,
            limit=20,
            listing_id=listing_id,
        )
        assert [str(record.id) for record in second.items] == expected[20:]
        assert second.next_position is None
