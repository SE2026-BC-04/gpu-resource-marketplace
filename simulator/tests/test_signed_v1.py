from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
import pytest

from gpu_marketplace_simulator.signed_v1 import (
    SIGNATURE_ENCODING,
    SIGNING_PREFIX,
    PayloadValidationError,
    SignedResultV1Envelope,
    SigningError,
    canonical_payload_bytes,
    payload_from_json,
    payload_from_mapping,
    sign_payload,
)


PUBLIC_KEY_HEX = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
# Public RFC 8032 test seed; test-only and not a production credential.
PUBLIC_TEST_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
VECTOR_SIGNATURE = (
    "903mx-bzZtTjVuZR_r6BfuZt-ghu4IG_Tknq1_wkFTv4SFE91BJ_1uDXwt-AGU71cki9s-xzwU8QdRQOWQT2AQ"
)
VECTOR_CANONICAL = (
    '{"attempt_id":"33333333-3333-4333-8333-333333333333","failure_reason":null,'
    '"finished_at":"2026-10-18T08:00:00.000000Z","job_id":"22222222-2222-4222-8222-222222222222",'
    '"key_id":"66666666-6666-4666-8666-666666666666","listing_id":"55555555-5555-4555-8555-555555555555",'
    '"outcome":"SUCCESS","result_digest":"sha256:09f2515ffa28dcb5b292d813bab12b968bcad73292ef2a98d63ca3ed77e2af38",'
    '"result_id":"11111111-1111-4111-8111-111111111111","schema_version":"1",'
    '"worker_id":"44444444-4444-4444-8444-444444444444"}'
)


def valid_payload() -> dict[str, object]:
    return {
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


class FixedTestSigner:
    def __init__(self) -> None:
        self.private_key = Ed25519PrivateKey.from_private_bytes(PUBLIC_TEST_SEED)
        self.identity: tuple[str, str] | None = None

    def sign(self, *, worker_id: str, key_id: str, message: bytes) -> bytes:
        self.identity = (worker_id, key_id)
        return self.private_key.sign(message)


def test_adr004_exact_schema_canonical_bytes_and_public_vector() -> None:
    payload = payload_from_mapping(valid_payload())
    assert set(type(payload).model_fields) == {
        "schema_version", "result_id", "job_id", "attempt_id", "worker_id",
        "listing_id", "outcome", "failure_reason", "result_digest",
        "finished_at", "key_id",
    }
    canonical = canonical_payload_bytes(payload)
    assert canonical == VECTOR_CANONICAL.encode("utf-8")
    assert not canonical.startswith(b"\xef\xbb\xbf") and not canonical.endswith(b"\n")
    assert SIGNING_PREFIX == b"GPU-MARKETPLACE:SIGNED-RESULT:V1\n"
    assert len(SIGNING_PREFIX + VECTOR_CANONICAL.encode("utf-8")) == 533
    assert (
        __import__("hashlib").sha256(SIGNING_PREFIX + VECTOR_CANONICAL.encode("utf-8")).hexdigest()
        == "152b4b0f1dd8c4a1ed96524247dc682892a0cfa661fbc396d32af5bfdcd16728"
    )


def test_signs_exact_vector_and_emits_only_approved_envelope_fields() -> None:
    payload = payload_from_mapping(valid_payload())
    signer = FixedTestSigner()
    signed = sign_payload(payload, signer)
    assert signer.identity == (payload.worker_id, payload.key_id)
    assert signed.signature == VECTOR_SIGNATURE
    assert len(signed.signature_bytes) == 64
    assert len(signed.signature) == 86
    assert signed.envelope().signature_encoding == SIGNATURE_ENCODING
    assert set(signed.envelope().model_dump()) == {"payload", "signature", "signature_encoding"}
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(
        signed.signature_bytes, signed.signing_message
    )
    assert sign_payload(payload, FixedTestSigner()).signature_bytes == signed.signature_bytes


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("key_id"),
        lambda value: value.update(extra="no"),
        lambda value: value.update(schema_version=1),
        lambda value: value.update(result_id="11111111111141118111111111111111"),
        lambda value: value.update(worker_id="AAAAAAAA-4444-4444-8444-444444444444"),
        lambda value: value.update(outcome="success"),
        lambda value: value.update(failure_reason="SYSTEM_FAULT"),
        lambda value: value.update(result_digest="sha256:" + "A" * 64),
        lambda value: value.update(finished_at="2026-10-18T08:00:00Z"),
        lambda value: value.update(finished_at="2026-02-30T08:00:00.000000Z"),
    ],
)
def test_invalid_payloads_fail_closed(mutate) -> None:
    value = valid_payload()
    mutate(value)
    with pytest.raises(PayloadValidationError):
        payload_from_mapping(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("result_id", True),
        ("outcome", 0),
        ("failure_reason", False),
        ("result_digest", 123),
        ("finished_at", None),
    ],
)
def test_payload_fields_reject_wrong_json_primitive_types(field: str, value: object) -> None:
    with pytest.raises(PayloadValidationError):
        payload_from_mapping(valid_payload() | {field: value})


def test_outcome_failure_reason_combinations_are_exact() -> None:
    for reason in ("WORKER_FAULT", "JOB_FAULT"):
        valid_failed = valid_payload() | {"outcome": "FAILED", "failure_reason": reason}
        assert payload_from_mapping(valid_failed).failure_reason == reason
    with pytest.raises(PayloadValidationError):
        payload_from_mapping(valid_payload() | {"outcome": "FAILED"})
    with pytest.raises(PayloadValidationError):
        payload_from_mapping(valid_payload() | {"failure_reason": "JOB_FAULT"})


def test_json_parser_rejects_duplicate_keys_and_non_json_constants() -> None:
    duplicate = json.dumps(valid_payload())[:-1] + ',"outcome":"FAILED"}'
    with pytest.raises(PayloadValidationError, match="duplicate"):
        payload_from_json(duplicate)
    with pytest.raises(PayloadValidationError, match="constant"):
        payload_from_json('{"value":NaN}')
    with pytest.raises(PayloadValidationError, match="UTF-8"):
        payload_from_json(b"\xff")


def test_signature_rejects_tampering_wrong_key_and_bad_provider_output() -> None:
    payload = payload_from_mapping(valid_payload())
    signed = sign_payload(payload, FixedTestSigner())
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    with pytest.raises(InvalidSignature):
        public_key.verify(signed.signature_bytes, signed.signing_message + b"x")
    with pytest.raises(InvalidSignature):
        public_key.verify(
            signed.signature_bytes,
            b"GPU-MARKETPLACE:SIGNED-RESULT:V2\n" + signed.canonical_payload,
        )
    wrong_key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(InvalidSignature):
        wrong_key.verify(signed.signature_bytes, signed.signing_message)
    with pytest.raises(SigningError):
        sign_payload(payload, type("BadSigner", (), {"sign": lambda *_args, **_kwargs: b"short"})())


def test_envelope_rejects_noncanonical_signature_encodings() -> None:
    payload = payload_from_mapping(valid_payload())
    with pytest.raises(ValueError):
        SignedResultV1Envelope(
            payload=payload,
            signature=VECTOR_SIGNATURE + "=",
            signature_encoding=SIGNATURE_ENCODING,
        )
    with pytest.raises(ValueError):
        SignedResultV1Envelope(payload=payload, signature="A" * 86, signature_encoding="other")


def test_node_independent_jcs_and_ed25519_verification() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable; independent runtime interop not run")
    payload = valid_payload()
    # Deliberately reverse insertion order; the Node oracle canonicalizes independently.
    payload = dict(reversed(list(payload.items())))
    signed = sign_payload(payload_from_mapping(payload), FixedTestSigner())
    script = Path(__file__).parents[1] / "tools" / "p2e10_node_verify.cjs"
    process = subprocess.run(
        [node, str(script)],
        input=json.dumps(
            {
                "payload": payload,
                "signature": signed.signature,
                "public_key_hex": PUBLIC_KEY_HEX,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(process.stdout)
    assert result == {"canonical": VECTOR_CANONICAL, "valid": True, "tampered_valid": False}
