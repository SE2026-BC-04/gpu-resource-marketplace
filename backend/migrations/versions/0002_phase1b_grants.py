"""Phase 1B least-privilege grants for the API and Manager role groups (decision D1).

The groups are created by the role bootstrap (``python -m gpu_marketplace.common.db_roles``) before this
revision runs. This revision never creates, alters or drops a role: roles are cluster-wide and shared
with the test cluster, so downgrade only revokes privileges.

Upgrade removes the database privileges of PUBLIC. Downgrade deliberately does NOT hand them back: the migration
cannot know whether an operator had already restricted PUBLIC, and silently widening access on a downgrade is
worse than leaving a hardened database hardened. Downgrade only revokes what this revision granted.

After granting, the revision checks the effective privileges of both groups and both login roles and fails closed
(transaction rolled back, no ACL touched) if any of them exceeds the matrix, whether through a direct grant or PUBLIC.

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
API_LOGIN = "gpm_api_app"
MANAGER_LOGIN = "gpm_manager_app"

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
    """Fail closed if a runtime role could create objects in schema public, directly or via PUBLIC.

    Roles that do not exist yet are skipped. The migration does not change any ACL, so the operator fixes it.
    """
    existing = sorted(
        bind.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"), {"names": list(groups)}).scalars()
    )
    for group in existing:
        can_create = bind.execute(
            sa.text("SELECT has_schema_privilege(CAST(:role AS name), 'public', 'CREATE')"), {"role": group}
        ).scalar_one()
        if can_create:
            raise RuntimeError(
                f"unexpected privilege: role {group} would have CREATE on schema public (direct, or usually PUBLIC "
                "on a cluster upgraded from PostgreSQL 14 or older): run REVOKE CREATE ON SCHEMA public FROM "
                "PUBLIC (or from the role) as the owner, then retry; no ACL was changed by this migration"
            )


# Column-level privileges that exist on the tables; DELETE/TRUNCATE/TRIGGER only exist per table.
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
TABLE_PRIVILEGES = ("DELETE", "TRUNCATE", "TRIGGER")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
REPORT_LIMIT = 20


def allowed_column_privileges(role: str) -> dict[tuple[str, str], set[str] | None]:
    """Privileges the matrix lets ``role`` hold, as {(privilege, table): columns}; None means every column.

    The login roles hold exactly what their group holds; the Manager holds nothing on tables in Phase 1B.
    """
    if role not in (API_GROUP, API_LOGIN):
        return {}
    allowed: dict[tuple[str, str], set[str] | None] = {("SELECT", table): None for table in API_SELECT_TABLES}
    for privilege, table, columns in API_COLUMN_GRANTS:
        current = allowed.setdefault((privilege, table), set())
        if current is not None:
            current.update(columns)
    return allowed


def require_no_excess_privileges(bind: sa.engine.Connection, roles: Sequence[str]) -> None:
    """Fail closed if any runtime role holds more than the matrix allows, however it got there.

    ``has_*_privilege`` evaluates the effective privilege: a direct grant on a login role, a grant to one of its
    groups, and anything inherited from PUBLIC all count. REVOKE ... FROM PUBLIC on the database does not touch
    PUBLIC privileges on tables or schema, so they have to be looked at here. Nothing is revoked: an ACL the
    migration did not create is the operator's to fix, and a transaction rollback leaves the database untouched.
    """
    existing = sorted(
        bind.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"), {"names": list(roles)}).scalars()
    )
    excess: list[str] = []

    columns = bind.execute(
        sa.text(
            "SELECT r.rolname, p.privilege, c.relname, a.attname "
            "FROM unnest(CAST(:roles AS text[])) AS r(rolname) "
            "CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(privilege) "
            "JOIN pg_class c ON c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
            "WHERE has_column_privilege(CAST(r.rolname AS name), c.oid, a.attnum, p.privilege) "
            "ORDER BY r.rolname, c.relname, p.privilege, a.attnum"
        ),
        {"roles": existing, "privileges": list(COLUMN_PRIVILEGES)},
    )
    granted_columns: dict[tuple[str, str, str], list[str]] = {}
    for role, privilege, table, column in columns:
        allowed = allowed_column_privileges(role).get((privilege, table), set())
        if allowed is None or column in allowed:
            continue
        granted_columns.setdefault((role, privilege, table), []).append(column)
    for (role, privilege, table), names in granted_columns.items():
        excess.append(f"{role} has {privilege} on column(s) {', '.join(names)} of table {table}")

    tables = bind.execute(
        sa.text(
            "SELECT r.rolname, p.privilege, c.relname "
            "FROM unnest(CAST(:roles AS text[])) AS r(rolname) "
            "CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(privilege) "
            "JOIN pg_class c ON c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
            "WHERE has_table_privilege(CAST(r.rolname AS name), c.oid, p.privilege) "
            "ORDER BY r.rolname, c.relname, p.privilege"
        ),
        {"roles": existing, "privileges": list(TABLE_PRIVILEGES)},
    )
    excess.extend(f"{role} has {privilege} on table {table}" for role, privilege, table in tables)

    sequences = bind.execute(
        sa.text(
            "SELECT r.rolname, p.privilege, c.relname "
            "FROM unnest(CAST(:roles AS text[])) AS r(rolname) "
            "CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(privilege) "
            "JOIN pg_class c ON c.relnamespace = 'public'::regnamespace AND c.relkind = 'S' "
            "WHERE has_sequence_privilege(CAST(r.rolname AS name), c.oid, p.privilege) "
            "ORDER BY r.rolname, c.relname, p.privilege"
        ),
        {"roles": existing, "privileges": list(SEQUENCE_PRIVILEGES)},
    )
    excess.extend(f"{role} has {privilege} on sequence {sequence}" for role, privilege, sequence in sequences)

    for role in existing:
        for scope, query, privilege in (
            ("schema public", "SELECT has_schema_privilege(CAST(:role AS name), 'public', 'CREATE')", "CREATE"),
            ("this database", "SELECT has_database_privilege(CAST(:role AS name), current_database(), 'CREATE')", "CREATE"),
            (
                "this database",
                "SELECT has_database_privilege(CAST(:role AS name), current_database(), 'TEMPORARY')",
                "TEMPORARY",
            ),
        ):
            if bind.execute(sa.text(query), {"role": role}).scalar_one():
                excess.append(f"{role} has {privilege} on {scope}")

    if excess:
        shown = "; ".join(excess[:REPORT_LIMIT])
        more = f" (and {len(excess) - REPORT_LIMIT} more)" if len(excess) > REPORT_LIMIT else ""
        raise RuntimeError(
            f"unexpected privilege(s) would exceed the approved runtime grants: {shown}{more}. "
            "The privilege may be direct, inherited, or granted to PUBLIC. Review it, REVOKE it explicitly as the "
            "owner (for PUBLIC, REVOKE ... FROM PUBLIC), then retry; no ACL was changed by this migration"
        )


def upgrade() -> None:
    bind = op.get_bind()
    require_groups(bind, (API_GROUP, MANAGER_GROUP))
    runtime_roles = (API_GROUP, MANAGER_GROUP, API_LOGIN, MANAGER_LOGIN)
    require_schema_closed(bind, runtime_roles)

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
    # Last: the transaction rolls back every grant above if something outside this revision gives more.
    require_no_excess_privileges(bind, runtime_roles)


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
