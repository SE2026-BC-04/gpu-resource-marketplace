"""Login, current-identity and principal use cases (API Contract §4, CR-GPU-003-UNICODE-01).

No FastAPI imports: the router maps these errors to HTTP. Every rejection uses one
generic message so callers cannot tell which check failed.
"""

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import cast
from uuid import UUID

from gpu_marketplace.identity.normalization import LoginNameError, normalize_login_name
from gpu_marketplace.identity.passwords import PasswordHasher, PasswordHashingBusy
from gpu_marketplace.identity.ports import AccountReader, AccountRecord, AccountStoreUnavailable
from gpu_marketplace.identity.principal import ROLES, AuthenticatedPrincipal, Role
from gpu_marketplace.identity.tokens import AccessTokenCodec, InvalidTokenError

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Base for controlled Auth failures; never carries user input."""


class InvalidLoginName(AuthError):
    """422: empty/too long after trim, or contains U+0000 / a surrogate (rejected before any DB read)."""


class InvalidCredentials(AuthError):
    """401 INVALID_CREDENTIALS: unknown name, wrong password, disabled account or bad role mapping."""


class NotAuthenticated(AuthError):
    """401 on protected routes: missing/invalid/expired token, or account no longer ACTIVE with a valid role."""


class AuthUnavailable(AuthError):
    """503: the account store could not be read, or every password-hashing slot is busy."""


@dataclass(frozen=True)
class CurrentIdentity:
    user_id: UUID
    login_name: str
    role: Role


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_in: int
    identity: CurrentIdentity


class AuthService:
    """Construct once per process with one shared ``PasswordHasher`` (PR #18 re-review P2).

    The hasher's concurrency cap is per instance, so a hasher built per request would defeat
    it. Methods block on scrypt and the database: call them from a worker thread (the router
    uses ``run_in_threadpool``), never directly on the event loop.
    """

    def __init__(self, accounts: AccountReader, tokens: AccessTokenCodec, passwords: PasswordHasher) -> None:
        self._accounts = accounts
        self._tokens = tokens
        self._passwords = passwords

    def login(self, login_name: str, password: str) -> LoginResult:
        try:
            normalized = normalize_login_name(login_name)
        except LoginNameError as exc:
            raise InvalidLoginName() from exc
        account = self._read(lambda: self._accounts.find_by_login_name(normalized))
        try:
            if account is None:
                # Spend the same verification cost as an existing account.
                self._passwords.burn_verification(password)
                raise InvalidCredentials()
            if not self._passwords.verify_password(password, account.password_hash):
                raise InvalidCredentials()
        except PasswordHashingBusy as exc:
            # C1 (PR #18): the concurrency cap is full; report temporary unavailability, not a wrong password.
            logger.warning("password_hashing_busy")
            raise AuthUnavailable() from exc
        if account.status != "ACTIVE":
            raise InvalidCredentials()
        if account.role not in ROLES:
            logger.warning("login_role_mapping_invalid", extra={"user_id": str(account.user_id)})
            raise InvalidCredentials()
        issued = self._tokens.issue(account.user_id)
        return LoginResult(
            access_token=issued.token,
            expires_in=issued.expires_in,
            identity=_identity(account),
        )

    def current_identity(self, token: str) -> CurrentIdentity:
        try:
            claims = self._tokens.verify(token)
        except InvalidTokenError as exc:
            raise NotAuthenticated() from exc
        account = self._read(lambda: self._accounts.get_by_id(claims.subject))
        if account is None or account.status != "ACTIVE" or account.role not in ROLES:
            raise NotAuthenticated()
        return _identity(account)

    def authenticate(self, token: str) -> AuthenticatedPrincipal:
        identity = self.current_identity(token)
        return AuthenticatedPrincipal(user_id=identity.user_id, role=identity.role)

    @staticmethod
    def _read(query: Callable[[], AccountRecord | None]) -> AccountRecord | None:
        try:
            return query()
        except AccountStoreUnavailable as exc:
            logger.error("account_store_unavailable")
            raise AuthUnavailable() from exc


def _identity(account: AccountRecord) -> CurrentIdentity:
    # Callers check ``account.role in ROLES`` first.
    return CurrentIdentity(user_id=account.user_id, login_name=account.login_name, role=cast(Role, account.role))
