"""Phase 2B execution tables: ``execution_attempts``, ``allocations`` and ``execution_outbox``.

Declarative mirror of migration ``0006_phase2b_schema`` (``PHASE2_SCHEMA_MATRIX.md`` sections 2-4). It exists so
the constraint and index names stay pinned by ``test_schema_metadata.py`` and so Alembic's drift check sees no
difference. Nothing imports these classes yet: the Phase 2 transaction adapters are later, separately gated work.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK

# D-05 / D-13 (P1): the immutable ten-key dispatch body. The whole predicate is wrapped in COALESCE(..., false)
# because a CHECK accepts NULL, and the object test is a CASE so a scalar or array payload is a plain CHECK
# violation instead of a jsonb operator error. Only immutable jsonb operators are used: the payload's timestamps
# are never cast, so their equality with ``execution_attempts`` is a transaction rule (``P2B-DRT-18``).
DISPATCH_PAYLOAD_KEYS = (
    "'outbox_event_id','job_id','attempt_id','worker_id','listing_id','gpu_count',"
    "'duration_seconds','simulation_input','finish_due_at','hard_deadline_at'"
)
DISPATCH_PAYLOAD_SHAPE = (
    "COALESCE(CASE WHEN jsonb_typeof(dispatch_payload) = 'object' THEN "
    f"(dispatch_payload ?& ARRAY[{DISPATCH_PAYLOAD_KEYS}]) "
    f"AND ((dispatch_payload - ARRAY[{DISPATCH_PAYLOAD_KEYS}]) = '{{}}'::jsonb) "
    "AND jsonb_typeof(dispatch_payload -> 'outbox_event_id') = 'string' "
    "AND (dispatch_payload ->> 'outbox_event_id') = event_id::text "
    "AND jsonb_typeof(dispatch_payload -> 'attempt_id') = 'string' "
    "AND (dispatch_payload ->> 'attempt_id') = attempt_id::text "
    "AND jsonb_typeof(dispatch_payload -> 'job_id') = 'string' "
    "AND jsonb_typeof(dispatch_payload -> 'worker_id') = 'string' "
    "AND jsonb_typeof(dispatch_payload -> 'listing_id') = 'string' "
    "AND (dispatch_payload -> 'simulation_input') = '{\"workload_profile\":\"demo-v1\"}'::jsonb "
    "ELSE false END, false)"
)


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_execution_attempts_job_id"),
        UniqueConstraint("job_id", "attempt_id", name="uq_execution_attempts_job_id_attempt_id"),
        CheckConstraint(
            "finish_due_at > started_at AND hard_deadline_at = finish_due_at + interval '120 seconds'",
            name="ck_execution_attempts_deadlines",
        ),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK, ForeignKey("jobs.id", name="fk_execution_attempts_job_id", ondelete="CASCADE")
    )
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    finish_due_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    hard_deadline_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "listing_id"],
            ["jobs.id", "jobs.listing_id"],
            name="fk_allocations_job_listing",
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", name="uq_allocations_job_id"),
        CheckConstraint("gpu_count > 0", name="ck_allocations_gpu_count_positive"),
        CheckConstraint("state IN ('ACTIVE','RELEASED')", name="ck_allocations_state"),
        CheckConstraint("(state = 'RELEASED') = (released_at IS NOT NULL)", name="ck_allocations_released_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    gpu_count: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(8), server_default=text("'ACTIVE'"))
    # Manager trusted time: no default, the allocation transaction supplies it.
    allocated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    released_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class ExecutionOutbox(Base):
    __tablename__ = "execution_outbox"
    __table_args__ = (
        UniqueConstraint("attempt_id", "event_type", name="uq_execution_outbox_attempt_id_event_type"),
        CheckConstraint("event_type IN ('EXECUTE_JOB')", name="ck_execution_outbox_event_type"),
        CheckConstraint(DISPATCH_PAYLOAD_SHAPE, name="ck_execution_outbox_payload_shape"),
        CheckConstraint("state IN ('PENDING','CLAIMED','ACKED','EXHAUSTED')", name="ck_execution_outbox_state"),
        CheckConstraint("delivery_attempts >= 0", name="ck_execution_outbox_delivery_attempts_nonneg"),
        CheckConstraint("lease_version >= 0", name="ck_execution_outbox_lease_version_nonneg"),
        # D-06: a lease exists exactly on CLAIMED rows, so an expired lease can never resurrect an ACKED or
        # EXHAUSTED row.
        CheckConstraint("(lease_owner IS NULL) = (lease_until IS NULL)", name="ck_execution_outbox_lease_pair"),
        CheckConstraint("(state = 'CLAIMED') = (lease_owner IS NOT NULL)", name="ck_execution_outbox_state_lease"),
        CheckConstraint("(state = 'ACKED') = (acked_at IS NOT NULL)", name="ck_execution_outbox_acked_at"),
        Index(
            "ix_execution_outbox_due",
            "next_retry_at",
            "event_id",
            postgresql_where=text("state IN ('PENDING','CLAIMED','ACKED')"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("execution_attempts.attempt_id", name="fk_execution_outbox_attempt_id", ondelete="CASCADE"),
    )
    event_type: Mapped[str] = mapped_column(String(16), server_default=text("'EXECUTE_JOB'"))
    dispatch_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(12), server_default=text("'PENDING'"))
    delivery_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_retry_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    lease_version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    acked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
