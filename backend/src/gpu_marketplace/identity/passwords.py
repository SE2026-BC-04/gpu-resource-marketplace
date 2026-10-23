"""Password hashing for Login verification and account provisioning.

PROPOSED, pending technical review (Phase 1C §2.4 and §5.3): scrypt from the standard
library, so no new dependency enters ``uv.lock``. The Login use case depends only on the
``PasswordHasher`` protocol, so the algorithm can change without touching its callers.
"""

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from typing import Protocol

_SCHEME = "scrypt"
_ENCODED = re.compile(
    r"scrypt\$n=(?P<n>[0-9]{1,8}),r=(?P<r>[0-9]{1,2}),p=(?P<p>[0-9]{1,2})"
    r"\$(?P<salt>[A-Za-z0-9+/]+={0,2})\$(?P<key>[A-Za-z0-9+/]+={0,2})"
)
# Bounds applied to values read back from the database, so a corrupted row cannot
# request unbounded memory or CPU.
_MAX_STORED_N = 2**20
_MAX_STORED_R = 32
_MAX_STORED_P = 16
_SALT_BYTES_RANGE = range(16, 65)
_KEY_BYTES_RANGE = range(32, 65)


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password: str, encoded: str) -> bool: ...

    def burn_verification(self, password: str) -> None:
        """Spend the cost of one verification when no account matched the login name."""
        ...


class ScryptPasswordHasher:
    def __init__(
        self,
        *,
        n: int = 2**15,
        r: int = 8,
        p: int = 1,
        salt_bytes: int = 16,
        key_bytes: int = 32,
    ) -> None:
        if not _valid_parameters(n, r, p):
            raise ValueError("invalid scrypt parameters")
        if salt_bytes not in _SALT_BYTES_RANGE or key_bytes not in _KEY_BYTES_RANGE:
            raise ValueError("scrypt salt must be 16..64 bytes and key 32..64 bytes")
        self._n = n
        self._r = r
        self._p = p
        self._salt_bytes = salt_bytes
        self._key_bytes = key_bytes
        self._dummy_salt = secrets.token_bytes(salt_bytes)

    def hash_password(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string")
        salt = secrets.token_bytes(self._salt_bytes)
        key = _derive(_encode_password(password), salt, self._n, self._r, self._p, self._key_bytes)
        return f"{_SCHEME}$n={self._n},r={self._r},p={self._p}${_b64(salt)}${_b64(key)}"

    def verify_password(self, password: str, encoded: str) -> bool:
        """Return False for a wrong password or an unreadable stored hash; never raise."""
        if not isinstance(password, str) or not isinstance(encoded, str):
            return False
        match = _ENCODED.fullmatch(encoded)
        if match is None:
            return False
        n, r, p = int(match["n"]), int(match["r"]), int(match["p"])
        if not _valid_parameters(n, r, p) or n > _MAX_STORED_N or r > _MAX_STORED_R or p > _MAX_STORED_P:
            return False
        try:
            salt = base64.b64decode(match["salt"], validate=True)
            expected = base64.b64decode(match["key"], validate=True)
            password_bytes = _encode_password(password)
        except (binascii.Error, UnicodeEncodeError):
            return False
        if len(salt) not in _SALT_BYTES_RANGE or len(expected) not in _KEY_BYTES_RANGE:
            return False
        actual = _derive(password_bytes, salt, n, r, p, len(expected))
        return hmac.compare_digest(actual, expected)

    def burn_verification(self, password: str) -> None:
        try:
            password_bytes = _encode_password(password if isinstance(password, str) else "")
        except UnicodeEncodeError:
            password_bytes = b""
        _derive(password_bytes, self._dummy_salt, self._n, self._r, self._p, self._key_bytes)


def _valid_parameters(n: int, r: int, p: int) -> bool:
    return n > 1 and n & (n - 1) == 0 and r >= 1 and p >= 1


def _derive(password: bytes, salt: bytes, n: int, r: int, p: int, key_bytes: int) -> bytes:
    # scrypt needs about 128 * r * n bytes; allow twice that before hashlib refuses.
    maxmem = 256 * r * (n + p)
    return hashlib.scrypt(password, salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=key_bytes)


def _encode_password(password: str) -> bytes:
    # Passwords are never trimmed or normalized; lone surrogates raise UnicodeEncodeError.
    return password.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
