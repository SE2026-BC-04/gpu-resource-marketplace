"""Phase 1B least-privilege grants for the API and Manager role groups (decision D1).

The groups are created by the role bootstrap (``python -m gpu_marketplace.common.db_roles``) before this
revision runs. This revision never creates, alters or drops a role: roles are cluster-wide and shared
with the test cluster, so downgrade only revokes privileges.

Upgrade removes the database privileges of PUBLIC. Downgrade deliberately does NOT hand them back: the migration
cannot know whether an operator had already restricted PUBLIC, and silently widening access on a downgrade is
worse than leaving a hardened database hardened. Downgrade only revokes what this revision granted.

Grants follow the GPU-002-A schema matrix section 6.3. Manager only needs CONNECT in Phase 1B. Neither group
gets DELETE, TRUNCATE, REFERENCES, TRIGGER or any DDL privilege; lifecycle triggers (D2) and guarded delete
(D3) are separate revisions.

Revision ID: 0002_phase1b_grants
Revises: 0001_phase1b_baseline
Create Date: 2026-10-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase1b_grants"
down_revision: Union[str, None] = "0001_phase1b_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

API_GROUP = "gpm_api_rw"
MANAGER_GROUP = "gpm_manager_rw"

TABLES = (
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
)

# Whole-table SELECT is granted where the API legitimately reads every column.
API_SELECT_TABLES = (
    "roles",
    "users",
    "user_roles",
    "workers",
    "gpu_listings",
    "jobs",
    "worker_reputation_aggregates",
)
# API never reads public_key_raw, the oracle (simulation_references) or audit_events.
API_COLUMN_GRANTS = (
    ("SELECT", "worker_public_keys", ("key_id", "worker_id", "registered_at", "retired_at")),
    (
        "INSERT",
        "gpu_listings",
        ("worker_id", "gpu_model", "vram_gb", "total_gpu_count", "mock_price_per_hour"),
    ),
    (
        "UPDATE",
        "gpu_listings",
        ("gpu_model", "vram_gb", "total_gpu_count", "status", "mock_price_per_hour"),
    ),
    (
        "INSERT",
        "jobs",
        (
            "client_id",
            "listing_id",
            "worker_id",
            "requested_gpu_count",
            "duration_seconds",
            "submitted_at",
            "idempotency_key",
            "request_sha256",
            "correlation_id",
        ),
    ),
    ("UPDATE", "jobs", ("status", "terminal_at")),
    (
        "INSERT",
        "simulation_references",
        (
            "job_id",
            "seed_value",
            "algorithm_version",
            "expected_outcome",
            "expected_failure_reason",
            "expected_digest",
        ),
    ),
    (
        "INSERT",
        "audit_events",
        (
            "actor_kind",
            "actor_ref",
            "correlation_id",
            "subject_type",
            "subject_id",
            "event_type",
            "outcome",
            "metadata_redacted",
        ),
    ),
)


def require_groups(bind: sa.engine.Connection, groups: Sequence[str]) -> None:
    """Stop with a clear message instead of creating roles: bootstrap must run first."""
    existing = set(
        bind.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"), {"names": list(groups)}).scalars()
    )
    missing = [group for group in groups if group not in existing]
    if missing:
        raise RuntimeError(
            "missing database role group(s) "
            + ", ".join(missing)
            + ": run the role bootstrap (python -m gpu_marketplace.common.db_roles) before the migration"
        )


def require_schema_closed(bind: sa.engine.Connection, groups: Sequence[str]) -> None:
    """Fail closed if the runtime groups could create objects in schema public, e.g. via PUBLIC on an old cluster.

    The migration does not change the privileges of PUBLIC itself, so the operator must fix this explicitly.
    """
    for group in groups:
        can_create = bind.execute(
            sa.text("SELECT has_schema_privilege(CAST(:role AS name), 'public', 'CREATE')"), {"role": group}
        ).scalar_one()
        if can_create:
            raise RuntimeError(
                f"role {group} would have CREATE on schema public (usually granted to PUBLIC on a cluster upgraded "
                "from PostgreSQL 14 or older): run REVOKE CREATE ON SCHEMA public FROM PUBLIC as the owner, then retry"
            )


def upgrade() -> None:
    bind = op.get_bind()
    require_groups(bind, (API_GROUP, MANAGER_GROUP))
    require_schema_closed(bind, (API_GROUP, MANAGER_GROUP))

    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()); "
            f"EXECUTE format('GRANT CONNECT ON DATABASE %I TO {API_GROUP}, {MANAGER_GROUP}', current_database()); "
            "END $$"
        )
    )
    # Explicit rather than relying on the default PUBLIC USAGE of schema public, which a recreated schema lacks.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {API_GROUP}, {MANAGER_GROUP}")
    for table in API_SELECT_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {API_GROUP}")
    for privilege, table, columns in API_COLUMN_GRANTS:
        op.execute(f"GRANT {privilege} ({', '.join(columns)}) ON {table} TO {API_GROUP}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {API_GROUP}, {MANAGER_GROUP}")
    for table in TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {API_GROUP}, {MANAGER_GROUP}")
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            f"EXECUTE format('REVOKE ALL ON DATABASE %I FROM {API_GROUP}, {MANAGER_GROUP}', current_database()); "
            "END $$"
        )
    )
