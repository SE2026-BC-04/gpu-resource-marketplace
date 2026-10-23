"""D1: least-privilege grants for the API and Manager groups (schema matrix 6.3), checked on real PostgreSQL.

Positive and negative cases run as ``gpm_api_app`` / ``gpm_manager_app`` through ``SET LOCAL ROLE`` inside a
transaction that is rolled back, so no password is needed and no data survives. Owner-side setup comes first
because the runtime roles cannot insert users or workers.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from test_schema_constraints import add_job, add_listing, add_user, add_worker, new_id, violated

API_GROUP = "gpm_api_rw"
MANAGER_GROUP = "gpm_manager_rw"
API_LOGIN = "gpm_api_app"
MANAGER_LOGIN = "gpm_manager_app"
DENIED = "42501"
VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

ALL_COLUMNS = "*"
API_SELECT = {
    "roles": ALL_COLUMNS,
    "users": ALL_COLUMNS,
    "user_roles": ALL_COLUMNS,
    "workers": ALL_COLUMNS,
    "worker_public_keys": {"key_id", "worker_id", "registered_at", "retired_at"},
    "gpu_listings": ALL_COLUMNS,
    "jobs": ALL_COLUMNS,
    "worker_reputation_aggregates": ALL_COLUMNS,
}
API_INSERT = {
    "gpu_listings": {"worker_id", "gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"},
    "jobs": {
        "client_id",
        "listing_id",
        "worker_id",
        "requested_gpu_count",
        "duration_seconds",
        "submitted_at",
        "idempotency_key",
        "request_sha256",
        "correlation_id",
    },
    "simulation_references": {
        "job_id",
        "seed_value",
        "algorithm_version",
        "expected_outcome",
        "expected_failure_reason",
        "expected_digest",
    },
    "audit_events": {
        "actor_kind",
        "actor_ref",
        "correlation_id",
        "subject_type",
        "subject_id",
        "event_type",
        "outcome",
        "metadata_redacted",
    },
}
API_UPDATE = {
    "gpu_listings": {"gpu_model", "vram_gb", "total_gpu_count", "status", "mock_price_per_hour"},
    "jobs": {"status", "terminal_at"},
}


def grants_module():
    files = sorted(VERSIONS.glob("0002_*.py"))
    assert len(files) == 1, "the grants revision must exist exactly once"
    spec = importlib.util.spec_from_file_location("grants_revision", files[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_columns(connection: Connection) -> dict[str, list[str]]:
    rows = connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name <> 'alembic_version' ORDER BY table_name, ordinal_position"
        )
    )
    columns: dict[str, list[str]] = {}
    for table, column in rows:
        columns.setdefault(table, []).append(column)
    return columns


def column_privileges(connection: Connection, role: str, privilege: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for table, columns in table_columns(connection).items():
        allowed = {
            column
            for column in columns
            if connection.execute(
                text("SELECT has_column_privilege(:role, :table, :column, :privilege)"),
                {"role": role, "table": f"public.{table}", "column": column, "privilege": privilege},
            ).scalar_one()
        }
        if allowed:
            result[table] = allowed
    return result


def expand(spec: dict[str, object], columns: dict[str, list[str]]) -> dict[str, set[str]]:
    return {table: set(columns[table]) if cols == ALL_COLUMNS else set(cols) for table, cols in spec.items()}


def test_api_group_has_exactly_the_matrix_column_privileges(conn: Connection) -> None:
    columns = table_columns(conn)
    assert column_privileges(conn, API_GROUP, "SELECT") == expand(API_SELECT, columns)
    assert column_privileges(conn, API_GROUP, "INSERT") == expand(API_INSERT, columns)
    assert column_privileges(conn, API_GROUP, "UPDATE") == expand(API_UPDATE, columns)


def test_manager_group_has_no_table_privileges_in_phase_1b(conn: Connection) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE"):
        assert column_privileges(conn, MANAGER_GROUP, privilege) == {}


@pytest.mark.parametrize("group", [API_GROUP, MANAGER_GROUP])
@pytest.mark.parametrize("privilege", ["DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"])
def test_runtime_groups_never_get_destructive_or_structural_table_privileges(
    conn: Connection, group: str, privilege: str
) -> None:
    for table in table_columns(conn):
        granted = conn.execute(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": group, "table": f"public.{table}", "privilege": privilege},
        ).scalar_one()
        assert granted is False, f"{group} must not have {privilege} on {table}"


def test_only_the_runtime_groups_may_connect(conn: Connection) -> None:
    stranger = f"gpm_stranger_{new_id()[:8]}"
    conn.execute(text(f'CREATE ROLE "{stranger}" LOGIN'))
    database = conn.execute(text("SELECT current_database()")).scalar_one()
    query = text("SELECT has_database_privilege(:role, :db, 'CONNECT')")
    assert conn.execute(query, {"role": stranger, "db": database}).scalar_one() is False
    for login in (API_LOGIN, MANAGER_LOGIN):
        assert conn.execute(query, {"role": login, "db": database}).scalar_one() is True


def test_runtime_roles_cannot_create_objects(conn: Connection) -> None:
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    assert violated(conn, "CREATE TABLE public.not_allowed (id integer)") == DENIED
    assert violated(conn, "CREATE TEMP TABLE not_allowed (id integer)") == DENIED


def test_api_cannot_read_the_raw_public_key_or_the_oracle(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    job_id = add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    conn.execute(
        text("INSERT INTO worker_public_keys (worker_id, public_key_raw) VALUES (:w, decode(repeat('ab', 32), 'hex'))"),
        {"w": worker_id},
    )
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    assert conn.execute(text("SELECT count(key_id) FROM worker_public_keys")).scalar_one() == 1
    assert violated(conn, "SELECT public_key_raw FROM worker_public_keys") == DENIED
    assert violated(conn, "SELECT * FROM worker_public_keys") == DENIED
    assert violated(conn, "SELECT * FROM simulation_references") == DENIED
    assert violated(conn, "SELECT count(*) FROM simulation_references") == DENIED
    assert violated(conn, "SELECT * FROM audit_events") == DENIED
    insert = (
        "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, expected_digest) "
        "VALUES (:job, 1, 'v1', 'SUCCESS', :digest)"
    )
    digest = "sha256:" + "a" * 64
    conn.execute(text(insert), {"job": job_id, "digest": digest})
    assert violated(conn, insert + " RETURNING job_id", job=job_id, digest=digest) == DENIED


def test_api_cannot_delete_or_truncate_runtime_data(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    assert violated(conn, "DELETE FROM jobs") == DENIED
    assert violated(conn, "TRUNCATE jobs") == DENIED
    assert violated(conn, "DELETE FROM audit_events") == DENIED
    assert violated(conn, "DELETE FROM gpu_listings") == DENIED


def test_api_can_submit_and_cancel_through_its_column_grants(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    # Listing before Job, as the lock order requires; FOR UPDATE needs UPDATE on some column.
    conn.execute(text("SELECT id FROM gpu_listings WHERE id = :id FOR UPDATE"), {"id": listing_id})
    job_id = conn.execute(
        text(
            "INSERT INTO jobs (client_id, listing_id, worker_id, requested_gpu_count, duration_seconds, "
            "submitted_at, correlation_id) VALUES (:c, :l, :w, 1, 60, clock_timestamp(), :corr) RETURNING id"
        ),
        {"c": client_id, "l": listing_id, "w": worker_id, "corr": new_id()},
    ).scalar_one()
    conn.execute(text("SELECT id FROM jobs WHERE id = :id FOR UPDATE"), {"id": job_id})
    seq = conn.execute(text("SELECT enqueue_seq FROM jobs WHERE id = :id"), {"id": job_id}).scalar_one()
    assert seq > 0
    conn.execute(
        text("UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id"),
        {"id": job_id},
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE jobs SET started_at = clock_timestamp()",
        "UPDATE jobs SET failure_reason = 'JOB_FAULT'",
        "UPDATE jobs SET client_id = client_id",
        "UPDATE gpu_listings SET allocated_gpu_count = 1",
        "UPDATE gpu_listings SET worker_id = worker_id",
        "UPDATE users SET status = 'DISABLED'",
        "UPDATE worker_reputation_aggregates SET successful_jobs = 1",
        "UPDATE simulation_references SET seed_value = 2",
    ],
)
def test_api_cannot_update_columns_outside_its_grants(conn: Connection, statement: str) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    assert violated(conn, statement) == DENIED


def test_api_cannot_backdate_database_owned_timestamps(conn: Connection) -> None:
    _, worker_id = add_worker(conn)
    conn.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    sql = (
        "INSERT INTO gpu_listings (worker_id, gpu_model, vram_gb, total_gpu_count, created_at) "
        "VALUES (:w, 'A100', 80, 4, now() - interval '1 year')"
    )
    assert violated(conn, sql, w=worker_id) == DENIED
    sql = "INSERT INTO jobs (client_id, listing_id, worker_id, requested_gpu_count, duration_seconds, submitted_at, correlation_id, status) VALUES (:c, :l, :w, 1, 1, now(), :corr, 'RUNNING')"
    assert violated(conn, sql, c=new_id(), l=new_id(), w=worker_id, corr=new_id()) == DENIED


def test_manager_can_connect_but_reads_no_business_table(conn: Connection) -> None:
    conn.execute(text(f"SET LOCAL ROLE {MANAGER_LOGIN}"))
    assert conn.execute(text("SELECT 1")).scalar_one() == 1
    assert violated(conn, "SELECT * FROM jobs") == DENIED


def test_migration_stops_with_a_clear_message_when_the_groups_are_missing(conn: Connection) -> None:
    module = grants_module()
    with pytest.raises(RuntimeError, match="role bootstrap"):
        module.require_groups(conn, ["gpm_group_that_does_not_exist"])


def public_database_acl(connection: Connection) -> str:
    return connection.execute(
        text("SELECT coalesce(datacl::text, '') FROM pg_database WHERE datname = current_database()")
    ).scalar_one()


def test_downgrade_removes_grants_never_drops_roles_and_never_widens_public(
    baseline_database: Engine, alembic_config: Config
) -> None:
    command.downgrade(alembic_config, "0001_phase1b_baseline")
    try:
        with baseline_database.connect() as connection:
            assert column_privileges(connection, API_GROUP, "SELECT") == {}
            acl = public_database_acl(connection)
            assert API_GROUP not in acl and MANAGER_GROUP not in acl
            # PUBLIC had its database privileges removed by the upgrade; a downgrade must not hand them back,
            # because the migration cannot know whether the operator had restricted them before.
            assert "=Tc/" not in acl and "=c/" not in acl and "=T/" not in acl
            roles = connection.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname IN (:a, :b, :c, :d)"),
                {"a": API_GROUP, "b": MANAGER_GROUP, "c": API_LOGIN, "d": MANAGER_LOGIN},
            ).scalar_one()
            assert roles == 4
    finally:
        command.upgrade(alembic_config, "head")


def test_upgrade_after_a_restricted_downgrade_is_repeatable(baseline_database: Engine, alembic_config: Config) -> None:
    command.downgrade(alembic_config, "0001_phase1b_baseline")
    command.upgrade(alembic_config, "head")
    with baseline_database.connect() as connection:
        assert column_privileges(connection, API_GROUP, "SELECT") != {}
        assert "=Tc/" not in public_database_acl(connection)


def test_p2_runtime_roles_have_no_create_on_schema_public(conn: Connection) -> None:
    for role in (API_GROUP, MANAGER_GROUP, API_LOGIN, MANAGER_LOGIN):
        for privilege in ("CREATE", "USAGE"):
            expected = privilege == "USAGE"
            granted = conn.execute(
                text("SELECT has_schema_privilege(:role, 'public', :privilege)"), {"role": role, "privilege": privilege}
            ).scalar_one()
            assert granted is expected, f"{role} {privilege} on schema public"


def test_p2_migration_fails_closed_when_public_can_create_in_schema_public(conn: Connection) -> None:
    """Clusters upgraded from PostgreSQL 14 or older can still grant CREATE on schema public to PUBLIC."""
    module = grants_module()
    module.require_schema_closed(conn, (API_GROUP, MANAGER_GROUP))
    conn.execute(text("GRANT CREATE ON SCHEMA public TO PUBLIC"))
    with pytest.raises(RuntimeError, match="CREATE on schema public"):
        module.require_schema_closed(conn, (API_GROUP, MANAGER_GROUP))
