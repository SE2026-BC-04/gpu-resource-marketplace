"""Phase 2B R1 (``0006_phase2b_schema``) on real PostgreSQL: P2B-MIG-01/02/03/04/06 and P2B-DRT-01 (R1 part).

Also the fail-closed preflight, the guarded downgrade and the proof that the runtime groups and logins hold no
privilege on the six new tables (R2 grants nothing yet). P2B-MIG-05 (activation gate) belongs to R2 and is not
tested here. Only the disposable cluster that passes ``db_safety.py`` is used; otherwise these tests are NOT_RUN.

Timezone: the local cluster runs ``Asia/Bangkok`` and CI runs UTC; nothing here compares wall-clock strings.
"""

from __future__ import annotations

import importlib.util
import secrets
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError

from db_safety import TestDatabase
from phase2_pg_support import (
    PHASE2_TABLE_ORDER,
    PHASE2_TABLES_REVERSE,
    row_counts,
    seed_graph,
    seed_phase1,
)
from role_credentials import restored_login_role_credentials
from test_schema_constraints import add_job, add_listing, add_user, add_worker
from test_schema_metadata import (
    EXPECTED_TABLES,
    PHASE2_CHECKS,
    PHASE2_FOREIGN_KEYS,
    PHASE2_INDEXES,
    PHASE2_TABLES,
    PHASE2_UNIQUES,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND_ROOT / "migrations" / "versions"
PARENT = "0005_listing_d7"
R1_REVISION = "0006_phase2b_schema"
DISPOSABLE_FLAG = "GPU_MARKETPLACE_PHASE2_DISPOSABLE_DOWNGRADE"

PHASE1_FINGERPRINT_TABLES = (
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

# (column, type, NOT NULL, default) in table column order: pins ``PHASE2_SCHEMA_MATRIX.md`` sections 2-7.
TS = "timestamp(6) with time zone"
EXPECTED_COLUMNS: dict[str, list[tuple[str, str, bool, str | None]]] = {
    "execution_attempts": [
        ("attempt_id", "uuid", True, "gen_random_uuid()"),
        ("job_id", "uuid", True, None),
        ("started_at", TS, True, None),
        ("finish_due_at", TS, True, None),
        ("hard_deadline_at", TS, True, None),
        ("created_at", TS, True, "clock_timestamp()"),
    ],
    "allocations": [
        ("id", "uuid", True, "gen_random_uuid()"),
        ("job_id", "uuid", True, None),
        ("listing_id", "uuid", True, None),
        ("gpu_count", "integer", True, None),
        ("state", "character varying(8)", True, "'ACTIVE'::character varying"),
        ("allocated_at", TS, True, None),
        ("released_at", TS, False, None),
    ],
    "execution_outbox": [
        ("event_id", "uuid", True, "gen_random_uuid()"),
        ("attempt_id", "uuid", True, None),
        ("event_type", "character varying(16)", True, "'EXECUTE_JOB'::character varying"),
        ("dispatch_payload", "jsonb", True, None),
        ("state", "character varying(12)", True, "'PENDING'::character varying"),
        ("delivery_attempts", "integer", True, "0"),
        ("next_retry_at", TS, True, None),
        ("lease_owner", "character varying(128)", False, None),
        ("lease_until", TS, False, None),
        ("lease_version", "bigint", True, "0"),
        ("acked_at", TS, False, None),
        ("created_at", TS, True, "clock_timestamp()"),
        ("updated_at", TS, True, "clock_timestamp()"),
    ],
    "result_inbox": [
        ("id", "uuid", True, "gen_random_uuid()"),
        ("result_id", "uuid", False, None),
        ("claimed_job_id", "uuid", False, None),
        ("claimed_attempt_id", "uuid", False, None),
        ("bound_job_id", "uuid", False, None),
        ("bound_attempt_id", "uuid", False, None),
        ("original_envelope_raw", "bytea", True, None),
        ("envelope_sha256", "bytea", True, None),
        ("received_at", TS, True, "clock_timestamp()"),
        ("state", "character varying(12)", True, "'PENDING'::character varying"),
        ("rejection_code", "character varying(64)", False, None),
        ("processed_at", TS, False, None),
    ],
    "signed_results": [
        ("result_id", "uuid", True, None),
        ("job_id", "uuid", True, None),
        ("attempt_id", "uuid", True, None),
        ("worker_id", "uuid", True, None),
        ("listing_id", "uuid", True, None),
        ("key_id", "uuid", True, None),
        ("schema_version", "character varying(4)", True, None),
        ("outcome", "character varying(8)", True, None),
        ("failure_reason", "character varying(16)", False, None),
        ("result_digest", "character varying(71)", True, None),
        ("finished_at_wire", "character varying(27)", True, None),
        ("payload_jcs_raw", "bytea", True, None),
        ("original_envelope_raw", "bytea", True, None),
        ("signature_raw", "bytea", True, None),
        ("verified_at", TS, True, None),
        ("accepted_at", TS, True, None),
    ],
    "job_reputation_contributions": [
        ("job_id", "uuid", True, None),
        ("worker_id", "uuid", True, None),
        ("initial_category", "character varying(12)", True, None),
        ("effective_category", "character varying(12)", True, None),
        ("corrected_by_dispute_id", "uuid", False, None),
        ("correction_version", "smallint", True, "0"),
        ("applied_at", TS, True, None),
        ("updated_at", TS, True, None),
    ],
}


def r1_module():
    files = sorted(VERSIONS.glob("0006_*.py"))
    assert len(files) == 1, "Phase 2B R1 must ship exactly one revision file"
    spec = importlib.util.spec_from_file_location("phase2b_r1_revision", files[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def user_tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
            ).scalars()
        )


def alembic_version(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())


def phase2_catalog(connection: Connection) -> dict[str, set[object]]:
    """Constraint and index inventory of the six tables, from the live catalog."""
    names = list(PHASE2_TABLES)
    result: dict[str, set[object]] = {}
    for kind in ("p", "u", "f", "c"):
        result[kind] = set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                    "WHERE t.relnamespace = 'public'::regnamespace AND t.relname = ANY(CAST(:names AS text[])) "
                    "AND c.contype = :kind"
                ),
                {"names": names, "kind": kind},
            ).scalars()
        )
    result["indexes"] = set(
        connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY(CAST(:names AS text[]))"),
            {"names": names},
        ).scalars()
    )
    return result


def phase2_definitions(engine: Engine) -> list[tuple[str, str, str]]:
    """Every constraint and index definition of the six tables, for before/after comparison."""
    with engine.connect() as connection:
        constraints = connection.execute(
            text(
                "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relnamespace = 'public'::regnamespace "
                "AND t.relname = ANY(CAST(:names AS text[])) ORDER BY 1, 2"
            ),
            {"names": list(PHASE2_TABLES)},
        ).all()
        indexes = connection.execute(
            text(
                "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = ANY(CAST(:names AS text[])) ORDER BY 1, 2"
            ),
            {"names": list(PHASE2_TABLES)},
        ).all()
    return [tuple(row) for row in constraints] + [tuple(row) for row in indexes]


def phase1_fingerprint(engine: Engine) -> dict[str, tuple[int, str | None]]:
    with engine.connect() as connection:
        return {
            table: tuple(  # type: ignore[misc]
                connection.execute(
                    text(f"SELECT count(*), md5(string_agg(t::text, '|' ORDER BY t::text)) FROM {table} t")  # noqa: S608
                ).one()
            )
            for table in PHASE1_FINGERPRINT_TABLES
        }


def seed_phase1_committed(engine: Engine) -> None:
    """A realistic Phase 1 population: QUEUED and RUNNING Jobs, a reference, a key, an aggregate, an audit row."""
    with engine.begin() as connection:
        seed = seed_phase1(connection, status="RUNNING")
        queued = add_job(connection, seed.client_id, seed.listing_id, seed.worker_id)
        connection.execute(
            text(
                "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, expected_digest) "
                "VALUES (:job, 7, 'v1', 'SUCCESS', :digest)"
            ),
            {"job": queued, "digest": "sha256:" + "b" * 64},
        )
        connection.execute(
            text("INSERT INTO worker_reputation_aggregates (worker_id, successful_jobs) VALUES (:worker, 3)"),
            {"worker": seed.worker_id},
        )
        connection.execute(
            text(
                "INSERT INTO audit_events (actor_kind, actor_ref, correlation_id, event_type, outcome) "
                "VALUES ('SERVICE', 'test', gen_random_uuid(), 'TEST', 'SUCCESS')"
            )
        )
        other_client = add_user(connection, "CLIENT")
        _, other_worker = add_worker(connection)
        add_job(connection, other_client, add_listing(connection, other_worker), other_worker)


@pytest.fixture
def parent_database(clean_database: Engine, alembic_config: Config) -> Engine:
    """Disposable database at the accepted Phase 1 head (``0005_listing_d7``) and nothing newer."""
    command.upgrade(alembic_config, PARENT)
    assert alembic_version(clean_database) == [PARENT]
    return clean_database


# -- P2B-MIG-01 / P2B-DRT-01 (R1 part) -------------------------------------------------------------


def test_p2b_mig_01_the_r1_revision_hangs_off_the_accepted_head_and_is_the_only_head(
    alembic_config: Config,
) -> None:
    script = ScriptDirectory.from_config(alembic_config)
    assert script.get_heads() == [R1_REVISION]
    revision = script.get_revision(R1_REVISION)
    assert revision.down_revision == PARENT
    assert revision.branch_labels == set() and revision.dependencies is None


def test_p2b_mig_01_fresh_upgrade_adds_exactly_six_tables_and_names_match_the_matrix(
    parent_database: Engine, alembic_config: Config
) -> None:
    before = user_tables(parent_database)
    assert before == EXPECTED_TABLES
    command.upgrade(alembic_config, "head")

    after = user_tables(parent_database)
    assert after - before == PHASE2_TABLES and before < after
    assert "disputes" not in after and "retention_exceptions" not in after
    assert alembic_version(parent_database) == [R1_REVISION]

    with parent_database.connect() as connection:
        catalog = phase2_catalog(connection)
    assert catalog["p"] == {f"pk_{table}" for table in PHASE2_TABLES}
    assert catalog["u"] == PHASE2_UNIQUES
    assert catalog["f"] == set(PHASE2_FOREIGN_KEYS)
    assert catalog["c"] == PHASE2_CHECKS
    assert catalog["indexes"] == {f"pk_{table}" for table in PHASE2_TABLES} | PHASE2_UNIQUES | PHASE2_INDEXES


def test_p2b_mig_01_column_inventory_matches_the_schema_matrix(parent_database: Engine, alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        for table, expected in EXPECTED_COLUMNS.items():
            rows = connection.execute(
                text(
                    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid) "
                    "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                    "WHERE a.attrelid = CAST(:table AS regclass) AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
                ),
                {"table": f"public.{table}"},
            ).all()
            assert [tuple(row) for row in rows] == expected, table


def test_p2b_mig_01_the_load_bearing_indexes_and_foreign_key_actions(parent_database: Engine, alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        defs = dict(
            connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            ).all()
        )
        actions = dict(
            connection.execute(
                text("SELECT conname, confdeltype FROM pg_constraint WHERE contype = 'f' AND conname = ANY(CAST(:n AS text[]))"),
                {"n": list(PHASE2_FOREIGN_KEYS)},
            ).all()
        )
    assert "(next_retry_at, event_id)" in defs["ix_execution_outbox_due"]
    assert "WHERE" in defs["ix_execution_outbox_due"] and "'PENDING'" in defs["ix_execution_outbox_due"]
    assert "'CLAIMED'" in defs["ix_execution_outbox_due"] and "'ACKED'" in defs["ix_execution_outbox_due"]
    assert "'EXHAUSTED'" not in defs["ix_execution_outbox_due"]
    assert "(bound_job_id, received_at, id)" in defs["ix_result_inbox_pending"]
    assert "'PENDING'" in defs["ix_result_inbox_pending"]
    assert defs["uq_result_inbox_result_id"].startswith("CREATE UNIQUE INDEX")
    assert "(result_id)" in defs["uq_result_inbox_result_id"] and "IS NOT NULL" in defs["uq_result_inbox_result_id"]
    expected_actions = {
        name: {"CASCADE": "c", "RESTRICT": "r", None: "a"}[spec[4]] for name, spec in PHASE2_FOREIGN_KEYS.items()
    }
    assert actions == expected_actions
    # D-09 / D-20: neither the optional allocation index nor any repair column is part of R1.
    assert not [name for name in defs if name.startswith("ix_allocations")]
    with parent_database.connect() as connection:
        repair = connection.execute(
            text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'execution_outbox' AND column_name LIKE 'repair%'")
        ).scalar_one()
    assert repair == 0


def test_p2b_mig_01_r1_changes_no_phase1_object_and_creates_no_function_or_trigger(
    parent_database: Engine, alembic_config: Config
) -> None:
    def inventory(connection: Connection) -> tuple[object, ...]:
        triggers = connection.execute(
            text("SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal ORDER BY 1, 2")
        ).all()
        functions = connection.execute(
            text("SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace ORDER BY 1")
        ).scalars().all()
        phase1_ddl = connection.execute(
            text(
                "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.connamespace = 'public'::regnamespace AND c.conrelid::regclass::text = ANY(CAST(:t AS text[])) "
                "ORDER BY 1, 2"
            ),
            {"t": sorted(EXPECTED_TABLES)},
        ).all()
        columns = connection.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY(CAST(:t AS text[])) ORDER BY 1, ordinal_position"
            ),
            {"t": sorted(EXPECTED_TABLES)},
        ).all()
        return (
            [tuple(r) for r in triggers],
            list(functions),
            [tuple(r) for r in phase1_ddl],
            [tuple(r) for r in columns],
        )

    with parent_database.connect() as connection:
        before = inventory(connection)
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        after = inventory(connection)
    assert after == before


# -- P2B-MIG-06 -----------------------------------------------------------------------------------


def test_p2b_mig_06_result_inbox_unique_surface_and_rejection_code_check(
    parent_database: Engine, alembic_config: Config
) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        unique_like = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT i.relname FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
                    "WHERE x.indrelid = 'public.result_inbox'::regclass AND (x.indisunique OR x.indisexclusion)"
                )
            )
        }
        constraint_like = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'public.result_inbox'::regclass "
                    "AND contype IN ('p', 'u', 'x')"
                )
            )
        }
        definition = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'public.result_inbox'::regclass AND conname = 'ck_result_inbox_rejection_code'"
            )
        ).scalar_one()
    assert unique_like == {"pk_result_inbox", "uq_result_inbox_result_id"}
    assert constraint_like == {"pk_result_inbox"}  # the partial unique is an index, never a constraint
    for code in ("UNKNOWN_KEY", "KEY_WORKER_MISMATCH", "CONTEXT_MISMATCH", "INVALID_SIGNATURE", "NOT_SELECTED", "ALREADY_TERMINAL"):
        assert f"'{code}'" in definition
    for removed in ("INVALID_STRUCTURE", "UNSUPPORTED_SCHEMA_VERSION"):
        assert removed not in definition
    assert definition.count("'") == 2 * 6 + 2  # six codes plus the 'REJECTED' literal, nothing else quoted


def test_null_sensitive_checks_are_wrapped_in_coalesce_and_use_no_mutable_cast(
    parent_database: Engine, alembic_config: Config
) -> None:
    """A CHECK accepts NULL, so the two predicates over nullable inputs must fail closed (D-05, TV3 action 1)."""
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        definitions = dict(
            connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname IN ('ck_execution_outbox_payload_shape', 'ck_result_inbox_rejection_code')"
                )
            ).all()
        )
    assert set(definitions) == {"ck_execution_outbox_payload_shape", "ck_result_inbox_rejection_code"}
    for name, definition in definitions.items():
        assert definition.startswith("CHECK (COALESCE("), name
        assert "false)" in definition, name
    payload = definitions["ck_execution_outbox_payload_shape"]
    assert "timestamp" not in payload and "::timestamptz" not in payload  # the not-immutable cast is never used
    assert "SELECT" not in payload.upper()  # PostgreSQL forbids subqueries in CHECK; guard against a future rewrite


# -- P2B-MIG-02 -----------------------------------------------------------------------------------


def test_p2b_mig_02_an_injected_ddl_error_rolls_the_whole_revision_back(
    parent_database: Engine, alembic_config: Config
) -> None:
    seed_phase1_committed(parent_database)
    before = phase1_fingerprint(parent_database)
    # A sequence squats on the name of an index created in the middle of R1 (after the first four tables
    # exist), so PostgreSQL itself raises "relation already exists" with real DDL partly done.
    with parent_database.begin() as connection:
        connection.execute(text("CREATE SEQUENCE ix_result_inbox_pending"))
    try:
        with pytest.raises(DBAPIError) as caught:
            command.upgrade(alembic_config, "head")
        assert caught.value.orig.sqlstate == "42P07"  # type: ignore[attr-defined]  # duplicate_table
        assert user_tables(parent_database) == EXPECTED_TABLES
        assert alembic_version(parent_database) == [PARENT]
        assert phase1_fingerprint(parent_database) == before
        with parent_database.connect() as connection:
            leftovers = connection.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND (relname LIKE 'uq\\_execution%' OR relname LIKE 'uq\\_signed%' OR relname LIKE 'uq\\_allocations%' "
                    "OR relname LIKE 'ix\\_execution%' OR relname LIKE 'pk\\_execution%' OR relname LIKE 'pk\\_signed%' "
                    "OR relname LIKE 'pk\\_result%' OR relname LIKE 'pk\\_allocations%' OR relname LIKE 'pk\\_job\\_reputation%')"
                )
            ).scalars().all()
        assert leftovers == []
    finally:
        with parent_database.begin() as connection:
            connection.execute(text("DROP SEQUENCE IF EXISTS ix_result_inbox_pending"))
    command.upgrade(alembic_config, "head")  # the revision is repeatable once the cause is gone
    assert user_tables(parent_database) == EXPECTED_TABLES | PHASE2_TABLES


# -- P2B-MIG-03 -----------------------------------------------------------------------------------


def test_p2b_mig_03_existing_phase1_rows_are_preserved(parent_database: Engine, alembic_config: Config) -> None:
    seed_phase1_committed(parent_database)
    before = phase1_fingerprint(parent_database)
    assert before["jobs"][0] == 3 and before["simulation_references"][0] == 1 and before["audit_events"][0] == 1
    command.upgrade(alembic_config, "head")
    assert phase1_fingerprint(parent_database) == before
    with parent_database.connect() as connection:
        assert set(row_counts(connection).values()) == {0}


# -- P2B-MIG-04 -----------------------------------------------------------------------------------


def test_p2b_mig_04_upgrade_downgrade_upgrade_round_trip_on_the_disposable_database(
    parent_database: Engine, alembic_config: Config
) -> None:
    seed_phase1_committed(parent_database)
    phase1 = phase1_fingerprint(parent_database)
    command.upgrade(alembic_config, "head")
    first = phase2_definitions(parent_database)
    assert first  # constraints and indexes exist

    command.downgrade(alembic_config, PARENT)  # empty Phase 2 tables: allowed without the disposable flag
    assert user_tables(parent_database) == EXPECTED_TABLES
    assert alembic_version(parent_database) == [PARENT]
    assert phase1_fingerprint(parent_database) == phase1

    command.upgrade(alembic_config, "head")
    assert user_tables(parent_database) == EXPECTED_TABLES | PHASE2_TABLES
    assert phase2_definitions(parent_database) == first
    assert phase1_fingerprint(parent_database) == phase1


def test_p2b_mig_04_downgrade_drops_in_reverse_dependency_order_without_side_effects(
    parent_database: Engine, alembic_config: Config
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")  # every revision, Phase 2 first
    assert user_tables(parent_database) == set()
    command.upgrade(alembic_config, "head")
    assert user_tables(parent_database) == EXPECTED_TABLES | PHASE2_TABLES
    assert PHASE2_TABLES_REVERSE == tuple(reversed(PHASE2_TABLE_ORDER))
    source = (VERSIONS / "0006_phase2b_schema.py").read_text(encoding="utf-8")
    drops = [source.index(f'op.drop_table("{table}")') for table in PHASE2_TABLES_REVERSE]
    assert drops == sorted(drops), "downgrade must drop job_reputation_contributions first and execution_attempts last"
    creates = [source.index(f'op.create_table(\n        "{table}"') for table in PHASE2_TABLE_ORDER]
    assert creates == sorted(creates), "upgrade must create execution_attempts first and the contributions last"


# -- downgrade guard ------------------------------------------------------------------------------


@pytest.mark.parametrize("table", PHASE2_TABLE_ORDER)
def test_downgrade_refuses_when_any_phase2_row_exists_unless_the_disposable_flag_is_set(
    parent_database: Engine, alembic_config: Config, monkeypatch: pytest.MonkeyPatch, table: str
) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.begin() as connection:
        seed_graph(connection)
        # Keep exactly one populated table: the others lose their row (cascade-free, owner-only fixture work).
        for other in PHASE2_TABLES_REVERSE:
            if other != table:
                connection.execute(text("SET LOCAL session_replication_role = 'replica'"))
                connection.execute(text(f"DELETE FROM {other}"))  # noqa: S608 (fixed table names)
    with parent_database.connect() as connection:
        counts = row_counts(connection)
    assert counts[table] == 1 and sum(counts.values()) == 1

    monkeypatch.delenv(DISPOSABLE_FLAG, raising=False)
    with pytest.raises(RuntimeError, match=table):
        command.downgrade(alembic_config, PARENT)
    assert user_tables(parent_database) == EXPECTED_TABLES | PHASE2_TABLES
    assert alembic_version(parent_database) == [R1_REVISION]
    with parent_database.connect() as connection:
        assert row_counts(connection) == counts

    monkeypatch.setenv(DISPOSABLE_FLAG, "yes")  # only the exact value "1" counts
    with pytest.raises(RuntimeError, match=table):
        command.downgrade(alembic_config, PARENT)

    monkeypatch.setenv(DISPOSABLE_FLAG, "1")
    command.downgrade(alembic_config, PARENT)
    assert user_tables(parent_database) == EXPECTED_TABLES
    assert alembic_version(parent_database) == [PARENT]


def test_downgrade_refusal_names_every_populated_table_and_never_prints_row_content(
    parent_database: Engine, alembic_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.begin() as connection:
        seed_graph(connection)
    monkeypatch.delenv(DISPOSABLE_FLAG, raising=False)
    with pytest.raises(RuntimeError) as caught:
        command.downgrade(alembic_config, PARENT)
    message = str(caught.value)
    for table in PHASE2_TABLES:
        assert table in message
    assert DISPOSABLE_FLAG in message
    assert "opaque-test-envelope" not in message and "demo-v1" not in message


# -- preflight: fail closed before any DDL --------------------------------------------------------


@pytest.fixture
def preflight_connection(parent_database: Engine) -> Connection:
    with parent_database.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def test_preflight_passes_on_the_accepted_parent(preflight_connection: Connection) -> None:
    r1_module().run_preflight(preflight_connection, [R1_REVISION])


def test_preflight_refuses_a_database_that_is_not_at_the_recorded_parent(preflight_connection: Connection) -> None:
    preflight_connection.execute(text("UPDATE alembic_version SET version_num = '0004_phase1b_jobs_guard_delete'"))
    with pytest.raises(RuntimeError, match="0005_listing_d7"):
        r1_module().run_preflight(preflight_connection, [R1_REVISION])


def test_preflight_refuses_an_empty_or_ambiguous_alembic_version_table(preflight_connection: Connection) -> None:
    preflight_connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('another_head')"))
    with pytest.raises(RuntimeError, match="alembic_version"):
        r1_module().run_preflight(preflight_connection, [R1_REVISION])
    preflight_connection.execute(text("DELETE FROM alembic_version"))
    with pytest.raises(RuntimeError, match="alembic_version"):
        r1_module().run_preflight(preflight_connection, [R1_REVISION])


@pytest.mark.parametrize("table", PHASE2_TABLE_ORDER)
def test_preflight_refuses_when_one_of_the_six_tables_already_exists(preflight_connection: Connection, table: str) -> None:
    preflight_connection.execute(text(f"CREATE TABLE {table} (squatter integer)"))  # noqa: S608 (fixed names)
    with pytest.raises(RuntimeError, match=table):
        r1_module().run_preflight(preflight_connection, [R1_REVISION])


@pytest.mark.parametrize(
    "drop, replacement",
    [
        ("jobs DROP CONSTRAINT uq_jobs_id_listing_id", None),
        ("jobs DROP CONSTRAINT uq_jobs_id_worker_id", None),
        ("jobs DROP CONSTRAINT uq_jobs_id_listing_id_worker_id", None),
        ("worker_public_keys DROP CONSTRAINT uq_worker_public_keys_worker_id_key_id", None),
        # present under the right name but on the wrong columns
        ("jobs DROP CONSTRAINT uq_jobs_id_worker_id", "jobs ADD CONSTRAINT uq_jobs_id_worker_id UNIQUE (id)"),
    ],
    ids=["listing", "worker", "listing_worker", "worker_key", "wrong_columns"],
)
def test_preflight_refuses_when_a_phase1_unique_target_is_missing_or_changed(
    preflight_connection: Connection, drop: str, replacement: str | None
) -> None:
    preflight_connection.execute(text(f"ALTER TABLE {drop}"))
    if replacement:
        preflight_connection.execute(text(f"ALTER TABLE {replacement}"))
    with pytest.raises(RuntimeError, match="uq_"):
        r1_module().run_preflight(preflight_connection, [R1_REVISION])


def test_preflight_refuses_a_second_head(preflight_connection: Connection) -> None:
    with pytest.raises(RuntimeError, match="head"):
        r1_module().run_preflight(preflight_connection, [R1_REVISION, "9999_other_head"])
    with pytest.raises(RuntimeError, match="head"):
        r1_module().run_preflight(preflight_connection, [])


def test_upgrade_through_alembic_refuses_before_any_ddl_when_a_table_already_exists(
    parent_database: Engine, alembic_config: Config
) -> None:
    with parent_database.begin() as connection:
        connection.execute(text("CREATE TABLE result_inbox (squatter integer)"))
    with pytest.raises(RuntimeError, match="result_inbox"):
        command.upgrade(alembic_config, "head")
    assert user_tables(parent_database) == EXPECTED_TABLES | {"result_inbox"}
    assert alembic_version(parent_database) == [PARENT]


def test_upgrade_through_alembic_refuses_a_second_head_before_any_ddl(
    parent_database: Engine, alembic_config: Config, tmp_path: Path
) -> None:
    scripts = tmp_path / "migrations"
    shutil.copytree(BACKEND_ROOT / "migrations", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "9999_other_head.py").write_text(
        'revision = "9999_other_head"\ndown_revision = "0004_phase1b_jobs_guard_delete"\n'
        "branch_labels = None\ndepends_on = None\n\n\ndef upgrade() -> None:\n    pass\n\n\n"
        "def downgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )
    forked = Config(str(BACKEND_ROOT / "alembic.ini"))
    forked.set_main_option("script_location", str(scripts))
    assert set(ScriptDirectory.from_config(forked).get_heads()) == {R1_REVISION, "9999_other_head"}
    with pytest.raises(RuntimeError, match="head"):
        command.upgrade(forked, R1_REVISION)  # an explicit target is accepted by Alembic; R1 refuses itself
    assert user_tables(parent_database) == EXPECTED_TABLES
    assert alembic_version(parent_database) == [PARENT]


# -- the runtime groups and logins have no privilege on the six tables after R1 -------------------

RUNTIME_ROLES = ("gpm_api_rw", "gpm_manager_rw", "gpm_api_app", "gpm_manager_app")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


def test_r1_grants_nothing_effective_direct_inherited_or_default_to_the_runtime_roles(
    parent_database: Engine, alembic_config: Config
) -> None:
    command.upgrade(alembic_config, "head")
    with parent_database.connect() as connection:
        for table in PHASE2_TABLES:
            relation = f"public.{table}"
            acl = connection.execute(text("SELECT relacl FROM pg_class WHERE oid = CAST(:r AS regclass)"), {"r": relation}).scalar_one()
            assert acl is None, f"{table} must carry no ACL entries (owner only), found {acl}"
            for role in RUNTIME_ROLES:
                for privilege in TABLE_PRIVILEGES:
                    granted = connection.execute(
                        text("SELECT has_table_privilege(CAST(:role AS name), CAST(:rel AS regclass), CAST(:priv AS text))"),
                        {"role": role, "rel": relation, "priv": privilege},
                    ).scalar_one()
                    assert granted is False, f"{role} has {privilege} on {table}"
                for privilege in COLUMN_PRIVILEGES:
                    granted = connection.execute(
                        text("SELECT has_any_column_privilege(CAST(:role AS name), CAST(:rel AS regclass), CAST(:priv AS text))"),
                        {"role": role, "rel": relation, "priv": privilege},
                    ).scalar_one()
                    assert granted is False, f"{role} has column {privilege} on {table}"
        public_acl = connection.execute(
            text(
                "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
                "WHERE c.relname = ANY(CAST(:t AS text[])) AND a.grantee = 0"
            ),
            {"t": list(PHASE2_TABLES)},
        ).scalar_one()
        assert public_acl == 0  # nothing granted to PUBLIC either


def test_native_runtime_logins_cannot_touch_the_six_tables_after_r1(
    parent_database: Engine, alembic_config: Config, test_database: TestDatabase
) -> None:
    """Real ``gpm_api_app`` and ``gpm_manager_app`` connections: SELECT and INSERT are refused with 42501.

    Role passwords are cluster-wide, so this runs inside ``restored_login_role_credentials``; the engines
    are disposed before the verifiers are restored (``DB_TEST_ISOLATION.md`` section 2).
    """
    command.upgrade(alembic_config, "head")
    refused: dict[tuple[str, str, str], str] = {}
    with restored_login_role_credentials(parent_database):
        passwords = {role: secrets.token_hex(16) for role in ("gpm_api_app", "gpm_manager_app")}
        with parent_database.begin() as connection:
            for role, password in passwords.items():
                connection.exec_driver_sql(f'ALTER ROLE "{role}" LOGIN PASSWORD \'{password}\'')
        engines: list[Engine] = []
        try:
            for role, password in passwords.items():
                url = make_url(test_database.url).set(username=role, password=password)
                engine = create_engine(
                    url.render_as_string(hide_password=False),
                    connect_args={"application_name": "gpm-phase2-r1-privileges", "connect_timeout": 5},
                )
                engines.append(engine)
                with engine.connect() as connection:
                    identity = tuple(connection.execute(text("SELECT current_user, session_user")).one())
                    assert identity == (role, role)
                for table in PHASE2_TABLE_ORDER:
                    for verb, statement in (
                        ("SELECT", f"SELECT 1 FROM {table} LIMIT 1"),  # noqa: S608 (fixed names)
                        ("INSERT", f"INSERT INTO {table} DEFAULT VALUES"),  # noqa: S608
                        ("DELETE", f"DELETE FROM {table}"),  # noqa: S608
                    ):
                        with engine.connect() as connection:
                            with pytest.raises(DBAPIError) as caught:
                                connection.execute(text(statement))
                            refused[(role, table, verb)] = caught.value.orig.sqlstate  # type: ignore[attr-defined]
        finally:
            for engine in engines:
                engine.dispose()
    assert len(refused) == 2 * len(PHASE2_TABLE_ORDER) * 3
    assert set(refused.values()) == {"42501"}
