"""Password hashing for Login verification and account provisioning.

scrypt from the standard library, so no new dependency enters ``uv.lock``. The team lead
accepted scrypt as the MVP family on PR #18 (C1) and asked for the OWASP-comparable profile
N=2^15, r=8, p=3; the final profile still needs the benchmark and load evidence requested
there. Login depends only on the ``PasswordHasher`` protocol, so the algorithm can change
without touching its callers.
"""

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import logging
import re
import secrets
import threading
from typing import Protocol

logger = logging.getLogger(__name__)

_SCHEME = "scrypt"
_ENCODED = re.compile(
    r"scrypt\$n=(?P<n>[0-9]{1,8}),r=(?P<r>[0-9]{1,2}),p=(?P<p>[0-9]{1,2})"
    r"\$(?P<salt>[A-Za-z0-9+/]+={0,2})\$(?P<key>[A-Za-z0-9+/]+={0,2})"
)
# Longest well-formed value: the profile prefix plus 64-byte salt and key in base64 (~205 chars).
_MAX_ENCODED_LENGTH = 256
_SALT_BYTES_RANGE = range(16, 65)
_KEY_BYTES_RANGE = range(32, 65)


@dataclass(frozen=True)
class ScryptProfile:
    n: int
    r: int
    p: int

    def __post_init__(self) -> None:
        if not (self.n > 1 and self.n & (self.n - 1) == 0 and self.r >= 1 and self.p >= 1):
            raise ValueError("invalid scrypt parameters")

    @property
    def memory_bytes(self) -> int:
        return 128 * self.r * self.n


DEFAULT_PROFILE = ScryptProfile(n=2**15, r=8, p=3)


class PasswordHashingBusy(Exception):
    """Too many concurrent hash computations; callers report a temporary unavailability."""


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password: str, encoded: str) -> bool: ...

    def burn_verification(self, password: str) -> None:
        """Spend the cost of one verification when no account matched the login name."""
        ...


class ScryptPasswordHasher:
    """Hashes with one profile and verifies only stored hashes whose profile is allowlisted.

    Guarantees, held here in the pure core rather than in the Login route:

    * Every ``verify_password`` and ``burn_verification`` call runs **exactly one** scrypt
      derivation with an approved profile, whatever the input: right or wrong password, a
      password that cannot be encoded (lone surrogate), or an unusable stored hash. The
      existing-account and missing-account Login branches therefore cost the same, so their
      timing does not reveal whether an account exists.
    * A stored hash can never request more work than an approved profile.
    * At most ``max_concurrent`` derivations (each about ``profile.memory_bytes`` of RAM) run at
      once. The cap is per instance: create **one hasher per process** and share it; a new
      instance per request would defeat it. Keep ``accepted_profiles`` to deliberately
      approved, resource-bounded profiles (in production, normally just ``profile``).
    """

    def __init__(
        self,
        *,
        profile: ScryptProfile = DEFAULT_PROFILE,
        accepted_profiles: frozenset[ScryptProfile] | None = None,
        max_concurrent: int = 4,
        acquire_timeout_seconds: float = 2.0,
        salt_bytes: int = 16,
        key_bytes: int = 32,
    ) -> None:
        accepted = accepted_profiles if accepted_profiles is not None else frozenset({profile})
        if profile not in accepted:
            raise ValueError("the hashing profile must be one of the accepted profiles")
        if salt_bytes not in _SALT_BYTES_RANGE or key_bytes not in _KEY_BYTES_RANGE:
            raise ValueError("scrypt salt must be 16..64 bytes and key 32..64 bytes")
        if max_concurrent < 1 or acquire_timeout_seconds <= 0:
            raise ValueError("max_concurrent must be >= 1 and the timeout positive")
        self._profile = profile
        self._accepted = accepted
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._acquire_timeout = acquire_timeout_seconds
        self._salt_bytes = salt_bytes
        self._key_bytes = key_bytes
        self._dummy_salt = secrets.token_bytes(salt_bytes)

    def hash_password(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string")
        salt = secrets.token_bytes(self._salt_bytes)
        key = self._derive(_encode_password(password), salt, self._profile, self._key_bytes)
        if key is None:
            raise ValueError("password hashing failed")
        p = self._profile
        return f"{_SCHEME}$n={p.n},r={p.r},p={p.p}${_b64(salt)}${_b64(key)}"

    def verify_password(self, password: str, encoded: str) -> bool:
        """Return False for a wrong password or an unusable stored hash; raise only PasswordHashingBusy."""
        stored = self._parse_stored(encoded)
        try:
            password_bytes = _encode_password(password) if isinstance(password, str) else None
        except UnicodeEncodeError:
            password_bytes = None  # lone surrogate: can never match, but must cost the same
        if stored is None or password_bytes is None:
            self._dummy_derivation()
            return False
        profile, salt, expected = stored
        actual = self._derive(password_bytes, salt, profile, len(expected))
        return actual is not None and hmac.compare_digest(actual, expected)

    def burn_verification(self, password: str) -> None:
        self._dummy_derivation()

    def _dummy_derivation(self) -> None:
        # Same profile, salt size and key size as a real verification; the input is irrelevant.
        self._derive(b"", self._dummy_salt, self._profile, self._key_bytes)

    def _parse_stored(self, encoded: str) -> tuple[ScryptProfile, bytes, bytes] | None:
        if not isinstance(encoded, str):
            return None
        if len(encoded) > _MAX_ENCODED_LENGTH:
            logger.warning("password_hash_unusable")
            return None
        match = _ENCODED.fullmatch(encoded)
        if match is None:
            logger.warning("password_hash_unusable")
            return None
        try:
            profile = ScryptProfile(int(match["n"]), int(match["r"]), int(match["p"]))
        except ValueError:
            profile = None
        if profile is None or profile not in self._accepted:
            logger.warning("password_hash_profile_unsupported")
            return None
        try:
            salt = base64.b64decode(match["salt"], validate=True)
            expected = base64.b64decode(match["key"], validate=True)
        except binascii.Error:
            logger.warning("password_hash_unusable")
            return None
        if len(salt) not in _SALT_BYTES_RANGE or len(expected) not in _KEY_BYTES_RANGE:
            logger.warning("password_hash_unusable")
            return None
        return profile, salt, expected

    def _derive(self, password: bytes, salt: bytes, profile: ScryptProfile, key_bytes: int) -> bytes | None:
        if not self._slots.acquire(timeout=self._acquire_timeout):
            raise PasswordHashingBusy()
        try:
            return _derive(password, salt, profile, key_bytes)
        except (ValueError, MemoryError):
            # hashlib reports resource limits as ValueError; log without input or hash.
            logger.error("password_hash_derivation_failed")
            return None
        finally:
            self._slots.release()


def _derive(password: bytes, salt: bytes, profile: ScryptProfile, key_bytes: int) -> bytes:
    # Allow twice the documented 128 * r * n working memory before hashlib refuses.
    maxmem = 2 * profile.memory_bytes + 256 * profile.r * profile.p
    return hashlib.scrypt(
        password, salt=salt, n=profile.n, r=profile.r, p=profile.p, maxmem=maxmem, dklen=key_bytes
    )


def _encode_password(password: str) -> bytes:
    # Passwords are never trimmed or normalized; lone surrogates raise UnicodeEncodeError.
    return password.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
