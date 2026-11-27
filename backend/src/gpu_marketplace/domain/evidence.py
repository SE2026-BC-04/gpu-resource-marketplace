"""Phase 2B evidence tables: ``result_inbox``, ``signed_results`` and ``job_reputation_contributions``.

Declarative mirror of migration ``0006_phase2b_schema`` (``PHASE2_SCHEMA_MATRIX.md`` sections 5-7). Nothing here
verifies a signature or decides an outcome; the schema only stores bytes and enforces shape. Nothing imports these
classes yet: the Phase 2 transaction adapters are later, separately gated work.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gpu_marketplace.domain.base import Base
from gpu_marketplace.domain.columns import NEW_UUID, NOW, TIMESTAMPTZ, UUID_PK

# TV3 verifier verdicts that are definitive after ingress admission, plus TV2 housekeeping codes. The whole
# predicate is wrapped in COALESCE(..., false) because a CHECK accepts NULL.
REJECTION_CODES = (
    "'UNKNOWN_KEY','KEY_WORKER_MISMATCH','CONTEXT_MISMATCH','INVALID_SIGNATURE','NOT_SELECTED','ALREADY_TERMINAL'"
)
REJECTION_CODE_CHECK = (
    "COALESCE(((state = 'REJECTED') = (rejection_code IS NOT NULL)) AND "
    f"(rejection_code IS NULL OR rejection_code IN ({REJECTION_CODES})), false)"
)


class ResultInbox(Base):
    __tablename__ = "result_inbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bound_job_id", "bound_attempt_id"],
            ["execution_attempts.job_id", "execution_attempts.attempt_id"],
            name="fk_result_inbox_bound_attempt",
            ondelete="CASCADE",
        ),
        CheckConstraint("state IN ('PENDING','ACCEPTED','REJECTED')", name="ck_result_inbox_state"),
        CheckConstraint("(bound_job_id IS NULL) = (bound_attempt_id IS NULL)", name="ck_result_inbox_bound_pair"),
        CheckConstraint("state <> 'PENDING' OR bound_job_id IS NOT NULL", name="ck_result_inbox_pending_bound"),
        CheckConstraint("(state = 'PENDING') = (processed_at IS NULL)", name="ck_result_inbox_processed_at"),
        CheckConstraint("octet_length(envelope_sha256) = 32", name="ck_result_inbox_sha256_len"),
        # D-01 Option C: the stored digest is always the digest of the stored bytes.
        CheckConstraint("envelope_sha256 = sha256(original_envelope_raw)", name="ck_result_inbox_sha256_matches"),
        CheckConstraint(REJECTION_CODE_CHECK, name="ck_result_inbox_rejection_code"),
        # R1-Q1: result_id stays nullable; the only uniqueness besides the primary key.
        Index("uq_result_inbox_result_id", "result_id", unique=True, postgresql_where=text("result_id IS NOT NULL")),
        Index(
            "ix_result_inbox_pending",
            "bound_job_id",
            "received_at",
            "id",
            postgresql_where=text("state = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True, server_default=NEW_UUID)
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    # Untrusted claims taken from the callback body: deliberately no foreign key.
    claimed_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    claimed_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    bound_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    bound_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    original_envelope_raw: Mapped[bytes] = mapped_column(LargeBinary)
    envelope_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    # D-17: read at insert time (clock_timestamp), after the ingress transaction took its locks.
    received_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    state: Mapped[str] = mapped_column(String(12), server_default=text("'PENDING'"))
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class SignedResult(Base):
    __tablename__ = "signed_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "attempt_id"],
            ["execution_attempts.job_id", "execution_attempts.attempt_id"],
            name="fk_signed_results_attempt",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["job_id", "listing_id", "worker_id"],
            ["jobs.id", "jobs.listing_id", "jobs.worker_id"],
            name="fk_signed_results_job_listing_worker",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["worker_id", "key_id"],
            ["worker_public_keys.worker_id", "worker_public_keys.key_id"],
            name="fk_signed_results_worker_key",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", name="uq_signed_results_job_id"),
        UniqueConstraint("job_id", "result_id", name="uq_signed_results_job_id_result_id"),
        CheckConstraint("schema_version = '1'", name="ck_signed_results_schema_version"),
        CheckConstraint("outcome IN ('SUCCESS','FAILED')", name="ck_signed_results_outcome"),
        CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN ('WORKER_FAULT','JOB_FAULT')",
            name="ck_signed_results_failure_reason",
        ),
        CheckConstraint("(outcome = 'SUCCESS') = (failure_reason IS NULL)", name="ck_signed_results_outcome_reason"),
        CheckConstraint("result_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_signed_results_result_digest"),
        CheckConstraint("octet_length(signature_raw) = 64", name="ck_signed_results_signature_len"),
    )

    result_id: Mapped[uuid.UUID] = mapped_column(UUID_PK, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    key_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    schema_version: Mapped[str] = mapped_column(String(4))
    outcome: Mapped[str] = mapped_column(String(8))
    failure_reason: Mapped[str | None] = mapped_column(String(16))
    result_digest: Mapped[str] = mapped_column(String(71))
    # The signed wire string: kept for evidence, never used for retention.
    finished_at_wire: Mapped[str] = mapped_column(String(27))
    payload_jcs_raw: Mapped[bytes] = mapped_column(LargeBinary)
    # D-10: an independent byte-exact copy, so accepted evidence does not depend on the Inbox row.
    original_envelope_raw: Mapped[bytes] = mapped_column(LargeBinary)
    signature_raw: Mapped[bytes] = mapped_column(LargeBinary)
    verified_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    accepted_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)


class JobReputationContribution(Base):
    __tablename__ = "job_reputation_contributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "worker_id"],
            ["jobs.id", "jobs.worker_id"],
            name="fk_job_reputation_contributions_job_worker",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "initial_category IN ('SUCCESS','WORKER_FAULT','NONE')",
            name="ck_job_reputation_contributions_initial_category",
        ),
        CheckConstraint(
            "effective_category IN ('SUCCESS','WORKER_FAULT','NONE')",
            name="ck_job_reputation_contributions_effective_category",
        ),
        # TRANSITIONAL (P2B-DEC-01): Phase 3 replaces this with the final correction CHECK and adds the
        # composite foreign key to disputes(job_id, id). Until then no correction can be stored.
        CheckConstraint(
            "correction_version = 0 AND corrected_by_dispute_id IS NULL AND effective_category = initial_category",
            name="ck_job_reputation_contributions_phase2_no_correction",
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID_PK,
        ForeignKey("jobs.id", name="fk_job_reputation_contributions_job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    initial_category: Mapped[str] = mapped_column(String(12))
    effective_category: Mapped[str] = mapped_column(String(12))
    # No foreign key in Phase 2: the disputes table does not exist yet.
    corrected_by_dispute_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    correction_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    applied_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
