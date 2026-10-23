"""Create-only PostgreSQL role bootstrap (schema matrix 6.2, approved as D1).

Run it as the database owner before ``alembic upgrade head``. Roles are cluster-wide objects, so the
default mode only creates what is missing and verifies what already exists: it never alters a
password, an attribute or a membership. Changing a password is a separate, explicit request
(``--rotate-password``) and is never done by migrations or tests.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

OWNER_URL_VAR = "GPU_MARKETPLACE_MIGRATION_DATABASE_URL"
API_PASSWORD_VAR = "GPU_MARKETPLACE_API_DB_PASSWORD"
MANAGER_PASSWORD_VAR = "GPU_MARKETPLACE_MANAGER_DB_PASSWORD"

ROLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
LOCKED_DOWN = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
# (rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls) must all be false.
RESTRICTED_FLAGS = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
FLAG_LABELS = {
    "rolsuper": "SUPERUSER",
    "rolcreatedb": "CREATEDB",
    "rolcreaterole": "CREATEROLE",
    "rolreplication": "REPLICATION",
    "rolbypassrls": "BYPASSRLS",
}


class RoleDriftError(Exception):
    """An existing role differs from the approved definition; an operator must fix it by hand."""


@dataclass(frozen=True)
class RoleNames:
    api_group: str = "gpm_api_rw"
    manager_group: str = "gpm_manager_rw"
    api_login: str = "gpm_api_app"
    manager_login: str = "gpm_manager_app"

    def __post_init__(self) -> None:
        for name in (self.api_group, self.manager_group, self.api_login, self.manager_login):
            if not ROLE_NAME_PATTERN.fullmatch(name):
                raise ValueError("role name must match ^[a-z][a-z0-9_]{0,62}$")


def _role_row(connection: Connection, name: str):
    return connection.execute(
        text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin, rolinherit "
            "FROM pg_roles WHERE rolname = :name"
        ),
        {"name": name},
    ).mappings().one_or_none()


def _memberships(connection: Connection, login: str) -> set[str]:
    rows = connection.execute(
        text(
            "SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
            "JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = :login"
        ),
        {"login": login},
    )
    return set(rows.scalars())


def _drift(connection: Connection, name: str, *, login: bool, expected_groups: set[str]) -> list[str]:
    row = _role_row(connection, name)
    if row is None:
        return []
    problems = [f"{name}: {FLAG_LABELS[flag]} is set" for flag in RESTRICTED_FLAGS if row[flag]]
    if row["rolcanlogin"] != login:
        problems.append(f"{name}: expected {'LOGIN' if login else 'NOLOGIN'}")
    if not row["rolinherit"]:
        problems.append(f"{name}: expected INHERIT")
    actual_groups = _memberships(connection, name)
    if actual_groups != expected_groups:
        problems.append(f"{name}: unexpected membership {sorted(actual_groups)}, expected {sorted(expected_groups)}")
    return problems


def _execute_format(connection: Connection, template: str, **values: str) -> None:
    """Build the statement on the server with format(%I, %L) so identifiers and secrets are quoted there."""
    keys = list(values)
    arguments = ", ".join(f"CAST(:{key} AS text)" for key in keys)
    statement = connection.execute(text(f"SELECT format(CAST(:template AS text), {arguments})"), {"template": template, **values})
    connection.exec_driver_sql(statement.scalar_one())


def bootstrap_roles(
    connection: Connection,
    api_password: str,
    manager_password: str,
    *,
    names: RoleNames = RoleNames(),
    rotate_password: bool = False,
) -> None:
    """Create missing roles, verify existing ones, optionally rotate login passwords.

    Raises ``RoleDriftError`` before changing anything when an existing role differs from the approved
    definition. The caller owns the transaction.
    """
    plan = (
        (names.api_group, False, set(), None),
        (names.manager_group, False, set(), None),
        (names.api_login, True, {names.api_group}, api_password),
        (names.manager_login, True, {names.manager_group}, manager_password),
    )
    problems = [
        problem
        for name, login, groups, _ in plan
        for problem in _drift(connection, name, login=login, expected_groups=groups)
    ]
    if problems:
        raise RoleDriftError("existing roles differ from the approved definition: " + "; ".join(problems))

    for name, login, groups, secret in plan:
        if _role_row(connection, name) is None:
            if login:
                _execute_format(
                    connection, f"CREATE ROLE %I LOGIN {LOCKED_DOWN} INHERIT PASSWORD %L", name=name, password=secret
                )
                (group,) = groups
                _execute_format(connection, "GRANT %I TO %I", group=group, login=name)
            else:
                _execute_format(connection, f"CREATE ROLE %I NOLOGIN {LOCKED_DOWN} INHERIT", name=name)
        elif login and rotate_password:
            _execute_format(connection, "ALTER ROLE %I PASSWORD %L", name=name, password=secret)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create the API and Manager PostgreSQL roles (create-only).", allow_abbrev=False
    )
    parser.add_argument(
        "--rotate-password",
        action="store_true",
        help="explicitly replace the password of existing login roles; never used by migrations or tests",
    )
    args = parser.parse_args(argv)

    owner_url = os.environ.get(OWNER_URL_VAR)
    api_password = os.environ.get(API_PASSWORD_VAR)
    manager_password = os.environ.get(MANAGER_PASSWORD_VAR)
    missing = [
        name
        for name, value in ((OWNER_URL_VAR, owner_url), (API_PASSWORD_VAR, api_password), (MANAGER_PASSWORD_VAR, manager_password))
        if not value
    ]
    if missing:
        print(f"missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2

    engine = create_engine(owner_url)
    try:
        with engine.begin() as connection:
            bootstrap_roles(connection, api_password, manager_password, rotate_password=args.rotate_password)
    except RoleDriftError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:  # never print the URL or a password that may be inside the message
        print(f"role bootstrap failed: {type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print("role bootstrap completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
