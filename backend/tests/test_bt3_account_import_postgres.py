"""BT3 VT-088: integration tests for bulk account import against real PostgreSQL.

Runs only on the safety-marked disposable cluster (conftest/db_safety). Each test gets a freshly
migrated database (``migrated_database_with_teardown``), commits for real, and reads back through
a *separate* connection, so "created" is checked against what PostgreSQL actually stored.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from bt3_account_writer import PostgresAccountWriter
from gpu_marketplace.common.database import create_engine
from gpu_marketplace.identity.account_import import FailReason, RejectReason, import_accounts
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.repositories.accounts import PostgresAccountReader
from identity_fakes import HASHER, SECRET

BATCH = [
    {"login_name": "  bt3_client\t", "password": "client-pass-1", "role_code": "CLIENT"},
    {"login_name": "bt3_bad_role", "password": "x-pass-1", "role_code": "ROOT"},
    {"login_name": "bt3_worker", "password": "worker-pass-1", "role_code": "WORKER"},
    {"login_name": "", "password": "x-pass-2", "role_code": "CLIENT"},
    {"login_name": "bt3_admin", "password": "admin-pass-1", "role_code": "ADMIN", "status": "ACTIVE"},
    {"login_name": "bt3_client", "password": "dup-pass-1", "role_code": "CLIENT"},
    "not a record",
    {"login_name": "bt3_disabled", "password": "disabled-pass-1", "role_code": "CLIENT", "status": "DISABLED"},
]
VALID_INDEXES = [0, 2, 4, 7]


@pytest.fixture
def engine(migrated_database_with_teardown: Engine) -> Iterator[Engine]:
    yield migrated_database_with_teardown


def stored_accounts(engine: Engine) -> dict[str, tuple[str, str, int]]:
    """Read back on a new connection: login_name -> (status, role_code, number of role rows)."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT u.login_name, u.status, min(r.role_code), count(r.user_id) "
                "FROM users u LEFT JOIN user_roles r ON r.user_id = u.id GROUP BY u.id, u.login_name, u.status"
            )
        ).all()
    return {name: (status, role, count) for name, status, role, count in rows}


def orphan_users(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM users u WHERE NOT EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id)")
        ).scalar_one()


def test_it01_valid_records_are_committed_and_can_log_in(engine: Engine) -> None:
    """AC-1, AC-3, AC-4 on a real database and the real Login path."""
    report = import_accounts(BATCH, PostgresAccountWriter(engine), HASHER)

    assert [c.index for c in report.created] == VALID_INDEXES
    assert {r.index: r.reason for r in report.rejected} == {
        1: RejectReason.INVALID_ROLE,
        3: RejectReason.INVALID_LOGIN_NAME,
        5: RejectReason.DUPLICATE_IN_BATCH,
        6: RejectReason.INVALID_RECORD,
    }
    assert report.failed == ()
    assert stored_accounts(engine) == {
        "bt3_client": ("ACTIVE", "CLIENT", 1),
        "bt3_worker": ("ACTIVE", "WORKER", 1),
        "bt3_admin": ("ACTIVE", "ADMIN", 1),
        "bt3_disabled": ("DISABLED", "CLIENT", 1),
    }

    auth = AuthService(PostgresAccountReader(sessionmaker(bind=engine)), AccessTokenCodec(SECRET), HASHER)
    ids = {c.index: c.user_id for c in report.created}
    for index, role in [(0, "CLIENT"), (2, "WORKER"), (4, "ADMIN")]:
        source = BATCH[index]
        identity = auth.login(source["login_name"], source["password"]).identity
        assert (identity.user_id, identity.role) == (ids[index], role)


def test_it02_reimporting_the_same_batch_creates_nothing_new(engine: Engine) -> None:
    """NFR-3 on PostgreSQL: the unique constraint is reported as LOGIN_NAME_TAKEN."""
    writer = PostgresAccountWriter(engine)
    import_accounts(BATCH, writer, HASHER)
    before = stored_accounts(engine)

    again = import_accounts(BATCH, writer, HASHER)

    assert again.created == ()
    assert {f.index: f.reason for f in again.failed} == {i: FailReason.LOGIN_NAME_TAKEN for i in VALID_INDEXES}
    assert stored_accounts(engine) == before


def test_it03_failure_path_commit_failure_is_reported_failed_and_leaves_nothing(engine: Engine) -> None:
    """The VT-088 risk on a real COMMIT: the inserts succeed, then COMMIT itself fails.

    A deferred constraint trigger raises at COMMIT time for one name only. That record must be
    ``failed`` (never ``created``), leave no row, and the records around it must still be saved.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION bt3_fail_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.login_name = 'bt3_commit_fails' THEN RAISE EXCEPTION 'bt3 injected commit failure'; END IF; "
                "RETURN NULL; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE CONSTRAINT TRIGGER bt3_fail_at_commit AFTER INSERT ON users "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION bt3_fail_at_commit()"
            )
        )
    batch = [
        {"login_name": "bt3_before", "password": "before-pass", "role_code": "CLIENT"},
        {"login_name": "bt3_commit_fails", "password": "fails-pass", "role_code": "CLIENT"},
        {"login_name": "bt3_after", "password": "after-pass", "role_code": "WORKER"},
    ]

    report = import_accounts(batch, PostgresAccountWriter(engine), HASHER)

    assert [c.index for c in report.created] == [0, 2]
    assert {f.index: f.reason for f in report.failed} == {1: FailReason.PERSISTENCE_ERROR}
    assert set(stored_accounts(engine)) == {"bt3_before", "bt3_after"}
    assert orphan_users(engine) == 0


def test_it04_unreachable_database_saves_nothing_and_reports_every_valid_record_failed(
    engine: Engine, test_database
) -> None:
    unreachable = create_engine(make_url(test_database.url).set(port=1).render_as_string(hide_password=False))
    try:
        report = import_accounts(BATCH, PostgresAccountWriter(unreachable), HASHER)
    finally:
        unreachable.dispose()
    assert report.created == ()
    assert {f.index: f.reason for f in report.failed} == {i: FailReason.DB_UNAVAILABLE for i in VALID_INDEXES}
    assert stored_accounts(engine) == {}


def test_it05_two_concurrent_imports_of_the_same_name_create_exactly_one_account(engine: Engine) -> None:
    writer = PostgresAccountWriter(engine)
    start = threading.Barrier(2)
    reports = []

    def run(password: str) -> None:
        start.wait()
        reports.append(import_accounts([{"login_name": "bt3_race", "password": password, "role_code": "CLIENT"}], writer, HASHER))

    threads = [threading.Thread(target=run, args=(f"race-pass-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(len(r.created) for r in reports) == [0, 1]
    assert [f.reason for r in reports for f in r.failed] == [FailReason.LOGIN_NAME_TAKEN]
    assert stored_accounts(engine) == {"bt3_race": ("ACTIVE", "CLIENT", 1)}
