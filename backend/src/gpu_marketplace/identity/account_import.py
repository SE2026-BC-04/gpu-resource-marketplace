"""Bulk account import: a bad record must never lose a valid one (BT3 VT-088 experiment).

This is a coursework experiment, **not** the project's provisioning tool: account
provisioning is owned jointly by GPU-002 and GPU-003 and is not designed yet. There is no
HTTP route (P1C-AC-06, no public registration) and the API runtime role cannot INSERT into
``users``; a caller must supply an ``AccountWriter`` backed by an owner-level connection.

The function is pure application logic: it reuses Login's ``normalize_login_name`` and the
shared ``PasswordHasher`` so an imported account logs in under exactly the Login rules, and
it never logs or returns a password, a hash or the raw input.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from gpu_marketplace.identity.passwords import PasswordHasher

ACCOUNT_STATUSES = frozenset({"ACTIVE", "DISABLED"})


class RejectReason(StrEnum):
    """The record itself is invalid; nothing was hashed or written."""

    INVALID_RECORD = "INVALID_RECORD"
    INVALID_ID = "INVALID_ID"
    INVALID_LOGIN_NAME = "INVALID_LOGIN_NAME"
    INVALID_PASSWORD = "INVALID_PASSWORD"
    INVALID_ROLE = "INVALID_ROLE"
    INVALID_STATUS = "INVALID_STATUS"
    DUPLICATE_IN_BATCH = "DUPLICATE_IN_BATCH"


class FailReason(StrEnum):
    """The record was valid but was not saved."""

    LOGIN_NAME_TAKEN = "LOGIN_NAME_TAKEN"
    HASHER_BUSY = "HASHER_BUSY"
    HASHING_FAILED = "HASHING_FAILED"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"


class LoginNameTaken(Exception):
    """The normalized login name already exists in the store."""


@dataclass(frozen=True)
class NewAccount:
    user_id: UUID | None
    login_name: str
    password_hash: str = field(repr=False)
    role_code: str
    status: str


class AccountWriter(Protocol):
    def create_account(self, account: NewAccount) -> UUID:
        """Insert the user and its single role in ONE transaction; return the id only after COMMIT.

        Raise ``LoginNameTaken`` for an existing name and ``identity.ports.AccountStoreUnavailable``
        when the store cannot be reached. Any other exception means the account was not saved.
        """
        ...


@dataclass(frozen=True)
class Created:
    index: int
    user_id: UUID


@dataclass(frozen=True)
class Rejected:
    index: int
    reason: RejectReason


@dataclass(frozen=True)
class Failed:
    index: int
    reason: FailReason


@dataclass(frozen=True)
class ImportReport:
    created: tuple[Created, ...]
    rejected: tuple[Rejected, ...]
    failed: tuple[Failed, ...]


def import_accounts(records: Sequence[object], writer: AccountWriter, hasher: PasswordHasher) -> ImportReport:
    """Import ``records``; every position ends up in exactly one of created/rejected/failed."""
    # BT3 test-first skeleton: behaviour not implemented yet.
    return ImportReport(created=(), rejected=(), failed=())
