"""Compatibility adapter for the canonical Signed Result V1 validator.

``signed_v1.envelope_from_json`` is the only structural parser. This module
retains the older cache-adapter API and adds dispatch identity binding only.
It does not verify Ed25519 signatures.
"""
from __future__ import annotations

from uuid import UUID

from gpu_marketplace_simulator.signed_v1 import (
    EnvelopeValidationError,
    envelope_from_json,
)


class InvalidSignedResultV1(ValueError):
    """Malformed canonical envelope or mismatch with the admitted dispatch."""


def validate_receipt_binding_v1(
    raw_envelope: bytes,
    *,
    outer_result_id: UUID,
    expected_attempt_id: UUID,
    expected_job_id: UUID,
    expected_worker_id: UUID,
    expected_listing_id: UUID,
) -> None:
    """Use the canonical V1 parser, then bind its five identities unchanged."""
    try:
        parsed = envelope_from_json(raw_envelope)
    except EnvelopeValidationError as error:
        raise InvalidSignedResultV1(str(error)) from error

    payload = parsed.envelope.payload
    expected = {
        "result_id": outer_result_id,
        "attempt_id": expected_attempt_id,
        "job_id": expected_job_id,
        "worker_id": expected_worker_id,
        "listing_id": expected_listing_id,
    }
    for name, value in expected.items():
        if type(value) is not UUID or value.version != 4:
            raise InvalidSignedResultV1(f"expected {name} must be UUIDv4")
        if getattr(payload, name) != str(value):
            raise InvalidSignedResultV1(f"payload {name} differs from its expected identity")
