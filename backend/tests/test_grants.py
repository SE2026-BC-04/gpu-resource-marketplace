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


RUNTIME_ROLES = (API_GROUP, MANAGER_GROUP, API_LOGIN, MANAGER_LOGIN)
BASELINE = "0001_phase1b_baseline"

# (grant applied by the owner to a database that is at the baseline, revoke used to clean up afterwards).
# The runtime roles must end up with exactly the matrix privileges, so none of these may survive an upgrade.
EXCESS_PRIVILEGES = [
    pytest.param(
        "GRANT CREATE ON SCHEMA public TO gpm_api_app",
        "REVOKE CREATE ON SCHEMA public FROM gpm_api_app",
        id="direct-schema-create-on-api-login",
    ),
    pytest.param(
        "GRANT CREATE ON SCHEMA public TO gpm_manager_app",
        "REVOKE CREATE ON SCHEMA public FROM gpm_manager_app",
        id="direct-schema-create-on-manager-login",
    ),
    pytest.param("GRANT DELETE ON jobs TO gpm_api_app", "REVOKE DELETE ON jobs FROM gpm_api_app", id="direct-delete-on-api-login"),
    pytest.param(
        "GRANT SELECT ON jobs TO gpm_manager_app",
        "REVOKE SELECT ON jobs FROM gpm_manager_app",
        id="direct-select-on-manager-login",
    ),
    pytest.param(
        "GRANT SELECT (expected_digest) ON simulation_references TO gpm_api_app",
        "REVOKE SELECT (expected_digest) ON simulation_references FROM gpm_api_app",
        id="direct-oracle-column-on-api-login",
    ),
    pytest.param(
        "GRANT SELECT ON simulation_references TO PUBLIC",
        "REVOKE SELECT ON simulation_references FROM PUBLIC",
        id="public-select-on-the-oracle",
    ),
    pytest.param(
        "GRANT SELECT ON audit_events TO gpm_api_rw",
        "REVOKE SELECT ON audit_events FROM gpm_api_rw",
        id="direct-select-on-audit-events-for-the-api-group",
    ),
    pytest.param(
        "GRANT TEMPORARY ON DATABASE {database} TO gpm_api_app",
        "REVOKE TEMPORARY ON DATABASE {database} FROM gpm_api_app",
        id="direct-temporary-on-the-database",
    ),
    pytest.param(
        "GRANT USAGE ON SEQUENCE {sequence} TO gpm_api_app",
        "REVOKE USAGE ON SEQUENCE {sequence} FROM gpm_api_app",
        id="direct-usage-on-the-enqueue-sequence",
    ),
]


def object_names(connection: Connection) -> dict[str, str]:
    return {
        "database": connection.execute(text("SELECT quote_ident(current_database())")).scalar_one(),
        "sequence": connection.execute(text("SELECT pg_get_serial_sequence('jobs', 'enqueue_seq')")).scalar_one(),
    }


@pytest.mark.parametrize(("grant", "revoke"), EXCESS_PRIVILEGES)
def test_p1_upgrade_fails_closed_when_existing_acls_exceed_the_matrix(
    baseline_database: Engine, alembic_config: Config, grant: str, revoke: str
) -> None:
    command.downgrade(alembic_config, BASELINE)
    try:
        with baseline_database.begin() as connection:
            names = object_names(connection)
            connection.execute(text(grant.format(**names)))
        with pytest.raises(RuntimeError, match="unexpected privilege"):
            command.upgrade(alembic_config, "head")
        with baseline_database.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == BASELINE, "a refused upgrade must leave the revision unchanged"
            acl = public_database_acl(connection)
            assert API_GROUP not in acl and MANAGER_GROUP not in acl, "a refused upgrade must not grant anything"
    finally:
        with baseline_database.begin() as connection:
            connection.execute(text(revoke.format(**object_names(connection))))
        command.upgrade(alembic_config, "head")


def test_p1_clean_matrix_state_passes_the_effective_privilege_check(conn: Connection) -> None:
    grants_module().require_no_excess_privileges(conn, RUNTIME_ROLES)


def test_p1_the_error_names_the_role_privilege_object_and_the_remedy(conn: Connection) -> None:
    module = grants_module()
    conn.execute(text("GRANT SELECT ON simulation_references TO PUBLIC"))
    with pytest.raises(RuntimeError) as failure:
        module.require_no_excess_privileges(conn, RUNTIME_ROLES)
    message = str(failure.value)
    assert "gpm_api_rw" in message and "SELECT" in message and "simulation_references" in message
    assert "REVOKE" in message and "no ACL was changed" in message
    assert "password" not in message.lower()


def test_p1_privileges_the_matrix_grants_do_not_trip_the_check(conn: Connection) -> None:
    """Whole-table SELECT on the API tables and column-level INSERT/UPDATE are inside the matrix."""
    module = grants_module()
    conn.execute(text(f"GRANT SELECT ON jobs TO {API_LOGIN}"))  # already inherited through the group
    module.require_no_excess_privileges(conn, RUNTIME_ROLES)


RUNTIME_LOGINS = {API_LOGIN: API_GROUP, MANAGER_LOGIN: MANAGER_GROUP}


def test_p2_bootstrapped_login_roles_pass_the_preflight(conn: Connection) -> None:
    grants_module().require_login_roles(conn, RUNTIME_LOGINS)


def test_p2_migration_stops_when_a_login_role_is_missing(conn: Connection) -> None:
    """Groups created by hand without their login roles must not let revision 0002 complete."""
    module = grants_module()
    missing = f"gpm_missing_{new_id()[:8]}"
    with pytest.raises(RuntimeError, match=f"missing database login role.*{missing}.*role bootstrap"):
        module.require_login_roles(conn, {missing: API_GROUP})


def test_p2_migration_stops_when_a_login_role_is_not_a_member_of_its_group(conn: Connection) -> None:
    module = grants_module()
    conn.execute(text(f"REVOKE {API_GROUP} FROM {API_LOGIN}"))  # rolled back with the test transaction
    with pytest.raises(RuntimeError, match=f"{API_LOGIN} is not a member of {API_GROUP}"):
        module.require_login_roles(conn, RUNTIME_LOGINS)


def test_p2_migration_stops_when_a_login_role_cannot_log_in(conn: Connection) -> None:
    module = grants_module()
    stand_in = f"gpm_nologin_{new_id()[:8]}"
    conn.execute(text(f'CREATE ROLE "{stand_in}" NOLOGIN IN ROLE {API_GROUP}'))
    with pytest.raises(RuntimeError, match=f"{stand_in} must be a LOGIN role"):
        module.require_login_roles(conn, {stand_in: API_GROUP})


def test_p2_upgrade_runs_the_login_role_preflight() -> None:
    source = (VERSIONS / "0002_phase1b_grants.py").read_bytes().decode("utf-8")
    upgrade_body = source.split("def upgrade() -> None:", 1)[1].split("def downgrade", 1)[0]
    assert "require_login_roles(bind" in upgrade_body
    assert upgrade_body.index("require_login_roles(") < upgrade_body.index("op.execute(")


# --- PR #27 review (TV5, P1): the migration re-checks the full role definition before granting ---------------------

INTRUDER = "gpm_t_role_intruder"

# (setup applied by the owner to a database at the baseline, cleanup, text the refusal must contain).
ROLE_DRIFT = [
    pytest.param(
        f"CREATE ROLE {INTRUDER} LOGIN; GRANT {API_GROUP} TO {INTRUDER}",
        f"DROP ROLE {INTRUDER}",
        f"{API_GROUP}: unexpected member(s) ['{INTRUDER}']",
        id="extra-direct-member-of-the-api-group",
    ),
    pytest.param(
        f"CREATE ROLE {INTRUDER} LOGIN; GRANT {API_LOGIN} TO {INTRUDER}",
        f"DROP ROLE {INTRUDER}",
        f"{API_LOGIN}: unexpected member(s) ['{INTRUDER}']",
        id="indirect-member-through-the-api-login",
    ),
    pytest.param(
        f"CREATE ROLE {INTRUDER} NOLOGIN; GRANT {MANAGER_GROUP} TO {INTRUDER}",
        f"DROP ROLE {INTRUDER}",
        f"{MANAGER_GROUP}: unexpected member(s) ['{INTRUDER}']",
        id="extra-member-of-the-manager-group",
    ),
    pytest.param(
        f"GRANT {MANAGER_GROUP} TO {API_LOGIN}",
        f"REVOKE {MANAGER_GROUP} FROM {API_LOGIN}",
        f"{API_LOGIN}: unexpected membership",
        id="api-login-also-in-the-manager-group",
    ),
    pytest.param(
        f"ALTER ROLE {API_LOGIN} CREATEROLE", f"ALTER ROLE {API_LOGIN} NOCREATEROLE", f"{API_LOGIN}: CREATEROLE is set",
        id="createrole-on-the-api-login",
    ),
    pytest.param(
        f"ALTER ROLE {MANAGER_GROUP} BYPASSRLS",
        f"ALTER ROLE {MANAGER_GROUP} NOBYPASSRLS",
        f"{MANAGER_GROUP}: BYPASSRLS is set",
        id="bypassrls-on-the-manager-group",
    ),
    pytest.param(
        f"ALTER ROLE {API_LOGIN} NOINHERIT", f"ALTER ROLE {API_LOGIN} INHERIT", f"{API_LOGIN}: expected INHERIT",
        id="noinherit-on-the-api-login",
    ),
    pytest.param(
        f"ALTER ROLE {API_GROUP} LOGIN", f"ALTER ROLE {API_GROUP} NOLOGIN", f"{API_GROUP}: expected NOLOGIN",
        id="login-on-the-api-group",
    ),
    # PostgreSQL 16 per-membership options (forwarded TV5 finding): the only membership keeps its group but changes
    # how it can be used, so no extra member exists for the membership-graph check to find.
    pytest.param(
        f"GRANT {API_GROUP} TO {API_LOGIN} WITH ADMIN TRUE",
        f"REVOKE ADMIN OPTION FOR {API_GROUP} FROM {API_LOGIN}",
        f"{API_LOGIN}: membership in {API_GROUP} has ADMIN OPTION",
        id="admin-option-on-the-api-membership",
    ),
    pytest.param(
        f"GRANT {MANAGER_GROUP} TO {MANAGER_LOGIN} WITH ADMIN TRUE",
        f"REVOKE ADMIN OPTION FOR {MANAGER_GROUP} FROM {MANAGER_LOGIN}",
        f"{MANAGER_LOGIN}: membership in {MANAGER_GROUP} has ADMIN OPTION",
        id="admin-option-on-the-manager-membership",
    ),
    pytest.param(
        f"GRANT {API_GROUP} TO {API_LOGIN} WITH INHERIT FALSE",
        f"GRANT {API_GROUP} TO {API_LOGIN} WITH INHERIT TRUE",
        f"{API_LOGIN}: membership in {API_GROUP} has INHERIT FALSE",
        id="inherit-false-on-the-api-membership",
    ),
    pytest.param(
        f"GRANT {MANAGER_GROUP} TO {MANAGER_LOGIN} WITH SET FALSE",
        f"GRANT {MANAGER_GROUP} TO {MANAGER_LOGIN} WITH SET TRUE",
        f"{MANAGER_LOGIN}: membership in {MANAGER_GROUP} has SET FALSE",
        id="set-false-on-the-manager-membership",
    ),
]


@pytest.mark.parametrize(("setup", "cleanup", "reason"), ROLE_DRIFT)
def test_upgrade_fails_closed_when_a_runtime_role_drifted_from_its_definition(
    baseline_database: Engine, alembic_config: Config, setup: str, cleanup: str, reason: str
) -> None:
    command.downgrade(alembic_config, BASELINE)
    try:
        with baseline_database.begin() as connection:
            for statement in setup.split("; "):
                connection.execute(text(statement))
        with pytest.raises(RuntimeError, match="runtime roles differ from the approved definition") as failure:
            command.upgrade(alembic_config, "head")
        assert reason in str(failure.value)
        assert "no role or ACL was changed" in str(failure.value)
        with baseline_database.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == BASELINE, "a refused upgrade must leave the revision unchanged"
            acl = public_database_acl(connection)
            assert API_GROUP not in acl and MANAGER_GROUP not in acl, "a refused upgrade must not grant anything"
            granted = connection.execute(text(f"SELECT has_table_privilege('{API_GROUP}', 'jobs', 'SELECT')")).scalar_one()
            assert granted is False, "a refused upgrade must not leave a partial grant"
    finally:
        with baseline_database.begin() as connection:
            for statement in cleanup.split("; "):
                connection.execute(text(statement))
        command.upgrade(alembic_config, "head")


def test_bootstrapped_roles_pass_the_role_definition_preflight(conn: Connection) -> None:
    grants_module().require_role_definitions(conn)


def test_bootstrap_grants_memberships_with_the_checked_default_options(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT r.rolname, g.rolname, m.admin_option, m.inherit_option, m.set_option FROM pg_auth_members m "
            "JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles r ON r.oid = m.member "
            "WHERE r.rolname IN (:api, :manager) ORDER BY r.rolname"
        ),
        {"api": API_LOGIN, "manager": MANAGER_LOGIN},
    ).all()
    assert [tuple(row) for row in rows] == [
        (API_LOGIN, API_GROUP, False, True, True),
        (MANAGER_LOGIN, MANAGER_GROUP, False, True, True),
    ]


def test_the_role_definition_refusal_never_shows_a_password(conn: Connection) -> None:
    conn.execute(text(f"ALTER ROLE {API_LOGIN} CREATEDB"))  # rolled back with the test transaction
    with pytest.raises(RuntimeError) as failure:
        grants_module().require_role_definitions(conn)
    message = str(failure.value)
    assert f"{API_LOGIN}: CREATEDB is set" in message
    assert "password" not in message.lower() and "scram" not in message.lower()


def test_upgrade_runs_the_role_definition_preflight_before_any_grant() -> None:
    source = (VERSIONS / "0002_phase1b_grants.py").read_bytes().decode("utf-8")
    upgrade_body = source.split("def upgrade() -> None:", 1)[1].split("def downgrade", 1)[0]
    assert "require_role_definitions(bind)" in upgrade_body
    assert upgrade_body.index("require_role_definitions(") < upgrade_body.index("op.execute(")
