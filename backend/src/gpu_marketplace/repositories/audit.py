"""Shared, redacted audit persistence for approved Phase 1 mutations.

Successful events are appended through the caller's transaction so a durable
SUCCESS row always commits with its mutation. Rejections/errors use a separate
best-effort transaction after the business transaction has rolled back.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from gpu_marketplace.domain.audit import AuditEvent

logger = logging.getLogger(__name__)

AuditOutcome = Literal["SUCCESS", "REJECTED", "ERROR"]
_EVENT_METADATA_KEYS: dict[str, frozenset[str]] = {
    "LISTING_CREATE": frozenset({"status"}),
    "LISTING_UPDATE": frozenset({"changed_fields"}),
    "LISTING_PAUSE": frozenset({"from_status", "to_status"}),
    "LISTING_RESUME": frozenset({"from_status", "to_status"}),
    "JOB_SUBMIT": frozenset({"requested_gpu_count", "duration_seconds"}),
    "JOB_CANCEL": frozenset({"from_status", "to_status"}),
}
_LISTING_FIELDS = frozenset(
    {"gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"}
)
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def append_audit_event(
    session: Session,
    *,
    actor_ref: str,
    correlation_id: UUID,
    subject_type: str,
    subject_id: UUID | None,
    event_type: str,
    outcome: AuditOutcome,
    metadata_redacted: Mapping[str, Any],
) -> None:
    """Append one allowlisted event to the caller's existing transaction.

    The schema supplies the trusted timestamp and event ID. Metadata keys are
    allowlisted per action so request bodies, credentials and protected oracle
    values cannot accidentally flow into the operational audit table.
    """
    if event_type not in _EVENT_METADATA_KEYS:
        raise ValueError("unsupported audit event type")
    if outcome not in {"SUCCESS", "REJECTED", "ERROR"}:
        raise ValueError("unsupported audit outcome")
    if not actor_ref or len(actor_ref) > 128:
        raise ValueError("invalid audit actor reference")
    if not isinstance(correlation_id, UUID):
        raise ValueError("invalid audit correlation ID")
    allowed = (
        _EVENT_METADATA_KEYS[event_type]
        if outcome == "SUCCESS"
        else frozenset({"reason_code"})
    )
    metadata = dict(metadata_redacted)
    if set(metadata) - allowed:
        raise ValueError("audit metadata contains a non-allowlisted field")
    if outcome != "SUCCESS":
        reason_code = metadata.get("reason_code")
        if not isinstance(reason_code, str) or not _SAFE_CODE.fullmatch(reason_code):
            raise ValueError("invalid redacted audit reason code")
    elif event_type == "LISTING_UPDATE":
        fields = metadata.get("changed_fields")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) or field not in _LISTING_FIELDS for field in fields)
        ):
            raise ValueError("invalid redacted Listing change metadata")
    elif event_type in {"LISTING_PAUSE", "LISTING_RESUME", "JOB_CANCEL"}:
        if set(metadata) != {"from_status", "to_status"}:
            raise ValueError("invalid redacted status transition metadata")
    elif event_type == "LISTING_CREATE":
        if metadata != {"status": "ACTIVE"}:
            raise ValueError("invalid redacted Listing create metadata")
    elif event_type == "JOB_SUBMIT":
        if (
            set(metadata) != {"requested_gpu_count", "duration_seconds"}
            or any(type(metadata[key]) is not int or metadata[key] <= 0 for key in metadata)
        ):
            raise ValueError("invalid redacted Job submission metadata")

    session.execute(
        insert(AuditEvent).inline().values(
            actor_kind="USER",
            actor_ref=actor_ref,
            correlation_id=correlation_id,
            subject_type=subject_type,
            subject_id=subject_id,
            event_type=event_type,
            outcome=outcome,
            metadata_redacted=metadata,
        )
    )


class PostgresAuditWriter:
    """Persist rejected/error outcomes without changing the original response."""

    def __init__(self, sessions: Callable[[], Session]) -> None:
        self._sessions = sessions

    def record_outcome(
        self,
        *,
        actor_ref: str,
        correlation_id: UUID,
        subject_type: str,
        subject_id: UUID | None,
        event_type: str,
        outcome: Literal["REJECTED", "ERROR"],
        reason_code: str,
    ) -> None:
        try:
            with self._sessions() as session:
                append_audit_event(
                    session,
                    actor_ref=actor_ref,
                    correlation_id=correlation_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    event_type=event_type,
                    outcome=outcome,
                    metadata_redacted={"reason_code": reason_code},
                )
                session.commit()
        except Exception as error:  # noqa: BLE001 - audit failure must not replace a domain result
            # Driver exceptions can contain bound values/SQL; log only the type.
            logger.error(
                "audit_outcome_write_failed",
                extra={"exception_type": type(error).__name__, "event_type": event_type},
            )
