"""Cross-runtime G2-A-INTEROP-01: independently encoded Node.js oracle.

The Node implementation is not imported from Python and has its own canonical
serializer, SHA-256, counter framing and rejection sampler. These tests compare
byte-exact traces for frozen and representative valid, non-vector inputs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

import pytest

from gpu_marketplace_simulator.deterministic import (
    SimulationInput,
    _derive_seed_value,
    _hash_domain,
    canonical_input_bytes,
    simulate,
)

NODE_ORACLE = Path(__file__).resolve().parents[1] / "tools" / "p2e09_node_oracle.cjs"
PREFIX = b"GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n"
WORKER = UUID("11111111-1111-4111-8111-111111111111")
LISTING = UUID("22222222-2222-4222-8222-222222222222")
JOB = UUID("33333333-3333-4333-8333-333333333333")
V4_JOB = UUID("33333333-3333-4333-8333-000000000c02")


@pytest.mark.parametrize(
    ("job", "listing", "worker", "gpu", "duration"),
    (
        (JOB, LISTING, WORKER, 2, 60),  # V1
        (JOB, LISTING, WORKER, 2, 2),  # V2
        (JOB, LISTING, WORKER, 2, 1),  # V3
        (V4_JOB, LISTING, WORKER, 2, 60),  # V4: counter-0 rejection
        (UUID("a6b2c3d4-1234-4abc-8def-0123456789ab"), LISTING, WORKER, 1, 3),
        (JOB, UUID("aabbccdd-eeee-4fff-8999-aabbccddeeff"), WORKER, 12, 3600),
        (JOB, LISTING, UUID("ffffeeee-dddd-4ccc-8bbb-aaaaaaaaaaaa"), 2**31 - 1, 1),
    ),
    ids=("V1", "V2", "V3", "V4", "nonvector-job", "nonvector-listing",
         "nonvector-worker-int32-max"),
)
def test_independent_node_byte_oracle(
    job: UUID, listing: UUID, worker: UUID, gpu: int, duration: int
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for mandatory G2-A-INTEROP-01; interop cannot be skipped")

    data = SimulationInput(
        job_id=job, listing_id=listing, worker_id=worker,
        requested_gpu_count=gpu, duration_seconds=duration,
    )
    fixture = {
        "job_id": str(job), "listing_id": str(listing), "worker_id": str(worker),
        "requested_gpu_count": gpu, "duration_seconds": duration,
        "workload_profile": "demo-v1",
    }
    completed = subprocess.run(
        [node, str(NODE_ORACLE)], input=json.dumps(fixture),
        text=True, capture_output=True, check=True, timeout=15,
    )
    trace = json.loads(completed.stdout)

    canonical_input = canonical_input_bytes(data)
    assert bytes.fromhex(trace["canonical_input_hex"]) == canonical_input
    assert trace["seed_value"] == str(_derive_seed_value(data))
    seed_preimage = PREFIX + b"seed\n" + canonical_input + b"\n" + (0).to_bytes(4, "big")
    assert bytes.fromhex(trace["seed_hash_input_hex"]) == seed_preimage
    assert trace["seed_hash_hex"] == _hash_domain("seed", 0, canonical_input).hex()
    assert hashlib.sha256(seed_preimage).hexdigest() == trace["seed_hash_hex"]

    for domain, size in (("outcome", 100), ("work_units", 1_000_000)):
        group = trace[domain]
        assert group["probes"], "must record at least one raw uint32 draw"
        limit = ((1 << 32) // size) * size
        for i, probe in enumerate(group["probes"]):
            counter = probe["counter"]
            assert counter == i
            preimage = (
                PREFIX + domain.encode("ascii") + b"\n" +
                canonical_input + b"\n" + counter.to_bytes(4, "big")
            )
            digest = _hash_domain(domain, counter, canonical_input)
            raw = int.from_bytes(digest[:4], "big")
            assert bytes.fromhex(probe["hash_input_hex"]) == preimage
            assert probe["hash_hex"] == digest.hex()
            assert probe["raw"] == raw
            assert probe["accepted"] is (raw < limit)
            if i < len(group["probes"]) - 1:
                assert raw >= limit
            else:
                assert raw < limit
                assert group["value"] == raw % size

    if job == V4_JOB:
        assert [p["raw"] for p in trace["work_units"]["probes"]] == [
            4294735637, 316562456
        ]
    result = simulate(data)
    assert trace["output"] == result.output
    output_bytes = json.dumps(
        result.output, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    assert bytes.fromhex(trace["canonical_output_hex"]) == output_bytes
    assert trace["result_digest"] == result.result_digest
    assert "seed_value" not in trace["output"]
    assert "expected_digest" not in trace["output"]
    assert "algorithm_version" not in trace["output"]
