"""D3: ``trg_jobs_guard_delete`` (schema matrix section 8), checked on real PostgreSQL.

The test connection is the cluster owner (a superuser): the trigger must refuse it too. A terminal Job's
age is set by writing ``terminal_at`` relative to the database clock, with a one-minute margin around the
23-day cutoff, far larger than the time a test takes.
"""

from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from test_jobs_guard_update import INTEGRITY, new_role, rejection
from test_schema_constraints import DIGEST, add_job, add_listing, add_user, add_worker

TRIGGER = "trg_jobs_guard_delete"
REASON = "job_delete_not_eligible"
BEFORE_D3 = "0003_phase1b_jobs_guard_update"
RUNTIME_ROLES = ("gpm_api_rw", "gpm_manager_rw", "gpm_api_app", "gpm_manager_app")
CUTOFF = timedelta(days=23)
MARGIN = timedelta(minutes=1)
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")


def db_now(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()


def make_job(connection: Connection, status: str = "QUEUED", age: timedelta = timedelta(0)) -> str:
    """Insert a Job in ``status``; a terminal Job became terminal ``age`` before now."""
    client_id = add_user(connection, "CLIENT")
    _, worker_id = add_worker(connection)
    extra: dict[str, object] = {}
    if status != "QUEUED":
        extra["status"] = status
    if status in TERMINAL:
        extra["terminal_at"] = db_now(connection) - age
    if status == "FAILED":
        extra["failure_reason"] = "WORKER_FAULT"
    return add_job(connection, client_id, add_listing(connection, worker_id), worker_id, extra)


def add_reference(connection: Connection, job_id: str) -> None:
    connection.execute(
        text(
            "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, expected_digest) "
            "VALUES (:job, 1, 'v1', 'SUCCESS', :digest)"
        ),
        {"job": job_id, "digest": DIGEST},
    )


def exists(connection: Connection, table: str, column: str, job_id: str) -> bool:
    return connection.execute(
        text(f"SELECT count(*) FROM {table} WHERE {column} = :id"), {"id": job_id}
    ).scalar_one() == 1


def assert_refused(connection: Connection, job_id: str) -> None:
    result = rejection(connection, "DELETE FROM jobs WHERE id = :id", id=job_id)
    assert result == (INTEGRITY, TRIGGER, REASON)
    assert exists(connection, "jobs", "id", job_id)


# --- the trigger exists and has the approved shape ------------------------------------------------------------


def test_trigger_is_an_enabled_row_level_before_delete_trigger_on_jobs(conn: Connection) -> None:
    row = conn.execute(
        text(
            "SELECT t.tgenabled, t.tgtype, p.proname, p.prosecdef FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid WHERE t.tgrelid = 'jobs'::regclass AND t.tgname = :name"
        ),
        {"name": TRIGGER},
    ).one()
    # tgtype bits: 1 = ROW, 2 = BEFORE, 8 = DELETE.
    assert row.tgenabled == "O"
    assert row.tgtype & (1 | 2 | 8) == (1 | 2 | 8)
    assert (row.proname, row.prosecdef) == ("fn_jobs_guard_delete", False)


def test_the_trigger_function_is_not_executable_by_public_or_runtime_roles(conn: Connection) -> None:
    acl = conn.execute(
        text("SELECT coalesce(proacl::text[], ARRAY[]::text[]) FROM pg_proc WHERE proname = 'fn_jobs_guard_delete'")
    ).scalar_one()
    assert not any(entry.startswith("=") for entry in acl), acl  # an empty grantee is PUBLIC
    for role in RUNTIME_ROLES:
        held = conn.execute(
            text("SELECT has_function_privilege(:role, 'fn_jobs_guard_delete()', 'EXECUTE')"), {"role": role}
        ).scalar_one()
        assert held is False, role


# --- layer 1: no runtime role can delete or truncate Jobs ------------------------------------------------------


@pytest.mark.parametrize("role", RUNTIME_ROLES)
@pytest.mark.parametrize("privilege", ["DELETE", "TRUNCATE"])
def test_no_runtime_role_holds_delete_or_truncate_on_jobs(conn: Connection, role: str, privilege: str) -> None:
    held = conn.execute(
        text("SELECT has_table_privilege(:role, 'jobs', :privilege)"), {"role": role, "privilege": privilege}
    ).scalar_one()
    assert held is False


# --- layer 2: the trigger, for every caller including the owner ------------------------------------------------


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_a_job_that_is_not_terminal_cannot_be_deleted_even_by_the_owner(conn: Connection, status: str) -> None:
    assert_refused(conn, make_job(conn, status))


@pytest.mark.parametrize("status", TERMINAL)
@pytest.mark.parametrize("age", [timedelta(0), CUTOFF - MARGIN], ids=["just-terminal", "cutoff-minus-1min"])
def test_a_terminal_job_younger_than_23_days_cannot_be_deleted(conn: Connection, status: str, age: timedelta) -> None:
    assert_refused(conn, make_job(conn, status, age))


def test_a_terminal_at_in_the_future_cannot_be_deleted(conn: Connection) -> None:
    assert_refused(conn, make_job(conn, "COMPLETED", -MARGIN))


@pytest.mark.parametrize("status", TERMINAL)
@pytest.mark.parametrize("age", [CUTOFF + MARGIN, timedelta(days=400)], ids=["cutoff-plus-1min", "400-days"])
def test_a_terminal_job_at_least_23_days_old_can_be_deleted(conn: Connection, status: str, age: timedelta) -> None:
    job_id = make_job(conn, status, age)
    conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
    assert not exists(conn, "jobs", "id", job_id)


def test_an_eligible_delete_cascades_to_the_simulation_reference(conn: Connection) -> None:
    job_id = make_job(conn, "COMPLETED", CUTOFF + MARGIN)
    add_reference(conn, job_id)
    conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
    assert not exists(conn, "simulation_references", "job_id", job_id)


def test_a_refused_delete_keeps_the_simulation_reference(conn: Connection) -> None:
    job_id = make_job(conn, "COMPLETED", CUTOFF - MARGIN)
    add_reference(conn, job_id)
    assert_refused(conn, job_id)
    assert exists(conn, "simulation_references", "job_id", job_id)


def test_one_ineligible_row_refuses_the_whole_statement(conn: Connection) -> None:
    old = make_job(conn, "COMPLETED", CUTOFF + MARGIN)
    young = make_job(conn, "COMPLETED", timedelta(0))
    result = rejection(conn, "DELETE FROM jobs WHERE id IN (:a, :b)", a=old, b=young)
    assert result == (INTEGRITY, TRIGGER, REASON)
    assert exists(conn, "jobs", "id", old) and exists(conn, "jobs", "id", young)


def test_a_role_granted_delete_is_still_bound_by_the_trigger(conn: Connection) -> None:
    # Phase 3 will grant DELETE to the Manager for cleanup; the trigger must hold for such a role too.
    role = new_role(conn, update=False)
    conn.execute(text(f'GRANT DELETE ON jobs TO "{role}"'))
    young = make_job(conn, "CANCELLED", timedelta(days=1))
    old = make_job(conn, "CANCELLED", CUTOFF + MARGIN)
    conn.execute(text(f'SET LOCAL ROLE "{role}"'))
    assert rejection(conn, "DELETE FROM jobs WHERE id = :id", id=young) == (INTEGRITY, TRIGGER, REASON)
    conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": old})
    conn.execute(text("RESET ROLE"))
    assert exists(conn, "jobs", "id", young) and not exists(conn, "jobs", "id", old)


# --- migration ----------------------------------------------------------------------------------------------------


def trigger_and_function_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        triggers = connection.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgrelid = 'jobs'::regclass AND tgname = :name"),
            {"name": TRIGGER},
        ).scalar_one()
        functions = connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'fn_jobs_guard_delete'")
        ).scalar_one()
    return triggers, functions


def test_downgrade_removes_the_trigger_and_function_and_upgrade_restores_them(
    baseline_database: Engine, alembic_config: Config
) -> None:
    assert trigger_and_function_counts(baseline_database) == (1, 1)
    command.downgrade(alembic_config, BEFORE_D3)
    try:
        assert trigger_and_function_counts(baseline_database) == (0, 0)
    finally:
        command.upgrade(alembic_config, "head")
    assert trigger_and_function_counts(baseline_database) == (1, 1)
