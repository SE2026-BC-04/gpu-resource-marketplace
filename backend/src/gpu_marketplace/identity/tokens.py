"""HS256 user access tokens with exact microsecond NumericDate (DEC-P1-03, Phase 1C §2.3).

Standard library only, so ``iat``/``exp`` are written and read as exact six-decimal JSON
numbers instead of being rounded through ``float`` or truncated to whole seconds.
"""

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import hmac
import json
import re
import time
from typing import Any
from uuid import UUID

TOKEN_ISSUER = "gpu-marketplace-api"
TOKEN_AUDIENCE = "gpu-marketplace-web"
TOKEN_LIFETIME_SECONDS = 900
MIN_SECRET_BYTES = 32  # 256 bits

_MICROSECONDS_PER_SECOND = 1_000_000
_LIFETIME_MICROSECONDS = TOKEN_LIFETIME_SECONDS * _MICROSECONDS_PER_SECOND
_HEADER = {"alg": "HS256", "typ": "JWT"}
_CLAIM_NAMES = frozenset({"iss", "aud", "sub", "iat", "exp"})
_BASE64URL_SEGMENT = re.compile(r"[A-Za-z0-9_-]*")

MicrosecondClock = Callable[[], int]


def system_clock_microseconds() -> int:
    """Trusted API-process wall clock as integer microseconds since the Unix epoch."""
    return time.time_ns() // 1_000


class InvalidTokenError(Exception):
    """The token must be rejected with 401; ``reason`` is only for redacted server logs."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AccessTokenClaims:
    subject: UUID
    issued_at_us: int
    expires_at_us: int


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    claims: AccessTokenClaims
    expires_in: int = TOKEN_LIFETIME_SECONDS


class AccessTokenCodec:
    def __init__(self, secret: bytes, clock: MicrosecondClock = system_clock_microseconds) -> None:
        if not isinstance(secret, bytes) or len(secret) < MIN_SECRET_BYTES:
            raise ValueError("JWT signing secret must be at least 256 bits")
        self._secret = secret
        self._clock = clock

    def issue(self, subject: UUID) -> IssuedAccessToken:
        if not isinstance(subject, UUID):
            raise TypeError("token subject must be a UUID")
        issued_at = self._clock()
        expires_at = issued_at + _LIFETIME_MICROSECONDS
        # Built by hand so the NumericDate text keeps exactly six fractional digits.
        payload = (
            f'{{"iss":{json.dumps(TOKEN_ISSUER)},"aud":{json.dumps(TOKEN_AUDIENCE)},'
            f'"sub":{json.dumps(str(subject))},'
            f'"iat":{_format_numeric_date(issued_at)},"exp":{_format_numeric_date(expires_at)}}}'
        )
        header_segment = _encode_segment(json.dumps(_HEADER, separators=(",", ":")).encode())
        signing_input = f"{header_segment}.{_encode_segment(payload.encode())}"
        token = f"{signing_input}.{_encode_segment(self._sign(signing_input))}"
        return IssuedAccessToken(
            token=token,
            claims=AccessTokenClaims(subject=subject, issued_at_us=issued_at, expires_at_us=expires_at),
        )

    def verify(self, token: str) -> AccessTokenClaims:
        """Return the claims or raise; account status and role must still be checked in the DB."""
        if not isinstance(token, str):
            raise InvalidTokenError("malformed")
        segments = token.split(".")
        # Validate every segment's alphabet before signing, so non-ASCII input cannot raise.
        if len(segments) != 3 or not all(_BASE64URL_SEGMENT.fullmatch(segment) for segment in segments):
            raise InvalidTokenError("malformed")
        header_segment, payload_segment, signature_segment = segments

        if _decode_json_object(header_segment) != _HEADER:
            raise InvalidTokenError("header")
        expected_signature = self._sign(f"{header_segment}.{payload_segment}")
        if not hmac.compare_digest(_decode_segment(signature_segment), expected_signature):
            raise InvalidTokenError("signature")

        payload = _decode_json_object(payload_segment)
        if set(payload) != _CLAIM_NAMES:
            raise InvalidTokenError("claims")
        if payload["iss"] != TOKEN_ISSUER:
            raise InvalidTokenError("issuer")
        if payload["aud"] != TOKEN_AUDIENCE:
            raise InvalidTokenError("audience")
        subject = _parse_subject(payload["sub"])
        issued_at = _parse_numeric_date(payload["iat"])
        expires_at = _parse_numeric_date(payload["exp"])
        if expires_at - issued_at != _LIFETIME_MICROSECONDS:
            raise InvalidTokenError("lifetime")
        # No leeway: a token is valid only strictly before exp.
        if self._clock() >= expires_at:
            raise InvalidTokenError("expired")
        return AccessTokenClaims(subject=subject, issued_at_us=issued_at, expires_at_us=expires_at)

    def _sign(self, signing_input: str) -> bytes:
        return hmac.new(self._secret, signing_input.encode("ascii"), hashlib.sha256).digest()


def _format_numeric_date(microseconds: int) -> str:
    seconds, fraction = divmod(microseconds, _MICROSECONDS_PER_SECOND)
    return f"{seconds}.{fraction:06d}"


def _parse_numeric_date(value: Any) -> int:
    if not isinstance(value, Decimal) or value.is_signed():
        raise InvalidTokenError("numeric_date")
    if value.as_tuple().exponent != -6:
        raise InvalidTokenError("numeric_date")
    return int(value.scaleb(6))


def _parse_subject(value: Any) -> UUID:
    if not isinstance(value, str):
        raise InvalidTokenError("subject")
    try:
        subject = UUID(value)
    except ValueError as exc:
        raise InvalidTokenError("subject") from exc
    if str(subject) != value:
        raise InvalidTokenError("subject")
    return subject


def _encode_segment(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_segment(segment: str) -> bytes:
    if not _BASE64URL_SEGMENT.fullmatch(segment) or len(segment) % 4 == 1:
        raise InvalidTokenError("malformed")
    try:
        data = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InvalidTokenError("malformed") from exc
    if _encode_segment(data) != segment:
        raise InvalidTokenError("malformed")
    return data


def _decode_json_object(segment: str) -> dict[str, Any]:
    try:
        text = _decode_segment(segment).decode("utf-8")
        value = json.loads(
            text,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidTokenError("malformed") from exc
    if not isinstance(value, dict):
        raise InvalidTokenError("malformed")
    return value


def _reject_json_constant(name: str) -> Any:
    raise ValueError(f"JSON constant {name} is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
