"""Real PostgreSQL SQL-level tests for D2 cancellation invariants.

These tests exercise the D2 trigger and PostgreSQL locks directly. They do not
exercise JobCancelService or a production TX-CANCEL adapter.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from db_safety import TestDatabase
from jobs_cancel_pg_support import (
    ListingLockAttempt,
    assert_non_job_side_effects_unchanged,
    read_database_clock,
    read_persisted_snapshot,
    seed_cancel_side_effect_rows,
    seed_committed_job,
)
from conftest import reset_schema


API_ROLE = "gpm_api_app"
TRIGGER = "trg_jobs_guard_update"
INTEGRITY_SQLSTATE = "23000"


@pytest.fixture
def cancel_postgres(migrated_database: Engine, test_database: TestDatabase) -> Iterator[Engine]:
    """Use the vetted, migrated disposable DB and reset it safely after this test."""
    try:
        yield migrated_database
    finally:
        # reset_schema revalidates the disposable-cluster marker before DROP SCHEMA.
        # No row-level DELETE bypasses D3 or other lifecycle triggers.
        reset_schema(migrated_database, test_database)


def _cancel_as_api(engine: Engine, job_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL ROLE "{API_ROLE}"'))
        connection.execute(
            text(
                "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() "
                "WHERE id = :id"
            ),
            {"id": job_id},
        )


def _assert_d2_rejection(error: DBAPIError, reason: str) -> None:
    original = error.orig
    assert getattr(original, "sqlstate", None) == INTEGRITY_SQLSTATE
    assert getattr(getattr(original, "diag", None), "constraint_name", None) == TRIGGER
    assert getattr(getattr(original, "diag", None), "message_primary", None) == reason


def _seed_snapshot_fixture(engine: Engine, *, listing_status: str = "ACTIVE"):
    fixture = seed_committed_job(engine, listing_status=listing_status)
    seed_cancel_side_effect_rows(engine, fixture)
    return fixture


def test_d2_api_can_cancel_queued_job_without_changing_other_phase1b_state(
    cancel_postgres: Engine,
) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)

    _cancel_as_api(cancel_postgres, fixture.job_id)

    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert before.job_row[6] == "QUEUED"
    assert after.job_row[6] == "CANCELLED"
    assert after.job_row[8] is None
    assert after.job_row[9] is not None
    assert after.job_row[10] is None
    assert_non_job_side_effects_unchanged(before, after)


def test_d2_api_cannot_take_manager_edge(cancel_postgres: Engine) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)

    with pytest.raises(DBAPIError) as caught:
        with cancel_postgres.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{API_ROLE}"'))
            connection.execute(
                text("UPDATE jobs SET status = 'RUNNING' WHERE id = :id"),
                {"id": fixture.job_id},
            )

    _assert_d2_rejection(caught.value, "job_transition_not_owned_by_api")
    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after == before


def test_d2_unknown_role_noop_update_is_rejected_and_rolled_back(cancel_postgres: Engine) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    role = f"gpm_t{uuid.uuid4().hex[:12]}_unknown"

    with pytest.raises(DBAPIError) as caught:
        with cancel_postgres.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            connection.execute(text(f'GRANT SELECT ON jobs TO "{role}"'))
            connection.execute(
                text(
                    f'GRANT UPDATE (status, started_at, terminal_at, failure_reason) '
                    f'ON jobs TO "{role}"'
                )
            )
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            connection.execute(
                text("UPDATE jobs SET status = status WHERE id = :id"),
                {"id": fixture.job_id},
            )

    _assert_d2_rejection(caught.value, "job_update_role_not_permitted")
    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after == before


def test_d2_update_rollback_preserves_queued_row_and_protected_side_effects(
    cancel_postgres: Engine,
) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres)
    before = read_persisted_snapshot(cancel_postgres, fixture)
    connection = cancel_postgres.connect()
    transaction = connection.begin()
    try:
        connection.execute(text(f'SET LOCAL ROLE "{API_ROLE}"'))
        connection.execute(
            text(
                "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() "
                "WHERE id = :id"
            ),
            {"id": fixture.job_id},
        )
        transaction.rollback()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()

    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after == before


def test_d2_cancel_is_allowed_for_paused_listing(cancel_postgres: Engine) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres, listing_status="PAUSED")
    before = read_persisted_snapshot(cancel_postgres, fixture)

    _cancel_as_api(cancel_postgres, fixture.job_id)

    after = read_persisted_snapshot(cancel_postgres, fixture)
    assert after.job_row[6] == "CANCELLED"
    assert after.job_row[9] is not None
    assert_non_job_side_effects_unchanged(before, after)


def test_d2_cancel_after_listing_lock_wait_uses_database_clock_and_two_connections(
    cancel_postgres: Engine,
) -> None:
    fixture = _seed_snapshot_fixture(cancel_postgres, listing_status="PAUSED")
    before = read_persisted_snapshot(cancel_postgres, fixture)
    first = cancel_postgres.connect()
    transaction = first.begin()
    attempt = ListingLockAttempt(cancel_postgres, fixture.listing_id)
    try:
        first.execute(
            text("SELECT id FROM gpu_listings WHERE id = :id FOR UPDATE"),
            {"id": fixture.listing_id},
        ).scalar_one()
        post_lock_time = first.execute(text("SELECT clock_timestamp()")).scalar_one()
        attempt.start()
        attempt.wait_until_blocked(timeout=5.0)

        first.execute(text(f'SET LOCAL ROLE "{API_ROLE}"'))
        first.execute(
            text(
                "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() "
                "WHERE id = :id"
            ),
            {"id": fixture.job_id},
        )
        transaction.commit()
        attempt.join(timeout=15.0)
    finally:
        if transaction.is_active:
            transaction.rollback()
        first.close()
        if attempt.thread.ident is not None:
            attempt.join(timeout=15.0)

    assert attempt.result == "lock_acquired"
    assert attempt.error_type is None
    after = read_persisted_snapshot(cancel_postgres, fixture)
    observed_after = read_database_clock(cancel_postgres)
    terminal_at = after.job_row[9]
    assert after.job_row[6] == "CANCELLED"
    assert terminal_at is not None
    assert post_lock_time <= terminal_at <= observed_after
    assert_non_job_side_effects_unchanged(before, after)
