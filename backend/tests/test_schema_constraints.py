"""GPU-002-B: the constraints in the baseline migration are really enforced by PostgreSQL.

Each case runs in a transaction that is rolled back, so no data survives a test. A rejected statement
must fail on the named constraint, because repositories map those names to API errors.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

DIGEST = "sha256:" + "a" * 64


def new_id() -> str:
    return str(uuid.uuid4())


def violated(connection: Connection, statement: str, **params: object) -> str:
    """Run a statement that must fail and return the constraint (or SQLSTATE) that rejected it."""
    savepoint = connection.begin_nested()
    with pytest.raises(DBAPIError) as caught:
        connection.execute(text(statement), params)
    savepoint.rollback()
    diag = caught.value.orig.diag
    return diag.constraint_name or caught.value.orig.sqlstate


def add_user(connection: Connection, role: str, login: str | None = None) -> str:
    user_id = new_id()
    connection.execute(
        text("INSERT INTO users (id, login_name, password_hash) VALUES (:id, :login, 'hash')"),
        {"id": user_id, "login": login or f"user-{user_id}"},
    )
    connection.execute(
        text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, :role)"), {"id": user_id, "role": role}
    )
    return user_id


def add_worker(connection: Connection) -> tuple[str, str]:
    user_id = add_user(connection, "WORKER")
    worker_id = new_id()
    connection.execute(
        text("INSERT INTO workers (id, user_id, display_name) VALUES (:id, :user, 'Worker')"),
        {"id": worker_id, "user": user_id},
    )
    return user_id, worker_id


def add_listing(connection: Connection, worker_id: str, total: int = 4) -> str:
    listing_id = new_id()
    connection.execute(
        text(
            "INSERT INTO gpu_listings (id, worker_id, gpu_model, vram_gb, total_gpu_count) "
            "VALUES (:id, :worker, 'A100', 80, :total)"
        ),
        {"id": listing_id, "worker": worker_id, "total": total},
    )
    return listing_id


JOB_INSERT = (
    "INSERT INTO jobs (id, client_id, listing_id, worker_id, requested_gpu_count, duration_seconds, "
    "submitted_at, correlation_id{extra_columns}) VALUES (:id, :client, :listing, :worker, 1, 60, "
    "clock_timestamp(), :corr{extra_values})"
)


def add_job(
    connection: Connection,
    client_id: str,
    listing_id: str,
    worker_id: str,
    extra: dict[str, object] | None = None,
) -> str:
    extra = extra or {}
    statement = JOB_INSERT.format(
        extra_columns="".join(f", {column}" for column in extra),
        extra_values="".join(f", :{column}" for column in extra),
    )
    job_id = new_id()
    connection.execute(
        text(statement),
        {"id": job_id, "client": client_id, "listing": listing_id, "worker": worker_id, "corr": new_id(), **extra},
    )
    return job_id


def test_role_code_outside_the_catalog_is_rejected(conn: Connection) -> None:
    assert violated(conn, "INSERT INTO roles (code, description) VALUES ('OWNER', 'x')") == "ck_roles_code"


def test_duplicate_login_name_is_rejected(conn: Connection) -> None:
    add_user(conn, "CLIENT", login="same")
    assert (
        violated(conn, "INSERT INTO users (login_name, password_hash) VALUES ('same', 'h')")
        == "uq_users_login_name"
    )


def test_unknown_user_status_is_rejected(conn: Connection) -> None:
    sql = "INSERT INTO users (login_name, password_hash, status) VALUES ('s', 'h', 'LOCKED')"
    assert violated(conn, sql) == "ck_users_status"


def test_an_account_cannot_hold_two_roles(conn: Connection) -> None:
    user_id = add_user(conn, "CLIENT")
    sql = "INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'WORKER')"
    assert violated(conn, sql, id=user_id) == "pk_user_roles"


def test_unknown_role_code_is_rejected(conn: Connection) -> None:
    user_id = add_user(conn, "CLIENT")
    conn.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": user_id})
    sql = "INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'GHOST')"
    assert violated(conn, sql, id=user_id) == "fk_user_roles_role_code"


def test_deleting_a_user_that_has_a_role_is_restricted(conn: Connection) -> None:
    user_id = add_user(conn, "CLIENT")
    assert violated(conn, "DELETE FROM users WHERE id = :id", id=user_id) == "fk_user_roles_user_id"


def test_dbp02_worker_profile_requires_a_worker_account(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    sql = "INSERT INTO workers (user_id, display_name) VALUES (:id, 'W')"
    assert violated(conn, sql, id=client_id) == "fk_workers_user_role"


def test_second_worker_profile_for_one_account_is_rejected(conn: Connection) -> None:
    user_id, _ = add_worker(conn)
    sql = "INSERT INTO workers (user_id, display_name) VALUES (:id, 'again')"
    assert violated(conn, sql, id=user_id) == "uq_workers_user_id"


@pytest.mark.parametrize("length", [31, 33])
def test_public_key_must_be_exactly_32_bytes(conn: Connection, length: int) -> None:
    _, worker_id = add_worker(conn)
    sql = "INSERT INTO worker_public_keys (worker_id, public_key_raw) VALUES (:w, decode(repeat('ab', :n), 'hex'))"
    assert violated(conn, sql, w=worker_id, n=length) == "ck_worker_public_keys_raw_len"


def test_public_key_cannot_be_retired_before_it_was_registered(conn: Connection) -> None:
    _, worker_id = add_worker(conn)
    sql = (
        "INSERT INTO worker_public_keys (worker_id, public_key_raw, registered_at, retired_at) "
        "VALUES (:w, decode(repeat('ab', 32), 'hex'), clock_timestamp(), clock_timestamp() - interval '1 hour')"
    )
    assert violated(conn, sql, w=worker_id) == "ck_worker_public_keys_retired_after_registered"


def test_worker_with_a_key_cannot_be_deleted(conn: Connection) -> None:
    _, worker_id = add_worker(conn)
    conn.execute(
        text("INSERT INTO worker_public_keys (worker_id, public_key_raw) VALUES (:w, decode(repeat('ab', 32), 'hex'))"),
        {"w": worker_id},
    )
    assert violated(conn, "DELETE FROM workers WHERE id = :w", w=worker_id) == "fk_worker_public_keys_worker_id"


def test_listing_for_an_unknown_worker_is_rejected(conn: Connection) -> None:
    sql = "INSERT INTO gpu_listings (worker_id, gpu_model, vram_gb, total_gpu_count) VALUES (:w, 'A100', 80, 4)"
    assert violated(conn, sql, w=new_id()) == "fk_gpu_listings_worker_id"


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("gpu_model", "   ", "ck_gpu_listings_gpu_model_nonblank"),
        ("vram_gb", 0, "ck_gpu_listings_vram_positive"),
        ("total_gpu_count", 0, "ck_gpu_listings_total_positive"),
        ("status", "DELETED", "ck_gpu_listings_status"),
        ("mock_price_per_hour", -0.01, "ck_gpu_listings_price_nonnegative"),
    ],
)
def test_listing_column_rules(conn: Connection, column: str, value: object, constraint: str) -> None:
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    sql = f"UPDATE gpu_listings SET {column} = :value WHERE id = :id"
    assert violated(conn, sql, value=value, id=listing_id) == constraint


@pytest.mark.parametrize("allocated", [-1, 5])
def test_dbp04_allocated_gpu_count_stays_within_capacity(conn: Connection, allocated: int) -> None:
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id, total=4)
    sql = "UPDATE gpu_listings SET allocated_gpu_count = :n WHERE id = :id"
    assert violated(conn, sql, n=allocated, id=listing_id) == "ck_gpu_listings_allocated_range"
    value = conn.execute(text("SELECT allocated_gpu_count FROM gpu_listings WHERE id = :id"), {"id": listing_id})
    assert value.scalar_one() == 0


def test_dbp01_job_owner_snapshot_must_match_the_listing_owner(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_one = add_worker(conn)
    _, worker_two = add_worker(conn)
    listing_id = add_listing(conn, worker_one)
    statement = JOB_INSERT.format(extra_columns="", extra_values="")
    params = {"id": new_id(), "client": client_id, "listing": listing_id, "worker": worker_two, "corr": new_id()}
    assert violated(conn, statement, **params) == "fk_jobs_listing_worker"
    assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0


def test_dbp02_only_a_client_account_can_submit_a_job(conn: Connection) -> None:
    worker_user, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    statement = JOB_INSERT.format(extra_columns="", extra_values="")
    params = {"id": new_id(), "client": worker_user, "listing": listing_id, "worker": worker_id, "corr": new_id()}
    assert violated(conn, statement, **params) == "fk_jobs_client_user_role"


def test_job_enqueue_seq_is_generated_and_increasing(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    first = add_job(conn, client_id, listing_id, worker_id)
    second = add_job(conn, client_id, listing_id, worker_id)
    rows = conn.execute(text("SELECT id::text, enqueue_seq FROM jobs ORDER BY enqueue_seq")).all()
    assert [row[0] for row in rows] == [first, second]
    assert rows[0][1] < rows[1][1]


def test_job_enqueue_seq_cannot_be_supplied_by_the_caller(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    with pytest.raises(DBAPIError) as caught:
        add_job(conn, client_id, listing_id, worker_id, {"enqueue_seq": 1})
    assert caught.value.orig.sqlstate == "428C9"


def test_job_submitted_at_has_no_default(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    sql = (
        "INSERT INTO jobs (client_id, listing_id, worker_id, requested_gpu_count, duration_seconds, correlation_id) "
        "VALUES (:c, :l, :w, 1, 60, :corr)"
    )
    assert violated(conn, sql, c=client_id, l=listing_id, w=worker_id, corr=new_id()) == "23502"


@pytest.mark.parametrize(
    ("extra", "constraint"),
    [
        ({"status": "CANCELLED"}, "ck_jobs_terminal_at_consistency"),
        ({"status": "FAILED", "terminal_at": "2026-01-01T00:00:00Z"}, "ck_jobs_failure_reason"),
        ({"status": "COMPLETED", "terminal_at": "2026-01-01T00:00:00Z", "failure_reason": "JOB_FAULT"}, "ck_jobs_failure_reason"),
        ({"started_at": "2026-01-01T00:00:00Z"}, "ck_jobs_started_at_never_running"),
        ({"status": "PAUSED"}, "ck_jobs_status"),
        ({"idempotency_key": "key-1"}, "ck_jobs_idempotency_pair"),
        ({"idempotency_key": "key-1", "request_sha256": b"\x00" * 31}, "ck_jobs_request_sha256_len"),
        ({"requested_gpu_count": 0}, "ck_jobs_requested_gpu_count_positive"),
        ({"duration_seconds": 0}, "ck_jobs_duration_seconds_positive"),
    ],
)
def test_job_state_rules(conn: Connection, extra: dict[str, object], constraint: str) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    columns = {"requested_gpu_count": 1, "duration_seconds": 60, **extra}
    statement = (
        "INSERT INTO jobs (client_id, listing_id, worker_id, submitted_at, correlation_id, "
        + ", ".join(columns)
        + ") VALUES (:c, :l, :w, clock_timestamp(), :corr, "
        + ", ".join(f":{column}" for column in columns)
        + ")"
    )
    params = {"c": client_id, "l": listing_id, "w": worker_id, "corr": new_id(), **columns}
    assert violated(conn, statement, **params) == constraint


def test_idempotency_key_is_unique_per_client_only(conn: Connection) -> None:
    client_one = add_user(conn, "CLIENT")
    client_two = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    key = {"idempotency_key": "same-key", "request_sha256": b"\x01" * 32}
    add_job(conn, client_one, listing_id, worker_id, key)
    add_job(conn, client_two, listing_id, worker_id, key)
    with pytest.raises(IntegrityError) as caught:
        savepoint = conn.begin_nested()
        try:
            add_job(conn, client_one, listing_id, worker_id, key)
        finally:
            savepoint.rollback()
    assert caught.value.orig.diag.constraint_name == "uq_jobs_client_idempotency"


def test_jobs_without_an_idempotency_key_never_collide(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    add_job(conn, client_id, listing_id, worker_id)
    add_job(conn, client_id, listing_id, worker_id)


def test_second_simulation_reference_for_a_job_is_rejected(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    job_id = add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    insert = (
        "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, expected_digest) "
        "VALUES (:job, 1, 'v1', 'SUCCESS', :digest)"
    )
    conn.execute(text(insert), {"job": job_id, "digest": DIGEST})
    assert violated(conn, insert, job=job_id, digest=DIGEST) == "pk_simulation_references"


@pytest.mark.parametrize(
    ("digest", "outcome", "reason", "constraint"),
    [
        ("sha256:" + "A" * 64, "SUCCESS", None, "ck_simulation_references_digest_format"),
        ("a" * 64, "SUCCESS", None, "ck_simulation_references_digest_format"),
        ("sha256:" + "a" * 63, "SUCCESS", None, "ck_simulation_references_digest_format"),
        (DIGEST, "SUCCESS", "WORKER_FAULT", "ck_simulation_references_outcome_reason"),
        (DIGEST, "FAILED", "SYSTEM_FAULT", "ck_simulation_references_outcome_reason"),
        (DIGEST, "FAILED", None, "ck_simulation_references_outcome_reason"),
        (DIGEST, "UNKNOWN", None, "ck_simulation_references_outcome"),
    ],
)
def test_simulation_reference_rules(
    conn: Connection, digest: str, outcome: str, reason: str | None, constraint: str
) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    job_id = add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    sql = (
        "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, "
        "expected_failure_reason, expected_digest) VALUES (:job, 1, 'v1', :outcome, :reason, :digest)"
    )
    assert violated(conn, sql, job=job_id, outcome=outcome, reason=reason, digest=digest) == constraint


def test_simulation_reference_cascades_when_its_job_is_deleted(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    job_id = add_job(conn, client_id, add_listing(conn, worker_id), worker_id)
    conn.execute(
        text(
            "INSERT INTO simulation_references (job_id, seed_value, algorithm_version, expected_outcome, expected_digest) "
            "VALUES (:job, 1, 'v1', 'SUCCESS', :digest)"
        ),
        {"job": job_id, "digest": DIGEST},
    )
    conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
    assert conn.execute(text("SELECT count(*) FROM simulation_references")).scalar_one() == 0


def test_listing_with_jobs_cannot_be_deleted(conn: Connection) -> None:
    client_id = add_user(conn, "CLIENT")
    _, worker_id = add_worker(conn)
    listing_id = add_listing(conn, worker_id)
    add_job(conn, client_id, listing_id, worker_id)
    assert violated(conn, "DELETE FROM gpu_listings WHERE id = :id", id=listing_id) == "fk_jobs_listing_worker"


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("successful_jobs", "ck_worker_reputation_aggregates_successful_nonneg"),
        ("worker_fault_jobs", "ck_worker_reputation_aggregates_fault_nonneg"),
    ],
)
def test_reputation_counters_cannot_be_negative(conn: Connection, column: str, constraint: str) -> None:
    _, worker_id = add_worker(conn)
    sql = f"INSERT INTO worker_reputation_aggregates (worker_id, {column}) VALUES (:w, -1)"
    assert violated(conn, sql, w=worker_id) == constraint


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("actor_kind", "ROBOT", "ck_audit_events_actor_kind"),
        ("outcome", "MAYBE", "ck_audit_events_outcome"),
        ("metadata_redacted", "[]", "ck_audit_events_metadata_object"),
    ],
)
def test_audit_event_rules(conn: Connection, column: str, value: str, constraint: str) -> None:
    values = {"actor_kind": "USER", "outcome": "SUCCESS", "metadata_redacted": "{}", column: value}
    sql = (
        "INSERT INTO audit_events (actor_kind, actor_ref, correlation_id, event_type, outcome, metadata_redacted) "
        "VALUES (:actor_kind, 'ref', :corr, 'TEST', :outcome, CAST(:metadata_redacted AS jsonb))"
    )
    assert violated(conn, sql, corr=new_id(), **values) == constraint


def test_audit_subject_id_has_no_foreign_key(conn: Connection) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_events (actor_kind, actor_ref, correlation_id, subject_type, subject_id, event_type, outcome) "
            "VALUES ('SERVICE', 'manager', :corr, 'JOB', :subject, 'JOB_PURGED', 'SUCCESS')"
        ),
        {"corr": new_id(), "subject": new_id()},
    )
