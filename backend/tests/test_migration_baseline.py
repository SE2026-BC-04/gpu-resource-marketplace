"""GPU-002-B acceptance on real PostgreSQL: baseline upgrade, exact tables, seed, catalog names, drift."""

import importlib.util
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Engine

import gpu_marketplace.domain  # noqa: F401
from gpu_marketplace.domain.base import Base
from test_schema_metadata import (
    EXPECTED_CHECKS,
    EXPECTED_FOREIGN_KEYS,
    EXPECTED_INDEXES,
    EXPECTED_TABLES,
    EXPECTED_UNIQUES,
)

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
EXPECTED_ROLES = {
    "CLIENT": "Client user",
    "WORKER": "GPU resource provider",
    "ADMIN": "System administrator",
}


def user_tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        )
        return set(rows.scalars())


def constraint_names(engine: Engine, kind: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = 'public' AND contype = :kind"
            ),
            {"kind": kind},
        )
        return set(rows.scalars())


def baseline_module():
    files = sorted(VERSIONS.glob("*.py"))
    assert len(files) == 1, "Phase 1B must ship exactly one baseline revision"
    spec = importlib.util.spec_from_file_location("baseline_revision", files[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_head_creates_exactly_the_ten_tables(migrated_database: Engine) -> None:
    assert user_tables(migrated_database) == EXPECTED_TABLES


def test_catalog_constraint_names_match_the_matrix(migrated_database: Engine) -> None:
    assert constraint_names(migrated_database, "c") == EXPECTED_CHECKS
    assert constraint_names(migrated_database, "f") == set(EXPECTED_FOREIGN_KEYS)
    with migrated_database.connect() as connection:
        index_names = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
            ).scalars()
        )
    primary_keys = {f"pk_{table}" for table in EXPECTED_TABLES}
    assert index_names == primary_keys | EXPECTED_UNIQUES | EXPECTED_INDEXES


def test_roles_are_seeded(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        rows = dict(connection.execute(text("SELECT code, description FROM roles")).all())
    assert rows == EXPECTED_ROLES


def test_role_seed_is_idempotent(migrated_database: Engine) -> None:
    module = baseline_module()
    with migrated_database.begin() as connection:
        connection.execute(text("UPDATE roles SET description = 'edited' WHERE code = 'CLIENT'"))
        module.seed_roles(connection)
        module.seed_roles(connection)
        rows = dict(connection.execute(text("SELECT code, description FROM roles")).all())
    assert set(rows) == set(EXPECTED_ROLES)
    assert rows["CLIENT"] == "edited", "seed must not overwrite existing rows"


def test_downgrade_then_upgrade_round_trips(migrated_database: Engine, alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    assert user_tables(migrated_database) == set()
    command.upgrade(alembic_config, "head")
    assert user_tables(migrated_database) == EXPECTED_TABLES
    with migrated_database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM roles")).scalar_one() == 3


def test_orm_metadata_has_no_drift_from_the_migration(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
