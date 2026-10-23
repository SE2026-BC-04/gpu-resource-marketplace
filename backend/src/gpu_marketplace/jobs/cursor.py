"""Opaque, context-bound HMAC cursor codec using only the Python stdlib."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

from gpu_marketplace.jobs.ports import CursorContext, CursorPosition


_VERSION = 1
_MAX_TOKEN_LENGTH = 2048
_REQUIRED_FIELDS = {
    "v",
    "user_id",
    "role",
    "scope",
    "status",
    "submitted_at",
    "job_id",
}


class HmacCursorCodec:
    """Sign cursor claims with an injected key; never loads or logs secrets.

    Production integration must supply a stable, dedicated key of at least 256
    bits and coordinate key rotation with cursor lifetime. The codec intentionally
    does not read environment, Settings, or database state.
    """

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("cursor signing key must contain at least 256 bits")
        self._key = key

    def encode(self, position: CursorPosition, *, context: CursorContext) -> str:
        timestamp = position.submitted_at
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        claims = {
            "v": _VERSION,
            "user_id": str(context.user_id),
            "role": context.role.value,
            "scope": context.scope,
            "status": context.status.value if context.status is not None else None,
            "submitted_at": timestamp.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "job_id": str(position.job_id),
        }
        payload = json.dumps(
            claims,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        payload_part = _b64encode(payload)
        signature_part = _b64encode(hmac.new(self._key, payload, hashlib.sha256).digest())
        token = f"{payload_part}.{signature_part}"
        if len(token) > _MAX_TOKEN_LENGTH:
            raise ValueError("cursor exceeds maximum length")
        return token

    def decode(self, token: str, *, context: CursorContext) -> CursorPosition:
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
            raise ValueError("invalid cursor length")
        parts = token.split(".")
        if len(parts) != 2:
            raise ValueError("invalid cursor encoding")
        payload = _b64decode(parts[0])
        signature = _b64decode(parts[1])
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid cursor signature")

        try:
            claims = json.loads(payload, object_pairs_hook=_unique_object)
            if not isinstance(claims, dict) or set(claims) != _REQUIRED_FIELDS:
                raise ValueError("invalid cursor claims")
            if type(claims["v"]) is not int or claims["v"] != _VERSION:
                raise ValueError("unsupported cursor version")
            if not all(
                isinstance(claims[name], str)
                for name in ("user_id", "role", "scope", "submitted_at", "job_id")
            ):
                raise ValueError("cursor claims have invalid types")
            if claims["status"] is not None and not isinstance(claims["status"], str):
                raise ValueError("cursor status has invalid type")
            expected_status = context.status.value if context.status is not None else None
            if (
                claims["user_id"] != str(context.user_id)
                or claims["role"] != context.role.value
                or claims["scope"] != context.scope
                or claims["status"] != expected_status
            ):
                raise ValueError("cursor does not match this query context")

            timestamp_text = claims["submitted_at"]
            if not timestamp_text.endswith("Z"):
                raise ValueError("cursor timestamp must use UTC Z notation")
            timestamp = datetime.fromisoformat(timestamp_text[:-1] + "+00:00")
            canonical_timestamp = timestamp.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            )
            if canonical_timestamp != timestamp_text:
                raise ValueError("cursor timestamp is not canonical")
            job_id = UUID(claims["job_id"])
            if str(job_id) != claims["job_id"]:
                raise ValueError("cursor Job ID is not canonical")
            return CursorPosition(submitted_at=timestamp, job_id=job_id)
        except ValueError:
            raise
        except (TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise ValueError("invalid cursor claims") from exc


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        raw = value.encode("ascii")
        decoded = base64.b64decode(
            raw + b"=" * (-len(raw) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError("invalid cursor base64") from exc
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical cursor base64")
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate cursor claim")
        result[key] = value
    return result
