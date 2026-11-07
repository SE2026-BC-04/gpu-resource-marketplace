"""Unit checks for the shared audit writer's event and redaction allowlists."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from gpu_marketplace.domain.audit import AuditEvent
from gpu_marketplace.repositories.audit import append_audit_event


class SessionSpy:
    def __init__(self) -> None:
        self.statement: Any | None = None

    def execute(self, statement: Any) -> None:
        self.statement = statement


def _success(session: SessionSpy, *, metadata: dict[str, Any]) -> None:
    append_audit_event(
        session,  # type: ignore[arg-type]
        actor_ref=str(uuid4()),
        correlation_id=uuid4(),
        subject_type="JOB",
        subject_id=uuid4(),
        event_type="JOB_SUBMIT",
        outcome="SUCCESS",
        metadata_redacted=metadata,
    )


def test_success_insert_uses_allowlisted_redacted_fields_and_database_defaults() -> None:
    session = SessionSpy()
    _success(session, metadata={"requested_gpu_count": 2, "duration_seconds": 60})

    assert session.statement is not None
    assert session.statement.table.name == AuditEvent.__tablename__
    inserted_columns = {column.key for column in session.statement._values}
    assert inserted_columns == {
        "actor_kind",
        "actor_ref",
        "correlation_id",
        "subject_type",
        "subject_id",
        "event_type",
        "outcome",
        "metadata_redacted",
    }
    assert "id" not in inserted_columns and "created_at" not in inserted_columns


@pytest.mark.parametrize(
    "metadata",
    [
        {"requested_gpu_count": 2, "duration_seconds": 60, "idempotency_key": "secret"},
        {"requested_gpu_count": 2, "duration_seconds": 60, "seed_value": 123},
        {"requested_gpu_count": 2, "duration_seconds": 60, "expected_digest": "secret"},
        {"requested_gpu_count": 2, "duration_seconds": 60, "authorization": "Bearer secret"},
    ],
)
def test_success_insert_rejects_non_allowlisted_or_protected_metadata(
    metadata: dict[str, Any],
) -> None:
    session = SessionSpy()

    with pytest.raises(ValueError, match="allowlisted"):
        _success(session, metadata=metadata)

    assert session.statement is None


def test_rejected_event_records_only_a_machine_reason_code() -> None:
    session = SessionSpy()
    append_audit_event(
        session,  # type: ignore[arg-type]
        actor_ref=str(uuid4()),
        correlation_id=uuid4(),
        subject_type="LISTING",
        subject_id=uuid4(),
        event_type="JOB_SUBMIT",
        outcome="REJECTED",
        metadata_redacted={"reason_code": "LISTING_PAUSED"},
    )

    inserted = {
        column.key: getattr(value, "value", value)
        for column, value in session.statement._values.items()
    }
    assert inserted["outcome"] == "REJECTED"
    assert inserted["metadata_redacted"] == {"reason_code": "LISTING_PAUSED"}
