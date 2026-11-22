"""Structural Signed Result V1 identity binding; no signature-verification claim."""
from __future__ import annotations

from base64 import urlsafe_b64encode
import json
from uuid import UUID

import pytest

from gpu_marketplace_simulator.signed_result_v1 import (
    InvalidSignedResultV1,
    validate_receipt_binding_v1,
)


ATTEMPT_ID = UUID("44444444-4444-4444-8444-444444444444")
RESULT_ID = UUID("77777777-7777-4777-8777-777777777777")


def payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "result_id": str(RESULT_ID),
        "job_id": "33333333-3333-4333-8333-333333333333",
        "attempt_id": str(ATTEMPT_ID),
        "worker_id": "11111111-1111-4111-8111-111111111111",
        "listing_id": "22222222-2222-4222-8222-222222222222",
        "outcome": "SUCCESS",
        "failure_reason": None,
        "result_digest": "sha256:" + "a" * 64,
        "finished_at": "2026-10-18T08:01:00.000000Z",
        "key_id": "88888888-8888-4888-8888-888888888888",
    }


def envelope_bytes(item: dict[str, object] | None = None) -> bytes:
    signature = urlsafe_b64encode(bytes(64)).rstrip(b"=").decode("ascii")
    return json.dumps(
        {"payload": payload() if item is None else item,
         "signature": signature,
         "signature_encoding": "base64url-no-padding"},
        separators=(",", ":"),
    ).encode("utf-8")


def test_v1_exact_fields_and_attempt_result_binding() -> None:
    validate_receipt_binding_v1(
        envelope_bytes(), outer_result_id=RESULT_ID, expected_attempt_id=ATTEMPT_ID
    )


def test_v1_rejects_wrong_attempt_and_wrong_outer_result_id() -> None:
    with pytest.raises(InvalidSignedResultV1, match="attempt_id"):
        validate_receipt_binding_v1(
            envelope_bytes(),
            outer_result_id=RESULT_ID,
            expected_attempt_id=UUID("55555555-5555-4555-8555-555555555555"),
        )
    with pytest.raises(InvalidSignedResultV1, match="result_id"):
        validate_receipt_binding_v1(
            envelope_bytes(),
            outer_result_id=UUID("99999999-9999-4999-8999-999999999999"),
            expected_attempt_id=ATTEMPT_ID,
        )


@pytest.mark.parametrize(
    "mutation", ("missing", "extra", "version", "enum", "reason", "digest", "time")
)
def test_v1_rejects_invalid_or_ambiguous_payload_fields(mutation: str) -> None:
    item = payload()
    if mutation == "missing":
        del item["key_id"]
    elif mutation == "extra":
        item["unexpected"] = "field"
    elif mutation == "version":
        item["schema_version"] = 1
    elif mutation == "enum":
        item["outcome"] = "success"
    elif mutation == "reason":
        item["failure_reason"] = "SYSTEM_FAULT"
    elif mutation == "digest":
        item["result_digest"] = "SHA256:" + "a" * 64
    else:
        item["finished_at"] = "2026-02-30T08:01:00.000000Z"
    with pytest.raises(InvalidSignedResultV1):
        validate_receipt_binding_v1(
            envelope_bytes(item), outer_result_id=RESULT_ID,
            expected_attempt_id=ATTEMPT_ID,
        )


def test_v1_rejects_outer_shape_signature_and_encoding_errors() -> None:
    valid = json.loads(envelope_bytes())
    cases = []
    cases.append({"payload": valid["payload"], "signature": valid["signature"]})
    cases.append({**valid, "unexpected": "field"})
    cases.append({**valid, "signature_encoding": "base64"})
    cases.append({**valid, "signature": valid["signature"][:-1] + "!"})
    cases.append({**valid, "signature": valid["signature"] + "=="})
    for invalid in cases:
        with pytest.raises(InvalidSignedResultV1):
            validate_receipt_binding_v1(
                json.dumps(invalid, separators=(",", ":")).encode(),
                outer_result_id=RESULT_ID,
                expected_attempt_id=ATTEMPT_ID,
            )


@pytest.mark.parametrize(
    "raw",
    (
        b"{",
        b'{"payload":{},"payload":{},"signature":"x","signature_encoding":"base64url-no-padding"}',
        b'{"payload":{"schema_version":"1","result_id":NaN},"signature":"x",'
        b'"signature_encoding":"base64url-no-padding"}',
    ),
)
def test_v1_rejects_malformed_json_duplicate_members_and_non_json_constants(raw: bytes) -> None:
    with pytest.raises(InvalidSignedResultV1):
        validate_receipt_binding_v1(
            raw, outer_result_id=RESULT_ID, expected_attempt_id=ATTEMPT_ID
        )


def test_v1_rejects_duplicate_member_inside_payload() -> None:
    valid = json.loads(envelope_bytes())
    encoded_payload = json.dumps(valid["payload"], separators=(",", ":"))
    duplicate_payload = (
        encoded_payload[:-1]
        + ',"attempt_id":"44444444-4444-4444-8444-444444444444"}'
    )
    raw = (
        '{"payload":' + duplicate_payload + ',"signature":"' + valid["signature"]
        + '","signature_encoding":"base64url-no-padding"}'
    ).encode()
    with pytest.raises(InvalidSignedResultV1, match="duplicate"):
        validate_receipt_binding_v1(
            raw, outer_result_id=RESULT_ID, expected_attempt_id=ATTEMPT_ID
        )
