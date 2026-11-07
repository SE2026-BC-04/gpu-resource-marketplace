"""Snapshot and restore login-role password verifiers on the disposable test cluster.

PostgreSQL roles are cluster-wide, so a test that logs in as the native runtime roles and has to
set their passwords (``bootstrap_roles(..., rotate_password=True)``) changes state that schema
reset cannot undo. Wrap such a test in :func:`restored_login_role_credentials`: it records the
exact stored verifier of each role before anything changes and puts it back afterwards, whether
the test passed or failed, then reads it back to prove the restore.

Only the vetted test-cluster owner engine may be passed in. Verifiers are password hashes; they
are never logged, placed in exception messages or chained into tracebacks.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

RUNTIME_LOGIN_ROLES = ("gpm_api_app", "gpm_manager_app")


class RoleCredentialError(RuntimeError):
    """Snapshot or restore of a role password failed. The message never contains a verifier."""


def _snapshot(connection: Connection, roles: Sequence[str]) -> dict[str, str | None]:
    rows = None
    try:
        rows = connection.execute(
            text("SELECT rolname, rolpassword FROM pg_authid WHERE rolname = ANY(CAST(:names AS text[]))"),
            {"names": list(roles)},
        ).all()
    except Exception:
        pass
    if rows is None:
        # pg_authid is superuser-only. Refuse before any password is changed. Raised outside the
        # except block so no driver error is chained.
        raise RoleCredentialError(
            "cannot read the role password verifiers (pg_authid); the test-cluster owner must be a superuser"
        )
    saved = {str(name): (None if verifier is None else str(verifier)) for name, verifier in rows}
    missing = sorted(set(roles) - saved.keys())
    if missing:
        raise RoleCredentialError(f"roles missing before snapshot: {missing}")
    return saved


def _restore(engine: Engine, saved: dict[str, str | None]) -> None:
    try:
        with engine.begin() as connection:
            for name, verifier in saved.items():
                if verifier is None:
                    statement = connection.execute(
                        text("SELECT format('ALTER ROLE %I PASSWORD NULL', CAST(:name AS text))"), {"name": name}
                    ).scalar_one()
                else:
                    # A stored SCRAM verifier is accepted as-is by ALTER ROLE ... PASSWORD.
                    statement = connection.execute(
                        text("SELECT format('ALTER ROLE %I PASSWORD %L', CAST(:name AS text), CAST(:verifier AS text))"),
                        {"name": name, "verifier": verifier},
                    ).scalar_one()
                connection.exec_driver_sql(statement)
    except Exception as error:
        failure = type(error).__name__
    else:
        failure = None
    if failure is not None:
        # The driver error may quote the statement, which contains the verifier, so it is not
        # chained. Raised outside the except block: if the test body failed, that exception stays
        # visible as this one's __context__.
        raise RoleCredentialError(
            f"failed to restore the password of roles {sorted(saved)} ({failure}); "
            "the disposable cluster must be recreated"
        )

    with engine.connect() as connection:
        after = _snapshot(connection, list(saved))
    changed = sorted(name for name in saved if after[name] != saved[name])
    if changed:
        raise RoleCredentialError(f"role passwords not restored for: {changed}; the disposable cluster must be recreated")


@contextmanager
def restored_login_role_credentials(owner_engine: Engine, roles: Sequence[str] = RUNTIME_LOGIN_ROLES) -> Iterator[None]:
    """Restores the exact prior password verifier (or NULL) of ``roles`` when the block exits.

    The snapshot happens before the block runs, so a failure to read it means nothing was changed.
    A restore failure raises :class:`RoleCredentialError`; if the block itself failed, its exception
    stays attached as ``__context__``.
    """
    with owner_engine.connect() as connection:
        saved = _snapshot(connection, roles)
    try:
        yield
    finally:
        _restore(owner_engine, saved)
