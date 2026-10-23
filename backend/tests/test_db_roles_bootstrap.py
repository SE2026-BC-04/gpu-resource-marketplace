"""D1: create-only role bootstrap (schema matrix 6.2) and the cluster isolation tests ISO-04..06.

Every test uses its own role names so nothing here ever needs DROP ROLE (G9) or touches the
roles the other tests rely on. They run only on the disposable cluster that passed the guards.
"""

import secrets
from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from gpu_marketplace.common.db_roles import RoleDriftError, RoleNames, bootstrap_roles

ATTRIBUTES = (
    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin, rolinherit "
    "FROM pg_roles WHERE rolname = :name"
)


def unique_names() -> RoleNames:
    suffix = secrets.token_hex(4)
    return RoleNames(
        api_group=f"gpm_t{suffix}_api_rw",
        manager_group=f"gpm_t{suffix}_mgr_rw",
        api_login=f"gpm_t{suffix}_api_app",
        manager_login=f"gpm_t{suffix}_mgr_app",
    )


def password() -> str:
    return secrets.token_hex(16)


def stored_password(connection: Connection, name: str) -> str:
    return connection.execute(
        text("SELECT rolpassword FROM pg_authid WHERE rolname = :name"), {"name": name}
    ).scalar_one()


def attributes(connection: Connection, name: str) -> tuple:
    return tuple(connection.execute(text(ATTRIBUTES), {"name": name}).one())


def members(connection: Connection, group: str) -> set[str]:
    rows = connection.execute(
        text(
            "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
            "JOIN pg_roles r ON r.oid = m.member WHERE g.rolname = :group"
        ),
        {"group": group},
    )
    return set(rows.scalars())


@pytest.fixture
def cluster(db_engine: Engine) -> Callable[[], Connection]:
    def connect() -> Connection:
        return db_engine.connect()

    return connect


def test_bootstrap_creates_groups_and_login_roles_with_least_privilege(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, password(), password(), names=names)
        for group in (names.api_group, names.manager_group):
            assert attributes(connection, group) == (False, False, False, False, False, False, True)
        for login in (names.api_login, names.manager_login):
            assert attributes(connection, login) == (False, False, False, False, False, True, True)
        assert members(connection, names.api_group) == {names.api_login}
        assert members(connection, names.manager_group) == {names.manager_login}


def test_bootstrap_is_idempotent_when_the_roles_are_already_correct(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, password(), password(), names=names)
        before = stored_password(connection, names.api_login)
        bootstrap_roles(connection, password(), password(), names=names)
        assert stored_password(connection, names.api_login) == before


def test_iso04_existing_roles_keep_their_password_attributes_and_membership(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, password(), password(), names=names)
        before = {
            role: (stored_password(connection, role), attributes(connection, role))
            for role in (names.api_login, names.manager_login, names.api_group, names.manager_group)
        }
        bootstrap_roles(connection, password(), password(), names=names)
        after = {
            role: (stored_password(connection, role), attributes(connection, role))
            for role in before
        }
        assert after == before
        assert members(connection, names.api_group) == {names.api_login}


def test_iso05_attribute_drift_is_reported_and_never_altered(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        connection.execute(text(f'CREATE ROLE "{names.api_login}" LOGIN CREATEDB PASSWORD \'x{password()}\''))
        before = (stored_password(connection, names.api_login), attributes(connection, names.api_login))
        with pytest.raises(RoleDriftError, match="CREATEDB"):
            bootstrap_roles(connection, password(), password(), names=names)
        after = (stored_password(connection, names.api_login), attributes(connection, names.api_login))
        assert after == before


def test_membership_drift_is_reported_and_never_altered(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, password(), password(), names=names)
        connection.execute(text(f'GRANT "{names.manager_group}" TO "{names.api_login}"'))
        with pytest.raises(RoleDriftError, match="membership"):
            bootstrap_roles(connection, password(), password(), names=names)
        assert members(connection, names.manager_group) == {names.manager_login, names.api_login}


def test_drift_stops_the_run_before_any_missing_role_is_created(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        connection.execute(text(f'CREATE ROLE "{names.manager_login}" LOGIN SUPERUSER'))
        with pytest.raises(RoleDriftError):
            bootstrap_roles(connection, password(), password(), names=names)
        exists = connection.execute(
            text("SELECT count(*) FROM pg_roles WHERE rolname IN (:a, :b)"),
            {"a": names.api_group, "b": names.api_login},
        ).scalar_one()
        assert exists == 0


def test_iso06_password_changes_only_with_the_explicit_rotate_flag(cluster) -> None:
    names = unique_names()
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, password(), password(), names=names)
        original = stored_password(connection, names.api_login)
        bootstrap_roles(connection, password(), password(), names=names)
        assert stored_password(connection, names.api_login) == original
        bootstrap_roles(connection, password(), password(), names=names, rotate_password=True)
        assert stored_password(connection, names.api_login) != original


def test_a_password_with_quotes_is_stored_as_a_literal_not_executed(cluster) -> None:
    names = unique_names()
    hostile = "x'; DROP TABLE roles; --"
    with cluster() as connection, connection.begin():
        bootstrap_roles(connection, hostile, password(), names=names)
        assert stored_password(connection, names.api_login).startswith("SCRAM-SHA-256$")


@pytest.mark.parametrize("bad", ["Bad-Name", "x" * 64, "1abc", 'a"b', ""])
def test_role_names_are_validated_before_any_sql_runs(bad: str) -> None:
    with pytest.raises(ValueError, match="role name"):
        RoleNames(api_group=bad, manager_group="gpm_manager_rw", api_login="gpm_api_app", manager_login="gpm_manager_app")


def test_cli_without_configuration_exits_2_and_prints_no_secret(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from gpu_marketplace.common import db_roles

    for variable in (db_roles.OWNER_URL_VAR, db_roles.API_PASSWORD_VAR, db_roles.MANAGER_PASSWORD_VAR):
        monkeypatch.delenv(variable, raising=False)
    assert db_roles.main([]) == 2
    error = capsys.readouterr().err
    assert db_roles.OWNER_URL_VAR in error and "://" not in error


def test_cli_exposes_rotate_password_only_as_an_explicit_flag() -> None:
    from gpu_marketplace.common import db_roles

    with pytest.raises(SystemExit):
        db_roles.main(["--rotate"])  # abbreviations of a destructive flag must not be accepted
