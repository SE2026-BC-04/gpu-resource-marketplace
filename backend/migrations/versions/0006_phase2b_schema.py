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

Safety gates (PR #70 review by TV1; none of them grants, revokes or changes anything outside these six tables):

* Preflight fails closed before any DDL: wrong parent, one of the six tables already present, a Phase 1 unique
  target missing or on other columns, a second head, or a ``search_path`` that does not resolve to schema ``public``.
  The CREATE/DROP/foreign-key names below are unqualified exactly like revisions 0001-0005, so the revision
  enforces the pinned contract (``current_schema()`` is ``public`` and ``alembic_version``, ``jobs`` and
  ``worker_public_keys`` resolve to their ``public`` tables, which also rejects a ``pg_temp`` shadow) instead of
  assuming it.
* Zero effective privilege: "this revision has no GRANT" does not prove the runtime roles hold nothing, because
  default ACLs of the migration owner, PUBLIC and role membership attach privileges to every new table. After its last
  DDL statement and before it can commit, ``upgrade()`` reads the effective table and column privileges of every
  ``gpm_api_*`` / ``gpm_manager_*`` role, of every role they belong to (inherited or SET-able) and of PUBLIC on the six
  tables. Any finding, or a missing expected runtime role, raises and rolls the whole revision back. Nothing is ever
  granted or revoked here; the operator removes the cause (typically a ``pg_default_acl`` entry) as the owner.
* Downgrade: it refuses while any of the six tables holds a row, because those rows are accepted evidence, and there
  is NO override (an environment flag cannot prove that a database is disposable). The guard takes ACCESS EXCLUSIVE
  locks on all six tables in a fixed order (``LOCK_ORDER``), checks them empty and the same transaction drops them, so a
  writer that commits after the check cannot lose its row: it waits for the lock and then either sees the tables gone
  or is checked after it. A bounded ``lock_timeout`` (``DEFAULT_LOCK_TIMEOUT`` unless the session already has one)
  turns an indefinitely blocked downgrade into a clean refusal. To remove populated Phase 2 tables, recreate the
  disposable database instead. Reverting this file in Git does not undo an applied revision.

Dispatch payload ownership: ``ck_execution_outbox_payload_shape`` pins only the exact ten-key set, the fixed
``simulation_input``, the two row-local ids and the string type of the three entity ids. It does not validate the full
dispatch contract. ``gpu_count``, ``duration_seconds``, the two timestamps (type, range, wire format, equality with
``execution_attempts``) and the UUID form and Job match of ``job_id`` / ``worker_id`` / ``listing_id`` belong to the
Manager dispatch serializer and to P2B-DRT-18; their negative tests ship with that later, separately authorized code.

Revision ID: 0006_phase2b_schema
Revises: 0005_listing_d7
Create Date: 2026-11-27
"""

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

# Creation order; the downgrade uses the reverse.
PHASE2_TABLES = (
    "execution_attempts",
    "allocations",
    "execution_outbox",
    "result_inbox",
    "signed_results",
    "job_reputation_contributions",
)

# Fixed lock order for the downgrade guard: parents first, i.e. the order in which a writer builds the graph, so that a
# writer inserting parent-then-child cannot deadlock with it. The drop order in ``downgrade()`` is the reverse.
LOCK_ORDER = PHASE2_TABLES
DEFAULT_LOCK_TIMEOUT = "10s"

# Unqualified names that the revision's CREATE/DROP statements and foreign keys resolve through ``search_path``.
SEARCH_PATH_NAMES = ("alembic_version", "jobs", "worker_public_keys")

# Runtime role families the zero-privilege check covers (direct, inherited and PUBLIC reach).
RUNTIME_ROLES = ("gpm_api_rw", "gpm_manager_rw", "gpm_api_app", "gpm_manager_app")
RUNTIME_ROLE_PATTERN = "^gpm_(api|manager)_"
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
MAX_REPORTED_FINDINGS = 20

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


def require_public_schema_resolution(bind: sa.engine.Connection, names: Sequence[str], when: str) -> None:
    """The unqualified names of this revision must resolve to schema ``public`` (the pinned ``search_path`` contract)."""
    current, path = bind.execute(sa.text("SELECT current_schema(), current_setting('search_path')")).one()
    if current != "public":
        raise RuntimeError(
            f"Phase 2B R1 refused: search_path must resolve to schema public (this revision, like 0001-0005, uses "
            f"unqualified CREATE/DROP and foreign-key names) but current_schema() is {current!r} with search_path "
            f"{path!r}; {when}"
        )
    shadowed = [
        name
        for name in names
        if bind.execute(
            sa.text("SELECT to_regclass(:bare) IS NOT NULL AND to_regclass(:bare) IS DISTINCT FROM to_regclass(:qualified)"),
            {"bare": name, "qualified": f"public.{name}"},
        ).scalar_one()
    ]
    if shadowed:
        raise RuntimeError(
            f"Phase 2B R1 refused: search_path {path!r} resolves {', '.join(shadowed)} outside schema public "
            f"(for example a temporary table or another schema earlier in the path); {when}"
        )


def run_preflight(bind: sa.engine.Connection, heads: Sequence[str]) -> None:
    """Fail closed, before any DDL, when the database is not exactly what this revision was written for."""
    require_public_schema_resolution(bind, SEARCH_PATH_NAMES, "no DDL was run")
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


def run_downgrade_guard(bind: sa.engine.Connection) -> None:
    """Lock the six tables, then refuse to drop accepted evidence: any row in any of them blocks the downgrade.

    The ACCESS EXCLUSIVE locks are taken before the emptiness check and live until the surrounding transaction ends,
    so the same transaction that passes this check also drops the tables (``downgrade()``). A concurrent writer
    cannot commit a row between the check and the drop; it queues behind the lock instead.
    """
    require_public_schema_resolution(bind, LOCK_ORDER, "no DDL was run")
    if bind.execute(sa.text("SELECT current_setting('lock_timeout')")).scalar_one() in ("0", "0ms"):
        bind.execute(sa.text(f"SET LOCAL lock_timeout = '{DEFAULT_LOCK_TIMEOUT}'"))
    for table in LOCK_ORDER:
        bind.execute(sa.text(f"LOCK TABLE public.{table} IN ACCESS EXCLUSIVE MODE"))  # noqa: S608 (fixed names)
    populated = [
        table
        for table in reversed(LOCK_ORDER)
        if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM public.{table})")).scalar_one()  # noqa: S608
    ]
    if populated:
        raise RuntimeError(
            f"Phase 2B R1 downgrade refused: table(s) {', '.join(populated)} hold rows (Inbox bytes, signed results "
            "or contributions are accepted evidence and a downgrade would destroy them). There is no override: "
            "export or retire the evidence through its own authorized process, or recreate a disposable database; "
            "no DDL was run"
        )


PRIVILEGE_FINDINGS_SQL = """
WITH RECURSIVE closure(oid) AS (
    SELECT r.oid FROM pg_roles r WHERE r.rolname ~ :pattern
    UNION
    SELECT m.roleid FROM pg_auth_members m JOIN closure c ON m.member = c.oid
),
targets AS (
    SELECT c.oid, c.relname FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(CAST(:tables AS text[]))
)
SELECT r.rolname AS grantee, t.relname AS table_name, p.priv AS privilege, 'table' AS scope
FROM closure cl JOIN pg_roles r ON r.oid = cl.oid CROSS JOIN targets t
CROSS JOIN unnest(CAST(:table_privileges AS text[])) AS p(priv)
WHERE has_table_privilege(r.oid, t.oid, p.priv)
UNION ALL
SELECT r.rolname, t.relname, p.priv, 'column'
FROM closure cl JOIN pg_roles r ON r.oid = cl.oid CROSS JOIN targets t
CROSS JOIN unnest(CAST(:column_privileges AS text[])) AS p(priv)
WHERE has_any_column_privilege(r.oid, t.oid, p.priv)
UNION ALL
SELECT 'PUBLIC', t.relname, a.privilege_type, 'table'
FROM targets t JOIN pg_class c ON c.oid = t.oid
CROSS JOIN LATERAL aclexplode(c.relacl) AS a WHERE a.grantee = 0
UNION ALL
SELECT 'PUBLIC', t.relname, a.privilege_type, 'column'
FROM targets t JOIN pg_attribute att ON att.attrelid = t.oid AND att.attnum > 0 AND NOT att.attisdropped
CROSS JOIN LATERAL aclexplode(att.attacl) AS a WHERE a.grantee = 0
ORDER BY 1, 2, 3, 4
"""

DEFAULT_ACL_HINTS_SQL = """
SELECT CASE WHEN d.defaclnamespace = 0 THEN 'every schema' ELSE d.defaclnamespace::regnamespace::text END,
       CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE a.grantee::regrole::text END,
       a.privilege_type
FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
WHERE d.defaclobjtype = 'r'
  AND d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user)
  AND d.defaclnamespace IN (0, 'public'::regnamespace)
  AND a.grantee <> d.defaclrole
ORDER BY 1, 2, 3
"""


def run_privilege_check(bind: sa.engine.Connection) -> None:
    """Fail closed when any runtime role or PUBLIC holds a privilege on the six tables (R1 must grant nothing).

    Read-only: it never grants or revokes. Table and column privileges are evaluated as the server sees them
    (``has_table_privilege`` / ``has_any_column_privilege``: direct, inherited, PUBLIC, default ACL, superuser),
    for every ``gpm_api_*`` / ``gpm_manager_*`` role and every role they belong to whatever the INHERIT/SET flags,
    plus the explicit PUBLIC entries of the table and column ACLs.
    """
    present = set(
        bind.execute(
            sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(CAST(:roles AS text[]))"),
            {"roles": list(RUNTIME_ROLES)},
        ).scalars()
    )
    missing = [role for role in RUNTIME_ROLES if role not in present]
    if missing:
        raise RuntimeError(
            f"Phase 2B R1 refused: expected runtime role(s) {', '.join(missing)} not found, so the zero-privilege "
            "check cannot be proven; run the role bootstrap (revision 0002 needs them too). The revision is rolled "
            "back as a whole; nothing was granted or revoked"
        )

    findings = bind.execute(
        sa.text(PRIVILEGE_FINDINGS_SQL),
        {
            "pattern": RUNTIME_ROLE_PATTERN,
            "tables": list(PHASE2_TABLES),
            "table_privileges": list(TABLE_PRIVILEGES),
            "column_privileges": list(COLUMN_PRIVILEGES),
        },
    ).all()
    if not findings:
        return

    unique = list(dict.fromkeys(tuple(row) for row in findings))
    lines = [
        f"{grantee} has {privilege}{' (column level)' if scope == 'column' else ''} on {table}"
        for grantee, table, privilege, scope in unique[:MAX_REPORTED_FINDINGS]
    ]
    more = len(unique) - len(lines)
    hints = bind.execute(sa.text(DEFAULT_ACL_HINTS_SQL)).all()
    hint_text = (
        "; pg_default_acl of the migration owner ("
        + ", ".join(f"{privilege} to {grantee} in {schema}" for schema, grantee, privilege in hints)
        + ") attaches privileges to every new table"
        if hints
        else ""
    )
    raise RuntimeError(
        "Phase 2B R1 refused: effective privilege on the six Phase 2 tables for a runtime role or PUBLIC, but this "
        "revision must grant nothing (R2 owns grants): "
        + "; ".join(lines)
        + (f"; and {more} more" if more else "")
        + hint_text
        + ". The revision is rolled back as a whole; nothing was granted or revoked. Review the default ACLs, "
        "role memberships and grants as the database owner, then retry"
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

    # Last statement before the revision can commit: R1 must leave every runtime role and PUBLIC with nothing.
    run_privilege_check(bind)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Phase 2B R1 needs a live connection for its downgrade guard; offline SQL is refused")
    run_downgrade_guard(op.get_bind())  # locks the six tables; the drops below run in the same transaction

    op.drop_table("job_reputation_contributions")
    op.drop_table("signed_results")
    op.drop_table("result_inbox")
    op.drop_table("execution_outbox")
    op.drop_table("allocations")
    op.drop_table("execution_attempts")
