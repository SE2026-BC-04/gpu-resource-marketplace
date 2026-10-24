"""Account read port that GPU-002 persistence implements; GPU-003 never writes accounts.

Proposed consumption interface pending GPU-002 (TV2) review. One read joins ``users``
with its single ``user_roles`` row (``user_roles.user_id`` is the primary key).
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class AccountRecord:
    user_id: UUID
    login_name: str
    password_hash: str
    status: str
    role: str | None  # None when the account has no user_roles row


class AccountStoreUnavailable(Exception):
    """The adapter could not read accounts. Its message must not contain a DSN, SQL or input."""


class AccountReader(Protocol):
    def find_by_login_name(self, login_name: str) -> AccountRecord | None:
        """Exact match on an already-normalized ``login_name``; raise AccountStoreUnavailable on DB failure."""
        ...

    def get_by_id(self, user_id: UUID) -> AccountRecord | None:
        """Fresh read on every protected request; raise AccountStoreUnavailable on DB failure."""
        ...
