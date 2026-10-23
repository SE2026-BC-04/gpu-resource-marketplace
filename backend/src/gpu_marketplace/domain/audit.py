import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_kind IN ('USER','SERVICE')", name="ck_audit_events_actor_kind"),
        CheckConstraint("outcome IN ('SUCCESS','REJECTED','ERROR')", name="ck_audit_events_outcome"),
        CheckConstraint("jsonb_typeof(metadata_redacted) = 'object'", name="ck_audit_events_metadata_object"),
        Index("ix_audit_events_created_at_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    actor_kind: Mapped[str] = mapped_column(String(12))
    actor_ref: Mapped[str] = mapped_column(String(128))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    subject_type: Mapped[str | None] = mapped_column(String(32))
    # Deliberately no foreign key: audit rows outlive the Jobs they describe (database-design 9.3).
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    event_type: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(12))
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
