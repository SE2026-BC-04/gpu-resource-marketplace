"""Contract tests for the reusable TX-CANCEL PostgreSQL test support."""

from datetime import UTC, datetime

import pytest

from jobs_cancel_pg_support import (
    PersistedJobSnapshot,
    assert_snapshot_unchanged,
    job_state_fields,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("QUEUED", {}),
        ("RUNNING", {"status": "RUNNING", "started_at": datetime(2026, 1, 2, tzinfo=UTC)}),
        (
            "COMPLETED",
            {
                "status": "COMPLETED",
                "started_at": datetime(2026, 1, 2, tzinfo=UTC),
                "terminal_at": datetime(2026, 1, 2, tzinfo=UTC),
            },
        ),
        (
            "FAILED",
            {
                "status": "FAILED",
                "started_at": datetime(2026, 1, 2, tzinfo=UTC),
                "terminal_at": datetime(2026, 1, 2, tzinfo=UTC),
                "failure_reason": "JOB_FAULT",
            },
        ),
        (
            "CANCELLED",
            {"status": "CANCELLED", "terminal_at": datetime(2026, 1, 2, tzinfo=UTC)},
        ),
    ],
)
def test_job_state_fields_match_existing_lifecycle_constraints(
    status: str, expected: dict[str, object]
) -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)

    assert job_state_fields(status, now) == expected


def test_job_state_fields_reject_unknown_status() -> None:
    with pytest.raises(ValueError, match="Unsupported Job fixture status"):
        job_state_fields("ALLOCATING", datetime(2026, 1, 2, tzinfo=UTC))


def test_snapshot_assertion_detects_any_existing_schema_side_effect() -> None:
    before = PersistedJobSnapshot(("job", "QUEUED"), 0, "reference-hash", None)
    assert_snapshot_unchanged(before, before)

    after = PersistedJobSnapshot(("job", "CANCELLED"), 0, "reference-hash", None)
    with pytest.raises(AssertionError):
        assert_snapshot_unchanged(before, after)
