"""Fixed vectors for the approved protected reference algorithm."""

from uuid import UUID

import pytest

from gpu_marketplace.jobs.reference import create_simulation_reference

JOB_ID = UUID("33333333-3333-4333-8333-333333333333")
LISTING_ID = UUID("22222222-2222-4222-8222-222222222222")
WORKER_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    ("duration", "job_id", "seed", "outcome", "failure_reason", "digest"),
    [
        (
            60,
            JOB_ID,
            3035342533442321017,
            "SUCCESS",
            None,
            "sha256:a643e286d2b4b89606cd8559078a8765cd73c7d602eec4f1ca4bba2ca732ef0c",
        ),
        (
            2,
            JOB_ID,
            8887054454783268118,
            "FAILED",
            "WORKER_FAULT",
            "sha256:9baaaaa338423c75753ecbd00da615a1f88a006eeb0a512d432635664754b7bf",
        ),
        (
            1,
            JOB_ID,
            2063102514678027846,
            "FAILED",
            "JOB_FAULT",
            "sha256:f1c9d8e371bd4e6876a73b2414c285c6362fe01bca4d8d432169f4d484b3d749",
        ),
        (
            60,
            UUID("33333333-3333-4333-8333-000000000c02"),
            2240287873181493078,
            "SUCCESS",
            None,
            "sha256:ad2212d44fef948b303afb1e5d5d8e9435eeab64f6701c54cafc3c6f3fd77aa7",
        ),
    ],
)
def test_reference_matches_approved_fixed_vectors(
    duration: int,
    job_id: UUID,
    seed: int,
    outcome: str,
    failure_reason: str | None,
    digest: str,
) -> None:
    reference = create_simulation_reference(
        job_id=job_id,
        listing_id=LISTING_ID,
        worker_id=WORKER_ID,
        requested_gpu_count=2,
        duration_seconds=duration,
    )

    assert reference.seed_value == seed
    assert reference.algorithm_version == "demo-v1-public1"
    assert reference.expected_outcome == outcome
    assert reference.expected_failure_reason == failure_reason
    assert reference.expected_digest == digest
