"""GPU-002-B / Phase 2B R1: ORM metadata must match the approved schema matrices (no database needed).

The ``EXPECTED_*`` sets are the ten Phase 1B tables; the ``PHASE2_*`` sets are the six Phase 2B R1 tables
(``PHASE2_SCHEMA_MATRIX.md``). The ``ALL_*`` sets are what ``alembic upgrade head`` must produce.
"""

from sqlalchemy import CheckConstraint, UniqueConstraint

import gpu_marketplace.domain  # noqa: F401  (registers the mappings on Base.metadata)
from gpu_marketplace.domain.base import Base

EXPECTED_TABLES = {
    "roles",
    "users",
    "user_roles",
    "workers",
    "worker_public_keys",
    "gpu_listings",
    "jobs",
    "simulation_references",
    "worker_reputation_aggregates",
    "audit_events",
}

EXPECTED_FOREIGN_KEYS = {
    "fk_user_roles_user_id": ("user_roles", ("user_id",), "users", ("id",), "RESTRICT"),
    "fk_user_roles_role_code": ("user_roles", ("role_code",), "roles", ("code",), "RESTRICT"),
    "fk_workers_user_role": (
        "workers",
        ("user_id", "role_code"),
        "user_roles",
        ("user_id", "role_code"),
        "RESTRICT",
    ),
    "fk_worker_public_keys_worker_id": ("worker_public_keys", ("worker_id",), "workers", ("id",), "RESTRICT"),
    "fk_gpu_listings_worker_id": ("gpu_listings", ("worker_id",), "workers", ("id",), "RESTRICT"),
    "fk_jobs_client_user_role": (
        "jobs",
        ("client_id", "client_role"),
        "user_roles",
        ("user_id", "role_code"),
        "RESTRICT",
    ),
    "fk_jobs_listing_worker": (
        "jobs",
        ("listing_id", "worker_id"),
        "gpu_listings",
        ("id", "worker_id"),
        "RESTRICT",
    ),
    "fk_simulation_references_job_id": ("simulation_references", ("job_id",), "jobs", ("id",), "CASCADE"),
    "fk_worker_reputation_aggregates_worker_id": (
        "worker_reputation_aggregates",
        ("worker_id",),
        "workers",
        ("id",),
        "RESTRICT",
    ),
}

EXPECTED_CHECKS = {
    "ck_roles_code",
    "ck_users_status",
    "ck_workers_role_code",
    "ck_worker_public_keys_raw_len",
    "ck_worker_public_keys_retired_after_registered",
    "ck_gpu_listings_gpu_model_nonblank",
    "ck_gpu_listings_vram_positive",
    "ck_gpu_listings_total_positive",
    "ck_gpu_listings_allocated_range",
    "ck_gpu_listings_status",
    "ck_gpu_listings_price_nonnegative",
    "ck_jobs_client_role",
    "ck_jobs_requested_gpu_count_positive",
    "ck_jobs_duration_seconds_positive",
    "ck_jobs_status",
    "ck_jobs_terminal_at_consistency",
    "ck_jobs_failure_reason",
    "ck_jobs_started_at_never_running",
    "ck_jobs_idempotency_pair",
    "ck_jobs_request_sha256_len",
    "ck_simulation_references_outcome",
    "ck_simulation_references_outcome_reason",
    "ck_simulation_references_digest_format",
    "ck_worker_reputation_aggregates_successful_nonneg",
    "ck_worker_reputation_aggregates_fault_nonneg",
    "ck_audit_events_actor_kind",
    "ck_audit_events_outcome",
    "ck_audit_events_metadata_object",
}

EXPECTED_UNIQUES = {
    "uq_users_login_name",
    "uq_user_roles_user_id_role_code",
    "uq_workers_user_id",
    "uq_worker_public_keys_worker_id_key_id",
    "uq_gpu_listings_id_worker_id",
    "uq_jobs_enqueue_seq",
    "uq_jobs_id_listing_id",
    "uq_jobs_id_worker_id",
    "uq_jobs_id_client_id",
    "uq_jobs_id_listing_id_worker_id",
}

EXPECTED_INDEXES = {
    "ix_gpu_listings_worker_id_status",
    "ix_jobs_listing_fifo",
    "ix_jobs_client_history",
    "ix_jobs_terminal_cleanup",
    "ix_audit_events_created_at_id",
    "uq_jobs_client_idempotency",
}

PHASE2_TABLES = {
    "execution_attempts",
    "allocations",
    "execution_outbox",
    "result_inbox",
    "signed_results",
    "job_reputation_contributions",
}

# Every Job-linked evidence FK cascades so the guarded purge removes the whole graph (database-design 9.3).
# NO ACTION on the two composite Job FKs made DELETE FROM jobs fail (P2B-FK-05); only the key FK is RESTRICT.
PHASE2_FOREIGN_KEYS = {
    "fk_execution_attempts_job_id": ("execution_attempts", ("job_id",), "jobs", ("id",), "CASCADE"),
    "fk_allocations_job_listing": (
        "allocations",
        ("job_id", "listing_id"),
        "jobs",
        ("id", "listing_id"),
        "CASCADE",
    ),
    "fk_execution_outbox_attempt_id": (
        "execution_outbox",
        ("attempt_id",),
        "execution_attempts",
        ("attempt_id",),
        "CASCADE",
    ),
    "fk_result_inbox_bound_attempt": (
        "result_inbox",
        ("bound_job_id", "bound_attempt_id"),
        "execution_attempts",
        ("job_id", "attempt_id"),
        "CASCADE",
    ),
    "fk_signed_results_attempt": (
        "signed_results",
        ("job_id", "attempt_id"),
        "execution_attempts",
        ("job_id", "attempt_id"),
        "CASCADE",
    ),
    "fk_signed_results_job_listing_worker": (
        "signed_results",
        ("job_id", "listing_id", "worker_id"),
        "jobs",
        ("id", "listing_id", "worker_id"),
        "CASCADE",
    ),
    "fk_signed_results_worker_key": (
        "signed_results",
        ("worker_id", "key_id"),
        "worker_public_keys",
        ("worker_id", "key_id"),
        "RESTRICT",
    ),
    "fk_job_reputation_contributions_job_id": (
        "job_reputation_contributions",
        ("job_id",),
        "jobs",
        ("id",),
        "CASCADE",
    ),
    "fk_job_reputation_contributions_job_worker": (
        "job_reputation_contributions",
        ("job_id", "worker_id"),
        "jobs",
        ("id", "worker_id"),
        "CASCADE",
    ),
}

PHASE2_CHECKS = {
    "ck_execution_attempts_deadlines",
    "ck_allocations_gpu_count_positive",
    "ck_allocations_state",
    "ck_allocations_released_at",
    "ck_execution_outbox_event_type",
    "ck_execution_outbox_state",
    "ck_execution_outbox_delivery_attempts_nonneg",
    "ck_execution_outbox_lease_version_nonneg",
    "ck_execution_outbox_payload_shape",
    "ck_execution_outbox_lease_pair",
    "ck_execution_outbox_state_lease",
    "ck_execution_outbox_acked_at",
    "ck_result_inbox_state",
    "ck_result_inbox_bound_pair",
    "ck_result_inbox_pending_bound",
    "ck_result_inbox_processed_at",
    "ck_result_inbox_sha256_len",
    "ck_result_inbox_sha256_matches",
    "ck_result_inbox_rejection_code",
    "ck_signed_results_schema_version",
    "ck_signed_results_outcome",
    "ck_signed_results_failure_reason",
    "ck_signed_results_outcome_reason",
    "ck_signed_results_result_digest",
    "ck_signed_results_signature_len",
    "ck_job_reputation_contributions_initial_category",
    "ck_job_reputation_contributions_effective_category",
    "ck_job_reputation_contributions_phase2_no_correction",
}

PHASE2_UNIQUES = {
    "uq_execution_attempts_job_id",
    "uq_execution_attempts_job_id_attempt_id",
    "uq_allocations_job_id",
    "uq_execution_outbox_attempt_id_event_type",
    "uq_signed_results_job_id",
    "uq_signed_results_job_id_result_id",
}

# No ix_allocations_listing_active (D-09) and no repair index (D-20): both are outside R1.
PHASE2_INDEXES = {
    "ix_execution_outbox_due",
    "ix_result_inbox_pending",
    "uq_result_inbox_result_id",
}

ALL_TABLES = EXPECTED_TABLES | PHASE2_TABLES
ALL_FOREIGN_KEYS = {**EXPECTED_FOREIGN_KEYS, **PHASE2_FOREIGN_KEYS}
ALL_CHECKS = EXPECTED_CHECKS | PHASE2_CHECKS
ALL_UNIQUES = EXPECTED_UNIQUES | PHASE2_UNIQUES
ALL_INDEXES = EXPECTED_INDEXES | PHASE2_INDEXES


def _constraint_names(kind: type) -> set[str]:
    return {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, kind)
    }


def test_metadata_contains_exactly_the_ten_phase_1b_and_six_phase_2b_tables() -> None:
    assert set(Base.metadata.tables) == ALL_TABLES
    assert len(ALL_TABLES) == 16
    assert "disputes" not in Base.metadata.tables  # Phase 3 creates it in its own revision


def test_every_table_has_a_named_primary_key() -> None:
    names = {table.name: table.primary_key.name for table in Base.metadata.tables.values()}
    assert names == {table: f"pk_{table}" for table in ALL_TABLES}


def test_foreign_keys_match_the_matrix() -> None:
    actual = {}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_key_constraints:
            actual[fk.name] = (
                table.name,
                tuple(element.parent.name for element in fk.elements),
                fk.referred_table.name,
                tuple(element.column.name for element in fk.elements),
                fk.ondelete,
            )
    assert actual == ALL_FOREIGN_KEYS


def test_check_constraints_match_the_matrix() -> None:
    assert _constraint_names(CheckConstraint) == ALL_CHECKS


def test_unique_constraints_match_the_matrix() -> None:
    assert _constraint_names(UniqueConstraint) == ALL_UNIQUES


def test_indexes_match_the_matrix() -> None:
    names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert names == ALL_INDEXES


def test_jobs_enqueue_seq_is_generated_always_identity() -> None:
    column = Base.metadata.tables["jobs"].c.enqueue_seq
    assert column.identity is not None and column.identity.always is True


def test_jobs_submitted_at_has_no_default() -> None:
    column = Base.metadata.tables["jobs"].c.submitted_at
    assert column.server_default is None and column.default is None


def test_worker_public_keys_has_no_private_key_column() -> None:
    columns = set(Base.metadata.tables["worker_public_keys"].c.keys())
    assert columns == {"key_id", "worker_id", "public_key_raw", "registered_at", "retired_at"}


def test_result_inbox_unique_surface_is_only_the_primary_key_and_the_partial_result_id_index() -> None:
    table = Base.metadata.tables["result_inbox"]
    assert not [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    unique_indexes = {index.name: index for index in table.indexes if index.unique}
    assert set(unique_indexes) == {"uq_result_inbox_result_id"}
    index = unique_indexes["uq_result_inbox_result_id"]
    assert [column.name for column in index.columns] == ["result_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "result_id IS NOT NULL"


def test_result_inbox_result_id_is_nullable_and_received_at_uses_the_database_clock() -> None:
    table = Base.metadata.tables["result_inbox"]
    assert table.c.result_id.nullable is True  # R1-Q1: non-NULL is enforced later by ingress, not by DDL
    assert str(table.c.received_at.server_default.arg) == "clock_timestamp()"  # D-17


def test_corrected_by_dispute_id_has_no_foreign_key_in_phase_2() -> None:
    column = Base.metadata.tables["job_reputation_contributions"].c.corrected_by_dispute_id
    assert column.nullable is True and not column.foreign_keys
