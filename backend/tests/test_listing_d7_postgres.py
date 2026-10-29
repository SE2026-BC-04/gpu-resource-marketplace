"""Approved D7 on disposable PostgreSQL; no production migrations are applied.

Setup/DDL use the vetted owner fixture. Adapter SQL uses the restricted role;
one test additionally opens a real gpm_api_app TCP connection without SET ROLE.
"""

import secrets
from datetime import timedelta

import psycopg
import pytest
from alembic import command
from psycopg import sql
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from db_safety import verify_cluster
from gpu_marketplace.domain.listings import GpuListing
from test_listing_repository_postgres import (
    StoreUnavailable,
    VALUES,
    data as listing_data_fixture,
    make_uow,
    sessions as listing_sessions_fixture,
)

data = listing_data_fixture
sessions = listing_sessions_fixture

TRIGGER = "trg_gpu_listings_guard_update"
FUNCTION = "public.fn_gpu_listings_guard_update()"
IDENTITY_ERROR = "ck_gpu_listings_identity_immutable"


def clock(uow):
    return uow._execute(text("SELECT clock_timestamp()")).scalar_one()


def migrate(config, engine, target, revision, *, downgrade=False):
    with engine.connect() as connection:
        verify_cluster(connection, target)
    action = command.downgrade if downgrade else command.upgrade
    action(config, revision)


def acl_snapshot(connection):
    return (
        connection.execute(
            text(
                "SELECT relname, relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND relkind IN ('r','S') ORDER BY relname"
            )
        ).all(),
        connection.execute(
            text(
                "SELECT datacl::text FROM pg_database WHERE datname=current_database()"
            )
        ).scalar_one(),
        connection.execute(
            text("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
        ).scalar_one(),
    )


def test_catalog_has_exact_trigger_function_security_and_no_runtime_execute(
    baseline_database,
):
    with baseline_database.connect() as connection:
        trigger = connection.execute(
            text(
                "SELECT t.tgtype, t.tgenabled, t.tgqual IS NULL, t.tgattr::text, p.prosecdef, p.proconfig "
                "FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
                "WHERE t.tgrelid='public.gpu_listings'::regclass AND t.tgname=:name "
                "AND t.tgfoid=CAST(:function AS regprocedure)"
            ),
            {"name": TRIGGER, "function": FUNCTION},
        ).one()
        assert tuple(trigger) == (19, "O", True, "", False, ["search_path=pg_catalog"])
        for role in ("gpm_api_rw", "gpm_api_app", "gpm_manager_rw", "gpm_manager_app"):
            assert (
                connection.execute(
                    text("SELECT has_function_privilege(:role, :function, 'EXECUTE')"),
                    {"role": role, "function": FUNCTION},
                ).scalar_one()
                is False
            )
        public_execute = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_proc p, "
                "LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a "
                "WHERE p.oid=CAST(:function AS regprocedure) AND a.grantee=0 AND a.privilege_type='EXECUTE')"
            ),
            {"function": FUNCTION},
        ).scalar_one()
        assert public_execute is False


@pytest.mark.parametrize("operation", ["metadata", "pause", "resume"])
def test_effective_writes_return_db_clock_from_same_transaction(
    sessions, data, operation
):
    listing_id = data.paused if operation == "resume" else data.listing
    with make_uow(sessions) as uow:
        before = uow.listings.get_for_update(listing_id)
        lower = clock(uow)
        if operation == "metadata":
            changed = uow.listings.update(
                listing_id,
                {
                    "gpu_model": "New simulated GPU",
                    "vram_gb": 48,
                    "total_gpu_count": 12,
                    "mock_price_per_hour": None,
                },
            )
            assert (changed.gpu_model, changed.vram_gb, changed.total_gpu_count) == (
                "New simulated GPU",
                48,
                12,
            )
        else:
            status = "ACTIVE" if operation == "resume" else "PAUSED"
            changed = uow.listings.set_status(listing_id, status)
            assert changed.status == status
        upper = clock(uow)
        assert lower <= changed.updated_at <= upper
        assert changed.updated_at != before.updated_at
        assert (
            changed.id,
            changed.worker.id,
            changed.created_at,
            changed.allocated_gpu_count,
        ) == (
            before.id,
            before.worker.id,
            before.created_at,
            before.allocated_gpu_count,
        )
        assert uow.listings.get(listing_id) == changed
        uow.commit()
    with make_uow(sessions) as uow:
        assert uow.listings.get(listing_id) == changed


def test_repository_noops_issue_no_update_and_preserve_timestamp(
    baseline_database, sessions, data
):
    updates = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            updates.append(statement)

    event.listen(baseline_database, "before_cursor_execute", capture)
    try:
        with make_uow(sessions) as uow:
            before = uow.listings.get_for_update(data.listing)
            assert uow.listings.update(data.listing, {}) == before
            assert (
                uow.listings.update(data.listing, {"gpu_model": before.gpu_model})
                == before
            )
            assert uow.listings.set_status(data.listing, before.status) == before
            uow.commit()
    finally:
        event.remove(baseline_database, "before_cursor_execute", capture)
    assert updates == []


def test_actual_sql_noop_touches_timestamp_even_without_function_execute(
    sessions, data
):
    with make_uow(sessions) as uow:
        before = uow.listings.get_for_update(data.listing)
        lower = clock(uow)
        timestamp = uow._execute(
            update(GpuListing.__table__)
            .where(GpuListing.id == data.listing)
            .values(gpu_model=GpuListing.gpu_model)
            .returning(GpuListing.updated_at)
        ).scalar_one()
        upper = clock(uow)
        assert lower <= timestamp <= upper and timestamp != before.updated_at
        assert uow.listings.get(data.listing).updated_at == timestamp
        uow.commit()


@pytest.mark.parametrize("field", ["id", "worker_id", "created_at"])
def test_immutable_identity_has_exact_stable_diagnostics(
    baseline_database, sessions, data, field
):
    with make_uow(sessions) as uow:
        before = uow.listings.get(data.listing)
    value = data.other_listing if field == "id" else data.other_worker
    if field == "created_at":
        value = before.created_at + timedelta(seconds=1)
    with pytest.raises(IntegrityError) as error:
        with baseline_database.begin() as owner:
            owner.execute(
                update(GpuListing)
                .where(GpuListing.id == data.listing)
                .values(**{field: value})
            )
    failure = error.value.orig
    assert failure.sqlstate == "23514"
    assert failure.diag.constraint_name == IDENTITY_ERROR
    assert (
        failure.diag.schema_name == "public"
        and failure.diag.table_name == "gpu_listings"
    )
    assert failure.diag.message_primary == "Listing identity is immutable."
    with make_uow(sessions) as uow:
        assert uow.listings.get(data.listing) == before


def test_owner_supplied_updated_at_is_overwritten_not_backdated(
    baseline_database, sessions, data
):
    with make_uow(sessions) as uow:
        before = uow.listings.get(data.listing)
    with baseline_database.begin() as owner:
        lower = owner.execute(text("SELECT clock_timestamp()")).scalar_one()
        changed = owner.execute(
            update(GpuListing)
            .where(GpuListing.id == data.listing)
            .values(updated_at=before.updated_at - timedelta(days=100))
            .returning(GpuListing.updated_at)
        ).scalar_one()
        upper = owner.execute(text("SELECT clock_timestamp()")).scalar_one()
        assert lower <= changed <= upper
    with make_uow(sessions) as uow:
        assert uow.listings.get(data.listing).created_at == before.created_at


@pytest.mark.parametrize(
    "failure", ["body_exception", "commit_failure", "constraint_failure"]
)
def test_failed_write_rolls_back_metadata_status_timestamp_and_prior_create(
    sessions, data, monkeypatch, failure
):
    from sqlalchemy.exc import OperationalError

    with make_uow(sessions) as uow:
        before = uow.listings.get(data.listing)
    with pytest.raises((StoreUnavailable, ValueError)):
        with make_uow(sessions) as uow:
            extra = uow.listings.create(data.worker, VALUES)
            uow.listings.get_for_update(data.listing)
            uow.listings.update(data.listing, {"gpu_model": "Must roll back"})
            uow.listings.set_status(data.listing, "PAUSED")
            if failure == "body_exception":
                raise ValueError("Synthetic failure after writes")
            if failure == "constraint_failure":
                uow.listings.update(data.listing, {"total_gpu_count": 0})
            else:

                def fail():
                    raise OperationalError("secret", {}, Exception("secret"))

                monkeypatch.setattr(uow._active(), "commit", fail)
                uow.commit()
    with make_uow(sessions) as uow:
        assert uow.listings.get(data.listing) == before
        assert uow.listings.get(extra.id) is None


def test_migration_round_trip_preserves_rows_d1_acls_and_rejects_missing_d7(
    baseline_database, test_database, alembic_config, sessions, data
):
    with make_uow(sessions) as uow:
        before = uow.listings.get(data.listing)
    with baseline_database.connect() as owner:
        expected_acls = acl_snapshot(owner)
    migrate(
        alembic_config,
        baseline_database,
        test_database,
        "0002_phase1b_grants",
        downgrade=True,
    )
    try:
        with baseline_database.connect() as owner:
            assert (
                owner.execute(
                    text("SELECT to_regprocedure(:name)"), {"name": FUNCTION}
                ).scalar_one()
                is None
            )
            assert acl_snapshot(owner) == expected_acls
        with pytest.raises(StoreUnavailable):
            with make_uow(sessions) as uow:
                uow.listings.get_for_update(data.listing)
                uow.listings.update(data.listing, {"total_gpu_count": 9})
        with make_uow(sessions) as uow:
            assert uow.listings.get(data.listing) == before
    finally:
        migrate(alembic_config, baseline_database, test_database, "head")
    with baseline_database.connect() as owner:
        assert acl_snapshot(owner) == expected_acls
        assert (
            owner.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0003_listing_d7"
        )
    with make_uow(sessions) as uow:
        assert uow.listings.get(data.listing) == before


def test_manager_gets_no_new_privileges(baseline_database, data):
    with baseline_database.connect() as owner:
        for role in ("gpm_manager_rw", "gpm_manager_app"):
            for column in ("allocated_gpu_count", "updated_at"):
                assert (
                    owner.execute(
                        text(
                            "SELECT has_column_privilege(:role, 'public.gpu_listings', :column, 'UPDATE')"
                        ),
                        {"role": role, "column": column},
                    ).scalar_one()
                    is False
                )


def set_test_password(engine, target, value):
    # Test-only, existing disposable cluster. Never print password/hash/DSN and
    # never alter attributes, memberships, grants or production bootstrap code.
    with engine.begin() as owner:
        verify_cluster(owner, target)
        try:
            from gpu_marketplace.common.db_roles import _scram_verifier

            verifier = value
            if value is not None and not value.startswith(("SCRAM-SHA-256$", "md5")):
                verifier = _scram_verifier(owner, "gpm_api_app", value)
            with owner.connection.driver_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier("gpm_api_app"), sql.Literal(verifier)
                    )
                )
        except psycopg.Error:
            raise RuntimeError(
                "Disposable runtime credential setup/cleanup failed"
            ) from None


def test_real_restricted_api_login_reads_creates_updates_and_denies_managed_columns(
    baseline_database, test_database, data
):
    with baseline_database.connect() as owner:
        verify_cluster(owner, test_database)
        previous = owner.execute(
            text("SELECT rolpassword FROM pg_authid WHERE rolname='gpm_api_app'")
        ).scalar_one()
    password = secrets.token_hex(32)
    runtime = None
    set_test_password(baseline_database, test_database, password)
    try:
        url = make_url(test_database.url).set(username="gpm_api_app", password=password)
        runtime = create_engine(
            url, hide_parameters=True, connect_args={"connect_timeout": 3}
        )
        factory = sessionmaker(bind=runtime)
        with make_uow(factory) as uow:
            assert tuple(
                uow._execute(text("SELECT current_user, session_user")).one()
            ) == ("gpm_api_app", "gpm_api_app")
            flags = uow._execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
            assert not any(flags)
            worker = uow.workers.find_by_user_id(data.user)
            record = uow.listings.create(worker.id, VALUES)
            uow.listings.get_for_update(record.id)
            changed = uow.listings.update(record.id, {"total_gpu_count": 10})
            assert changed.total_gpu_count == 10
            assert uow.listings.set_status(record.id, "PAUSED").status == "PAUSED"
            assert uow.listings.set_status(record.id, "ACTIVE").status == "ACTIVE"
            uow.commit()
        with make_uow(factory) as uow:
            assert uow.listings.get(record.id).total_gpu_count == 10
        for column, value in (
            ("allocated_gpu_count", 1),
            ("updated_at", record.created_at),
            ("worker_id", data.other_worker),
        ):
            with pytest.raises(StoreUnavailable):
                with make_uow(factory) as uow:
                    uow._execute(
                        update(GpuListing)
                        .where(GpuListing.id == record.id)
                        .values(**{column: value})
                    )
    finally:
        if runtime is not None:
            runtime.dispose()
        set_test_password(baseline_database, test_database, previous)
        with baseline_database.connect() as owner:
            verify_cluster(owner, test_database)
            restored = owner.execute(
                text("SELECT rolpassword FROM pg_authid WHERE rolname='gpm_api_app'")
            ).scalar_one()
            if restored != previous:
                raise AssertionError("Disposable runtime credential was not restored")
        password = previous = None
