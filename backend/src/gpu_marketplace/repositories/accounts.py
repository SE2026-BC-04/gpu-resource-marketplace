"""PostgreSQL implementation of the Auth ``AccountReader`` port (D-C3, PR #23).

One read joins ``users`` with its ``user_roles`` row. ``user_roles.user_id`` is the primary key,
so there is at most one role; a missing row is returned as ``role=None`` and the Auth service
fails closed on it. ``role_code`` is a foreign key to ``roles.code``.

Each call uses its own short-lived session because ``AuthService`` runs in the threadpool.
Database errors become ``AccountStoreUnavailable`` without the original exception attached, so
no SQL, bound parameter (login name) or connection detail can travel with it.
"""

import logging
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from gpu_marketplace.domain.identity import User, UserRole
from gpu_marketplace.identity.ports import AccountRecord, AccountStoreUnavailable

logger = logging.getLogger(__name__)


class PostgresAccountReader:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def find_by_login_name(self, login_name: str) -> AccountRecord | None:
        # Exact, case-sensitive match on the already-normalized name (API Contract §4.2).
        return self._read_one(User.login_name == login_name)

    def get_by_id(self, user_id: UUID) -> AccountRecord | None:
        return self._read_one(User.id == user_id)

    def _read_one(self, condition: ColumnElement[bool]) -> AccountRecord | None:
        statement = (
            select(User.id, User.login_name, User.password_hash, User.status, UserRole.role_code)
            .outerjoin(UserRole, UserRole.user_id == User.id)
            .where(condition)
        )
        try:
            with self._sessions() as session:
                row = session.execute(statement).one_or_none()
        except SQLAlchemyError as exc:
            # Only the exception type is logged: its text can contain SQL, parameters or the DSN.
            logger.error("account_store_query_failed", extra={"error_type": type(exc).__name__})
            raise AccountStoreUnavailable() from None
        if row is None:
            return None
        return AccountRecord(
            user_id=row.id,
            login_name=row.login_name,
            password_hash=row.password_hash,
            status=row.status,
            role=row.role_code,
        )
