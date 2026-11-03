"""PostgreSQL ``AccountReader`` adapter (D-C3) against the disposable test cluster.

Rows are inserted as the owner inside a rolled-back transaction; every read then runs as
``gpm_api_rw`` (SET LOCAL ROLE), so the tests also prove the runtime grants are sufficient.
"""

import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from gpu_marketplace.common.database import create_engine
from gpu_marketplace.identity.ports import AccountRecord, AccountStoreUnavailable
from gpu_marketplace.identity.service import AuthService, InvalidCredentials, NotAuthenticated
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.repositories.accounts import PostgresAccountReader
from identity_fakes import HASHER, PASSWORD, SECRET

CLIENT = UUID("3f1b8a52-6a5e-4f0e-9d0b-6a7c1e2f3a41")
WORKER = UUID("5c2d9e63-7b6f-4a1f-8e1c-7b8d2f3a4b52")
DISABLED = UUID("7e3f0a74-8c7a-4b2a-9f2d-8c9e3a4b5c63")
NO_ROLE = UUID("9a4b1c85-9d8b-4c3b-8a3e-9daf4b5c6d74")
UNKNOWN = UUID("b05c2d96-ae9c-4d4c-9b4f-aeb05c6d7e85")


@pytest.fixture
def sessions(conn: Connection) -> Iterator[sessionmaker[Session]]:
    password_hash = HASHER.hash_password(PASSWORD)
    for user_id, login_name, status, role in [
        (CLIENT, "demo_client_01", "ACTIVE", "CLIENT"),
        (WORKER, "demo_worker_01", "ACTIVE", "WORKER"),
        (DISABLED, "demo_disabled_01", "DISABLED", "CLIENT"),
        (NO_ROLE, "demo_no_role", "ACTIVE", None),
    ]:
        conn.execute(
            text("INSERT INTO users (id, login_name, password_hash, status) VALUES (:id, :name, :hash, :status)"),
            {"id": user_id, "name": login_name, "hash": password_hash, "status": status},
        )
        if role is not None:
            conn.execute(
                text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, :role)"), {"id": user_id, "role": role}
            )
    conn.execute(text("SET LOCAL ROLE gpm_api_rw"))
    # Sessions join the outer transaction through savepoints, so the fixture rollback undoes everything.
    yield sessionmaker(bind=conn, join_transaction_mode="create_savepoint")


@pytest.fixture
def reader(sessions: sessionmaker[Session]) -> PostgresAccountReader:
    return PostgresAccountReader(sessions)


def test_find_by_login_name_returns_the_joined_record(reader: PostgresAccountReader) -> None:
    record = reader.find_by_login_name("demo_worker_01")
    assert isinstance(record, AccountRecord)
    assert (record.user_id, record.login_name, record.status, record.role) == (
        WORKER,
        "demo_worker_01",
        "ACTIVE",
        "WORKER",
    )
    assert HASHER.verify_password(PASSWORD, record.password_hash)


def test_get_by_id_returns_the_joined_record(reader: PostgresAccountReader) -> None:
    record = reader.get_by_id(CLIENT)
    assert record is not None
    assert (record.user_id, record.login_name, record.status, record.role) == (
        CLIENT,
        "demo_client_01",
        "ACTIVE",
        "CLIENT",
    )


def test_unknown_account_is_none(reader: PostgresAccountReader) -> None:
    assert reader.find_by_login_name("nobody") is None
    assert reader.get_by_id(UNKNOWN) is None


def test_match_is_exact_and_case_sensitive(reader: PostgresAccountReader) -> None:
    assert reader.find_by_login_name("Demo_Client_01") is None
    assert reader.find_by_login_name("DEMO_CLIENT_01") is None
    assert reader.find_by_login_name("demo_client_0") is None
    assert reader.find_by_login_name(" demo_client_01") is None


def test_login_name_collation_is_deterministic(conn: Connection) -> None:
    # A nondeterministic collation would make case/accents compare equal and break exact matching.
    deterministic = conn.execute(
        text(
            "SELECT COALESCE(c.collisdeterministic, true) FROM pg_attribute a "
            "LEFT JOIN pg_collation c ON c.oid = a.attcollation "
            "WHERE a.attrelid = 'users'::regclass AND a.attname = 'login_name'"
        )
    ).scalar_one()
    assert deterministic is True


def test_missing_role_row_is_none_role(reader: PostgresAccountReader) -> None:
    record = reader.get_by_id(NO_ROLE)
    assert record is not None and record.role is None
    by_name = reader.find_by_login_name("demo_no_role")
    assert by_name is not None and by_name.role is None


def test_disabled_status_is_returned_as_stored(reader: PostgresAccountReader) -> None:
    record = reader.find_by_login_name("demo_disabled_01")
    assert record is not None and record.status == "DISABLED"


def test_reads_run_as_the_api_runtime_role(conn: Connection, reader: PostgresAccountReader) -> None:
    assert conn.execute(text("SELECT current_user")).scalar_one() == "gpm_api_rw"
    assert reader.get_by_id(CLIENT) is not None


def test_auth_service_end_to_end_with_the_adapter(reader: PostgresAccountReader) -> None:
    service = AuthService(reader, AccessTokenCodec(SECRET), HASHER)
    result = service.login("  demo_client_01\t", PASSWORD)
    assert (result.identity.user_id, result.identity.role) == (CLIENT, "CLIENT")
    assert service.authenticate(result.access_token).user_id == CLIENT
    for login_name, password in [
        ("demo_client_01", "wrong"),
        ("nobody", PASSWORD),
        ("demo_disabled_01", PASSWORD),
        ("demo_no_role", PASSWORD),
    ]:
        with pytest.raises(InvalidCredentials):
            service.login(login_name, password)


def test_auth_service_rechecks_status_on_every_request(
    conn: Connection, reader: PostgresAccountReader
) -> None:
    service = AuthService(reader, AccessTokenCodec(SECRET), HASHER)
    token = service.login("demo_worker_01", PASSWORD).access_token
    conn.execute(text("RESET ROLE"))
    conn.execute(text("UPDATE users SET status = 'DISABLED' WHERE id = :id"), {"id": WORKER})
    conn.execute(text("SET LOCAL ROLE gpm_api_rw"))
    with pytest.raises(NotAuthenticated):
        service.authenticate(token)


@pytest.fixture
def unreachable_engine() -> Iterator[Engine]:
    # Port 1 on loopback refuses connections; nothing is written anywhere.
    engine = create_engine("postgresql+psycopg://probe:secret-in-dsn@127.0.0.1:1/gpu_marketplace_probe")
    try:
        yield engine
    finally:
        engine.dispose()


def test_database_failure_becomes_a_sanitized_unavailable_error(
    unreachable_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    reader = PostgresAccountReader(sessionmaker(bind=unreachable_engine))
    for call in (lambda: reader.find_by_login_name("secret_login_name"), lambda: reader.get_by_id(CLIENT)):
        with caplog.at_level(logging.ERROR), pytest.raises(AccountStoreUnavailable) as raised:
            call()
        error = raised.value
        assert str(error) == "" and error.args == ()
        assert error.__cause__ is None and error.__suppress_context__ is True
    logged = caplog.text
    for leaked in ("secret-in-dsn", "secret_login_name", "127.0.0.1", "SELECT", "probe"):
        assert leaked not in logged
        assert leaked not in repr(raised.value)
    assert "account_store_query_failed" in logged


def test_permission_failure_is_also_unavailable(conn: Connection, reader: PostgresAccountReader) -> None:
    # Fail closed if the runtime grant is ever missing: a controlled 503, not a 500 with SQL text.
    # CREATE ROLE is transactional, so the fixture rollback removes this role again.
    conn.execute(text("RESET ROLE"))
    conn.execute(text("CREATE ROLE gpm_test_no_account_access NOLOGIN"))
    conn.execute(text("SET LOCAL ROLE gpm_test_no_account_access"))
    with pytest.raises(AccountStoreUnavailable):
        reader.get_by_id(CLIENT)
