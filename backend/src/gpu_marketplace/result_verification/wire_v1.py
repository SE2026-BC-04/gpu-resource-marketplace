"""Strict Signed Result V1 wire parser and ``extract_signed_parts_v1`` (TV3-P2C-07).

Pure and I/O free: no database, HTTP, Session, clock, logging or randomness. It
parses the HTTP envelope ``{payload, signature, signature_encoding}`` defined by
ADR-004 section 3.3 from the raw bytes, enforces the exact eleven-field payload
and the canonical field formats, and returns typed immutable values together
with the unmodified original bytes.

This module only decides whether bytes are a well-formed V1 envelope. It never
verifies Ed25519 and never decides a business outcome: a ``SignedV1WireError``
is a parse/schema failure, not one of the four definitive rejection codes of
Phase 2C section 6.6.2. Its messages are fixed strings; input is never echoed.

Limits are not defaulted. Every caller must pass the configured ``max_bytes`` and
``max_depth`` as required keyword arguments. ``PROPOSED_MAX_ENVELOPE_BYTES`` and
``PROPOSED_MAX_NESTING_DEPTH`` are only the proposed values of Phase 2C section
6.3 item 1: they are labelled proposals, remain ``PENDING_PARAMS`` until TV1
approves them, and are not approved for production.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import rfc8785

# PENDING_PARAMS (Phase 2C section 6.3 Q2): proposed, not approved production values.
# They are not used as defaults anywhere; callers must pass their own configured limits.
PROPOSED_MAX_ENVELOPE_BYTES = 16_384
PROPOSED_MAX_NESTING_DEPTH = 4

SIGNATURE_ENCODING = "base64url-no-padding"

_UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_TIMESTAMP = re.compile(
    r"([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T"
    r"([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])\.([0-9]{6})Z"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}")

_ENVELOPE_FIELDS = frozenset({"payload", "signature", "signature_encoding"})
_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "result_id",
        "job_id",
        "attempt_id",
        "worker_id",
        "listing_id",
        "outcome",
        "failure_reason",
        "result_digest",
        "finished_at",
        "key_id",
    }
)
_UUID_FIELDS = ("result_id", "job_id", "attempt_id", "worker_id", "listing_id", "key_id")
_OUTCOMES = frozenset({"SUCCESS", "FAILED"})
_FAILURE_REASONS = frozenset({"WORKER_FAULT", "JOB_FAULT"})


class WireErrorCode(str, Enum):
    """Stable, non-secret reason categories. None of them is a verifier rejection code."""

    NOT_BYTES = "NOT_BYTES"
    TOO_LARGE = "TOO_LARGE"
    NOT_UTF8 = "NOT_UTF8"
    TOO_DEEP = "TOO_DEEP"
    MALFORMED_JSON = "MALFORMED_JSON"
    DUPLICATE_MEMBER = "DUPLICATE_MEMBER"
    NON_JSON_CONSTANT = "NON_JSON_CONSTANT"
    ENVELOPE_SHAPE = "ENVELOPE_SHAPE"
    PAYLOAD_SHAPE = "PAYLOAD_SHAPE"
    FIELD_VALUE = "FIELD_VALUE"


class SignedV1WireError(ValueError):
    """The bytes are not a strict Signed Result V1 envelope. Carries only a code."""

    def __init__(self, code: WireErrorCode) -> None:
        super().__init__(f"signed result V1 envelope rejected: {code.value}")
        self.code = code
        self.__suppress_context__ = True


@dataclass(frozen=True, slots=True)
class SignedPayloadV1:
    """The eleven ADR-004 V1 payload fields, exactly as validated."""

    schema_version: str
    result_id: str
    job_id: str
    attempt_id: str
    worker_id: str
    listing_id: str
    outcome: str
    failure_reason: str | None
    result_digest: str
    finished_at: str
    key_id: str


@dataclass(frozen=True, slots=True)
class SignedEnvelopeV1:
    payload: SignedPayloadV1
    signature: str
    signature_encoding: str


@dataclass(frozen=True, slots=True)
class ParsedSignedEnvelopeV1:
    """A validated envelope together with the exact bytes it was parsed from."""

    envelope: SignedEnvelopeV1
    raw_envelope: bytes


def _validate_limit(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _max_nesting_depth(text: str, limit: int) -> int:
    """Greatest object/array nesting counting the root as 1; stops once ``limit`` is exceeded.

    Brackets inside JSON strings do not count. This runs before ``json.loads`` so
    hostile nesting never reaches the recursive parser.
    """
    depth = 0
    deepest = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > limit:
                    return deepest
        elif char in "}]" and depth:
            depth -= 1
    return deepest


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SignedV1WireError(WireErrorCode.DUPLICATE_MEMBER)
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise SignedV1WireError(WireErrorCode.NON_JSON_CONSTANT)


def _string(value: object, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    try:
        datetime(*(int(part) for part in match.groups()))
    except ValueError:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE) from None
    return value


def _decode_signature(value: object) -> bytes:
    if type(value) is not str or _SIGNATURE.fullmatch(value) is None:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
    except (binascii.Error, ValueError):
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE) from None
    if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    return decoded


def _payload_from_object(value: object) -> SignedPayloadV1:
    if type(value) is not dict or set(value) != _PAYLOAD_FIELDS:
        raise SignedV1WireError(WireErrorCode.PAYLOAD_SHAPE)
    if type(value["schema_version"]) is not str or value["schema_version"] != "1":
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    identifiers = {name: _string(value[name], _UUID_V4) for name in _UUID_FIELDS}

    outcome = value["outcome"]
    failure_reason = value["failure_reason"]
    if type(outcome) is not str or outcome not in _OUTCOMES:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    if outcome == "SUCCESS":
        if failure_reason is not None:
            raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    elif type(failure_reason) is not str or failure_reason not in _FAILURE_REASONS:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)

    return SignedPayloadV1(
        schema_version="1",
        result_id=identifiers["result_id"],
        job_id=identifiers["job_id"],
        attempt_id=identifiers["attempt_id"],
        worker_id=identifiers["worker_id"],
        listing_id=identifiers["listing_id"],
        outcome=outcome,
        failure_reason=failure_reason,
        result_digest=_string(value["result_digest"], _DIGEST),
        finished_at=_timestamp(value["finished_at"]),
        key_id=identifiers["key_id"],
    )


def _parse(
    raw: bytes, max_bytes: int, max_depth: int
) -> tuple[ParsedSignedEnvelopeV1, bytes]:
    _validate_limit(max_bytes, "max_bytes")
    _validate_limit(max_depth, "max_depth")
    if type(raw) is not bytes:
        raise SignedV1WireError(WireErrorCode.NOT_BYTES)
    if len(raw) > max_bytes:
        raise SignedV1WireError(WireErrorCode.TOO_LARGE)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SignedV1WireError(WireErrorCode.NOT_UTF8) from None
    if _max_nesting_depth(text, max_depth) > max_depth:
        raise SignedV1WireError(WireErrorCode.TOO_DEEP)
    try:
        decoded = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except SignedV1WireError:
        raise
    except (ValueError, RecursionError, TypeError):
        # json.JSONDecodeError and the integer-conversion limit are ValueErrors.
        raise SignedV1WireError(WireErrorCode.MALFORMED_JSON) from None

    if type(decoded) is not dict or set(decoded) != _ENVELOPE_FIELDS:
        raise SignedV1WireError(WireErrorCode.ENVELOPE_SHAPE)
    if type(decoded["signature_encoding"]) is not str or decoded["signature_encoding"] != SIGNATURE_ENCODING:
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)
    signature_raw = _decode_signature(decoded["signature"])
    payload = _payload_from_object(decoded["payload"])
    envelope = SignedEnvelopeV1(
        payload=payload,
        signature=decoded["signature"],
        signature_encoding=SIGNATURE_ENCODING,
    )
    return ParsedSignedEnvelopeV1(envelope=envelope, raw_envelope=raw), signature_raw


def parse_signed_envelope_v1(
    raw: bytes,
    *,
    max_bytes: int,
    max_depth: int,
) -> ParsedSignedEnvelopeV1:
    """Strictly parse ``raw`` as a Signed Result V1 envelope.

    ``max_bytes`` and ``max_depth`` are required keyword arguments: the caller
    must pass the configured limits (there is no default). Omitting either raises
    ``TypeError``. The ``PROPOSED_*`` constants are proposals, not approved values.

    Rejects: non-bytes input, bodies above ``max_bytes``, invalid UTF-8, nesting
    above ``max_depth``, malformed JSON, duplicate members at any level, non-JSON
    constants, a field set other than exactly three outer and eleven payload
    fields, and any field that is not in its single canonical V1 form.

    The returned ``raw_envelope`` is the very object passed in; nothing is
    re-serialized. Raises ``ValueError`` for an invalid limit and
    ``SignedV1WireError`` for every input problem.
    """
    parsed, _ = _parse(raw, max_bytes, max_depth)
    return parsed


def extract_signed_parts_v1(
    raw: bytes,
    *,
    max_bytes: int,
    max_depth: int,
) -> tuple[bytes, bytes]:
    """Return ``(payload_jcs_raw, signature_raw)`` for a strictly valid V1 envelope.

    ``max_bytes`` and ``max_depth`` are required keyword arguments (no default);
    the caller must pass the configured limits.

    ``payload_jcs_raw`` is ``UTF-8(JCS(payload))`` (RFC 8785) **without** the
    ``GPU-MARKETPLACE:SIGNED-RESULT:V1\\n`` domain prefix, which is added only for
    verification. It is derived from the validated payload, never sliced from
    ``raw``. ``signature_raw`` is the 64 decoded Ed25519 signature bytes.
    Raises the same errors as :func:`parse_signed_envelope_v1`.
    """
    parsed, signature_raw = _parse(raw, max_bytes, max_depth)
    payload = parsed.envelope.payload
    payload_jcs_raw = rfc8785.dumps(
        {
            "schema_version": payload.schema_version,
            "result_id": payload.result_id,
            "job_id": payload.job_id,
            "attempt_id": payload.attempt_id,
            "worker_id": payload.worker_id,
            "listing_id": payload.listing_id,
            "outcome": payload.outcome,
            "failure_reason": payload.failure_reason,
            "result_digest": payload.result_digest,
            "finished_at": payload.finished_at,
            "key_id": payload.key_id,
        }
    )
    return bytes(payload_jcs_raw), signature_raw
