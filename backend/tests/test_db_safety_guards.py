"""Unit tests (no PostgreSQL) for the test-database guards G1-G4 and C1 of the schema matrix 9.2/9.3."""

import pytest

from db_safety import UnsafeTestDatabase, resolve_test_database

TOKEN = "t" * 32
GOOD = {
    "GPU_MARKETPLACE_TEST_DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:55432/gpu_marketplace_test",
    "GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS": "1",
    "GPU_MARKETPLACE_TEST_CLUSTER_TOKEN": TOKEN,
}


def env(**overrides: str | None) -> dict[str, str]:
    merged: dict[str, str | None] = {**GOOD, **overrides}
    return {key: value for key, value in merged.items() if value is not None}


def test_iso07_no_test_url_means_not_run_without_touching_any_database() -> None:
    assert resolve_test_database({}) is None


def test_g1_missing_opt_in_means_not_run() -> None:
    assert resolve_test_database(env(GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=None)) is None


def test_valid_configuration_is_accepted() -> None:
    target = resolve_test_database(env())
    assert target is not None
    assert target.database == "gpu_marketplace_test"
    assert target.port == 55432


@pytest.mark.parametrize(
    "database",
    ["gpu_marketplace", "postgres", "template1", "prod_test", "x_test", "gpu_marketplace_test_UPPER", "gpu_marketplace_test_" + "a" * 17],
)
def test_g2_database_name_must_match_the_whole_pattern(database: str) -> None:
    url = f"postgresql+psycopg://u:p@127.0.0.1:55432/{database}"
    with pytest.raises(UnsafeTestDatabase, match="database name"):
        resolve_test_database(env(GPU_MARKETPLACE_TEST_DATABASE_URL=url))


@pytest.mark.parametrize("host", ["db.example.com", "10.0.0.5", "postgres"])
def test_g3_host_must_be_loopback(host: str) -> None:
    url = f"postgresql+psycopg://u:p@{host}:55432/gpu_marketplace_test"
    with pytest.raises(UnsafeTestDatabase, match="loopback"):
        resolve_test_database(env(GPU_MARKETPLACE_TEST_DATABASE_URL=url))


def test_g4_refuses_the_runtime_database() -> None:
    url = "postgresql+psycopg://u:p@localhost:55432/gpu_marketplace_test"
    with pytest.raises(UnsafeTestDatabase, match="runtime database"):
        resolve_test_database(
            env(GPU_MARKETPLACE_TEST_DATABASE_URL=url, GPU_MARKETPLACE_DATABASE_URL=url)
        )


def test_g4_refuses_the_migration_database() -> None:
    url = "postgresql+psycopg://u:p@127.0.0.1:55432/gpu_marketplace_test"
    with pytest.raises(UnsafeTestDatabase, match="migration database"):
        resolve_test_database(env(GPU_MARKETPLACE_MIGRATION_DATABASE_URL=url))


def test_iso01_c1_refuses_the_dev_port_by_default() -> None:
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/gpu_marketplace_test"
    with pytest.raises(UnsafeTestDatabase, match="port"):
        resolve_test_database(env(GPU_MARKETPLACE_TEST_DATABASE_URL=url))


def test_iso01_c1_refuses_the_compose_published_port() -> None:
    with pytest.raises(UnsafeTestDatabase, match="port"):
        resolve_test_database(env(POSTGRES_HOST_PORT="55432"))


def test_iso01_c1_refuses_the_runtime_database_port() -> None:
    dev = "postgresql+psycopg://u:p@localhost:55432/gpu_marketplace"
    with pytest.raises(UnsafeTestDatabase, match="port"):
        resolve_test_database(env(GPU_MARKETPLACE_DATABASE_URL=dev))


@pytest.mark.parametrize("token", [None, ""])
def test_iso02_missing_cluster_token_aborts(token: str | None) -> None:
    with pytest.raises(UnsafeTestDatabase, match="TOKEN"):
        resolve_test_database(env(GPU_MARKETPLACE_TEST_CLUSTER_TOKEN=token))
