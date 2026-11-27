"""Phase 2B R1: the six Phase 2 tables (schema only; no grant, trigger or function).

Hand-written from ``PHASE2_SCHEMA_MATRIX.md`` and ``database-design.md`` section 9.2 tables 09-13 and 16, section
9.3 (FK actions) and section 9.4 (indexes). Coding authorization: ``CODE_AUTHORIZED TV2-P2B-07 / G1-R1 SCHEMA
MIGRATION ONLY (CONDITIONAL)`` (PR #66, comment 7222971404). It creates exactly, in this order,
``execution_attempts``, ``allocations``, ``execution_outbox``, ``result_inbox``, ``signed_results`` and
``job_reputation_contributions``. No Phase 1 table, column, grant, trigger or function is touched, and no seventh
table (``disputes`` belongs to Phase 3).

Applying this revision does NOT activate Phase 2. The runtime groups hold no privilege on the new tables until the
separately gated R2 revision (column grants and the two guard triggers), and the Manager runtime stays disabled
until R1 and R2 are both applied and verified (P2B-MIG-05).

Decisions carried by the DDL (all from the lead's R1 decision, no others invented):

* R1-Q1: ``result_inbox.result_id`` stays nullable; the partial unique index ``uq_result_inbox_result_id
  WHERE result_id IS NOT NULL`` is the only uniqueness besides the primary key. A non-NULL ``result_id`` is enforced
  later by ingress and the verifier carriers, not by this DDL.
* D-01: ``envelope_sha256 = sha256(original_envelope_raw)`` and a 32-byte length are CHECKs.
* D-05 / D-13 (P1): ``ck_execution_outbox_payload_shape`` pins the exact ten-key dispatch body.
* D-06: three Outbox coherence CHECKs (lease pair, lease only on CLAIMED, ``acked_at`` iff ACKED).
* D-10: ``signed_results`` keeps its own byte copies of the evidence.
* FK actions (``database-design.md`` 9.3): every foreign key from a Job-linked evidence table is ``ON DELETE
  CASCADE`` so the guarded Job purge removes the whole graph; only ``signed_results -> worker_public_keys`` is
  ``RESTRICT``. The two composite Job foreign keys (``signed_results``, ``job_reputation_contributions``) are
  CASCADE too because the matrix names no action for them and NO ACTION made ``DELETE FROM jobs`` fail with
  ``fk_signed_results_job_listing_worker`` on PostgreSQL 16 (found by ``P2B-FK-05``).
* D-17: ``result_inbox.received_at DEFAULT clock_timestamp()`` (the INSERT ... RETURNING admission transaction is
  not part of R1).
* D-18: no partial unique index on active Worker keys. Not created here and not created anywhere.
* Transitional CHECK ``ck_job_reputation_contributions_phase2_no_correction`` (P2B-DEC-01); Phase 3 replaces it.

Not in R1: D-19 repair columns, D-20 discovery reads, the optional D-09 allocation index, any grant or revoke.

Preflight fails closed before any DDL (wrong parent, one of the six tables already present, a Phase 1 unique target
missing or on other columns, a second head). Downgrade drops the tables in reverse dependency order and refuses
while any of them holds a row, because those rows are accepted evidence; set
``GPU_MARKETPLACE_PHASE2_DISPOSABLE_DOWNGRADE=1`` only on a disposable database. Reverting this file in Git does not
undo an applied revision.

Revision ID: 0006_phase2b_schema
Revises: 0005_listing_d7
Create Date: 2026-11-27
"""

import os
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0006_phase2b_schema"
down_revision: Union[str, None] = "0005_listing_d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARENT = "0005_listing_d7"
DISPOSABLE_FLAG = "GPU_MARKETPLACE_PHASE2_DISPOSABLE_DOWNGRADE"

# Creation order; the downgrade uses the reverse.
PHASE2_TABLES = (
    "execution_attempts",
    "allocations",
    "execution_outbox",
    "result_inbox",
    "signed_results",
    "job_reputation_contributions",
)

# Phase 1 objects that the new composite foreign keys point at: (table, constraint, type, columns).
PHASE1_TARGETS = (
    ("jobs", "pk_jobs", "p", ("id",)),
    ("jobs", "uq_jobs_id_listing_id", "u", ("id", "listing_id")),
    ("jobs", "uq_jobs_id_worker_id", "u", ("id", "worker_id")),
    ("jobs", "uq_jobs_id_listing_id_worker_id", "u", ("id", "listing_id", "worker_id")),
    ("worker_public_keys", "uq_worker_public_keys_worker_id_key_id", "u", ("worker_id", "key_id")),
)

TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True, precision=6)
NOW = sa.text("clock_timestamp()")
NEW_UUID = sa.text("gen_random_uuid()")
UUID = postgresql.UUID(as_uuid=True)

# D-05 / D-13 (P1). COALESCE because a CHECK accepts NULL; CASE so a scalar or array payload is a plain CHECK
# violation instead of a jsonb operator error. Immutable jsonb operators only: the payload's timestamps are never
# cast (their equality with execution_attempts is a transaction rule, P2B-DRT-18).
PAYLOAD_KEYS = (
    "'outbox_event_id','job_id','attempt_id','worker_id','listing_id','gpu_count',"
    "'duration_seconds','simulation_input','finish_due_at','hard_deadline_at'"
)
PAYLOAD_SHAPE = (
    "COALESCE(CASE WHEN jsonb_typeof(dispatch_payload) = 'object' THEN "
    f"(dispatch_payload ?& ARRAY[{PAYLOAD_KEYS}]) "
    f"AND ((dispatch_payload - ARRAY[{PAYLOAD_KEYS}]) = '{{}}'::jsonb) "
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

REJECTION_CODES = (
    "'UNKNOWN_KEY','KEY_WORKER_MISMATCH','CONTEXT_MISMATCH','INVALID_SIGNATURE','NOT_SELECTED','ALREADY_TERMINAL'"
)
REJECTION_CODE_CHECK = (
    "COALESCE(((state = 'REJECTED') = (rejection_code IS NOT NULL)) AND "
    f"(rejection_code IS NULL OR rejection_code IN ({REJECTION_CODES})), false)"
)


def run_preflight(bind: sa.engine.Connection, heads: Sequence[str]) -> None:
    """Fail closed, before any DDL, when the database is not exactly what this revision was written for."""
    versions = list(bind.execute(sa.text("SELECT version_num FROM public.alembic_version")).scalars())
    if versions != [PARENT]:
        raise RuntimeError(
            f"Phase 2B R1 refused: public.alembic_version must hold exactly [{PARENT!r}] (the accepted Phase 1 "
            f"head this revision revises), found {versions!r}; no DDL was run"
        )

    present = [
        table
        for table in PHASE2_TABLES
        if bind.execute(sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"}).scalar_one()
    ]
    if present:
        raise RuntimeError(
            f"Phase 2B R1 refused: table(s) {', '.join(present)} already exist in schema public; this revision "
            "creates them and never adopts or alters existing ones; no DDL was run"
        )

    for table, constraint, kind, columns in PHASE1_TARGETS:
        found = bind.execute(
            sa.text(
                "SELECT array_agg(a.attname::text ORDER BY k.ord) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "WHERE t.relnamespace = 'public'::regnamespace AND t.relname = :table "
                "AND c.conname = :name AND c.contype = :kind"
            ),
            {"table": table, "name": constraint, "kind": kind},
        ).scalar_one()
        if found is None or tuple(found) != columns:
            raise RuntimeError(
                f"Phase 2B R1 refused: Phase 1 constraint {constraint} on public.{table} must be a "
                f"{'primary key' if kind == 'p' else 'unique constraint'} on ({', '.join(columns)}) but is "
                f"{'missing' if found is None else 'on (' + ', '.join(found) + ')'}; no DDL was run"
            )

    if len(heads) != 1:
        raise RuntimeError(
            f"Phase 2B R1 refused: the migration graph must have exactly one head, found {len(heads)} "
            f"({', '.join(sorted(heads)) or 'none'}); resolve the branch first; no DDL was run"
        )


def run_downgrade_guard(bind: sa.engine.Connection, disposable: bool) -> None:
    """Refuse to drop accepted evidence: any row in any of the six tables blocks the downgrade."""
    populated = [
        table
        for table in reversed(PHASE2_TABLES)
        if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM public.{table})")).scalar_one()  # noqa: S608
    ]
    if populated and not disposable:
        raise RuntimeError(
            f"Phase 2B R1 downgrade refused: table(s) {', '.join(populated)} hold rows (Inbox bytes, signed results "
            "or contributions are accepted evidence and a downgrade would destroy them). On a disposable database "
            f"only, set {DISPOSABLE_FLAG}=1 to drop them anyway; no DDL was run"
        )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Phase 2B R1 needs a live connection for its preflight; offline SQL generation is refused")
    bind = op.get_bind()
    run_preflight(bind, op.get_context().script.get_heads())

    op.create_table(
        "execution_attempts",
        sa.Column("attempt_id", UUID, nullable=False, server_default=NEW_UUID),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("started_at", TIMESTAMPTZ, nullable=False),
        sa.Column("finish_due_at", TIMESTAMPTZ, nullable=False),
        sa.Column("hard_deadline_at", TIMESTAMPTZ, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_execution_attempts"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_execution_attempts_job_id", ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_execution_attempts_job_id"),
        sa.UniqueConstraint("job_id", "attempt_id", name="uq_execution_attempts_job_id_attempt_id"),
        sa.CheckConstraint(
            "finish_due_at > started_at AND hard_deadline_at = finish_due_at + interval '120 seconds'",
            name="ck_execution_attempts_deadlines",
        ),
    )

    op.create_table(
        "allocations",
        sa.Column("id", UUID, nullable=False, server_default=NEW_UUID),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("listing_id", UUID, nullable=False),
        sa.Column("gpu_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(8), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("allocated_at", TIMESTAMPTZ, nullable=False),
        sa.Column("released_at", TIMESTAMPTZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_allocations"),
        sa.ForeignKeyConstraint(
            ["job_id", "listing_id"],
            ["jobs.id", "jobs.listing_id"],
            name="fk_allocations_job_listing",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("job_id", name="uq_allocations_job_id"),
        sa.CheckConstraint("gpu_count > 0", name="ck_allocations_gpu_count_positive"),
        sa.CheckConstraint("state IN ('ACTIVE','RELEASED')", name="ck_allocations_state"),
        sa.CheckConstraint("(state = 'RELEASED') = (released_at IS NOT NULL)", name="ck_allocations_released_at"),
    )

    op.create_table(
        "execution_outbox",
        sa.Column("event_id", UUID, nullable=False, server_default=NEW_UUID),
        sa.Column("attempt_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False, server_default=sa.text("'EXECUTE_JOB'")),
        sa.Column("dispatch_payload", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", TIMESTAMPTZ, nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_until", TIMESTAMPTZ, nullable=True),
        sa.Column("lease_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("acked_at", TIMESTAMPTZ, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=NOW),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("event_id", name="pk_execution_outbox"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["execution_attempts.attempt_id"],
            name="fk_execution_outbox_attempt_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("attempt_id", "event_type", name="uq_execution_outbox_attempt_id_event_type"),
        sa.CheckConstraint("event_type IN ('EXECUTE_JOB')", name="ck_execution_outbox_event_type"),
        sa.CheckConstraint(PAYLOAD_SHAPE, name="ck_execution_outbox_payload_shape"),
        sa.CheckConstraint("state IN ('PENDING','CLAIMED','ACKED','EXHAUSTED')", name="ck_execution_outbox_state"),
        sa.CheckConstraint("delivery_attempts >= 0", name="ck_execution_outbox_delivery_attempts_nonneg"),
        sa.CheckConstraint("lease_version >= 0", name="ck_execution_outbox_lease_version_nonneg"),
        sa.CheckConstraint("(lease_owner IS NULL) = (lease_until IS NULL)", name="ck_execution_outbox_lease_pair"),
        sa.CheckConstraint("(state = 'CLAIMED') = (lease_owner IS NOT NULL)", name="ck_execution_outbox_state_lease"),
        sa.CheckConstraint("(state = 'ACKED') = (acked_at IS NOT NULL)", name="ck_execution_outbox_acked_at"),
    )
    op.create_index(
        "ix_execution_outbox_due",
        "execution_outbox",
        ["next_retry_at", "event_id"],
        postgresql_where=sa.text("state IN ('PENDING','CLAIMED','ACKED')"),
    )

    op.create_table(
        "result_inbox",
        sa.Column("id", UUID, nullable=False, server_default=NEW_UUID),
        sa.Column("result_id", UUID, nullable=True),
        sa.Column("claimed_job_id", UUID, nullable=True),
        sa.Column("claimed_attempt_id", UUID, nullable=True),
        sa.Column("bound_job_id", UUID, nullable=True),
        sa.Column("bound_attempt_id", UUID, nullable=True),
        sa.Column("original_envelope_raw", sa.LargeBinary(), nullable=False),
        sa.Column("envelope_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("received_at", TIMESTAMPTZ, nullable=False, server_default=NOW),
        sa.Column("state", sa.String(12), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("rejection_code", sa.String(64), nullable=True),
        sa.Column("processed_at", TIMESTAMPTZ, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_result_inbox"),
        sa.ForeignKeyConstraint(
            ["bound_job_id", "bound_attempt_id"],
            ["execution_attempts.job_id", "execution_attempts.attempt_id"],
            name="fk_result_inbox_bound_attempt",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("state IN ('PENDING','ACCEPTED','REJECTED')", name="ck_result_inbox_state"),
        sa.CheckConstraint("(bound_job_id IS NULL) = (bound_attempt_id IS NULL)", name="ck_result_inbox_bound_pair"),
        sa.CheckConstraint("state <> 'PENDING' OR bound_job_id IS NOT NULL", name="ck_result_inbox_pending_bound"),
        sa.CheckConstraint("(state = 'PENDING') = (processed_at IS NULL)", name="ck_result_inbox_processed_at"),
        sa.CheckConstraint("octet_length(envelope_sha256) = 32", name="ck_result_inbox_sha256_len"),
        sa.CheckConstraint("envelope_sha256 = sha256(original_envelope_raw)", name="ck_result_inbox_sha256_matches"),
        sa.CheckConstraint(REJECTION_CODE_CHECK, name="ck_result_inbox_rejection_code"),
    )
    op.create_index(
        "uq_result_inbox_result_id",
        "result_inbox",
        ["result_id"],
        unique=True,
        postgresql_where=sa.text("result_id IS NOT NULL"),
    )
    op.create_index(
        "ix_result_inbox_pending",
        "result_inbox",
        ["bound_job_id", "received_at", "id"],
        postgresql_where=sa.text("state = 'PENDING'"),
    )

    op.create_table(
        "signed_results",
        sa.Column("result_id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("attempt_id", UUID, nullable=False),
        sa.Column("worker_id", UUID, nullable=False),
        sa.Column("listing_id", UUID, nullable=False),
        sa.Column("key_id", UUID, nullable=False),
        sa.Column("schema_version", sa.String(4), nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("failure_reason", sa.String(16), nullable=True),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("finished_at_wire", sa.String(27), nullable=False),
        sa.Column("payload_jcs_raw", sa.LargeBinary(), nullable=False),
        sa.Column("original_envelope_raw", sa.LargeBinary(), nullable=False),
        sa.Column("signature_raw", sa.LargeBinary(), nullable=False),
        sa.Column("verified_at", TIMESTAMPTZ, nullable=False),
        sa.Column("accepted_at", TIMESTAMPTZ, nullable=False),
        sa.PrimaryKeyConstraint("result_id", name="pk_signed_results"),
        sa.ForeignKeyConstraint(
            ["job_id", "attempt_id"],
            ["execution_attempts.job_id", "execution_attempts.attempt_id"],
            name="fk_signed_results_attempt",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "listing_id", "worker_id"],
            ["jobs.id", "jobs.listing_id", "jobs.worker_id"],
            name="fk_signed_results_job_listing_worker",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id", "key_id"],
            ["worker_public_keys.worker_id", "worker_public_keys.key_id"],
            name="fk_signed_results_worker_key",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", name="uq_signed_results_job_id"),
        sa.UniqueConstraint("job_id", "result_id", name="uq_signed_results_job_id_result_id"),
        sa.CheckConstraint("schema_version = '1'", name="ck_signed_results_schema_version"),
        sa.CheckConstraint("outcome IN ('SUCCESS','FAILED')", name="ck_signed_results_outcome"),
        sa.CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN ('WORKER_FAULT','JOB_FAULT')",
            name="ck_signed_results_failure_reason",
        ),
        sa.CheckConstraint("(outcome = 'SUCCESS') = (failure_reason IS NULL)", name="ck_signed_results_outcome_reason"),
        sa.CheckConstraint("result_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_signed_results_result_digest"),
        sa.CheckConstraint("octet_length(signature_raw) = 64", name="ck_signed_results_signature_len"),
    )

    op.create_table(
        "job_reputation_contributions",
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("worker_id", UUID, nullable=False),
        sa.Column("initial_category", sa.String(12), nullable=False),
        sa.Column("effective_category", sa.String(12), nullable=False),
        sa.Column("corrected_by_dispute_id", UUID, nullable=True),
        sa.Column("correction_version", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("applied_at", TIMESTAMPTZ, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="pk_job_reputation_contributions"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_reputation_contributions_job_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "worker_id"],
            ["jobs.id", "jobs.worker_id"],
            name="fk_job_reputation_contributions_job_worker",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "initial_category IN ('SUCCESS','WORKER_FAULT','NONE')",
            name="ck_job_reputation_contributions_initial_category",
        ),
        sa.CheckConstraint(
            "effective_category IN ('SUCCESS','WORKER_FAULT','NONE')",
            name="ck_job_reputation_contributions_effective_category",
        ),
        # TRANSITIONAL (P2B-DEC-01): Phase 3 drops this CHECK, adds the final correction CHECK and the composite
        # foreign key (job_id, corrected_by_dispute_id) -> disputes (job_id, id).
        sa.CheckConstraint(
            "correction_version = 0 AND corrected_by_dispute_id IS NULL AND effective_category = initial_category",
            name="ck_job_reputation_contributions_phase2_no_correction",
        ),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Phase 2B R1 needs a live connection for its downgrade guard; offline SQL is refused")
    run_downgrade_guard(op.get_bind(), os.environ.get(DISPOSABLE_FLAG) == "1")

    op.drop_table("job_reputation_contributions")
    op.drop_table("signed_results")
    op.drop_table("result_inbox")
    op.drop_table("execution_outbox")
    op.drop_table("allocations")
    op.drop_table("execution_attempts")
