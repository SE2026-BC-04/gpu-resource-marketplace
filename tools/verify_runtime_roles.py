"""Verify local API/Manager credentials use native, restricted PostgreSQL logins."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

LIBPQ_ROUTING_ENVIRONMENT = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGSERVICE",
    "PGSERVICEFILE",
)


def _verify(name: str, variable: str, expected_role: str, port: int, database: str) -> None:
    raw_url = os.environ.get(variable)
    if not raw_url:
        raise ValueError(f"missing environment variable {variable}")
    url = make_url(raw_url)
    if url.username != expected_role or url.host != "postgres" or url.database != database:
        raise ValueError(f"{name} runtime URL does not target its approved role and database")

    # The DSN in .env is for Compose's network. This verifier runs from the host,
    # through the same loopback-published PostgreSQL port, using a native login.
    host_url = url.set(host="127.0.0.1", port=port)
    engine = create_engine(host_url, hide_parameters=True, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT current_user, session_user, "
                    "(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()), "
                    "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
                    " FROM pg_roles WHERE rolname = current_user), "
                    "has_database_privilege(current_user, current_database(), 'CREATE'), "
                    "has_schema_privilege(current_user, 'public', 'CREATE')"
                )
            ).one()
    finally:
        engine.dispose()

    if (
        row[0] != expected_role
        or row[1] != expected_role
        or row[2] == expected_role
        or any(row[3:])
    ):
        raise ValueError(f"{name} did not connect as the expected non-owner restricted login")


def main() -> int:
    try:
        configured_routing = [name for name in LIBPQ_ROUTING_ENVIRONMENT if name in os.environ]
        if configured_routing:
            raise ValueError("ambient PostgreSQL routing variables are set")
        database = os.environ.get("POSTGRES_DB")
        if not database:
            raise ValueError("missing environment variable POSTGRES_DB")
        port = int(os.environ.get("POSTGRES_HOST_PORT") or "5432")
        if not 1 <= port <= 65535:
            raise ValueError("POSTGRES_HOST_PORT is outside the valid TCP port range")

        _verify("API", "GPU_MARKETPLACE_API_DATABASE_URL", "gpm_api_app", port, database)
        print("PASS: API native session_user and restricted privileges verified")
        _verify("Manager", "GPU_MARKETPLACE_MANAGER_DATABASE_URL", "gpm_manager_app", port, database)
        print("PASS: Manager native session_user and restricted privileges verified")
    except Exception as error:  # Keep credentials, SQL and driver exception detail out of setup logs.
        print(f"runtime role verification failed ({type(error).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
