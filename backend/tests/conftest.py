import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from db_safety import TestDatabase, UnsafeTestDatabase, resolve_test_database, verify_cluster

BACKEND_ROOT = Path(__file__).resolve().parents[1]
NOT_RUN_REASON = (
    "NOT_RUN: PostgreSQL tests need GPU_MARKETPLACE_TEST_DATABASE_URL, "
    "GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=1 and GPU_MARKETPLACE_TEST_CLUSTER_TOKEN "
    "for a disposable cluster (schema matrix 9.2/9.3)"
)


@pytest.fixture(scope="session")
def test_database() -> TestDatabase:
    try:
        target = resolve_test_database(os.environ)
    except UnsafeTestDatabase as error:
        pytest.exit(f"Unsafe test database configuration, aborting session: {error}", returncode=2)
    if target is None:
        pytest.skip(NOT_RUN_REASON)
    return target


@pytest.fixture(scope="session")
def db_engine(test_database: TestDatabase) -> Iterator[Engine]:
    engine = create_engine(
        test_database.url,
        connect_args={"application_name": "gpm-pytest", "connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            try:
                verify_cluster(connection, test_database)
            except UnsafeTestDatabase as error:
                pytest.exit(f"Unsafe test cluster, aborting session: {error}", returncode=2)
        yield engine
    finally:
        engine.dispose()


def reset_schema(engine: Engine, target: TestDatabase) -> None:
    """Empty the test database. The cluster and database guards are re-checked on every call (G8)."""
    with engine.begin() as connection:
        try:
            verify_cluster(connection, target)
        except UnsafeTestDatabase as error:
            pytest.exit(f"Unsafe test cluster, aborting session: {error}", returncode=2)
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def clean_database(db_engine: Engine, test_database: TestDatabase) -> Engine:
    reset_schema(db_engine, test_database)
    return db_engine


@pytest.fixture
def alembic_config(test_database: TestDatabase, monkeypatch: pytest.MonkeyPatch) -> Config:
    # migrations/env.py reads the database URL from Settings, so point it at the vetted test database.
    monkeypatch.setenv("GPU_MARKETPLACE_DATABASE_URL", test_database.url)
    return Config(str(BACKEND_ROOT / "alembic.ini"))


@pytest.fixture
def migrated_database(clean_database: Engine, alembic_config: Config) -> Engine:
    command.upgrade(alembic_config, "head")
    return clean_database


@pytest.fixture(scope="module")
def baseline_database(db_engine: Engine, test_database: TestDatabase) -> Iterator[Engine]:
    """Schema at ``head`` for a whole module; tests isolate themselves with a rolled-back transaction."""
    reset_schema(db_engine, test_database)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GPU_MARKETPLACE_DATABASE_URL", test_database.url)
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    yield db_engine


@pytest.fixture
def conn(baseline_database: Engine) -> Iterator[Connection]:
    with baseline_database.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
