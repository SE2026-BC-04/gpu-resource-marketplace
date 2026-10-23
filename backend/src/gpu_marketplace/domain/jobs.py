import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["client_id", "client_role"],
            ["user_roles.user_id", "user_roles.role_code"],
            name="fk_jobs_client_user_role",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["listing_id", "worker_id"],
            ["gpu_listings.id", "gpu_listings.worker_id"],
            name="fk_jobs_listing_worker",
            ondelete="RESTRICT",
        ),
        CheckConstraint("client_role = 'CLIENT'", name="ck_jobs_client_role"),
        CheckConstraint("requested_gpu_count > 0", name="ck_jobs_requested_gpu_count_positive"),
        CheckConstraint("duration_seconds > 0", name="ck_jobs_duration_seconds_positive"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')", name="ck_jobs_status"
        ),
        CheckConstraint(
            "(status IN ('COMPLETED','FAILED','CANCELLED')) = (terminal_at IS NOT NULL)",
            name="ck_jobs_terminal_at_consistency",
        ),
        CheckConstraint(
            "(status = 'FAILED') = (failure_reason IS NOT NULL) AND "
            "(failure_reason IS NULL OR failure_reason IN ('WORKER_FAULT','JOB_FAULT','SYSTEM_FAULT'))",
            name="ck_jobs_failure_reason",
        ),
        CheckConstraint(
            "status NOT IN ('QUEUED','CANCELLED') OR started_at IS NULL",
            name="ck_jobs_started_at_never_running",
        ),
        CheckConstraint("(idempotency_key IS NULL) = (request_sha256 IS NULL)", name="ck_jobs_idempotency_pair"),
        CheckConstraint(
            "request_sha256 IS NULL OR octet_length(request_sha256) = 32", name="ck_jobs_request_sha256_len"
        ),
        UniqueConstraint("enqueue_seq", name="uq_jobs_enqueue_seq"),
        UniqueConstraint("id", "listing_id", name="uq_jobs_id_listing_id"),
        UniqueConstraint("id", "worker_id", name="uq_jobs_id_worker_id"),
        UniqueConstraint("id", "client_id", name="uq_jobs_id_client_id"),
        UniqueConstraint("id", "listing_id", "worker_id", name="uq_jobs_id_listing_id_worker_id"),
        Index(
            "uq_jobs_client_idempotency",
            "client_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_jobs_listing_fifo", "listing_id", "enqueue_seq", postgresql_where=text("status = 'QUEUED'")),
        Index("ix_jobs_client_history", "client_id", desc("submitted_at"), desc("id")),
        Index(
            "ix_jobs_terminal_cleanup",
            "terminal_at",
            "id",
            postgresql_where=text("status IN ('COMPLETED','FAILED','CANCELLED')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    client_role: Mapped[str] = mapped_column(String(8), server_default=text("'CLIENT'"))
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    requested_gpu_count: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), server_default=text("'QUEUED'"))
    # No default: the caller supplies clock_timestamp() after taking the Listing lock (database-design 11.3 A).
    submitted_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    enqueue_seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    terminal_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    failure_reason: Mapped[str | None] = mapped_column(String(16))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)


class SimulationReference(Base):
    __tablename__ = "simulation_references"
    __table_args__ = (
        CheckConstraint("expected_outcome IN ('SUCCESS','FAILED')", name="ck_simulation_references_outcome"),
        CheckConstraint(
            "(expected_outcome = 'SUCCESS' AND expected_failure_reason IS NULL) OR "
            "(expected_outcome = 'FAILED' AND expected_failure_reason IS NOT NULL AND "
            "expected_failure_reason IN ('WORKER_FAULT','JOB_FAULT'))",
            name="ck_simulation_references_outcome_reason",
        ),
        CheckConstraint(
            "expected_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_simulation_references_digest_format"
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("jobs.id", name="fk_simulation_references_job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    seed_value: Mapped[int] = mapped_column(BigInteger)
    algorithm_version: Mapped[str] = mapped_column(String(32))
    expected_outcome: Mapped[str] = mapped_column(String(8))
    expected_failure_reason: Mapped[str | None] = mapped_column(String(16))
    expected_digest: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
