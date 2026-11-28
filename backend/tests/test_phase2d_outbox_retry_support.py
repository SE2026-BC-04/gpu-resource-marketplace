from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from phase2d_outbox_retry_support import (
    LeaseSnapshot,
    RetrySnapshot,
    assert_paused_retry_preserves_execution,
    assert_stale_settlement_is_inert,
)


NOW = datetime(2026, 11, 28, tzinfo=UTC)


@pytest.fixture
def execution() -> RetrySnapshot:
    return RetrySnapshot(
        listing_status="PAUSED",
        job_status="RUNNING",
        listing_id=UUID(int=1),
        job_id=UUID(int=2),
        allocation_ids=(UUID(int=3),),
        attempt_id=UUID(int=4),
        event_id=UUID(int=5),
        dispatch_payload=b'{"workload_profile":"demo-v1"}',
        finish_due_at=NOW,
        hard_deadline_at=NOW + timedelta(seconds=120),
        allocated_gpu_count=2,
    )


def test_accepts_same_execution_snapshot(execution: RetrySnapshot) -> None:
    assert_paused_retry_preserves_execution(execution, replace(execution))


@pytest.mark.parametrize(
    "change",
    [
        {"allocation_ids": (UUID(int=3), UUID(int=9))},
        {"allocated_gpu_count": 4},
        {"attempt_id": UUID(int=9)},
        {"event_id": UUID(int=9)},
        {"dispatch_payload": b"changed"},
        {"finish_due_at": NOW + timedelta(seconds=1)},
        {"hard_deadline_at": NOW + timedelta(seconds=121)},
        {"job_status": "COMPLETED"},
    ],
)
def test_retry_oracle_detects_changed_execution(execution: RetrySnapshot, change: dict) -> None:
    with pytest.raises(AssertionError, match="changed the PAUSED"):
        assert_paused_retry_preserves_execution(execution, replace(execution, **change))


def test_stale_ack_requires_zero_writes_and_unchanged_replacement_lease() -> None:
    lease = LeaseSnapshot(UUID(int=5), "worker-b", 2, "CLAIMED", NOW, NOW, 2)
    assert_stale_settlement_is_inert(lease, replace(lease), affected_rows=0)

    with pytest.raises(AssertionError, match="allowed to write"):
        assert_stale_settlement_is_inert(lease, lease, affected_rows=1)
    with pytest.raises(AssertionError, match="changed the replacement lease"):
        assert_stale_settlement_is_inert(lease, replace(lease, state="ACKED"), affected_rows=0)
