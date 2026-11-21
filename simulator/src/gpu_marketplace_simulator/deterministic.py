"""Pure demo-v1-public1 simulator core; no database or protected-reference access.

Only the fixed ASCII/UUIDv4/integer schema below is accepted. For these values,
compact sorted-key JSON is byte-equivalent to RFC 8785 JCS; this helper is NOT
a general-purpose JCS encoder for arbitrary floats or Unicode data.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from uuid import UUID

ALGORITHM_VERSION = "demo-v1-public1"
WORKLOAD_PROFILE = "demo-v1"
_PREFIX = b"GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n"
_MAX_UINT32 = 1 << 32
_MAX_INT32 = (1 << 31) - 1


@dataclass(frozen=True, slots=True)
class SimulationInput:
    job_id: UUID
    listing_id: UUID
    worker_id: UUID
    requested_gpu_count: int
    duration_seconds: int
    workload_profile: str = WORKLOAD_PROFILE

    def __post_init__(self) -> None:
        for name in ("job_id", "listing_id", "worker_id"):
            value = getattr(self, name)
            if not isinstance(value, UUID) or value.version != 4:
                raise ValueError(f"{name} must be a UUIDv4")
        for name in ("requested_gpu_count", "duration_seconds"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= _MAX_INT32:
                raise ValueError(f"{name} must be a positive signed-32-bit integer")
        if self.workload_profile != WORKLOAD_PROFILE:
            raise ValueError("only the frozen demo-v1 workload is supported")


@dataclass(frozen=True, slots=True)
class SimulatedResult:
    output: dict[str, object]
    result_digest: str


def simulate(data: SimulationInput) -> SimulatedResult:
    """Derive the nine-field public mock output from the frozen input.

    The protected seed and expected result are NEVER read from the database or
    accepted from callers. This function performs no I/O or signing.
    """
    canonical_input = canonical_input_bytes(data)
    bucket = _uniform("outcome", canonical_input, 100)
    if bucket < 80:
        outcome, reason = "SUCCESS", None
    elif bucket < 90:
        outcome, reason = "FAILED", "WORKER_FAULT"
    else:
        outcome, reason = "FAILED", "JOB_FAULT"

    output: dict[str, object] = {
        "duration_seconds": data.duration_seconds,
        "failure_reason": reason,
        "job_id": str(data.job_id),
        "listing_id": str(data.listing_id),
        "outcome": outcome,
        "requested_gpu_count": data.requested_gpu_count,
        "schema_version": WORKLOAD_PROFILE,
        "work_units": _uniform("work_units", canonical_input, 1_000_000),
        "workload_profile": WORKLOAD_PROFILE,
    }
    digest = hashlib.sha256(_canonical_json(output)).hexdigest()
    return SimulatedResult(output=output, result_digest=f"sha256:{digest}")


def canonical_input_bytes(data: SimulationInput) -> bytes:
    """The precise seven-key reference input used by demo-v1-public1."""
    return _canonical_json({
        "algorithm_version": ALGORITHM_VERSION,
        "duration_seconds": data.duration_seconds,
        "job_id": str(data.job_id),
        "listing_id": str(data.listing_id),
        "requested_gpu_count": data.requested_gpu_count,
        "worker_id": str(data.worker_id),
        "workload_profile": data.workload_profile,
    })


def _derive_seed_value(data: SimulationInput) -> int:
    """Internal compatibility oracle for frozen reference fixtures; not output."""
    digest = _hash_domain("seed", 0, canonical_input_bytes(data))
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _uniform(domain: str, canonical_input: bytes, size: int) -> int:
    if not 1 <= size <= _MAX_UINT32:
        raise ValueError("range must fit in UINT32")
    limit = (_MAX_UINT32 // size) * size
    for counter in range(_MAX_UINT32):
        raw = int.from_bytes(_hash_domain(domain, counter, canonical_input)[:4], "big")
        if raw < limit:
            return raw % size
    raise RuntimeError("rejection sampling exhausted all UINT32 counters")


def _hash_domain(domain: str, counter: int, canonical_input: bytes) -> bytes:
    if domain not in ("seed", "outcome", "work_units"):
        raise ValueError("unknown deterministic domain")
    if not 0 <= counter < _MAX_UINT32:
        raise ValueError("counter is outside UINT32")
    return hashlib.sha256(
        _PREFIX
        + domain.encode("ascii")
        + b"\n"
        + canonical_input
        + b"\n"
        + counter.to_bytes(4, "big")
    ).digest()


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
