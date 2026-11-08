"""Application-side port for recording non-success audit outcomes."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID


class AuditOutcomeWriter(Protocol):
    """Best-effort durable recording after a rejected/error transaction exits."""

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
    ) -> None: ...
