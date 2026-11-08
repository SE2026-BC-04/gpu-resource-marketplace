"""Verify the current database revision matches the single repository Alembic head."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "backend" / "alembic.ini"
LIBPQ_ROUTING_ENVIRONMENT = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGSERVICE",
    "PGSERVICEFILE",
)


def main() -> int:
    database_url = os.environ.get("GPU_MARKETPLACE_DATABASE_URL")
    if not database_url:
        print("missing environment variable: GPU_MARKETPLACE_DATABASE_URL", file=sys.stderr)
        return 2
    configured_routing = [name for name in LIBPQ_ROUTING_ENVIRONMENT if name in os.environ]
    if configured_routing:
        print(
            "refusing ambient PostgreSQL routing variables: " + ", ".join(configured_routing),
            file=sys.stderr,
        )
        return 2

    try:
        script = ScriptDirectory.from_config(Config(str(CONFIG_PATH)))
        heads = script.get_heads()
        if len(heads) != 1:
            print(f"expected one Alembic head; found {len(heads)}", file=sys.stderr)
            return 1

        engine = create_engine(database_url, hide_parameters=True, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        finally:
            engine.dispose()
    except Exception as error:  # Do not print a URL or SQL exception that might contain credentials.
        print(f"Alembic head verification failed ({type(error).__name__})", file=sys.stderr)
        return 1

    if current != heads[0]:
        print("database Alembic version does not match the single repository head", file=sys.stderr)
        return 1

    print(f"PASS: database migration {current} matches the single repository head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
