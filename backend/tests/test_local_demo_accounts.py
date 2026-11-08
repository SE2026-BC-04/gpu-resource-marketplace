from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from gpu_marketplace.common.local_demo_accounts import (
    _insert_demo_accounts,
    validate_local_database_identity,
    validate_local_libpq_environment,
    validate_local_owner_url,
)
from gpu_marketplace.identity.passwords import ScryptPasswordHasher
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.repositories.accounts import PostgresAccountReader


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace",
        "postgresql+psycopg://owner:secret@localhost:25432/gpu_marketplace",
        "postgresql+psycopg://owner:secret@[::1]:5432/gpu_marketplace",
    ],
)
def test_local_demo_provisioner_accepts_only_loopback_postgresql(raw_url: str) -> None:
    assert validate_local_owner_url(raw_url) == make_url(raw_url)


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql+psycopg://owner:secret@db.example/gpu_marketplace",
        "postgresql+psycopg://owner:secret@127.0.0.1/postgres",
        "postgresql://owner:secret@127.0.0.1/gpu_marketplace",
        "postgresql+psycopg://owner:secret@127.0.0.1/gpu_marketplace",
        "postgresql+psycopg://owner:secret@127.0.0.1:0/gpu_marketplace",
        "postgresql+psycopg://owner:secret@127.0.0.1:65536/gpu_marketplace",
        "postgresql+psycopg:///gpu_marketplace",
    ],
)
def test_local_demo_provisioner_rejects_nonlocal_or_wrong_database(raw_url: str) -> None:
    with pytest.raises(ValueError):
        validate_local_owner_url(raw_url)


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace?host=remote.example",
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace?hostaddr=10.0.0.20",
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace?service=external",
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace?sslmode=require",
    ],
)
def test_local_demo_provisioner_rejects_all_query_parameters(raw_url: str) -> None:
    with pytest.raises(ValueError, match="query parameters are forbidden"):
        validate_local_owner_url(raw_url)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PGHOST", "remote.example"),
        ("PGHOSTADDR", "10.0.0.20"),
        ("PGPORT", "6543"),
        ("PGDATABASE", "other_database"),
        ("PGUSER", "other_user"),
        ("PGSERVICE", "external"),
        ("PGSERVICEFILE", "C:/temp/pg_service.conf"),
    ],
)
def test_local_demo_provisioner_rejects_libpq_routing_environment(
    name: str, value: str
) -> None:
    with pytest.raises(ValueError, match="libpq routing environment variables are forbidden"):
        validate_local_libpq_environment({name: value})


def test_local_demo_provisioner_reports_malformed_url_without_echoing_credentials() -> None:
    with pytest.raises(ValueError) as error:
        validate_local_owner_url(
            "postgresql+psycopg://owner:private-secret@127.0.0.1:invalid/gpu_marketplace"
        )

    assert str(error.value) == "database URL is invalid"
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("database", "current_user", "owner"),
    [
        ("production", "gpu_marketplace", "gpu_marketplace"),
        ("gpu_marketplace", "gpm_api_app", "gpu_marketplace"),
    ],
)
def test_local_demo_provisioner_rejects_wrong_db_or_non_owner(
    database: str, current_user: str, owner: str
) -> None:
    with pytest.raises(ValueError):
        validate_local_database_identity(database, current_user, owner)


def test_local_demo_provisioner_accepts_expected_owner_database() -> None:
    validate_local_database_identity("gpu_marketplace", "gpu_marketplace", "gpu_marketplace")


def test_local_demo_provisioner_rejects_routing_environment_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gpu_marketplace.common import local_demo_accounts

    engine_calls: list[object] = []
    raw_url = "postgresql+psycopg://owner:private-secret@127.0.0.1:5432/gpu_marketplace"
    monkeypatch.setenv("GPU_MARKETPLACE_MIGRATION_DATABASE_URL", raw_url)
    monkeypatch.setenv("PGHOSTADDR", "10.0.0.20")
    monkeypatch.setattr(local_demo_accounts, "create_engine", lambda *args, **kwargs: engine_calls.append(args))

    assert local_demo_accounts.main(["--allow-local-dev-db"]) == 2
    captured = capsys.readouterr()
    assert "PGHOSTADDR" in captured.err
    assert "10.0.0.20" not in captured.err
    assert "private-secret" not in captured.err
    assert engine_calls == []


def test_local_demo_provisioner_rejects_url_override_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gpu_marketplace.common import local_demo_accounts

    engine_calls: list[object] = []
    raw_url = (
        "postgresql+psycopg://owner:private-secret@127.0.0.1:5432/"
        "gpu_marketplace?host=remote.example"
    )
    monkeypatch.setenv("GPU_MARKETPLACE_MIGRATION_DATABASE_URL", raw_url)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.setattr(local_demo_accounts, "create_engine", lambda *args, **kwargs: engine_calls.append(args))

    assert local_demo_accounts.main(["--allow-local-dev-db"]) == 2
    captured = capsys.readouterr()
    assert "query parameters are forbidden" in captured.err
    assert "private-secret" not in captured.err
    assert "remote.example" not in captured.err
    assert engine_calls == []


def _demo_credentials(suffix: str) -> tuple[str, str, str, str]:
    return (
        f"demo_worker_{suffix}",
        f"worker-password-{suffix}",
        f"demo_client_{suffix}",
        f"client-password-{suffix}",
    )


def _account_snapshot(engine: Engine, worker_login: str, client_login: str) -> tuple[list, list]:
    with engine.connect() as connection:
        users = connection.execute(
            text(
                "SELECT id, login_name, password_hash, status FROM users "
                "WHERE login_name IN (:worker, :client) ORDER BY login_name"
            ),
            {"worker": worker_login, "client": client_login},
        ).all()
        workers = connection.execute(
            text(
                "SELECT w.id, u.login_name, w.display_name FROM workers AS w "
                "JOIN users AS u ON u.id = w.user_id "
                "WHERE u.login_name IN (:worker, :client) ORDER BY u.login_name"
            ),
            {"worker": worker_login, "client": client_login},
        ).all()
    return list(users), list(workers)


def test_local_demo_accounts_insert_and_authenticate_on_disposable_postgres(
    migrated_database_with_teardown: Engine,
) -> None:
    engine = migrated_database_with_teardown
    worker_login, worker_password, client_login, client_password = _demo_credentials(uuid4().hex[:12])
    hasher = ScryptPasswordHasher()
    worker_hash = hasher.hash_password(worker_password)
    client_hash = hasher.hash_password(client_password)

    with engine.begin() as connection:
        worker_user_id, client_user_id = _insert_demo_accounts(
            connection,
            worker_login=worker_login,
            worker_hash=worker_hash,
            worker_name="Disposable PostgreSQL Demo Worker",
            client_login=client_login,
            client_hash=client_hash,
        )

    with engine.connect() as connection:
        worker = connection.execute(
            text(
                "SELECT u.password_hash, u.status, ur.role_code "
                "FROM users AS u JOIN user_roles AS ur ON ur.user_id = u.id "
                "WHERE u.id = :id"
            ),
            {"id": worker_user_id},
        ).one()
        client = connection.execute(
            text(
                "SELECT u.password_hash, u.status, ur.role_code "
                "FROM users AS u JOIN user_roles AS ur ON ur.user_id = u.id "
                "WHERE u.id = :id"
            ),
            {"id": client_user_id},
        ).one()
        worker_profiles = connection.execute(
            text("SELECT count(*) FROM workers WHERE user_id = :id"),
            {"id": worker_user_id},
        ).scalar_one()
        client_profiles = connection.execute(
            text("SELECT count(*) FROM workers WHERE user_id = :id"),
            {"id": client_user_id},
        ).scalar_one()
        password_columns = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'users'"
            )
        ).scalars().all()

    assert tuple(worker[1:]) == ("ACTIVE", "WORKER")
    assert tuple(client[1:]) == ("ACTIVE", "CLIENT")
    assert worker_profiles == 1
    assert client_profiles == 0
    assert worker[0] == worker_hash and client[0] == client_hash
    assert worker_password not in worker[0] and client_password not in client[0]
    assert worker[0].startswith("scrypt$n=32768,r=8,p=3$")
    assert client[0].startswith("scrypt$n=32768,r=8,p=3$")
    assert "password_hash" in password_columns
    assert "password" not in password_columns
    assert hasher.verify_password(worker_password, worker[0])
    assert hasher.verify_password(client_password, client[0])

    auth = AuthService(
        accounts=PostgresAccountReader(sessionmaker(bind=engine)),
        tokens=AccessTokenCodec(b"local-demo-postgres-test-jwt-secret-32-bytes"),
        passwords=hasher,
    )
    assert auth.login(worker_login, worker_password).identity.role == "WORKER"
    assert auth.login(client_login, client_password).identity.role == "CLIENT"


def test_local_demo_accounts_duplicate_login_does_not_modify_existing_rows(
    migrated_database_with_teardown: Engine,
) -> None:
    engine = migrated_database_with_teardown
    worker_login, worker_password, client_login, client_password = _demo_credentials(uuid4().hex[:12])
    hasher = ScryptPasswordHasher()
    with engine.begin() as connection:
        _insert_demo_accounts(
            connection,
            worker_login=worker_login,
            worker_hash=hasher.hash_password(worker_password),
            worker_name="Existing Demo Worker",
            client_login=client_login,
            client_hash=hasher.hash_password(client_password),
        )
    before = _account_snapshot(engine, worker_login, client_login)

    with pytest.raises(ValueError, match="login names already exist"):
        with engine.begin() as connection:
            _insert_demo_accounts(
                connection,
                worker_login=worker_login,
                worker_hash="replacement-worker-hash",
                worker_name="Replacement Worker Name",
                client_login=client_login,
                client_hash="replacement-client-hash",
            )

    assert _account_snapshot(engine, worker_login, client_login) == before


def test_local_demo_accounts_mid_transaction_failure_rolls_back_all_rows(
    migrated_database_with_teardown: Engine,
) -> None:
    engine = migrated_database_with_teardown
    worker_login, _worker_password, client_login, _client_password = _demo_credentials(uuid4().hex[:12])

    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            _insert_demo_accounts(
                connection,
                worker_login=worker_login,
                worker_hash="test-worker-hash",
                worker_name="x" * 161,
                client_login=client_login,
                client_hash="test-client-hash",
            )

    assert _account_snapshot(engine, worker_login, client_login) == ([], [])


def test_local_demo_database_identity_guard_blocks_insert_on_mismatch(
    migrated_database_with_teardown: Engine,
) -> None:
    engine = migrated_database_with_teardown
    worker_login, _worker_password, client_login, _client_password = _demo_credentials(uuid4().hex[:12])
    with engine.connect() as connection:
        database, current_user, owner = connection.execute(
            text(
                "SELECT current_database(), current_user, "
                "pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
            )
        ).one()

    invalid_identities = [
        ("not_gpu_marketplace", current_user, owner),
        (database, "not_the_owner", owner),
    ]
    for identity in invalid_identities:
        with pytest.raises(ValueError):
            with engine.begin() as connection:
                validate_local_database_identity(*identity)
                _insert_demo_accounts(
                    connection,
                    worker_login=worker_login,
                    worker_hash="test-worker-hash",
                    worker_name="Must Not Be Inserted",
                    client_login=client_login,
                    client_hash="test-client-hash",
                )

    assert _account_snapshot(engine, worker_login, client_login) == ([], [])
