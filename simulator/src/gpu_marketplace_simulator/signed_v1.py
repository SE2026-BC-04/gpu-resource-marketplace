"""Pure Signed Result V1 payload validation, encoding, and signing.

This module deliberately has no key loading, persistence, HTTP, or Manager logic.
Callers inject a signer that resolves a trusted ``(worker_id, key_id)`` pair.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Literal, Protocol

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


SIGNING_PREFIX = b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n"
SIGNATURE_ENCODING = "base64url-no-padding"
_UUID_V4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T"
    r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]{86}$")


class SignedResultError(ValueError):
    """Base class for safe, typed Signed Result errors."""


class PayloadValidationError(SignedResultError):
    """The supplied payload is not an exact, valid Signed Result V1 object."""


class SigningError(SignedResultError):
    """The injected signer failed or returned an invalid signature."""


class SignedResultV1Payload(BaseModel):
    """The exact eleven-field ADR-004 V1 signed payload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"]
    result_id: str = Field(pattern=_UUID_V4.pattern)
    job_id: str = Field(pattern=_UUID_V4.pattern)
    attempt_id: str = Field(pattern=_UUID_V4.pattern)
    worker_id: str = Field(pattern=_UUID_V4.pattern)
    listing_id: str = Field(pattern=_UUID_V4.pattern)
    outcome: Literal["SUCCESS", "FAILED"]
    failure_reason: Literal["WORKER_FAULT", "JOB_FAULT"] | None
    result_digest: str = Field(pattern=_DIGEST.pattern)
    finished_at: str
    key_id: str = Field(pattern=_UUID_V4.pattern)

    @model_validator(mode="after")
    def validate_semantics(self) -> SignedResultV1Payload:
        if (self.outcome == "SUCCESS") != (self.failure_reason is None):
            raise ValueError("failure_reason is inconsistent with outcome")
        if not _TIMESTAMP.fullmatch(self.finished_at):
            raise ValueError("finished_at must use canonical UTC microseconds")
        try:
            datetime.fromisoformat(self.finished_at[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("finished_at is not a valid Gregorian timestamp") from exc
        return self


class SignedResultV1Envelope(BaseModel):
    """Pure value representation of the approved HTTP envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    payload: SignedResultV1Payload
    signature: str = Field(pattern=_B64URL.pattern)
    signature_encoding: Literal["base64url-no-padding"]

    @model_validator(mode="after")
    def validate_signature_encoding(self) -> SignedResultV1Envelope:
        try:
            decoded = base64.urlsafe_b64decode(self.signature + "==")
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("signature is not valid unpadded base64url") from exc
        if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != self.signature:
            raise ValueError("signature is not canonical 64-byte unpadded base64url")
        return self


class SignerProvider(Protocol):
    """Injected signing boundary, bound to trusted Worker/key identity."""

    def sign(self, *, worker_id: str, key_id: str, message: bytes) -> bytes:
        """Sign ``message`` using the key registered for this identity pair."""


@dataclass(frozen=True, slots=True)
class SignedResultV1:
    payload: SignedResultV1Payload
    canonical_payload: bytes
    signing_message: bytes
    signature_bytes: bytes
    signature: str

    def envelope(self) -> SignedResultV1Envelope:
        return SignedResultV1Envelope(
            payload=self.payload,
            signature=self.signature,
            signature_encoding=SIGNATURE_ENCODING,
        )


def payload_from_mapping(value: object) -> SignedResultV1Payload:
    """Validate a mapping without coercion and reject missing/extra fields."""
    if not isinstance(value, dict):
        raise PayloadValidationError("payload must be a JSON object")
    try:
        return SignedResultV1Payload.model_validate(value, strict=True)
    except ValidationError as exc:
        raise PayloadValidationError("payload does not satisfy Signed Result V1") from exc


def payload_from_json(raw: str | bytes) -> SignedResultV1Payload:
    """Parse JSON strictly, rejecting duplicate keys and non-JSON constants."""
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PayloadValidationError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(_: str) -> object:
        raise PayloadValidationError("non-JSON numeric constant")

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        decoded = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except PayloadValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise PayloadValidationError("payload is not valid UTF-8 JSON") from exc
    return payload_from_mapping(decoded)


def canonical_payload_bytes(payload: SignedResultV1Payload) -> bytes:
    """Return RFC 8785 JCS UTF-8 bytes, with no BOM or trailing newline."""
    validated = _revalidate_payload(payload)
    return rfc8785.dumps(validated.model_dump(mode="json"))


def _revalidate_payload(payload: object) -> SignedResultV1Payload:
    """Rebuild a payload from its stored fields; never trust Pydantic provenance."""
    if type(payload) is not SignedResultV1Payload:
        raise PayloadValidationError("payload does not satisfy Signed Result V1")
    raw_fields = vars(payload).copy()
    if set(raw_fields) != set(SignedResultV1Payload.model_fields):
        raise PayloadValidationError("payload does not satisfy Signed Result V1")
    try:
        return SignedResultV1Payload.model_validate(raw_fields, strict=True)
    except ValidationError:
        raise PayloadValidationError("payload does not satisfy Signed Result V1") from None


def signing_message(payload: SignedResultV1Payload) -> bytes:
    return SIGNING_PREFIX + canonical_payload_bytes(payload)


def sign_payload(payload: SignedResultV1Payload, signer: SignerProvider) -> SignedResultV1:
    """Sign the canonical eleven-field payload through the injected provider."""
    validated = _revalidate_payload(payload)
    canonical = rfc8785.dumps(validated.model_dump(mode="json"))
    message = SIGNING_PREFIX + canonical
    try:
        signature_bytes = signer.sign(
            worker_id=validated.worker_id,
            key_id=validated.key_id,
            message=message,
        )
    except Exception:
        raise SigningError("injected signer failed") from None
    if not isinstance(signature_bytes, bytes) or len(signature_bytes) != 64:
        raise SigningError("injected signer must return exactly 64 raw Ed25519 bytes")
    encoded = base64.urlsafe_b64encode(signature_bytes).decode("ascii").rstrip("=")
    if len(encoded) != 86:
        raise SigningError("signature encoding is not canonical V1 base64url")
    return SignedResultV1(validated, canonical, message, signature_bytes, encoded)
