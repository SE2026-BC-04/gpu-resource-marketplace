"""GPU-002-B: ORM metadata must match the approved schema matrix (no database needed)."""

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


def _constraint_names(kind: type) -> set[str]:
    return {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, kind)
    }


def test_metadata_contains_exactly_the_ten_phase_1b_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_has_a_named_primary_key() -> None:
    names = {table.name: table.primary_key.name for table in Base.metadata.tables.values()}
    assert names == {table: f"pk_{table}" for table in EXPECTED_TABLES}


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
    assert actual == EXPECTED_FOREIGN_KEYS


def test_check_constraints_match_the_matrix() -> None:
    assert _constraint_names(CheckConstraint) == EXPECTED_CHECKS


def test_unique_constraints_match_the_matrix() -> None:
    assert _constraint_names(UniqueConstraint) == EXPECTED_UNIQUES


def test_indexes_match_the_matrix() -> None:
    names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert names == EXPECTED_INDEXES


def test_jobs_enqueue_seq_is_generated_always_identity() -> None:
    column = Base.metadata.tables["jobs"].c.enqueue_seq
    assert column.identity is not None and column.identity.always is True


def test_jobs_submitted_at_has_no_default() -> None:
    column = Base.metadata.tables["jobs"].c.submitted_at
    assert column.server_default is None and column.default is None


def test_worker_public_keys_has_no_private_key_column() -> None:
    columns = set(Base.metadata.tables["worker_public_keys"].c.keys())
    assert columns == {"key_id", "worker_id", "public_key_raw", "registered_at", "retired_at"}
