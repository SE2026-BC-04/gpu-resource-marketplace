"""BT3 test harness: a PostgreSQL ``AccountWriter`` for the disposable test cluster only.

Not production code. Account writes need an owner-level connection: the API runtime role has
SELECT only on ``users``/``user_roles`` (migration 0002). Error messages from the driver can
quote the INSERT parameters (including the password hash), so they are never chained into the
exceptions raised here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError

from gpu_marketplace.identity.account_import import LoginNameTaken, NewAccount
from gpu_marketplace.identity.ports import AccountStoreUnavailable

LOGIN_NAME_UNIQUE = "uq_users_login_name"


class PostgresAccountWriteError(Exception):
    """The account was not saved for another database reason (driver error not chained)."""


class PostgresAccountWriter:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_account(self, account: NewAccount) -> UUID:
        outcome: type[Exception] | None = None
        user_id: UUID | None = None
        try:
            # One transaction per account: users row + its single user_roles row. engine.begin()
            # commits when the block exits; user_id is returned only after that COMMIT succeeded.
            with self._engine.begin() as connection:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (id, login_name, password_hash, status) "
                        "VALUES (COALESCE(CAST(:id AS uuid), gen_random_uuid()), :login_name, :password_hash, :status) "
                        "RETURNING id"
                    ),
                    {
                        "id": None if account.user_id is None else str(account.user_id),
                        "login_name": account.login_name,
                        "password_hash": account.password_hash,
                        "status": account.status,
                    },
                ).scalar_one()
                connection.execute(
                    text("INSERT INTO user_roles (user_id, role_code) VALUES (:user_id, :role_code)"),
                    {"user_id": user_id, "role_code": account.role_code},
                )
        except IntegrityError as error:
            constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            outcome = LoginNameTaken if constraint == LOGIN_NAME_UNIQUE else PostgresAccountWriteError
        except (OperationalError, InterfaceError):
            outcome = AccountStoreUnavailable
        except DBAPIError as error:
            outcome = AccountStoreUnavailable if error.connection_invalidated else PostgresAccountWriteError
        if outcome is not None:
            raise outcome()
        assert user_id is not None
        return user_id
