"""Pure Ed25519 / RFC 8785 Signed Result V1 verifier (TV3-P2C-08, V-OUT).

Synchronous and I/O free: no database, HTTP, Session, clock, file, environment,
logging or randomness. The caller (TV1 Manager, through TV2's trusted read
adapters) supplies the immutable Inbox bytes, a trusted binding and a trusted key
answer; this module returns a typed ``VerifiedV1Receipt`` or ``RejectedV1Receipt``.

Order of checks (fixed):

1. Argument types and limits: a wrong type is ``TypeError``, a non-positive limit
   is ``ValueError``. These are programming errors, never verdicts.
2. ``sha256(original_envelope_raw)`` must equal ``binding.envelope_sha256``
   (constant-time compare), else ``EvidenceIntegrityError``.
3. Parse with the P2C-07 strict parser. Bytes that ingress already admitted but
   that no longer parse are drift or corruption, not a verdict:
   ``ParserDriftError``.
4. ``payload.result_id`` must equal ``binding.result_id``, else
   ``EvidenceIntegrityError`` (ingress stores the payload's own ``result_id``).
5. ``CONTEXT_MISMATCH``: signed ``job_id``, ``attempt_id``, ``worker_id`` or
   ``listing_id`` differ from the bound context.
6. ``UNKNOWN_KEY``: the trusted lookup answered ``KEY_ABSENT``.
7. ``key.key_id`` must equal ``payload.key_id``, else ``TrustedKeyError`` (the
   adapter returned the wrong row; not a fault of the receipt).
8. ``KEY_WORKER_MISMATCH``: the key row belongs to another Worker than the payload.
9. The public key must be 32 ``bytes``, must not be an unsafe encoding (see
   "Public-key validity") and must load, else ``TrustedKeyError``. Only a loader
   ``ValueError`` means unusable key material; any other loader exception is
   ``VerifierInternalError`` (retryable), never a key verdict.
10. Ed25519 over ``SIGNED_RESULT_V1_PREFIX + payload_jcs_raw``. Only an
    ``InvalidSignature`` is ``INVALID_SIGNATURE``; any other exception is
    ``VerifierInternalError`` and never a rejection.

Only the four ``RejectionCodeV1`` values can reject. Every ``SignedV1VerificationFault``
is **not** a verdict: the caller keeps the Inbox row ``PENDING``, blocks only that
row's Job, alerts and retries within a bound (Phase 2C section 7.9 R2/R3). A
retired key verifies like an active one; the number of active keys is not an
input (Phase 2C section 6.6.3, 7.3).

``KEY_ABSENT`` must be passed only when the key lookup answered definitively that
no row has this ``key_id``. If the registry is unavailable, times out or cannot be
read, the adapter must raise and must not call this function (section 7.9 R1).

Exception messages are fixed strings; input, keys and signatures are never echoed.

Public-key validity (PROPOSED policy, TV2/TV5 ACK pending; TV1/TV5 review of #72)
---------------------------------------------------------------------------------
On the pinned ``cryptography`` 46.0.7 (OpenSSL backend) ``Ed25519PublicKey.from_public_bytes``
accepts any 32 bytes and never decodes the point. The signature R=identity, S=0 is then
accepted for every message when the key is the identity point, and for a fraction of
messages when it is another small-order point or a non-canonical encoding of one (see the
reproduction tests). Such a key would make any envelope "verify", so before verifying the
verifier refuses, with ``TrustedKeyError``: (a) a ``y`` coordinate that is not below the
field prime (non-canonical encoding), and (b) a constant blocklist of the eight small-order
encodings plus the two non-canonical ``x = 0`` / sign-bit-set encodings. There is no
curve arithmetic here: only an integer comparison and a constant set, on top of the
vetted backend. An unusable key is a fault of the trusted key row, never a verdict on the
receipt: no ``VerifiedV1Receipt`` and no ``INVALID_SIGNATURE``.

KNOWN LIMITATION: a 32-byte string that is not a curve point is not detected here (the
backend cannot tell it apart from a bad signature without decoding the point, which would
need curve arithmetic). It cannot forge a signature, but a genuine receipt checked against
such a row is answered ``INVALID_SIGNATURE``. Registration (G1, proof of possession) must
refuse it before the key can be active; that is outside this module.

Trust and provenance (PROPOSED, TV1/TV2/TV5 ACK pending)
--------------------------------------------------------
``_ISSUER`` and the frozen dataclasses only prevent accidental construction of a receipt.
They are not a security boundary: any code in the same process can import ``_ISSUER``, and
``dataclasses.replace`` keeps the issuer while changing any field. The receipts are typed
carriers handed between trusted code of the same process (TV1 orchestration and TV2
adapters). The adapter must therefore re-check, under the locks and against the locked Inbox
row, the raw evidence, the identities and the values before it writes (TV2 ``finalize_one`` /
``reject_candidate``); an identity check alone does not prove that a signature was verified
for an arbitrary forged carrier. Negative tests for modified carriers belong to the future
adapter boundary and are NOT implemented here: a ``dataclasses.replace`` receipt with another
outcome or digest; a receipt whose ``payload_jcs_raw`` / ``signature_raw`` differ from the
locked row; a receipt whose ids differ from the locked Inbox row or Job; a receipt for a row
that is no longer ``PENDING``; and a ``RejectedV1Receipt`` whose code the locked recheck does
not reproduce.

Key lookup boundary (PROPOSED, owner ACK pending)
-------------------------------------------------
``result_inbox`` does not store ``key_id``; it exists only inside the signed payload. The
caller reads it with ``read_signed_key_id_v1`` (the same hash check and strict parse as the
verifier, same error mapping), looks the key up by ``key_id`` (its primary key), and passes
either the row or ``KEY_ABSENT`` (only for a definitive "no row" answer) to the verifier.

Cost: a lookup followed by a verification parses the envelope twice, and
``verify_signed_result_v1`` itself parses it twice (``parse_signed_envelope_v1`` and then
``extract_signed_parts_v1``, in P2C-07, which is deliberately unchanged here). At the proposed
16 KiB limit this is small; account for it in the future operation budget.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gpu_marketplace.result_verification.wire_v1 import (
    ParsedSignedEnvelopeV1,
    SignedV1WireError,
    extract_signed_parts_v1,
    parse_signed_envelope_v1,
)

SIGNED_RESULT_V1_PREFIX = b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n"

# Ed25519 field prime 2**255 - 19 and the mask of the 255 ``y`` bits of an encoding.
_FIELD_PRIME = (1 << 255) - 19
_Y_MASK = (1 << 255) - 1
# Small-order encodings that make "R = identity, S = 0" verify (see the module docstring):
# the 8 small-order points, plus the two non-canonical encodings with x = 0 and the sign bit set.
_UNSAFE_PUBLIC_KEY_ENCODINGS = frozenset(
    bytes.fromhex(value)
    for value in (
        "0100000000000000000000000000000000000000000000000000000000000000",  # identity
        "0100000000000000000000000000000000000000000000000000000000000080",  # identity, x=0 sign=1 (non-canonical)
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",  # order 2 (y = -1)
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",  # order 2, x=0 sign=1 (non-canonical)
        "0000000000000000000000000000000000000000000000000000000000000000",  # order 4 (y = 0)
        "0000000000000000000000000000000000000000000000000000000000000080",  # order 4 (y = 0, other x)
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",  # order 8
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",  # order 8
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",  # order 8
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",  # order 8
    )
)

# Module-private capability: only this module can build a receipt.
_ISSUER = object()


class RejectionCodeV1(StrEnum):
    """The four definitive verifier codes of Phase 2C section 6.6.2 (closed enum)."""

    UNKNOWN_KEY = "UNKNOWN_KEY"
    KEY_WORKER_MISMATCH = "KEY_WORKER_MISMATCH"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"


# --- non-definitive faults (never a RejectedV1Receipt) -------------------------------


class SignedV1VerificationFault(Exception):
    """Root of every non-definitive fault. Carries only a fixed category and reason."""

    category = "VERIFICATION_FAULT"

    def __init__(self, reason: str) -> None:
        super().__init__(f"{self.category}: {reason}")
        self.reason = reason
        self.__suppress_context__ = True


class EvidenceIntegrityError(SignedV1VerificationFault):
    """The retained evidence disagrees with the trusted binding (hash, result_id)."""

    category = "EVIDENCE_INTEGRITY"


class ParserDriftError(SignedV1VerificationFault):
    """Admitted bytes no longer parse as strict V1: version mismatch or corrupt data."""

    category = "PARSER_DRIFT"


class TrustedKeyError(SignedV1VerificationFault):
    """The trusted key answer is unusable (wrong row, bad key material)."""

    category = "TRUSTED_KEY"


class VerifierInternalError(SignedV1VerificationFault):
    """An unexpected failure inside the verifier or the Ed25519 primitive."""

    category = "VERIFIER_INTERNAL"


# --- trusted inputs ------------------------------------------------------------------


def _require_uuid(value: object, name: str) -> None:
    if type(value) is not UUID:
        raise TypeError(f"{name} must be a uuid.UUID")


@dataclass(frozen=True, slots=True)
class TrustedInboxBindingV1:
    """Immutable context read by TV2's adapter from the committed Inbox row and Job."""

    inbox_id: UUID
    result_id: UUID
    envelope_sha256: bytes
    job_id: UUID
    attempt_id: UUID
    worker_id: UUID
    listing_id: UUID

    def __post_init__(self) -> None:
        for name in ("inbox_id", "result_id", "job_id", "attempt_id", "worker_id", "listing_id"):
            _require_uuid(getattr(self, name), name)
        if type(self.envelope_sha256) is not bytes:
            raise TypeError("envelope_sha256 must be bytes")
        if len(self.envelope_sha256) != 32:
            raise ValueError("envelope_sha256 must be exactly 32 bytes")


@dataclass(frozen=True, slots=True)
class TrustedWorkerKeyV1:
    """Snapshot of one ``worker_public_keys`` row, looked up by ``key_id`` (its primary key).

    ``public_key_raw`` is deliberately not checked here: unusable key material is
    reported by the verifier as ``TrustedKeyError``.
    """

    key_id: UUID
    worker_id: UUID
    public_key_raw: bytes
    retired_at: datetime | None

    def __post_init__(self) -> None:
        _require_uuid(self.key_id, "key_id")
        _require_uuid(self.worker_id, "worker_id")
        if self.retired_at is not None and type(self.retired_at) is not datetime:
            raise TypeError("retired_at must be a datetime or None")


@dataclass(frozen=True, slots=True)
class KeyAbsentV1:
    """The lookup answered definitively that no row has this ``key_id``.

    Return it only for a definitive answer. A database error, timeout or unreadable
    row is not "absent": the adapter must raise and must not call the verifier.
    """


KEY_ABSENT = KeyAbsentV1()


# --- outputs -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifiedV1Receipt:
    """Signature and context verified. Built only by ``verify_signed_result_v1``.

    A typed carrier for trusted code of the same process. The private issuer token and
    the frozen dataclass only prevent accidental construction: this is not a security
    boundary (``dataclasses.replace`` keeps the issuer). The adapter must re-check the
    locked evidence, identities and values itself (module docstring, "Trust and provenance").
    """

    inbox_id: UUID
    result_id: UUID
    envelope_sha256: bytes
    job_id: UUID
    attempt_id: UUID
    worker_id: UUID
    listing_id: UUID
    key_id: UUID
    schema_version: str
    outcome: str
    failure_reason: str | None
    result_digest: str
    finished_at_wire: str
    payload_jcs_raw: bytes = field(repr=False)
    signature_raw: bytes = field(repr=False)
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise TypeError("VerifiedV1Receipt can only be issued by the verifier")


@dataclass(frozen=True, slots=True)
class RejectedV1Receipt:
    """Definitive rejection of the examined row. Built only by the verifier.

    Same convention as ``VerifiedV1Receipt``: a typed carrier between trusted code of the
    same process, not a security boundary. The adapter re-checks the locked row before it
    writes a rejection.
    """

    inbox_id: UUID
    result_id: UUID
    envelope_sha256: bytes
    job_id: UUID
    attempt_id: UUID
    rejection_code: RejectionCodeV1
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise TypeError("RejectedV1Receipt can only be issued by the verifier")
        if type(self.rejection_code) is not RejectionCodeV1:
            raise TypeError("rejection_code must be a RejectionCodeV1")


def _reject(binding: TrustedInboxBindingV1, code: RejectionCodeV1) -> RejectedV1Receipt:
    return RejectedV1Receipt(
        inbox_id=binding.inbox_id,
        result_id=binding.result_id,
        envelope_sha256=binding.envelope_sha256,
        job_id=binding.job_id,
        attempt_id=binding.attempt_id,
        rejection_code=code,
        _issuer=_ISSUER,
    )


# --- verification --------------------------------------------------------------------


def _check_arguments(
    original_envelope_raw: object,
    binding: object,
    key: object,
    max_bytes: object,
    max_depth: object,
) -> None:
    if type(original_envelope_raw) is not bytes:
        raise TypeError("original_envelope_raw must be bytes")
    if type(binding) is not TrustedInboxBindingV1:
        raise TypeError("binding must be a TrustedInboxBindingV1")
    if type(key) is not TrustedWorkerKeyV1 and type(key) is not KeyAbsentV1:
        raise TypeError("key must be a TrustedWorkerKeyV1 or KEY_ABSENT")
    _check_limits(max_bytes, max_depth)


def _check_limits(max_bytes: object, max_depth: object) -> None:
    for value, name in ((max_bytes, "max_bytes"), (max_depth, "max_depth")):
        if type(value) is not int:
            raise TypeError(f"{name} must be an int")
        if value < 1:
            raise ValueError(f"{name} must be positive")


def _parse_checked(
    original_envelope_raw: bytes, expected_sha256: bytes, max_bytes: int, max_depth: int
) -> ParsedSignedEnvelopeV1:
    """The one hash check + strict parse shared by the verifier and ``read_signed_key_id_v1``."""
    actual_sha256 = hashlib.sha256(original_envelope_raw).digest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise EvidenceIntegrityError("ENVELOPE_HASH_MISMATCH")
    try:
        return parse_signed_envelope_v1(original_envelope_raw, max_bytes=max_bytes, max_depth=max_depth)
    except SignedV1WireError as error:
        raise ParserDriftError(f"ENVELOPE_NOT_STRICT_V1_{error.code.value}") from None


def _unsafe_public_key_reason(public_key_raw: bytes) -> str | None:
    """Reason a 32-byte key encoding is refused before verifying, or ``None`` (see module docstring)."""
    if int.from_bytes(public_key_raw, "little") & _Y_MASK >= _FIELD_PRIME:
        return "PUBLIC_KEY_NON_CANONICAL_ENCODING"
    if public_key_raw in _UNSAFE_PUBLIC_KEY_ENCODINGS:
        return "PUBLIC_KEY_SMALL_ORDER"
    return None


def read_signed_key_id_v1(
    original_envelope_raw: bytes,
    *,
    envelope_sha256: bytes,
    max_bytes: int,
    max_depth: int,
) -> UUID:
    """Return the ``key_id`` signed in a retained envelope, for the trusted key lookup. PROPOSED.

    Pure and I/O free. Applies the same hash check and strict parse as
    ``verify_signed_result_v1`` (one shared code path) and the same error mapping: a hash that
    differs is ``EvidenceIntegrityError`` and bytes that no longer parse as strict V1 are
    ``ParserDriftError``, both faults and never a verdict. The result is untrusted until the
    verifier has checked the signature; it only selects which row to look up by primary key.
    ``max_bytes`` and ``max_depth`` are required, as for the verifier. It parses the envelope
    once and does not extract the signed parts.
    """
    if type(original_envelope_raw) is not bytes:
        raise TypeError("original_envelope_raw must be bytes")
    if type(envelope_sha256) is not bytes:
        raise TypeError("envelope_sha256 must be bytes")
    if len(envelope_sha256) != 32:
        raise ValueError("envelope_sha256 must be exactly 32 bytes")
    _check_limits(max_bytes, max_depth)
    try:
        parsed = _parse_checked(original_envelope_raw, envelope_sha256, max_bytes, max_depth)
        return UUID(parsed.envelope.payload.key_id)
    except SignedV1VerificationFault:
        raise
    except Exception:
        raise VerifierInternalError("UNEXPECTED_FAILURE") from None


def _verify(
    original_envelope_raw: bytes,
    binding: TrustedInboxBindingV1,
    key: TrustedWorkerKeyV1 | KeyAbsentV1,
    max_bytes: int,
    max_depth: int,
) -> VerifiedV1Receipt | RejectedV1Receipt:
    parsed = _parse_checked(original_envelope_raw, binding.envelope_sha256, max_bytes, max_depth)
    try:
        payload_jcs_raw, signature_raw = extract_signed_parts_v1(
            original_envelope_raw, max_bytes=max_bytes, max_depth=max_depth
        )
    except SignedV1WireError as error:
        raise ParserDriftError(f"ENVELOPE_NOT_STRICT_V1_{error.code.value}") from None
    payload = parsed.envelope.payload

    if payload.result_id != str(binding.result_id):
        raise EvidenceIntegrityError("RESULT_ID_MISMATCH")

    if (
        payload.job_id != str(binding.job_id)
        or payload.attempt_id != str(binding.attempt_id)
        or payload.worker_id != str(binding.worker_id)
        or payload.listing_id != str(binding.listing_id)
    ):
        return _reject(binding, RejectionCodeV1.CONTEXT_MISMATCH)

    if type(key) is KeyAbsentV1:
        return _reject(binding, RejectionCodeV1.UNKNOWN_KEY)

    if payload.key_id != str(key.key_id):
        raise TrustedKeyError("KEY_ROW_NOT_THE_SIGNED_KEY_ID")
    if payload.worker_id != str(key.worker_id):
        return _reject(binding, RejectionCodeV1.KEY_WORKER_MISMATCH)

    if type(key.public_key_raw) is not bytes or len(key.public_key_raw) != 32:
        raise TrustedKeyError("PUBLIC_KEY_NOT_32_BYTES")
    unsafe_reason = _unsafe_public_key_reason(key.public_key_raw)
    if unsafe_reason is not None:
        raise TrustedKeyError(unsafe_reason)
    try:
        public_key = Ed25519PublicKey.from_public_bytes(key.public_key_raw)
    except ValueError:
        # Only a loader ValueError proves unusable key material. Anything else is an
        # unexpected backend failure and becomes a retryable VerifierInternalError.
        raise TrustedKeyError("PUBLIC_KEY_NOT_LOADABLE") from None

    try:
        public_key.verify(signature_raw, SIGNED_RESULT_V1_PREFIX + payload_jcs_raw)
    except InvalidSignature:
        return _reject(binding, RejectionCodeV1.INVALID_SIGNATURE)

    return VerifiedV1Receipt(
        inbox_id=binding.inbox_id,
        result_id=binding.result_id,
        envelope_sha256=binding.envelope_sha256,
        job_id=binding.job_id,
        attempt_id=binding.attempt_id,
        worker_id=binding.worker_id,
        listing_id=binding.listing_id,
        key_id=key.key_id,
        schema_version=payload.schema_version,
        outcome=payload.outcome,
        failure_reason=payload.failure_reason,
        result_digest=payload.result_digest,
        finished_at_wire=payload.finished_at,
        payload_jcs_raw=payload_jcs_raw,
        signature_raw=signature_raw,
        _issuer=_ISSUER,
    )


def verify_signed_result_v1(
    original_envelope_raw: bytes,
    *,
    binding: TrustedInboxBindingV1,
    key: TrustedWorkerKeyV1 | KeyAbsentV1,
    max_bytes: int,
    max_depth: int,
) -> VerifiedV1Receipt | RejectedV1Receipt:
    """Verify one retained Signed Result V1 envelope against trusted inputs.

    Returns ``VerifiedV1Receipt`` or ``RejectedV1Receipt`` (four codes only). Raises
    ``TypeError``/``ValueError`` for invalid arguments and a
    ``SignedV1VerificationFault`` subclass for every non-definitive condition. The
    order of checks is documented in the module docstring. ``max_bytes`` and
    ``max_depth`` are required and are passed to the P2C-07 parser; there are no
    defaults (the proposed values remain ``PENDING_PARAMS``).
    """
    _check_arguments(original_envelope_raw, binding, key, max_bytes, max_depth)
    try:
        return _verify(original_envelope_raw, binding, key, max_bytes, max_depth)
    except SignedV1VerificationFault:
        raise
    except Exception:
        # Anything unexpected is a fault, never a verdict on the receipt.
        raise VerifierInternalError("UNEXPECTED_FAILURE") from None
