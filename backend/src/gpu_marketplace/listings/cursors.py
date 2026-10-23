"""Authenticated keyset cursors; the signing key is supplied by the integrator."""

import base64
from datetime import datetime
import hashlib
import hmac
import json
from uuid import UUID

from .errors import ListingError
from .models import ListingPosition, utc_timestamp


class ListingCursorCodec:
    def __init__(self, signing_key: bytes) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("cursor signing key must contain at least 32 bytes")
        self._key = signing_key

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @classmethod
    def _decode(cls, value: str) -> bytes:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        if cls._encode(raw) != value:
            raise ValueError("noncanonical base64")
        return raw

    def encode(
        self, position: ListingPosition, context: tuple[str, str | None, str | None]
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "context": context,
                "created_at": utc_timestamp(position.created_at),
                "id": str(position.id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return (
            self._encode(payload)
            + "."
            + self._encode(hmac.digest(self._key, payload, hashlib.sha256))
        )

    def decode(
        self, token: str, context: tuple[str, str | None, str | None]
    ) -> ListingPosition:
        try:
            if not token or len(token) > 2048:
                raise ValueError("invalid size")
            encoded, signature = token.split(".")
            payload = self._decode(encoded)
            if not hmac.compare_digest(
                self._decode(signature), hmac.digest(self._key, payload, hashlib.sha256)
            ):
                raise ValueError("invalid signature")
            data = json.loads(payload)
            if (
                set(data) != {"v", "context", "created_at", "id"}
                or type(data["v"]) is not int
                or data["v"] != 1
                or data["context"] != list(context)
            ):
                raise ValueError("invalid context")
            instant = datetime.fromisoformat(data["created_at"])
            identity = UUID(data["id"])
            if (
                identity.version != 4
                or str(identity) != data["id"]
                or utc_timestamp(instant) != data["created_at"]
            ):
                raise ValueError("invalid position")
            return ListingPosition(instant, identity)
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            UnicodeError,
            OverflowError,
        ) as exc:
            raise ListingError(
                400, "INVALID_CURSOR", "Invalid pagination cursor."
            ) from exc
