"""TV3-P2C-08: pure Ed25519 / RFC 8785 Signed Result V1 verifier (V-OUT).

Pure tests: no database, HTTP, Session or clock. The vector is the public ADR-004
section 3.4 vector (copied from the ADR). Other signatures are produced by Ed25519
keys generated in memory for the test and never written anywhere. The size and
depth limits are the PROPOSED_* values (PENDING_PARAMS) and are passed explicitly.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import inspect
import json
import subprocess
import sys
from datetime import datetime, timezone
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from gpu_marketplace.result_verification import verifier_v1
from gpu_marketplace.result_verification.verifier_v1 import (
    KEY_ABSENT,
    SIGNED_RESULT_V1_PREFIX,
    EvidenceIntegrityError,
    KeyAbsentV1,
    ParserDriftError,
    RejectedV1Receipt,
    RejectionCodeV1,
    SignedV1VerificationFault,
    TrustedInboxBindingV1,
    TrustedKeyError,
    TrustedWorkerKeyV1,
    VerifiedV1Receipt,
    VerifierInternalError,
    verify_signed_result_v1,
)
from gpu_marketplace.result_verification.wire_v1 import (
    PROPOSED_MAX_ENVELOPE_BYTES,
    PROPOSED_MAX_NESTING_DEPTH,
    SignedV1WireError,
    WireErrorCode,
    extract_signed_parts_v1,
)

# --- ADR-004 section 3.4 public vector ----------------------------------------------

VECTOR_PAYLOAD = {
    "schema_version": "1",
    "result_id": "11111111-1111-4111-8111-111111111111",
    "job_id": "22222222-2222-4222-8222-222222222222",
    "attempt_id": "33333333-3333-4333-8333-333333333333",
    "worker_id": "44444444-4444-4444-8444-444444444444",
    "listing_id": "55555555-5555-4555-8555-555555555555",
    "outcome": "SUCCESS",
    "failure_reason": None,
    "result_digest": "sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38",
    "finished_at": "2026-10-18T08:00:00.000000Z",
    "key_id": "66666666-6666-4666-8666-666666666666",
}
VECTOR_SIGNATURE = (
    "903mx-bzZtTjVuZR_r6BfuZt-ghu4IG_Tknq1_wkFTv4SFE91BJ_1uDXwt-AGU71cki9s-xzwU8QdRQOWQT2AQ"
)
VECTOR_PUBLIC_KEY = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
INBOX_ID = UUID("77777777-7777-4777-8777-777777777777")
OTHER_UUID = "aaaaaaaa-1111-4111-8111-111111111111"
LIMITS = {"max_bytes": PROPOSED_MAX_ENVELOPE_BYTES, "max_depth": PROPOSED_MAX_NESTING_DEPTH}
UUID_FIELDS = ("result_id", "job_id", "attempt_id", "worker_id", "listing_id", "key_id")


# --- helpers ------------------------------------------------------------------------


def payload_with(**changes) -> dict:
    payload = dict(VECTOR_PAYLOAD)
    payload.update(changes)
    return payload


def make_envelope(payload: dict | None = None, signature: str = VECTOR_SIGNATURE) -> bytes:
    return json.dumps(
        {
            "payload": VECTOR_PAYLOAD if payload is None else payload,
            "signature": signature,
            "signature_encoding": "base64url-no-padding",
        },
        separators=(",", ":"),
    ).encode("utf-8")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jcs_of(payload: dict) -> bytes:
    """JCS bytes of ``payload`` via the P2C-07 extractor (envelope signature is a placeholder)."""
    return extract_signed_parts_v1(make_envelope(payload), **LIMITS)[0]


def new_key() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()  # in memory only
    return private, private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def sign_message(private: Ed25519PrivateKey, message: bytes) -> str:
    return b64url(private.sign(message))


def sign_payload(private: Ed25519PrivateKey, payload: dict) -> str:
    return sign_message(private, SIGNED_RESULT_V1_PREFIX + jcs_of(payload))


def binding_for(raw: bytes, payload: dict | None = None, **over) -> TrustedInboxBindingV1:
    payload = VECTOR_PAYLOAD if payload is None else payload
    values = {
        "inbox_id": INBOX_ID,
        "result_id": UUID(payload["result_id"]),
        "envelope_sha256": hashlib.sha256(raw).digest(),
        "job_id": UUID(payload["job_id"]),
        "attempt_id": UUID(payload["attempt_id"]),
        "worker_id": UUID(payload["worker_id"]),
        "listing_id": UUID(payload["listing_id"]),
    }
    values.update(over)
    return TrustedInboxBindingV1(**values)


def key_for(payload: dict | None = None, public_key_raw=VECTOR_PUBLIC_KEY, **over) -> TrustedWorkerKeyV1:
    payload = VECTOR_PAYLOAD if payload is None else payload
    values = {
        "key_id": UUID(payload["key_id"]),
        "worker_id": UUID(payload["worker_id"]),
        "public_key_raw": public_key_raw,
        "retired_at": None,
    }
    values.update(over)
    return TrustedWorkerKeyV1(**values)


def verify(raw: bytes, binding, key, **limits):
    return verify_signed_result_v1(raw, binding=binding, key=key, **(limits or LIMITS))


def rejected_with(code: RejectionCodeV1, result) -> None:
    assert type(result) is RejectedV1Receipt
    assert result.rejection_code is code


# --- baseline: ADR-004 vector, field set, retained inputs ---------------------------


def test_adr004_vector_is_verified_with_every_field_populated() -> None:
    raw = make_envelope()
    binding = binding_for(raw)
    result = verify(raw, binding, key_for())
    assert type(result) is VerifiedV1Receipt
    assert result.inbox_id == INBOX_ID
    assert result.result_id == UUID(VECTOR_PAYLOAD["result_id"])
    assert result.envelope_sha256 == hashlib.sha256(raw).digest()
    assert (result.job_id, result.attempt_id) == (UUID(VECTOR_PAYLOAD["job_id"]), UUID(VECTOR_PAYLOAD["attempt_id"]))
    assert (result.worker_id, result.listing_id) == (UUID(VECTOR_PAYLOAD["worker_id"]), UUID(VECTOR_PAYLOAD["listing_id"]))
    assert result.key_id == UUID(VECTOR_PAYLOAD["key_id"])
    assert result.schema_version == "1"
    assert result.outcome == "SUCCESS" and result.failure_reason is None
    assert result.result_digest == VECTOR_PAYLOAD["result_digest"]
    assert result.finished_at_wire == VECTOR_PAYLOAD["finished_at"]
    assert len(result.payload_jcs_raw) == 500 and not result.payload_jcs_raw.startswith(SIGNED_RESULT_V1_PREFIX)
    assert len(result.signature_raw) == 64
    assert b64url(result.signature_raw) == VECTOR_SIGNATURE


def test_prefix_constant_is_the_adr004_domain_separator() -> None:
    assert SIGNED_RESULT_V1_PREFIX == b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n"
    assert len(SIGNED_RESULT_V1_PREFIX) == 33


def test_verified_receipt_has_exactly_the_section_6_6_1_fields() -> None:
    names = {field.name for field in dataclasses.fields(VerifiedV1Receipt) if not field.name.startswith("_")}
    assert names == {
        "inbox_id", "result_id", "envelope_sha256", "job_id", "attempt_id", "worker_id", "listing_id", "key_id",
        "schema_version", "outcome", "failure_reason", "result_digest", "finished_at_wire", "payload_jcs_raw",
        "signature_raw",
    }
    assert not hasattr(VerifiedV1Receipt, "original_envelope_raw") and "verified" not in names


def test_rejected_receipt_has_exactly_the_section_6_6_1_fields() -> None:
    names = {field.name for field in dataclasses.fields(RejectedV1Receipt) if not field.name.startswith("_")}
    assert names == {"inbox_id", "result_id", "envelope_sha256", "job_id", "attempt_id", "rejection_code"}


def test_rejection_code_enum_has_exactly_the_four_definitive_values() -> None:
    assert {code.value for code in RejectionCodeV1} == {
        "UNKNOWN_KEY", "KEY_WORKER_MISMATCH", "CONTEXT_MISMATCH", "INVALID_SIGNATURE",
    }
    assert len(RejectionCodeV1) == 4
    for housekeeping in ("NOT_SELECTED", "ALREADY_TERMINAL", "INVALID_STRUCTURE", "UNSUPPORTED_SCHEMA_VERSION"):
        assert housekeeping not in RejectionCodeV1.__members__


def test_function_signature_is_keyword_only_with_required_limits_and_no_active_key_count() -> None:
    parameters = inspect.signature(verify_signed_result_v1).parameters
    assert list(parameters) == ["original_envelope_raw", "binding", "key", "max_bytes", "max_depth"]
    for name in ("binding", "key", "max_bytes", "max_depth"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty
    assert not any("active" in name for name in parameters)


@pytest.mark.parametrize("drop", ["max_bytes", "max_depth", "binding", "key"])
def test_missing_required_keyword_is_a_type_error(drop) -> None:
    raw = make_envelope()
    arguments = {"binding": binding_for(raw), "key": key_for(), **LIMITS}
    del arguments[drop]
    with pytest.raises(TypeError):
        verify_signed_result_v1(raw, **arguments)


def test_positional_trusted_arguments_are_refused() -> None:
    raw = make_envelope()
    with pytest.raises(TypeError):
        verify_signed_result_v1(raw, binding_for(raw), key_for(), **LIMITS)  # type: ignore[misc]


# --- SIG-01 / SIG-03: other raw forms and signers -----------------------------------


def test_sig01_reordered_pretty_printed_envelope_still_verifies_with_its_own_sha() -> None:
    reordered = json.dumps(
        {
            "signature_encoding": "base64url-no-padding",
            "signature": VECTOR_SIGNATURE,
            "payload": dict(reversed(list(VECTOR_PAYLOAD.items()))),
        },
        indent=4,
    ).encode() + b"\n"
    assert reordered != make_envelope()
    result = verify(reordered, binding_for(reordered), key_for())
    assert type(result) is VerifiedV1Receipt
    assert result.envelope_sha256 == hashlib.sha256(reordered).digest()
    assert len(result.payload_jcs_raw) == 500


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"outcome": "FAILED", "failure_reason": "WORKER_FAULT"},
        {"outcome": "FAILED", "failure_reason": "JOB_FAULT"},
    ],
    ids=["success", "failed-worker-fault", "failed-job-fault"],
)
def test_sig03_a_generated_key_signing_each_outcome_is_verified(changes) -> None:
    private, public = new_key()
    payload = payload_with(**changes)
    raw = make_envelope(payload, sign_payload(private, payload))
    result = verify(raw, binding_for(raw, payload), key_for(payload, public_key_raw=public))
    assert type(result) is VerifiedV1Receipt
    assert (result.outcome, result.failure_reason) == (payload["outcome"], payload["failure_reason"])


# --- SIG-04: tampering a signed field keeps the old signature -----------------------

TAMPERED = {
    "result_digest": {"result_digest": "sha256:" + "1" * 64},
    "finished_at": {"finished_at": "2026-10-18T08:00:01.000000Z"},
    "outcome-failed-worker-fault": {"outcome": "FAILED", "failure_reason": "WORKER_FAULT"},
    "outcome-failed-job-fault": {"outcome": "FAILED", "failure_reason": "JOB_FAULT"},
    "result_id": {"result_id": OTHER_UUID},
    "job_id": {"job_id": OTHER_UUID},
    "attempt_id": {"attempt_id": OTHER_UUID},
    "worker_id": {"worker_id": OTHER_UUID},
    "listing_id": {"listing_id": OTHER_UUID},
    "key_id": {"key_id": OTHER_UUID},
}


@pytest.mark.parametrize("changes", list(TAMPERED.values()), ids=list(TAMPERED))
def test_sig04_changing_any_signed_field_with_the_old_signature_is_invalid_signature(changes) -> None:
    payload = payload_with(**changes)
    raw = make_envelope(payload, VECTOR_SIGNATURE)  # signature made for the untouched vector
    # Binding and key follow the tampered ids, so the flow reaches signature verification.
    result = verify(raw, binding_for(raw, payload), key_for(payload))
    rejected_with(RejectionCodeV1.INVALID_SIGNATURE, result)


def _signed_over(message_for_jcs) -> tuple[bytes, bytes]:
    private, public = new_key()
    message = message_for_jcs(jcs_of(VECTOR_PAYLOAD))
    raw = make_envelope(VECTOR_PAYLOAD, sign_message(private, message))
    return raw, public


@pytest.mark.parametrize(
    "build",
    [
        lambda jcs: jcs,
        lambda jcs: b"GPU-MARKETPLACE:SIGNED-RESULT:V2\n" + jcs,
        lambda jcs: b"GPU-MARKETPLACE:SIGNED-RESULT:V1" + jcs,
        lambda jcs: b"gpu-marketplace:signed-result:v1\n" + jcs,
        lambda jcs: SIGNED_RESULT_V1_PREFIX + jcs + b"\n",
        lambda jcs: SIGNED_RESULT_V1_PREFIX + jcs[:-1],
    ],
    ids=["no-prefix", "v2-prefix", "prefix-missing-lf", "lowercase-prefix", "trailing-lf", "truncated"],
)
def test_wrong_signed_bytes_are_invalid_signature(build) -> None:
    raw, public = _signed_over(build)
    result = verify(raw, binding_for(raw), key_for(public_key_raw=public))
    rejected_with(RejectionCodeV1.INVALID_SIGNATURE, result)


# --- SIG-05: key and Worker --------------------------------------------------------


def test_sig05_right_ids_but_another_public_key_is_invalid_signature() -> None:
    _, other_public = new_key()
    raw = make_envelope()
    rejected_with(RejectionCodeV1.INVALID_SIGNATURE, verify(raw, binding_for(raw), key_for(public_key_raw=other_public)))


def test_sig05_key_that_belongs_to_another_worker_is_key_worker_mismatch() -> None:
    raw = make_envelope()
    result = verify(raw, binding_for(raw), key_for(worker_id=UUID(OTHER_UUID)))
    rejected_with(RejectionCodeV1.KEY_WORKER_MISMATCH, result)


def test_key_absent_is_unknown_key() -> None:
    raw = make_envelope()
    rejected_with(RejectionCodeV1.UNKNOWN_KEY, verify(raw, binding_for(raw), KEY_ABSENT))
    assert isinstance(KEY_ABSENT, KeyAbsentV1)


@pytest.mark.parametrize("key", [None, object(), "KEY_ABSENT", b"", 0, {}], ids=["none", "object", "str", "bytes", "int", "dict"])
def test_anything_but_a_trusted_key_or_key_absent_is_a_type_error_never_unknown_key(key) -> None:
    raw = make_envelope()
    with pytest.raises(TypeError):
        verify(raw, binding_for(raw), key)


def test_sig09_a_retired_key_still_verifies() -> None:
    raw = make_envelope()
    retired = key_for(retired_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert type(verify(raw, binding_for(raw), retired)) is VerifiedV1Receipt


# --- SIG-06: context ----------------------------------------------------------------


@pytest.mark.parametrize("field", ["job_id", "attempt_id", "worker_id", "listing_id"])
def test_sig06_each_context_mismatch_is_rejected_with_the_examined_rows_identity(field) -> None:
    raw = make_envelope()
    binding = binding_for(raw, **{field: UUID(OTHER_UUID)})
    result = verify(raw, binding, key_for())
    rejected_with(RejectionCodeV1.CONTEXT_MISMATCH, result)
    assert result.inbox_id == INBOX_ID
    assert result.result_id == binding.result_id
    assert result.envelope_sha256 == binding.envelope_sha256
    assert (result.job_id, result.attempt_id) == (binding.job_id, binding.attempt_id)


# --- ordering -----------------------------------------------------------------------


def _bad_signature_case():
    payload = payload_with(result_digest="sha256:" + "1" * 64)
    raw = make_envelope(payload, VECTOR_SIGNATURE)
    return raw, payload


def test_context_mismatch_wins_over_an_invalid_signature() -> None:
    raw, payload = _bad_signature_case()
    result = verify(raw, binding_for(raw, payload, job_id=UUID(OTHER_UUID)), key_for(payload))
    rejected_with(RejectionCodeV1.CONTEXT_MISMATCH, result)


def test_context_mismatch_wins_over_an_absent_key() -> None:
    raw = make_envelope()
    result = verify(raw, binding_for(raw, listing_id=UUID(OTHER_UUID)), KEY_ABSENT)
    rejected_with(RejectionCodeV1.CONTEXT_MISMATCH, result)


def test_unknown_key_wins_over_an_invalid_signature() -> None:
    raw, payload = _bad_signature_case()
    rejected_with(RejectionCodeV1.UNKNOWN_KEY, verify(raw, binding_for(raw, payload), KEY_ABSENT))


def test_key_worker_mismatch_wins_over_an_invalid_signature() -> None:
    raw, payload = _bad_signature_case()
    result = verify(raw, binding_for(raw, payload), key_for(payload, worker_id=UUID(OTHER_UUID)))
    rejected_with(RejectionCodeV1.KEY_WORKER_MISMATCH, result)


# --- non-definitive faults are exceptions, never rejections -------------------------


def test_envelope_hash_mismatch_is_an_evidence_integrity_error() -> None:
    raw = make_envelope()
    binding = binding_for(raw, envelope_sha256=hashlib.sha256(raw + b" ").digest())
    with pytest.raises(EvidenceIntegrityError):
        verify(raw, binding, key_for())


def test_binding_result_id_that_differs_from_the_payload_is_an_evidence_integrity_error() -> None:
    raw = make_envelope()
    with pytest.raises(EvidenceIntegrityError):
        verify(raw, binding_for(raw, result_id=UUID(OTHER_UUID)), key_for())


@pytest.mark.parametrize("length", [0, 31, 33, 64])
def test_binding_hash_must_be_exactly_32_bytes(length) -> None:
    raw = make_envelope()
    with pytest.raises(ValueError):
        binding_for(raw, envelope_sha256=bytes(length))


@pytest.mark.parametrize("bad", ["a" * 32, bytearray(32), None, 32])
def test_binding_hash_must_be_bytes(bad) -> None:
    with pytest.raises(TypeError):
        binding_for(make_envelope(), envelope_sha256=bad)


def _admitted_but_unparseable(mutate):
    payload = dict(VECTOR_PAYLOAD)
    outer = json.loads(make_envelope(payload))
    mutate(outer)
    raw = json.dumps(outer).encode()
    return raw, binding_for(raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda outer: outer["payload"].update(extra="x"),
        lambda outer: outer["payload"].pop("job_id"),
        lambda outer: outer.update(signature_encoding="base64"),
        lambda outer: outer["payload"].update(schema_version="2"),
        lambda outer: outer.update(signature="short"),
    ],
    ids=["extra-field", "missing-field", "bad-encoding", "unsupported-schema-version", "bad-signature-text"],
)
def test_bytes_that_ingress_admitted_but_do_not_parse_are_parser_drift_not_a_rejection(mutate) -> None:
    raw, binding = _admitted_but_unparseable(mutate)
    with pytest.raises(ParserDriftError):
        verify(raw, binding, key_for())


def test_a_body_above_the_injected_limit_is_parser_drift() -> None:
    raw = make_envelope()
    with pytest.raises(ParserDriftError):
        verify(raw, binding_for(raw), key_for(), max_bytes=len(raw) - 1, max_depth=PROPOSED_MAX_NESTING_DEPTH)


@pytest.mark.parametrize("name", ["parse_signed_envelope_v1", "extract_signed_parts_v1"])
def test_regression_a_parser_failure_on_admitted_bytes_is_never_a_verdict(monkeypatch, name) -> None:
    def boom(*_args, **_kwargs):
        raise SignedV1WireError(WireErrorCode.FIELD_VALUE)

    monkeypatch.setattr(verifier_v1, name, boom)
    raw = make_envelope()
    with pytest.raises(ParserDriftError):
        verify(raw, binding_for(raw), key_for())


def test_an_unexpected_parser_exception_is_an_internal_fault_not_parser_drift_or_a_rejection(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise MemoryError("SECRET-MARKER-internal")

    monkeypatch.setattr(verifier_v1, "extract_signed_parts_v1", boom)
    raw = make_envelope()
    with pytest.raises(VerifierInternalError):
        verify(raw, binding_for(raw), key_for())


def test_a_key_row_for_another_key_id_is_a_trusted_key_error() -> None:
    raw = make_envelope()
    with pytest.raises(TrustedKeyError):
        verify(raw, binding_for(raw), key_for(key_id=UUID(OTHER_UUID)))


@pytest.mark.parametrize(
    "bad_key",
    [bytes(31), bytes(33), bytes(0), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", bytearray(VECTOR_PUBLIC_KEY), None, 32],
    ids=["31-bytes", "33-bytes", "empty", "hex-str", "bytearray", "none", "int"],
)
def test_unusable_public_key_material_is_a_trusted_key_error(bad_key) -> None:
    raw = make_envelope()
    with pytest.raises(TrustedKeyError):
        verify(raw, binding_for(raw), key_for(public_key_raw=bad_key))


def test_a_failing_ed25519_primitive_is_an_internal_fault_and_never_invalid_signature(monkeypatch) -> None:
    class BrokenKey:
        def verify(self, *_args):
            raise RuntimeError("SECRET-MARKER-primitive")

    class BrokenFactory:
        @staticmethod
        def from_public_bytes(_raw):
            return BrokenKey()

    monkeypatch.setattr(verifier_v1, "Ed25519PublicKey", BrokenFactory)
    raw = make_envelope()
    with pytest.raises(VerifierInternalError):
        verify(raw, binding_for(raw), key_for())


def test_every_non_definitive_fault_shares_one_root_and_is_not_a_type_error() -> None:
    for fault in (EvidenceIntegrityError, ParserDriftError, TrustedKeyError, VerifierInternalError):
        assert issubclass(fault, SignedV1VerificationFault)
        assert not issubclass(fault, TypeError)
    assert issubclass(SignedV1VerificationFault, Exception)


# --- input type validation (programming errors) -------------------------------------


@pytest.mark.parametrize(
    "bad_raw", ["text", bytearray(b"{}"), memoryview(b"{}"), None, 7], ids=["str", "bytearray", "memoryview", "none", "int"]
)
def test_raw_must_be_immutable_bytes(bad_raw) -> None:
    raw = make_envelope()
    with pytest.raises(TypeError):
        verify(bad_raw, binding_for(raw), key_for())


@pytest.mark.parametrize("bad_binding", [None, object(), {"inbox_id": INBOX_ID}], ids=["none", "object", "dict"])
def test_binding_must_be_a_trusted_inbox_binding(bad_binding) -> None:
    with pytest.raises(TypeError):
        verify(make_envelope(), bad_binding, key_for())


@pytest.mark.parametrize("bad", [True, False, 1.5, None, "16384"])
def test_limits_must_be_integers(bad) -> None:
    raw = make_envelope()
    for name in ("max_bytes", "max_depth"):
        limits = dict(LIMITS)
        limits[name] = bad
        with pytest.raises(TypeError):
            verify(raw, binding_for(raw), key_for(), **limits)


@pytest.mark.parametrize("bad", [0, -1])
def test_limits_must_be_positive(bad) -> None:
    raw = make_envelope()
    for name in ("max_bytes", "max_depth"):
        limits = dict(LIMITS)
        limits[name] = bad
        with pytest.raises(ValueError):
            verify(raw, binding_for(raw), key_for(), **limits)


@pytest.mark.parametrize(
    "field,bad",
    [("inbox_id", "x"), ("result_id", None), ("job_id", 1), ("attempt_id", b"x" * 16), ("worker_id", object()), ("listing_id", "x")],
)
def test_binding_ids_must_be_uuids(field, bad) -> None:
    with pytest.raises(TypeError):
        binding_for(make_envelope(), **{field: bad})


@pytest.mark.parametrize("field,bad", [("key_id", "x"), ("worker_id", None), ("retired_at", "2026-11-01"), ("retired_at", 5)])
def test_key_snapshot_field_types_are_checked(field, bad) -> None:
    with pytest.raises(TypeError):
        key_for(**{field: bad})


# --- receipts are issued only by the verifier ---------------------------------------


def _verified_fields() -> dict:
    raw = make_envelope()
    receipt = verify(raw, binding_for(raw), key_for())
    return {f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt) if not f.name.startswith("_")}


def test_receipts_cannot_be_built_outside_the_verifier() -> None:
    with pytest.raises(TypeError):
        VerifiedV1Receipt(**_verified_fields())
    with pytest.raises(TypeError):
        VerifiedV1Receipt(**_verified_fields(), _issuer=object())
    with pytest.raises(TypeError):
        RejectedV1Receipt(INBOX_ID, UUID(VECTOR_PAYLOAD["result_id"]), bytes(32), INBOX_ID, INBOX_ID, RejectionCodeV1.UNKNOWN_KEY)
    with pytest.raises(TypeError):
        RejectedV1Receipt(
            INBOX_ID, UUID(VECTOR_PAYLOAD["result_id"]), bytes(32), INBOX_ID, INBOX_ID, RejectionCodeV1.UNKNOWN_KEY,
            _issuer=object(),
        )


def test_a_rejected_receipt_cannot_carry_a_code_outside_the_enum() -> None:
    raw = make_envelope()
    result = verify(raw, binding_for(raw), KEY_ABSENT)
    for bad in ("NOT_SELECTED", "UNKNOWN_KEY", None):
        with pytest.raises(TypeError):
            dataclasses.replace(result, rejection_code=bad)


def test_receipts_are_frozen() -> None:
    raw = make_envelope()
    verified = verify(raw, binding_for(raw), key_for())
    rejected = verify(raw, binding_for(raw), KEY_ABSENT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        verified.outcome = "FAILED"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rejected.rejection_code = RejectionCodeV1.INVALID_SIGNATURE  # type: ignore[misc]


def test_receipt_repr_never_shows_signature_or_jcs_bytes() -> None:
    raw = make_envelope()
    verified = verify(raw, binding_for(raw), key_for())
    text = repr(verified)
    assert "signature_raw" not in text and "payload_jcs_raw" not in text
    assert VECTOR_SIGNATURE not in text and verified.signature_raw.hex() not in text
    assert str(verified.payload_jcs_raw) not in text


# --- redaction ----------------------------------------------------------------------

MARKER = "SECRET-MARKER-9f3a"


def _fault_cases():
    raw = make_envelope()
    yield "evidence", EvidenceIntegrityError, (raw, binding_for(raw, envelope_sha256=bytes(32)), key_for())
    marked = json.dumps({**json.loads(raw), MARKER: 1}).encode()
    yield "parser", ParserDriftError, (marked, binding_for(marked), key_for())
    yield "key-id", TrustedKeyError, (raw, binding_for(raw), key_for(key_id=UUID(OTHER_UUID)))
    yield "key-bytes", TrustedKeyError, (raw, binding_for(raw), key_for(public_key_raw=MARKER.encode()))


@pytest.mark.parametrize("label,fault,arguments", list(_fault_cases()), ids=[c[0] for c in _fault_cases()])
def test_faults_never_echo_input_keys_or_signatures(label, fault, arguments) -> None:
    raw, binding, key = arguments
    with pytest.raises(fault) as caught:
        verify(raw, binding, key)
    error = caught.value
    forbidden = (MARKER, VECTOR_SIGNATURE, VECTOR_PUBLIC_KEY.hex(), raw.decode("latin-1"))
    for text in (str(error), repr(error), repr(error.args)):
        for secret in forbidden:
            assert secret not in text
    assert error.__cause__ is None and error.__suppress_context__ is True


def test_internal_faults_do_not_echo_the_underlying_exception(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError(MARKER + VECTOR_SIGNATURE)

    monkeypatch.setattr(verifier_v1, "extract_signed_parts_v1", boom)
    raw = make_envelope()
    with pytest.raises(VerifierInternalError) as caught:
        verify(raw, binding_for(raw), key_for())
    error = caught.value
    for text in (str(error), repr(error), repr(error.args)):
        assert MARKER not in text and VECTOR_SIGNATURE not in text
    assert error.__cause__ is None and error.__suppress_context__ is True


# --- purity -------------------------------------------------------------------------


def test_importing_the_verifier_pulls_in_no_database_http_or_logging_module() -> None:
    code = (
        "import sys, json\n"
        "import gpu_marketplace.result_verification.verifier_v1\n"
        "banned = ('sqlalchemy', 'fastapi', 'httpx', 'psycopg', 'logging', 'starlette', 'socket')\n"
        "print(json.dumps([m for m in banned if m in sys.modules]))\n"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == []
