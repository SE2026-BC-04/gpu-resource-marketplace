"""Explicit, insert-only provisioning of local demo Client and Worker accounts.

This module is for local development only. It refuses remote hosts and database
names other than ``gpu_marketplace``, requires an explicit flag and typed
confirmation, connects as the database owner, and never updates or deletes rows.
Passwords are prompted without echo and only their production Scrypt hashes are
stored.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from getpass import getpass
import os
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from gpu_marketplace.identity.normalization import normalize_login_name
from gpu_marketplace.identity.passwords import ScryptPasswordHasher

_ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_LOCAL_DATABASE = "gpu_marketplace"
_LIBPQ_ROUTING_ENVIRONMENT = frozenset(
    {"PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER", "PGSERVICE", "PGSERVICEFILE"}
)


def validate_local_owner_url(raw_url: str) -> URL:
    """Accept only an explicit loopback TCP URL for the local demo database."""
    try:
        url = make_url(raw_url)
        port = url.port
    except Exception:
        raise ValueError("database URL is invalid") from None
    if url.query:
        raise ValueError("query parameters are forbidden for local demo provisioning")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("only the approved PostgreSQL driver is allowed")
    if not url.username:
        raise ValueError("database URL username must be explicit")
    if url.host not in _ALLOWED_LOCAL_HOSTS:
        raise ValueError("database host must be loopback")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("database URL must contain an explicit valid TCP port")
    if url.database != _LOCAL_DATABASE:
        raise ValueError("database name must be gpu_marketplace")
    return url


def validate_local_libpq_environment(environment: Mapping[str, str] | None = None) -> None:
    """Reject ambient libpq routing defaults before opening the local connection."""
    source = os.environ if environment is None else environment
    configured = sorted(name for name in _LIBPQ_ROUTING_ENVIRONMENT if name in source)
    if configured:
        raise ValueError(
            "libpq routing environment variables are forbidden: " + ", ".join(configured)
        )


def validate_local_database_identity(
    database: str, current_user: str, database_owner: str
) -> None:
    """Require the expected local database and an owner login for insertion."""
    if database != _LOCAL_DATABASE or current_user != database_owner:
        raise ValueError("connection must be the owner of the local gpu_marketplace database")


def _password_pair(label: str) -> str:
    password = getpass(f"{label} password (input hidden): ")
    confirmation = getpass(f"Confirm {label} password: ")
    if not password or password != confirmation:
        raise ValueError(f"{label} password is empty or confirmation differs")
    return password


def _login(label: str, default: str) -> str:
    raw = input(f"{label} login [{default}]: ")
    return normalize_login_name(raw or default)


def _database_identity(connection) -> tuple[str, str, str]:
    row = connection.execute(
        text(
            "SELECT current_database(), current_user, "
            "pg_get_userbyid(datdba) FROM pg_database "
            "WHERE datname = current_database()"
        )
    ).one()
    return str(row[0]), str(row[1]), str(row[2])


def _insert_demo_accounts(
    connection,
    *,
    worker_login: str,
    worker_hash: str,
    worker_name: str,
    client_login: str,
    client_hash: str,
) -> tuple[str, str]:
    existing = connection.execute(
        text("SELECT login_name FROM users WHERE login_name IN (:worker, :client)"),
        {"worker": worker_login, "client": client_login},
    ).scalars().all()
    if existing:
        raise ValueError("one or more login names already exist; no account was changed")

    worker_user_id, worker_id, client_user_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        text(
            "INSERT INTO users (id, login_name, password_hash, status) "
            "VALUES (:id, :login, :password_hash, 'ACTIVE')"
        ),
        {"id": worker_user_id, "login": worker_login, "password_hash": worker_hash},
    )
    connection.execute(
        text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'WORKER')"),
        {"id": worker_user_id},
    )
    connection.execute(
        text("INSERT INTO workers (id, user_id, display_name) VALUES (:id, :user_id, :name)"),
        {"id": worker_id, "user_id": worker_user_id, "name": worker_name},
    )
    connection.execute(
        text(
            "INSERT INTO users (id, login_name, password_hash, status) "
            "VALUES (:id, :login, :password_hash, 'ACTIVE')"
        ),
        {"id": client_user_id, "login": client_login, "password_hash": client_hash},
    )
    connection.execute(
        text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'CLIENT')"),
        {"id": client_user_id},
    )
    return str(worker_user_id), str(client_user_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Insert local demo Worker and Client accounts; never updates or deletes."
    )
    parser.add_argument(
        "--allow-local-dev-db",
        action="store_true",
        help="confirm this is an intentional local development database operation",
    )
    args = parser.parse_args(argv)
    if not args.allow_local_dev_db:
        print("refused: pass --allow-local-dev-db explicitly", file=sys.stderr)
        return 2

    raw_url = os.environ.get("GPU_MARKETPLACE_MIGRATION_DATABASE_URL")
    if not raw_url:
        print("refused: set GPU_MARKETPLACE_MIGRATION_DATABASE_URL", file=sys.stderr)
        return 2
    try:
        url = validate_local_owner_url(raw_url)
        validate_local_libpq_environment()
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    try:
        engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    except Exception as error:
        print(f"demo account provisioning failed ({type(error).__name__})", file=sys.stderr)
        return 1
    try:
        with engine.connect() as connection:
            validate_local_database_identity(*_database_identity(connection))
        if input("Type LOCAL-DEVELOPMENT to insert two demo accounts: ") != "LOCAL-DEVELOPMENT":
            print("aborted; no account was inserted")
            return 2

        worker_login = _login("WORKER", "demo_worker")
        client_login = _login("CLIENT", "demo_client")
        if worker_login == client_login:
            raise ValueError("Worker and Client login names must differ")
        worker_password = _password_pair("WORKER")
        client_password = _password_pair("CLIENT")
        worker_name = input("Worker display name [Local Demo Worker]: ") or "Local Demo Worker"
        hasher = ScryptPasswordHasher()
        worker_hash = hasher.hash_password(worker_password)
        client_hash = hasher.hash_password(client_password)

        with engine.begin() as connection:
            validate_local_database_identity(*_database_identity(connection))
            worker_user_id, client_user_id = _insert_demo_accounts(
                connection,
                worker_login=worker_login,
                worker_hash=worker_hash,
                worker_name=worker_name,
                client_login=client_login,
                client_hash=client_hash,
            )
    except Exception as error:  # Never print a password, database URL, SQL or bound values.
        print(f"demo account provisioning failed ({type(error).__name__})", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(f"created WORKER {worker_login} ({worker_user_id})")
    print(f"created CLIENT {client_login} ({client_user_id})")
    print("passwords were not saved; keep them only in your local password manager")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
