"""D2: ``trg_jobs_guard_update`` (schema matrix section 7), checked on real PostgreSQL.

The test connection is the cluster owner (a superuser), which the trigger classifies as OWNER_MAINTENANCE. Runtime
callers are exercised through ``SET LOCAL ROLE``; roles that do not exist in Phase 1B (a Manager with UPDATE
grants, an ambiguous or unknown role) are created inside the rolled-back test transaction so nothing persists.
Concurrency tests commit real rows on separate connections; the module-scoped schema is rebuilt for the next module.
"""

import secrets
import threading
import time
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from test_schema_constraints import add_job, add_listing, add_user, add_worker, new_id

TRIGGER = "trg_jobs_guard_update"
INTEGRITY = "23000"
API_GROUP = "gpm_api_rw"
MANAGER_GROUP = "gpm_manager_rw"
API_LOGIN = "gpm_api_app"
BASELINE_WITH_GRANTS = "0002_phase1b_grants"
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")

def job_state(status: str) -> dict[str, object]:
    """Columns that make an inserted Job satisfy the lifecycle CHECK constraints in ``status``."""
    now = datetime.now(timezone.utc)
    states: dict[str, dict[str, object]] = {
        "QUEUED": {},
        "RUNNING": {"status": "RUNNING", "started_at": now},
        "COMPLETED": {"status": "COMPLETED", "started_at": now, "terminal_at": now},
        "FAILED": {"status": "FAILED", "started_at": now, "terminal_at": now, "failure_reason": "WORKER_FAULT"},
        "CANCELLED": {"status": "CANCELLED", "terminal_at": now},
    }
    return states[status]


def make_job(connection: Connection, status: str = "QUEUED") -> str:
    """Insert a Job directly in ``status`` (INSERT is not guarded; only UPDATE is)."""
    client_id = add_user(connection, "CLIENT")
    _, worker_id = add_worker(connection)
    return add_job(connection, client_id, add_listing(connection, worker_id), worker_id, job_state(status))


def status_of(connection: Connection, job_id: str) -> str:
    return connection.execute(text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}).scalar_one()


def rejection(connection: Connection, statement: str, **params: object) -> tuple[str, str, str]:
    """Run a statement that must be rejected; return (SQLSTATE, constraint name, message)."""
    savepoint = connection.begin_nested()
    with pytest.raises(DBAPIError) as caught:
        connection.execute(text(statement), params)
    savepoint.rollback()
    diag = caught.value.orig.diag
    return caught.value.orig.sqlstate, diag.constraint_name or "", diag.message_primary or ""


def assert_guard(connection: Connection, statement: str, reason: str, **params: object) -> None:
    assert rejection(connection, statement, **params) == (INTEGRITY, TRIGGER, reason)


def new_role(connection: Connection, *, member_of: tuple[str, ...] = (), update: bool = True, login: bool = True) -> str:
    """A throw-away role with UPDATE on the Job lifecycle columns, living only in the test transaction."""
    name = f"gpm_t{secrets.token_hex(4)}_caller"
    groups = f" IN ROLE {', '.join(member_of)}" if member_of else ""
    connection.execute(text(f'CREATE ROLE "{name}" {"LOGIN" if login else "NOLOGIN"}{groups}'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{name}"'))
    connection.execute(text(f'GRANT SELECT ON jobs TO "{name}"'))
    if update:
        connection.execute(
            text(f'GRANT UPDATE (status, started_at, terminal_at, failure_reason) ON jobs TO "{name}"')
        )
    return name


def as_role(connection: Connection, role: str) -> None:
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))


# --- the trigger exists and has the approved shape ------------------------------------------------------------


def test_trigger_is_a_row_level_before_update_trigger_on_jobs(conn: Connection) -> None:
    row = conn.execute(
        text(
            "SELECT t.tgenabled, t.tgtype, p.prosecdef, l.lanname, p.proconfig "
            "FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_language l ON l.oid = p.prolang "
            "WHERE t.tgrelid = 'public.jobs'::regclass AND t.tgname = :name AND NOT t.tgisinternal"
        ),
        {"name": TRIGGER},
    ).one()
    enabled, tgtype, security_definer, language, config = row
    assert enabled == "O"
    assert tgtype & 1 and tgtype & 2 and tgtype & 16 and not tgtype & 4 and not tgtype & 8  # row, before, update only
    assert security_definer is False, "the caller must be classified by current_user, so SECURITY INVOKER"
    assert language == "plpgsql"
    assert config and any(setting.startswith("search_path=") for setting in config)


# --- rules (a)-(c): hold for every caller, including the owner ------------------------------------------------


@pytest.mark.parametrize("status", TERMINAL)
def test_a_terminal_job_cannot_be_updated_even_by_the_owner(conn: Connection, status: str) -> None:
    job_id = make_job(conn, status)
    assert_guard(conn, "UPDATE jobs SET started_at = clock_timestamp() WHERE id = :id", "job_terminal_immutable", id=job_id)
    assert_guard(conn, "UPDATE jobs SET status = 'QUEUED' WHERE id = :id", "job_terminal_immutable", id=job_id)
    assert status_of(conn, job_id) == status


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
@pytest.mark.parametrize(
    "assignment",
    [
        "id = gen_random_uuid()",
        "client_id = gen_random_uuid()",
        "listing_id = gen_random_uuid()",
        "worker_id = gen_random_uuid()",
        "requested_gpu_count = requested_gpu_count + 1",
        "duration_seconds = duration_seconds + 1",
        "submitted_at = submitted_at - interval '1 day'",
        "enqueue_seq = DEFAULT",
        "idempotency_key = 'rewritten'",
        "request_sha256 = decode(repeat('ab', 32), 'hex')",
        "correlation_id = gen_random_uuid()",
    ],
)
def test_identity_columns_are_immutable_even_for_the_owner(conn: Connection, status: str, assignment: str) -> None:
    job_id = make_job(conn, status)
    assert_guard(conn, f"UPDATE jobs SET {assignment} WHERE id = :id", "job_identity_immutable", id=job_id)


@pytest.mark.parametrize(
    ("status", "assignment"),
    [
        ("QUEUED", "started_at = clock_timestamp()"),
        ("QUEUED", "failure_reason = 'JOB_FAULT'"),
        ("RUNNING", "started_at = clock_timestamp()"),
        ("RUNNING", "terminal_at = clock_timestamp()"),
        ("RUNNING", "failure_reason = 'JOB_FAULT'"),
    ],
)
def test_without_a_status_change_no_column_may_change(conn: Connection, status: str, assignment: str) -> None:
    job_id = make_job(conn, status)
    assert_guard(conn, f"UPDATE jobs SET {assignment} WHERE id = :id", "job_update_without_transition", id=job_id)


def test_an_update_that_changes_nothing_is_allowed(conn: Connection) -> None:
    job_id = make_job(conn, "RUNNING")
    conn.execute(text("UPDATE jobs SET status = status, started_at = started_at WHERE id = :id"), {"id": job_id})
    assert status_of(conn, job_id) == "RUNNING"


@pytest.mark.parametrize(
    ("old", "new"),
    [("RUNNING", "QUEUED"), ("QUEUED", "COMPLETED"), ("QUEUED", "FAILED"), ("RUNNING", "CANCELLED")],
)
def test_only_the_four_lifecycle_edges_exist_even_for_the_owner(conn: Connection, old: str, new: str) -> None:
    job_id = make_job(conn, old)
    assert_guard(conn, f"UPDATE jobs SET status = '{new}' WHERE id = :id", "job_illegal_transition", id=job_id)
    assert status_of(conn, job_id) == old


LEGAL_EDGES = {
    ("QUEUED", "RUNNING"): "status = 'RUNNING', started_at = clock_timestamp()",
    ("QUEUED", "CANCELLED"): "status = 'CANCELLED', terminal_at = clock_timestamp()",
    ("RUNNING", "COMPLETED"): "status = 'COMPLETED', terminal_at = clock_timestamp()",
    ("RUNNING", "FAILED"): "status = 'FAILED', terminal_at = clock_timestamp(), failure_reason = 'JOB_FAULT'",
}


@pytest.mark.parametrize(("old", "new"), list(LEGAL_EDGES))
def test_the_owner_may_follow_every_legal_edge(conn: Connection, old: str, new: str) -> None:
    job_id = make_job(conn, old)
    conn.execute(text(f"UPDATE jobs SET {LEGAL_EDGES[(old, new)]} WHERE id = :id"), {"id": job_id})
    assert status_of(conn, job_id) == new


# --- rule (d): which caller may follow which edge --------------------------------------------------------------


def test_api_may_cancel_a_queued_job(conn: Connection) -> None:
    job_id = make_job(conn)
    as_role(conn, API_LOGIN)
    conn.execute(
        text("UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id"), {"id": job_id}
    )
    conn.execute(text("RESET ROLE"))
    assert status_of(conn, job_id) == "CANCELLED"


@pytest.mark.parametrize(
    ("old", "new"), [("QUEUED", "RUNNING"), ("RUNNING", "COMPLETED"), ("RUNNING", "FAILED")]
)
def test_api_cannot_follow_manager_edges_although_it_holds_update_on_status(
    conn: Connection, old: str, new: str
) -> None:
    job_id = make_job(conn, old)
    as_role(conn, API_LOGIN)
    # The column grant lets the statement through; only the trigger stops the transition.
    assert_guard(conn, f"UPDATE jobs SET status = '{new}' WHERE id = :id", "job_transition_not_owned_by_api", id=job_id)


def test_the_api_group_itself_is_classified_as_api(conn: Connection) -> None:
    job_id = make_job(conn)
    as_role(conn, API_GROUP)
    assert_guard(conn, "UPDATE jobs SET status = 'RUNNING' WHERE id = :id", "job_transition_not_owned_by_api", id=job_id)


def test_a_role_nested_inside_the_api_group_is_classified_as_api(conn: Connection) -> None:
    middle = f"gpm_t{secrets.token_hex(4)}_middle"
    conn.execute(text(f'CREATE ROLE "{middle}" NOLOGIN IN ROLE {API_GROUP}'))
    caller = new_role(conn, member_of=(middle,))
    job_id = make_job(conn)
    as_role(conn, caller)
    assert_guard(conn, "UPDATE jobs SET status = 'RUNNING' WHERE id = :id", "job_transition_not_owned_by_api", id=job_id)


@pytest.mark.parametrize(
    ("old", "new"), [("QUEUED", "RUNNING"), ("RUNNING", "COMPLETED"), ("RUNNING", "FAILED")]
)
def test_a_manager_may_follow_its_own_edges(conn: Connection, old: str, new: str) -> None:
    manager = new_role(conn, member_of=(MANAGER_GROUP,))
    job_id = make_job(conn, old)
    as_role(conn, manager)
    conn.execute(text(f"UPDATE jobs SET {LEGAL_EDGES[(old, new)]} WHERE id = :id"), {"id": job_id})
    conn.execute(text("RESET ROLE"))
    assert status_of(conn, job_id) == new


def test_a_manager_cannot_cancel(conn: Connection) -> None:
    manager = new_role(conn, member_of=(MANAGER_GROUP,))
    job_id = make_job(conn)
    as_role(conn, manager)
    assert_guard(
        conn,
        "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id",
        "job_transition_not_owned_by_manager",
        id=job_id,
    )


def test_a_role_in_both_groups_is_refused_for_every_edge(conn: Connection) -> None:
    both = new_role(conn, member_of=(API_GROUP, MANAGER_GROUP))
    job_id = make_job(conn)
    as_role(conn, both)
    assert_guard(
        conn,
        "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id",
        "job_update_role_ambiguous",
        id=job_id,
    )


def test_a_role_with_update_grants_but_no_group_fails_closed(conn: Connection) -> None:
    stranger = new_role(conn)
    job_id = make_job(conn)
    as_role(conn, stranger)
    assert_guard(
        conn,
        "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id",
        "job_update_role_not_permitted",
        id=job_id,
    )


def test_the_database_owner_without_superuser_is_maintenance_but_still_bound_by_the_common_rules(
    conn: Connection,
) -> None:
    owner = new_role(conn)
    database = conn.execute(text("SELECT quote_ident(current_database())")).scalar_one()
    conn.execute(text(f'ALTER DATABASE {database} OWNER TO "{owner}"'))
    running = make_job(conn, "RUNNING")
    terminal = make_job(conn, "COMPLETED")
    as_role(conn, owner)
    conn.execute(text("UPDATE jobs SET status = 'COMPLETED', terminal_at = clock_timestamp() WHERE id = :id"), {"id": running})
    assert_guard(conn, "UPDATE jobs SET status = 'QUEUED' WHERE id = :id", "job_terminal_immutable", id=terminal)


# --- statement-level behavior, rollback and concurrency ----------------------------------------------------------


def test_one_rejected_row_rejects_the_whole_statement(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    queued = add_job(conn, client_id, listing_id, worker_id)
    add_job(conn, client_id, listing_id, worker_id, job_state("CANCELLED"))
    assert_guard(
        conn,
        "UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE client_id = :client",
        "job_terminal_immutable",
        client=client_id,
    )
    assert status_of(conn, queued) == "QUEUED"


def test_a_rejected_update_rolls_back_with_the_surrounding_transaction(baseline_database: Engine) -> None:
    with baseline_database.begin() as setup:
        job_id = make_job(setup, "RUNNING")
    connection = baseline_database.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            text("UPDATE jobs SET status = 'COMPLETED', terminal_at = clock_timestamp() WHERE id = :id"), {"id": job_id}
        )
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE jobs SET status = 'FAILED' WHERE id = :id"), {"id": job_id})
    finally:
        transaction.rollback()
        connection.close()
    with baseline_database.connect() as check:
        assert status_of(check, job_id) == "RUNNING"


def wait_until_blocked(engine: Engine, outcome: dict[str, object], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    with engine.connect() as watcher:
        while time.monotonic() < deadline:
            blocked = watcher.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' AND state = 'active'"
                )
            ).scalar_one()
            # pg_stat_activity is cached for the length of a transaction, so every poll needs a fresh one.
            watcher.rollback()
            if blocked:
                return
            time.sleep(0.05)
    pytest.fail(f"the second session never blocked on the row lock; its outcome: {outcome.get('result')!r}")


def test_a_queued_job_has_exactly_one_winner_between_api_cancel_and_owner_start(baseline_database: Engine) -> None:
    """Race cancel against start: the loser re-reads the committed row, sees a terminal Job and is refused."""
    with baseline_database.begin() as setup:
        job_id = make_job(setup)

    outcome: dict[str, object] = {}
    first = baseline_database.connect()
    first_transaction = first.begin()
    first.execute(text(f"SET LOCAL ROLE {API_LOGIN}"))
    first.execute(
        text("UPDATE jobs SET status = 'CANCELLED', terminal_at = clock_timestamp() WHERE id = :id"), {"id": job_id}
    )

    def second_session() -> None:
        with baseline_database.begin() as connection:
            try:
                connection.execute(
                    text("UPDATE jobs SET status = 'RUNNING', started_at = clock_timestamp() WHERE id = :id"),
                    {"id": job_id},
                )
                outcome["result"] = "updated"
            except DBAPIError as error:
                outcome["result"] = (error.orig.sqlstate, error.orig.diag.constraint_name, error.orig.diag.message_primary)
            except Exception as error:  # surfaced in the assertion below instead of dying inside the thread
                outcome["result"] = f"unexpected {type(error).__name__}: {error}"

    thread = threading.Thread(target=second_session)
    thread.start()
    try:
        wait_until_blocked(baseline_database, outcome)
        first_transaction.commit()
    finally:
        first.close()
        thread.join(timeout=15)
    assert not thread.is_alive()
    assert outcome["result"] == (INTEGRITY, TRIGGER, "job_terminal_immutable")
    with baseline_database.connect() as check:
        assert status_of(check, job_id) == "CANCELLED"


def test_two_terminal_transitions_race_and_only_the_first_commits(baseline_database: Engine) -> None:
    with baseline_database.begin() as setup:
        job_id = make_job(setup, "RUNNING")

    outcome: dict[str, object] = {}
    first = baseline_database.connect()
    first_transaction = first.begin()
    first.execute(text("UPDATE jobs SET status = 'COMPLETED', terminal_at = clock_timestamp() WHERE id = :id"), {"id": job_id})

    def second_session() -> None:
        with baseline_database.begin() as connection:
            try:
                connection.execute(
                    text(
                        "UPDATE jobs SET status = 'FAILED', terminal_at = clock_timestamp(), "
                        "failure_reason = 'WORKER_FAULT' WHERE id = :id"
                    ),
                    {"id": job_id},
                )
                outcome["result"] = "updated"
            except DBAPIError as error:
                outcome["result"] = error.orig.diag.message_primary

    thread = threading.Thread(target=second_session)
    thread.start()
    try:
        wait_until_blocked(baseline_database, outcome)
        first_transaction.commit()
    finally:
        first.close()
        thread.join(timeout=15)
    assert outcome["result"] == "job_terminal_immutable"
    with baseline_database.connect() as check:
        assert status_of(check, job_id) == "COMPLETED"


# --- migration lifecycle -------------------------------------------------------------------------------------------


def trigger_and_function_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        triggers = connection.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgname = :n AND NOT tgisinternal"), {"n": TRIGGER}
        ).scalar_one()
        functions = connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'fn_jobs_guard_update'")
        ).scalar_one()
    return triggers, functions


def test_downgrade_removes_the_trigger_and_function_and_upgrade_restores_them(
    baseline_database: Engine, alembic_config: Config
) -> None:
    assert trigger_and_function_counts(baseline_database) == (1, 1)
    command.downgrade(alembic_config, BASELINE_WITH_GRANTS)
    try:
        assert trigger_and_function_counts(baseline_database) == (0, 0)
        with baseline_database.connect() as connection:
            roles = connection.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname IN (:a, :b)"), {"a": API_GROUP, "b": MANAGER_GROUP}
            ).scalar_one()
            assert roles == 2, "downgrade must never drop a role"
    finally:
        command.upgrade(alembic_config, "head")
    assert trigger_and_function_counts(baseline_database) == (1, 1)
