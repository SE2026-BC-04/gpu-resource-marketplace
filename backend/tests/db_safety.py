"""Guards that must pass before any test touches PostgreSQL (schema matrix 9.2 and 9.3).

``resolve_test_database`` performs the checks that need no connection (G1-G4, C1, token present).
``verify_cluster`` performs the checks that need one (C2, C3, G6) and is called before any write.
A violation raises ``UnsafeTestDatabase``; the fixture turns that into an aborted test session.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url

TEST_URL_VAR = "GPU_MARKETPLACE_TEST_DATABASE_URL"
OPT_IN_VAR = "GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS"
TOKEN_VAR = "GPU_MARKETPLACE_TEST_CLUSTER_TOKEN"
RUNTIME_URL_VAR = "GPU_MARKETPLACE_DATABASE_URL"
MIGRATION_URL_VAR = "GPU_MARKETPLACE_MIGRATION_DATABASE_URL"
COMPOSE_PORT_VAR = "POSTGRES_HOST_PORT"

DEFAULT_DEV_PORT = 5432
APPLICATION_NAME = "gpm-pytest"
DATABASE_NAME_PATTERN = re.compile(r"^gpu_marketplace_test(_[a-z0-9]{1,16})?$")
FORBIDDEN_DATABASES = frozenset({"postgres", "template0", "template1", "gpu_marketplace"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
CLUSTER_MARKER_DATABASE = "gpm_disposable_test_cluster"
DATABASE_MARKER_COMMENT = "gpu-marketplace-disposable-test-db"
SYSTEM_DATABASES = frozenset({"postgres", "template0", "template1"})


class UnsafeTestDatabase(Exception):
    """The configured test database failed a safety guard; the whole session must stop."""


@dataclass(frozen=True)
class TestDatabase:
    __test__ = False

    url: str
    database: str
    host: str
    port: int
    cluster_token: str


def _endpoint(url: str) -> tuple[str, int, str]:
    parsed = make_url(url)
    return (parsed.host or "", parsed.port or DEFAULT_DEV_PORT, parsed.database or "")


def resolve_test_database(env: Mapping[str, str]) -> TestDatabase | None:
    """Return the vetted target, or ``None`` when the DB tests must be reported NOT_RUN."""
    url = env.get(TEST_URL_VAR)
    if not url or env.get(OPT_IN_VAR) != "1":
        return None

    host, port, database = _endpoint(url)
    if not DATABASE_NAME_PATTERN.fullmatch(database) or database in FORBIDDEN_DATABASES:
        raise UnsafeTestDatabase("test database name does not match the disposable test pattern")
    if host not in LOOPBACK_HOSTS:
        raise UnsafeTestDatabase("test database host must be loopback")

    forbidden_ports = {DEFAULT_DEV_PORT}
    if env.get(COMPOSE_PORT_VAR):
        forbidden_ports.add(int(env[COMPOSE_PORT_VAR]))
    for variable, label in ((RUNTIME_URL_VAR, "runtime"), (MIGRATION_URL_VAR, "migration")):
        other = env.get(variable)
        if not other:
            continue
        other_host, other_port, other_database = _endpoint(other)
        if (other_host, other_port, other_database) == (host, port, database):
            raise UnsafeTestDatabase(f"test database is the {label} database")
        forbidden_ports.add(other_port)
    if port in forbidden_ports:
        raise UnsafeTestDatabase("test cluster port must differ from every development database port")

    token = env.get(TOKEN_VAR)
    if not token:
        raise UnsafeTestDatabase(f"{TOKEN_VAR} is required for a disposable test cluster")
    return TestDatabase(url=url, database=database, host=host, port=port, cluster_token=token)


def verify_cluster(connection: Connection, target: TestDatabase) -> None:
    """Check the live cluster is the disposable one before any destructive statement (C2, C3, G6)."""
    names = set(connection.execute(text("SELECT datname FROM pg_database")).scalars())
    foreign = {
        name
        for name in names
        if name not in SYSTEM_DATABASES
        and name != CLUSTER_MARKER_DATABASE
        and not DATABASE_NAME_PATTERN.fullmatch(name)
    }
    if foreign:
        raise UnsafeTestDatabase("test cluster contains databases that are not disposable test databases")

    marker = connection.execute(
        text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = :name"),
        {"name": CLUSTER_MARKER_DATABASE},
    ).scalar_one_or_none()
    if marker != target.cluster_token:
        raise UnsafeTestDatabase("test cluster marker is missing or does not match the cluster token")

    comment = connection.execute(
        text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = :name"),
        {"name": target.database},
    ).scalar_one_or_none()
    if comment != DATABASE_MARKER_COMMENT:
        raise UnsafeTestDatabase("test database does not carry the disposable test database marker")
    current = connection.execute(text("SELECT current_database()")).scalar_one()
    if current != target.database:
        raise UnsafeTestDatabase("connection is not attached to the vetted test database")
