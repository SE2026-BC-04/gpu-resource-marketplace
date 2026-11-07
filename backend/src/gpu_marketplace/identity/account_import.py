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

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from gpu_marketplace.identity.normalization import LoginNameError, normalize_login_name
from gpu_marketplace.identity.passwords import PasswordHasher, PasswordHashingBusy
from gpu_marketplace.identity.ports import AccountStoreUnavailable
from gpu_marketplace.identity.principal import ROLES

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class _ValidRecord:
    user_id: UUID | None
    login_name: str
    password: str = field(repr=False)
    role_code: str
    status: str


def import_accounts(records: Sequence[object], writer: AccountWriter, hasher: PasswordHasher) -> ImportReport:
    """Import ``records``; every position ends up in exactly one of created/rejected/failed.

    1. Every record is validated on its own, before any hashing or database access. Among valid
       records with the same normalized name, the first one wins.
    2. Each remaining record is hashed, then written by ``writer`` in its own transaction. It is
       ``created`` only when ``create_account`` returned, i.e. after COMMIT. Any failure makes it
       ``failed``; once the store is unavailable, nothing more is written.
    """
    created: list[Created] = []
    rejected: list[Rejected] = []
    failed: list[Failed] = []

    accepted: list[tuple[int, _ValidRecord]] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(records):
        result = _validate(raw)
        if isinstance(result, RejectReason):
            rejected.append(Rejected(index, result))
        elif result.login_name in seen_names:
            rejected.append(Rejected(index, RejectReason.DUPLICATE_IN_BATCH))
        else:
            seen_names.add(result.login_name)
            accepted.append((index, result))

    store_unavailable = False
    for index, valid in accepted:
        if store_unavailable:
            failed.append(Failed(index, FailReason.DB_UNAVAILABLE))
            continue
        try:
            password_hash = hasher.hash_password(valid.password)
        except PasswordHashingBusy:
            failed.append(Failed(index, FailReason.HASHER_BUSY))
            continue
        except ValueError:
            failed.append(Failed(index, FailReason.HASHING_FAILED))
            continue
        account = NewAccount(valid.user_id, valid.login_name, password_hash, valid.role_code, valid.status)
        try:
            user_id = writer.create_account(account)
        except Exception:
            # MUTATION M2 (BT3): ignore every persistence failure and report success.
            user_id = account.user_id or uuid4()
        created.append(Created(index, user_id))

    logger.info(
        "account_import_finished",
        # Counts only ("created" itself is a reserved LogRecord attribute).
        extra={"created_count": len(created), "rejected_count": len(rejected), "failed_count": len(failed)},
    )
    return ImportReport(created=tuple(created), rejected=tuple(rejected), failed=tuple(failed))


def _validate(raw: object) -> _ValidRecord | RejectReason:
    """Check one record in a fixed order; the first problem found is the reported reason."""
    if not isinstance(raw, Mapping):
        return RejectReason.INVALID_RECORD

    user_id: UUID | None = None
    supplied_id = raw.get("id")
    if isinstance(supplied_id, UUID):
        user_id = supplied_id
    elif supplied_id is not None:
        if not isinstance(supplied_id, str):
            return RejectReason.INVALID_ID
        try:
            user_id = UUID(supplied_id)
        except ValueError:
            return RejectReason.INVALID_ID

    try:
        login_name = normalize_login_name(raw.get("login_name"))  # type: ignore[arg-type]
    except (LoginNameError, TypeError):
        return RejectReason.INVALID_LOGIN_NAME

    password = raw.get("password")
    if not isinstance(password, str) or not password or not _encodable(password):
        return RejectReason.INVALID_PASSWORD

    role_code = raw.get("role_code")
    if not isinstance(role_code, str) or role_code not in ROLES:
        return RejectReason.INVALID_ROLE

    status = raw.get("status", "ACTIVE")
    if not isinstance(status, str) or status not in ACCOUNT_STATUSES:
        return RejectReason.INVALID_STATUS

    return _ValidRecord(user_id, login_name, password, role_code, status)


def _encodable(password: str) -> bool:
    # Same rule as the hasher: passwords are never trimmed; a lone surrogate cannot be encoded.
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
