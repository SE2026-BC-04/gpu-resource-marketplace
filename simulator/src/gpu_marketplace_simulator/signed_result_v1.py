"""Strict, I/O-free structural checks for the immutable Signed Result V1 envelope.

This module binds cached receipt identity only. It does not verify Ed25519 or
assert that a signed claim represents physical execution; that remains the
Manager's responsibility under ADR-004.
"""
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
import binascii
from datetime import datetime
import json
import re
from uuid import UUID


_ENVELOPE_FIELDS = frozenset({"payload", "signature", "signature_encoding"})
_PAYLOAD_FIELDS = frozenset({
    "schema_version", "result_id", "job_id", "attempt_id", "worker_id",
    "listing_id", "outcome", "failure_reason", "result_digest", "finished_at",
    "key_id",
})
_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{86}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FINISHED_AT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)


class InvalidSignedResultV1(ValueError):
    """Malformed, ambiguous or identity-mismatched Signed Result V1 envelope."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSignedResultV1("duplicate JSON object member")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InvalidSignedResultV1(f"invalid JSON constant: {value}")


def _canonical_uuid4(value: object, field: str) -> UUID:
    if type(value) is not str or _UUID4.fullmatch(value) is None:
        raise InvalidSignedResultV1(f"{field} must be canonical lowercase UUIDv4")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise InvalidSignedResultV1(f"{field} must be canonical UUIDv4") from error
    if parsed.version != 4 or str(parsed) != value:
        raise InvalidSignedResultV1(f"{field} must be canonical lowercase UUIDv4")
    return parsed


def _validate_signature(value: object) -> None:
    if type(value) is not str or _SIGNATURE.fullmatch(value) is None:
        raise InvalidSignedResultV1("signature must be unpadded base64url Ed25519 bytes")
    try:
        decoded = urlsafe_b64decode(value + "==")
    except (ValueError, binascii.Error) as error:
        raise InvalidSignedResultV1("signature encoding is invalid") from error
    if len(decoded) != 64 or urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise InvalidSignedResultV1("signature encoding is not canonical")


def validate_receipt_binding_v1(
    raw_envelope: bytes,
    *,
    outer_result_id: UUID,
    expected_attempt_id: UUID,
    expected_job_id: UUID,
    expected_worker_id: UUID,
    expected_listing_id: UUID,
) -> None:
    """Strictly parse V1 and bind payload IDs without rewriting its raw bytes.

    Signature bytes are checked for the exact V1 representation only. No
    cryptographic verification is performed here.
    """
    if type(raw_envelope) is not bytes or not raw_envelope:
        raise InvalidSignedResultV1("envelope must be nonempty immutable bytes")
    if type(outer_result_id) is not UUID or outer_result_id.version != 4:
        raise InvalidSignedResultV1("outer result_id must be UUIDv4")
    expected_ids = {
        "attempt_id": expected_attempt_id,
        "job_id": expected_job_id,
        "worker_id": expected_worker_id,
        "listing_id": expected_listing_id,
    }
    for field, value in expected_ids.items():
        if type(value) is not UUID or value.version != 4:
            raise InvalidSignedResultV1(f"expected {field} must be UUIDv4")
    try:
        envelope = json.loads(
            raw_envelope.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise InvalidSignedResultV1("envelope JSON is malformed") from error
    if type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS:
        raise InvalidSignedResultV1("envelope must contain exactly the V1 fields")
    if envelope["signature_encoding"] != "base64url-no-padding":
        raise InvalidSignedResultV1("signature_encoding is not the V1 encoding")
    _validate_signature(envelope["signature"])

    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != _PAYLOAD_FIELDS:
        raise InvalidSignedResultV1("payload must contain exactly the eleven V1 fields")
    if type(payload["schema_version"]) is not str or payload["schema_version"] != "1":
        raise InvalidSignedResultV1("schema_version must be the V1 string")

    ids = {
        field: _canonical_uuid4(payload[field], field)
        for field in ("result_id", "job_id", "attempt_id", "worker_id", "listing_id", "key_id")
    }
    if ids["result_id"] != outer_result_id:
        raise InvalidSignedResultV1("payload result_id differs from the receipt identity")
    if ids["attempt_id"] != expected_attempt_id:
        raise InvalidSignedResultV1("payload attempt_id differs from the admitted Attempt")
    for field in ("job_id", "worker_id", "listing_id"):
        if ids[field] != expected_ids[field]:
            raise InvalidSignedResultV1(
                f"payload {field} differs from the admitted dispatch"
            )

    outcome = payload["outcome"]
    failure_reason = payload["failure_reason"]
    if type(outcome) is not str or outcome not in {"SUCCESS", "FAILED"}:
        raise InvalidSignedResultV1("outcome is not an accepted V1 value")
    if outcome == "SUCCESS":
        if failure_reason is not None:
            raise InvalidSignedResultV1("SUCCESS requires a null failure_reason")
    elif (type(failure_reason) is not str
          or failure_reason not in {"WORKER_FAULT", "JOB_FAULT"}):
        raise InvalidSignedResultV1("FAILED requires an accepted V1 failure_reason")

    if (type(payload["result_digest"]) is not str
            or _DIGEST.fullmatch(payload["result_digest"]) is None):
        raise InvalidSignedResultV1("result_digest is not canonical V1 sha256")
    finished_at = payload["finished_at"]
    if type(finished_at) is not str or _FINISHED_AT.fullmatch(finished_at) is None:
        raise InvalidSignedResultV1("finished_at is not canonical V1 UTC time")
    try:
        datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidSignedResultV1("finished_at is not a valid calendar instant") from error
