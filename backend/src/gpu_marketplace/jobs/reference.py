"""Deterministic protected simulation reference generator (approved GPU-005-B)."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from gpu_marketplace.jobs.submit_ports import SimulationReference

ALGORITHM_VERSION = "demo-v1-public1"
WORKLOAD_PROFILE = "demo-v1"
_PREFIX = b"GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n"
_MAX_UINT32 = 1 << 32


def create_simulation_reference(
    *,
    job_id: UUID,
    listing_id: UUID,
    worker_id: UUID,
    requested_gpu_count: int,
    duration_seconds: int,
) -> SimulationReference:
    """Create the fixed-version reference without exposing it to public DTOs.

    All string values are canonical ASCII identifiers/constants and all numbers
    are signed-32-bit integers. Under those exact input constraints, compact
    sorted-key JSON bytes are identical to the RFC 8785 JCS representation.
    """
    source = {
        "algorithm_version": ALGORITHM_VERSION,
        "duration_seconds": duration_seconds,
        "job_id": str(job_id),
        "listing_id": str(listing_id),
        "requested_gpu_count": requested_gpu_count,
        "worker_id": str(worker_id),
        "workload_profile": WORKLOAD_PROFILE,
    }
    canonical_input = _canonical_json(source)
    seed_digest = _hash_domain("seed", 0, canonical_input)
    seed_value = int.from_bytes(seed_digest[:8], "big") & 0x7FFFFFFFFFFFFFFF

    outcome_bucket = _uniform("outcome", canonical_input, 100)
    if outcome_bucket < 80:
        outcome, failure_reason = "SUCCESS", None
    elif outcome_bucket < 90:
        outcome, failure_reason = "FAILED", "WORKER_FAULT"
    else:
        outcome, failure_reason = "FAILED", "JOB_FAULT"

    work_units = _uniform("work_units", canonical_input, 1_000_000)
    expected_output = {
        "duration_seconds": duration_seconds,
        "failure_reason": failure_reason,
        "job_id": str(job_id),
        "listing_id": str(listing_id),
        "outcome": outcome,
        "requested_gpu_count": requested_gpu_count,
        "schema_version": WORKLOAD_PROFILE,
        "work_units": work_units,
        "workload_profile": WORKLOAD_PROFILE,
    }
    digest = hashlib.sha256(_canonical_json(expected_output)).hexdigest()
    return SimulationReference(
        seed_value=seed_value,
        algorithm_version=ALGORITHM_VERSION,
        expected_outcome=outcome,
        expected_failure_reason=failure_reason,
        expected_digest=f"sha256:{digest}",
    )


def _uniform(domain: str, canonical_input: bytes, size: int) -> int:
    limit = (_MAX_UINT32 // size) * size
    for counter in range(_MAX_UINT32):
        raw = int.from_bytes(_hash_domain(domain, counter, canonical_input)[:4], "big")
        if raw < limit:
            return raw % size
    raise RuntimeError("deterministic reference rejection counter exhausted")


def _hash_domain(domain: str, counter: int, canonical_input: bytes) -> bytes:
    if not 0 <= counter < _MAX_UINT32:
        raise ValueError("reference counter is outside UINT32")
    return hashlib.sha256(
        _PREFIX
        + domain.encode("utf-8")
        + b"\n"
        + canonical_input
        + b"\n"
        + counter.to_bytes(4, "big")
    ).digest()


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
