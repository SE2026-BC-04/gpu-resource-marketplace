"""Phase 1 Listing guard checks with pre- and post-allocation inputs."""

from dataclasses import replace

import pytest


BASE = "/api/v1/gpu-listings"


@pytest.mark.parametrize(
    ("allocated", "head_status", "http_status"),
    [
        pytest.param(3, "QUEUED", 200, id="resize-sees-queued-head"),
        pytest.param(7, "RUNNING", 409, id="resize-sees-committed-reservation"),
    ],
)
def test_downsize_guard_uses_the_latest_capacity_visible_to_the_listing_uow(
    env, allocated: int, head_status: str, http_status: int,
) -> None:
    # Model two committed input snapshots. The repository double does not
    # model an allocator or demonstrate real concurrency.
    original = replace(env.store.l1, allocated_gpu_count=allocated)
    env.store.records[original.id] = original
    jobs = [("RUNNING", 3), (head_status, 4)]
    env.store.job_rows[original.id] = list(jobs)

    response = env.client.patch(
        f"{BASE}/{original.id}",
        json={"total_gpu_count": 4, "mock_price_per_hour": "1.00"},
    )

    assert response.status_code == http_status
    assert env.store.events[0] == ("lock", original.id)
    assert env.store.job_rows[original.id] == jobs
    saved = env.store.records[original.id]
    assert saved.allocated_gpu_count == allocated
    if head_status == "QUEUED":
        assert saved.total_gpu_count == 4
        # A later allocator sees one free GPU for the four-GPU head.
        assert saved.total_gpu_count - saved.allocated_gpu_count == 1
    else:
        assert response.json()["error"]["code"] == "LISTING_CAPACITY_BELOW_ALLOCATED"
        assert saved == original
        assert not any(operation == "update" for operation, _ in env.store.events)


@pytest.mark.parametrize("head_status", ["QUEUED", "RUNNING"])
def test_paused_listing_still_rejects_hardware_changes_with_a_nonterminal_job(
    env, head_status: str,
) -> None:
    original = replace(
        env.store.l1,
        status="PAUSED",
        allocated_gpu_count=4 if head_status == "RUNNING" else 0,
    )
    env.store.records[original.id] = original
    env.store.job_rows[original.id] = [(head_status, 4)]

    response = env.client.patch(
        f"{BASE}/{original.id}",
        json={"vram_gb": 96, "mock_price_per_hour": "1.00"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LISTING_HARDWARE_LOCKED"
    assert env.store.records[original.id] == original
    assert env.store.events[0] == ("lock", original.id)
    assert not any(operation == "update" for operation, _ in env.store.events)
