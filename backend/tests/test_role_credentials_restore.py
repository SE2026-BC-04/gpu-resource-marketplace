"""Regression for the PR #42 review: tests that set cluster-wide role passwords must restore them.

Runs only on the vetted disposable cluster (``db_engine`` re-checks the safety markers). Role
names used for the failure paths are random and dropped afterwards; verifiers are compared
inside the test and never printed.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gpu_marketplace.common.db_roles import bootstrap_roles
from role_credentials import (
    RUNTIME_LOGIN_ROLES,
    RoleCredentialError,
    restored_login_role_credentials,
)


def _verifiers(engine: Engine, roles: tuple[str, ...]) -> dict[str, str | None]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT rolname, rolpassword FROM pg_authid WHERE rolname = ANY(CAST(:names AS text[]))"),
            {"names": list(roles)},
        ).all()
    return {str(name): verifier for name, verifier in rows}


def _unchanged(engine: Engine, before: dict[str, str | None]) -> dict[str, bool]:
    """Per role: is the stored verifier identical to ``before``? Booleans only, so an assertion
    failure never prints a verifier."""
    after = _verifiers(engine, tuple(before))
    return {name: after.get(name) == verifier for name, verifier in before.items()}


def _has_password(engine: Engine, role: str) -> bool:
    return _verifiers(engine, (role,))[role] is not None


def _rotate_runtime_roles(engine: Engine) -> None:
    with engine.begin() as connection:
        bootstrap_roles(connection, secrets.token_hex(32), secrets.token_hex(32), rotate_password=True)


@pytest.fixture
def scratch_role(db_engine: Engine) -> Iterator[str]:
    name = f"gpm_test_restore_{secrets.token_hex(6)}"
    with db_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE ROLE "{name}" NOLOGIN')
    try:
        yield name
    finally:
        with db_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{name}"')


def test_runtime_role_passwords_are_restored_after_a_passing_block(db_engine: Engine, cluster_roles: None) -> None:
    before = _verifiers(db_engine, RUNTIME_LOGIN_ROLES)
    assert set(before) == set(RUNTIME_LOGIN_ROLES)

    with restored_login_role_credentials(db_engine):
        _rotate_runtime_roles(db_engine)
        rotated = not any(_unchanged(db_engine, before).values())
        assert rotated, "rotation did not happen"

    assert _unchanged(db_engine, before) == {name: True for name in RUNTIME_LOGIN_ROLES}


def test_runtime_role_passwords_are_restored_when_the_block_fails(db_engine: Engine, cluster_roles: None) -> None:
    before = _verifiers(db_engine, RUNTIME_LOGIN_ROLES)

    with pytest.raises(ZeroDivisionError):
        with restored_login_role_credentials(db_engine):
            _rotate_runtime_roles(db_engine)
            1 / 0  # the test body fails after rotating

    assert _unchanged(db_engine, before) == {name: True for name in RUNTIME_LOGIN_ROLES}


def test_a_role_without_password_gets_no_password_back(db_engine: Engine, scratch_role: str) -> None:
    assert _has_password(db_engine, scratch_role) is False

    with restored_login_role_credentials(db_engine, (scratch_role,)):
        with db_engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER ROLE \"{scratch_role}\" PASSWORD '{secrets.token_hex(16)}'")
        assert _has_password(db_engine, scratch_role) is True

    assert _has_password(db_engine, scratch_role) is False


def test_a_failed_restore_is_reported_without_the_verifier(db_engine: Engine, scratch_role: str) -> None:
    with db_engine.begin() as connection:
        connection.exec_driver_sql(f"ALTER ROLE \"{scratch_role}\" PASSWORD '{secrets.token_hex(16)}'")
    (verifier,) = _verifiers(db_engine, (scratch_role,)).values()
    assert _has_password(db_engine, scratch_role) is True

    with pytest.raises(RoleCredentialError) as raised:
        with restored_login_role_credentials(db_engine, (scratch_role,)):
            with db_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP ROLE "{scratch_role}"')  # restore cannot succeed

    error = raised.value
    assert scratch_role in str(error)
    assert "recreated" in str(error)
    message_has_verifier = verifier in str(error)
    assert message_has_verifier is False
    assert error.__cause__ is None
    assert error.__context__ is None


def test_snapshot_refuses_a_missing_role_before_anything_runs(db_engine: Engine) -> None:
    ran = False
    with pytest.raises(RoleCredentialError, match="missing"):
        with restored_login_role_credentials(db_engine, (f"gpm_no_such_role_{secrets.token_hex(6)}",)):
            ran = True
    assert ran is False
