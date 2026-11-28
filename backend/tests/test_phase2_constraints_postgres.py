"""Phase 2B R1: every constraint of the six new tables is really enforced by PostgreSQL.

Covers P2B-DRT-15 (transitional contribution CHECK), P2B-FK-01..05, P2B-MIG-06 and a negative case for each
CHECK, unique key and foreign key. Each case runs in a rolled-back transaction (``conn``) and must fail on the
*named* constraint, because repositories map those names to errors. Positive controls prove a negative case
is not failing for an unrelated reason.

Time: all instants are fixed timezone-aware values, so the local ``Asia/Bangkok`` cluster and UTC CI agree.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from phase2_pg_support import (
    CONTRIBUTION_INSERT,
    FINISH_DUE_AT,
    HARD_DEADLINE_AT,
    INBOX_INSERT,
    OUTBOX_INSERT,
    SIGNED_INSERT,
    STARTED_AT,
    Phase1Seed,
    contribution_params,
    dispatch_payload,
    inbox_params,
    insert_allocation,
    insert_attempt,
    insert_contribution,
    insert_inbox,
    insert_outbox,
    insert_signed,
    outbox_params,
    row_counts,
    seed_graph,
    seed_phase1,
    signed_params,
)
from test_schema_constraints import new_id, violated

NOT_NULL = "23502"


@pytest.fixture
def seed(conn: Connection) -> Phase1Seed:
    return seed_phase1(conn)


@pytest.fixture
def attempt(conn: Connection, seed: Phase1Seed) -> str:
    return insert_attempt(conn, seed.job_id)


# -- execution_attempts ----------------------------------------------------------------------------


def test_attempt_positive_control_and_database_time_default(conn: Connection, seed: Phase1Seed) -> None:
    attempt_id = insert_attempt(conn, seed.job_id)
    created = conn.execute(
        text("SELECT created_at <= clock_timestamp() FROM execution_attempts WHERE attempt_id = :id"),
        {"id": attempt_id},
    ).scalar_one()
    assert created is True


@pytest.mark.parametrize(
    "finish_offset, hard_offset",
    [
        (0, 120),  # finish_due_at equals started_at
        (-1, 119),  # finish_due_at before started_at
        (60, 179),  # hard deadline 1 s short of finish_due_at + 120 s
        (60, 181),  # hard deadline 1 s past finish_due_at + 120 s
        (60, 60),  # hard deadline equals finish_due_at
    ],
)
def test_attempt_deadlines_must_follow_the_adr_005_arithmetic(
    conn: Connection, seed: Phase1Seed, finish_offset: int, hard_offset: int
) -> None:
    sql = (
        "INSERT INTO execution_attempts (job_id, started_at, finish_due_at, hard_deadline_at) "
        "VALUES (:job, :started, :finish, :hard)"
    )
    code = violated(
        conn,
        sql,
        job=seed.job_id,
        started=STARTED_AT,
        finish=STARTED_AT + timedelta(seconds=finish_offset),
        hard=STARTED_AT + timedelta(seconds=hard_offset),
    )
    assert code == "ck_execution_attempts_deadlines"


def test_attempt_is_unique_per_job(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    sql = (
        "INSERT INTO execution_attempts (job_id, started_at, finish_due_at, hard_deadline_at) "
        "VALUES (:job, :started, :finish, :hard)"
    )
    code = violated(conn, sql, job=seed.job_id, started=STARTED_AT, finish=FINISH_DUE_AT, hard=HARD_DEADLINE_AT)
    assert code == "uq_execution_attempts_job_id"


def test_attempt_requires_an_existing_job(conn: Connection) -> None:
    sql = (
        "INSERT INTO execution_attempts (job_id, started_at, finish_due_at, hard_deadline_at) "
        "VALUES (:job, :started, :finish, :hard)"
    )
    code = violated(conn, sql, job=new_id(), started=STARTED_AT, finish=FINISH_DUE_AT, hard=HARD_DEADLINE_AT)
    assert code == "fk_execution_attempts_job_id"


@pytest.mark.parametrize("column", ["started_at", "finish_due_at", "hard_deadline_at", "job_id"])
def test_attempt_columns_are_not_null(conn: Connection, seed: Phase1Seed, column: str) -> None:
    values = {
        "job_id": seed.job_id,
        "started_at": STARTED_AT,
        "finish_due_at": FINISH_DUE_AT,
        "hard_deadline_at": HARD_DEADLINE_AT,
    }
    values[column] = None
    sql = (
        "INSERT INTO execution_attempts (job_id, started_at, finish_due_at, hard_deadline_at) "
        "VALUES (:job_id, :started_at, :finish_due_at, :hard_deadline_at)"
    )
    assert violated(conn, sql, **values) == NOT_NULL


# -- allocations -----------------------------------------------------------------------------------


def test_allocation_positive_controls(conn: Connection, seed: Phase1Seed) -> None:
    insert_allocation(conn, seed.job_id, seed.listing_id)
    other = seed_phase1(conn)
    insert_allocation(conn, other.job_id, other.listing_id, state="RELEASED", released=FINISH_DUE_AT)


@pytest.mark.parametrize("gpus", [0, -1])
def test_allocation_gpu_count_must_be_positive(conn: Connection, seed: Phase1Seed, gpus: int) -> None:
    sql = (
        "INSERT INTO allocations (job_id, listing_id, gpu_count, allocated_at) VALUES (:job, :listing, :gpus, :at)"
    )
    code = violated(conn, sql, job=seed.job_id, listing=seed.listing_id, gpus=gpus, at=STARTED_AT)
    assert code == "ck_allocations_gpu_count_positive"


def test_allocation_state_is_closed(conn: Connection, seed: Phase1Seed) -> None:
    sql = (
        "INSERT INTO allocations (job_id, listing_id, gpu_count, state, allocated_at) "
        "VALUES (:job, :listing, 1, 'DONE', :at)"
    )
    assert violated(conn, sql, job=seed.job_id, listing=seed.listing_id, at=STARTED_AT) == "ck_allocations_state"


@pytest.mark.parametrize("state, released", [("RELEASED", None), ("ACTIVE", FINISH_DUE_AT)])
def test_allocation_released_at_tracks_the_state(
    conn: Connection, seed: Phase1Seed, state: str, released: object
) -> None:
    sql = (
        "INSERT INTO allocations (job_id, listing_id, gpu_count, state, allocated_at, released_at) "
        "VALUES (:job, :listing, 1, :state, :at, :released)"
    )
    code = violated(
        conn, sql, job=seed.job_id, listing=seed.listing_id, state=state, at=STARTED_AT, released=released
    )
    assert code == "ck_allocations_released_at"


def test_allocation_is_unique_per_job(conn: Connection, seed: Phase1Seed) -> None:
    insert_allocation(conn, seed.job_id, seed.listing_id)
    sql = (
        "INSERT INTO allocations (job_id, listing_id, gpu_count, allocated_at) VALUES (:job, :listing, 1, :at)"
    )
    assert violated(conn, sql, job=seed.job_id, listing=seed.listing_id, at=STARTED_AT) == "uq_allocations_job_id"


def test_allocation_listing_must_be_the_jobs_listing(conn: Connection, seed: Phase1Seed) -> None:
    other = seed_phase1(conn)
    sql = (
        "INSERT INTO allocations (job_id, listing_id, gpu_count, allocated_at) VALUES (:job, :listing, 1, :at)"
    )
    code = violated(conn, sql, job=seed.job_id, listing=other.listing_id, at=STARTED_AT)
    assert code == "fk_allocations_job_listing"


def test_allocation_columns_without_default_are_not_null(conn: Connection, seed: Phase1Seed) -> None:
    sql = "INSERT INTO allocations (job_id, listing_id, gpu_count) VALUES (:job, :listing, 1)"
    assert violated(conn, sql, job=seed.job_id, listing=seed.listing_id) == NOT_NULL  # allocated_at has no default


# -- execution_outbox ------------------------------------------------------------------------------


def test_outbox_positive_control_and_defaults(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    event_id = new_id()
    payload = json.dumps(
        dispatch_payload(
            event_id=event_id,
            attempt_id=attempt,
            job_id=seed.job_id,
            worker_id=seed.worker_id,
            listing_id=seed.listing_id,
        )
    )
    conn.execute(
        text(
            "INSERT INTO execution_outbox (event_id, attempt_id, dispatch_payload, next_retry_at) "
            "VALUES (:event, :attempt, CAST(:payload AS jsonb), :next_retry)"
        ),
        {"event": event_id, "attempt": attempt, "payload": payload, "next_retry": STARTED_AT},
    )
    row = conn.execute(
        text(
            "SELECT event_type, state, delivery_attempts, lease_owner, lease_until, lease_version, acked_at, "
            "created_at <= clock_timestamp(), updated_at <= clock_timestamp() "
            "FROM execution_outbox WHERE event_id = :id"
        ),
        {"id": event_id},
    ).one()
    assert tuple(row) == ("EXECUTE_JOB", "PENDING", 0, None, None, 0, None, True, True)


@pytest.mark.parametrize(
    "state, owner, until, acked",
    [
        ("CLAIMED", "dispatcher-1", STARTED_AT + timedelta(seconds=30), None),
        ("ACKED", None, None, FINISH_DUE_AT),
        ("EXHAUSTED", None, None, None),
        ("PENDING", None, None, None),
    ],
)
def test_outbox_valid_state_lease_combinations(
    conn: Connection, seed: Phase1Seed, attempt: str, state: str, owner: object, until: object, acked: object
) -> None:
    insert_outbox(
        conn, seed, attempt, state=state, lease_owner=owner, lease_until=until, acked_at=acked
    )


def test_outbox_event_type_is_closed(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    code = violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, event_type="CANCEL_JOB"))
    assert code == "ck_execution_outbox_event_type"


def test_outbox_state_is_closed(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    code = violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, state="DONE"))
    assert code == "ck_execution_outbox_state"


def test_outbox_counters_are_nonnegative(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    assert (
        violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, deliveries=-1))
        == "ck_execution_outbox_delivery_attempts_nonneg"
    )
    assert (
        violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, lease_version=-1))
        == "ck_execution_outbox_lease_version_nonneg"
    )


@pytest.mark.parametrize(
    "owner, until",
    [("dispatcher-1", None), (None, STARTED_AT + timedelta(seconds=30))],
)
def test_outbox_lease_owner_and_lease_until_come_as_a_pair(
    conn: Connection, seed: Phase1Seed, attempt: str, owner: object, until: object
) -> None:
    params = outbox_params(seed, attempt, state="PENDING", lease_owner=owner, lease_until=until)
    assert violated(conn, OUTBOX_INSERT, **params) == "ck_execution_outbox_lease_pair"


@pytest.mark.parametrize(
    "state, owner, until",
    [
        ("CLAIMED", None, None),  # CLAIMED without a lease
        ("PENDING", "dispatcher-1", STARTED_AT + timedelta(seconds=30)),
        ("EXHAUSTED", "dispatcher-1", STARTED_AT + timedelta(seconds=30)),
    ],
)
def test_outbox_only_claimed_rows_carry_a_lease(
    conn: Connection, seed: Phase1Seed, attempt: str, state: str, owner: object, until: object
) -> None:
    params = outbox_params(seed, attempt, state=state, lease_owner=owner, lease_until=until)
    assert violated(conn, OUTBOX_INSERT, **params) == "ck_execution_outbox_state_lease"


def test_outbox_acked_row_cannot_keep_a_lease(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    params = outbox_params(
        seed,
        attempt,
        state="ACKED",
        lease_owner="dispatcher-1",
        lease_until=STARTED_AT + timedelta(seconds=30),
        acked_at=FINISH_DUE_AT,
    )
    assert violated(conn, OUTBOX_INSERT, **params) == "ck_execution_outbox_state_lease"


def test_outbox_an_expired_lease_cannot_resurrect_an_acked_row(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    insert_outbox(conn, seed, attempt, state="ACKED", acked_at=FINISH_DUE_AT)
    sql = (
        "UPDATE execution_outbox SET state = 'CLAIMED', lease_owner = 'dispatcher-2', lease_until = :until "
        "WHERE attempt_id = :attempt"
    )
    code = violated(conn, sql, attempt=attempt, until=STARTED_AT)
    assert code == "ck_execution_outbox_acked_at"  # acked_at would have to be NULL for a CLAIMED row


@pytest.mark.parametrize("state, acked", [("ACKED", None), ("PENDING", FINISH_DUE_AT), ("EXHAUSTED", FINISH_DUE_AT)])
def test_outbox_acked_at_is_set_iff_the_state_is_acked(
    conn: Connection, seed: Phase1Seed, attempt: str, state: str, acked: object
) -> None:
    params = outbox_params(seed, attempt, state=state, acked_at=acked)
    assert violated(conn, OUTBOX_INSERT, **params) == "ck_execution_outbox_acked_at"


def test_outbox_one_event_type_per_attempt(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    insert_outbox(conn, seed, attempt)
    code = violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt))
    assert code == "uq_execution_outbox_attempt_id_event_type"


def test_outbox_requires_an_existing_attempt(conn: Connection, seed: Phase1Seed) -> None:
    code = violated(conn, OUTBOX_INSERT, **outbox_params(seed, new_id()))
    assert code == "fk_execution_outbox_attempt_id"


def test_outbox_dispatch_payload_is_not_null(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    assert violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, payload=None)) == NOT_NULL


def _good_payload(seed: Phase1Seed, attempt: str, event: str) -> dict[str, object]:
    return dispatch_payload(
        event_id=event, attempt_id=attempt, job_id=seed.job_id, worker_id=seed.worker_id, listing_id=seed.listing_id
    )


def _payload_cases(seed: Phase1Seed, attempt: str, event: str) -> dict[str, str]:
    """Each value is the JSON text of one payload that ``ck_execution_outbox_payload_shape`` must refuse."""
    good = _good_payload(seed, attempt, event)
    cases: dict[str, str] = {}

    def variant(name: str, mutate) -> None:  # noqa: ANN001
        candidate = copy.deepcopy(good)
        mutate(candidate)
        cases[name] = json.dumps(candidate)

    variant("nine_keys", lambda p: p.pop("gpu_count"))
    variant("eleven_keys", lambda p: p.update(seed_value=1))
    variant("eleven_keys_oracle_field", lambda p: p.update(expected_digest="sha256:" + "0" * 64))
    variant("renamed_key", lambda p: p.update(job_identifier=p.pop("job_id")))
    variant("wrong_profile", lambda p: p.update(simulation_input={"workload_profile": "demo-v2"}))
    variant("profile_with_extra_key", lambda p: p["simulation_input"].update(command="x"))
    variant("profile_empty_object", lambda p: p.update(simulation_input={}))
    variant("profile_missing_as_null", lambda p: p.update(simulation_input=None))
    variant("profile_is_string", lambda p: p.update(simulation_input="demo-v1"))
    variant("event_id_json_null", lambda p: p.update(outbox_event_id=None))
    variant("attempt_id_json_null", lambda p: p.update(attempt_id=None))
    variant("event_id_missing_replaced", lambda p: p.update(x=p.pop("outbox_event_id")))
    variant("attempt_id_missing_replaced", lambda p: p.update(x=p.pop("attempt_id")))
    variant("event_id_number", lambda p: p.update(outbox_event_id=12345))
    variant("attempt_id_number", lambda p: p.update(attempt_id=12345))
    variant("event_id_differs", lambda p: p.update(outbox_event_id=new_id()))
    variant("attempt_id_differs", lambda p: p.update(attempt_id=new_id()))
    variant("event_id_uppercase", lambda p: p.update(outbox_event_id=event.upper()))
    variant("attempt_id_uppercase", lambda p: p.update(attempt_id=attempt.upper()))
    variant("event_id_braced", lambda p: p.update(outbox_event_id="{" + event + "}"))
    variant("job_id_number", lambda p: p.update(job_id=1))
    variant("worker_id_json_null", lambda p: p.update(worker_id=None))
    variant("listing_id_object", lambda p: p.update(listing_id={"id": 1}))
    cases["array_payload"] = json.dumps([good])
    cases["empty_array_payload"] = "[]"
    cases["string_payload"] = json.dumps("demo-v1")
    cases["number_payload"] = "1"
    cases["json_null_payload"] = "null"
    cases["empty_object_payload"] = "{}"
    return cases


def test_outbox_payload_shape_refuses_every_malformed_payload(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    event = new_id()
    outcomes = {}
    for name, payload in _payload_cases(seed, attempt, event).items():
        code = violated(conn, OUTBOX_INSERT, **outbox_params(seed, attempt, event_id=event, payload=payload))
        outcomes[name] = code
    assert outcomes == {name: "ck_execution_outbox_payload_shape" for name in outcomes}, outcomes


def test_outbox_payload_shape_accepts_the_ten_key_payload_and_is_not_a_cross_table_check(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    """The CHECK pins key set, profile and the two row-local ids; Job/Worker/Listing ids are strings only.

    Equality of the other ids and of the timestamps with their source rows is a transaction rule
    (``P2B-DRT-18``), so a CHECK-level acceptance of a different (but well-formed) job id is intended.
    """
    event = new_id()
    payload = _good_payload(seed, attempt, event)
    payload["job_id"] = new_id()
    insert_outbox(conn, seed, attempt, event_id=event, payload=json.dumps(payload))


def test_outbox_payload_shape_does_not_validate_the_remaining_field_types_or_values(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    """Division of ownership recorded for TV1 review (PR #70, point 3), pinned so nobody assumes more.

    The DDL owns the exact ten-key set, the fixed ``simulation_input``, the two row-local ids and the string type
    of the three entity ids. It does NOT check ``gpu_count``, ``duration_seconds``, ``finish_due_at`` or
    ``hard_deadline_at`` (type, range, wire format, equality with ``execution_attempts``) nor that ``job_id``,
    ``worker_id`` and ``listing_id`` are UUID text or match their Job. The Manager dispatch serializer owns those
    checks (OPEN_DECISION_REGISTER, TV5 re-review row: "field type tests kept in the Manager serializer"), together
    with the transaction rule P2B-DRT-18. The negative serializer tests ship with that later, separately authorized
    code, not with R1. Until then a payload that passes this CHECK is NOT a validated dispatch contract.
    """
    permissive = {
        "gpu_count_string": ("gpu_count", "many"),
        "gpu_count_negative": ("gpu_count", -5),
        "duration_zero": ("duration_seconds", 0),
        "duration_null": ("duration_seconds", None),
        "finish_not_a_timestamp": ("finish_due_at", "not-a-timestamp"),
        "hard_deadline_number": ("hard_deadline_at", 7),
        "job_id_not_a_uuid": ("job_id", "not-a-uuid"),
    }
    for name, (key, value) in permissive.items():
        event = new_id()
        payload = _good_payload(seed, attempt, event)
        payload[key] = value
        savepoint = conn.begin_nested()
        try:
            conn.execute(
                text(OUTBOX_INSERT),
                outbox_params(seed, attempt, event_id=event, payload=json.dumps(payload)),
            )
        except Exception as error:  # noqa: BLE001
            pytest.fail(f"{name}: the DDL now validates {key}; update the ownership note and this test ({error})")
        finally:
            savepoint.rollback()


def test_outbox_payload_shape_failure_is_a_check_violation_not_an_evaluation_error(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    """A scalar or array payload must be refused by the CHECK (23514), never by a jsonb operator error."""
    for payload in ("1", '"x"', "[1,2]", "true"):
        savepoint = conn.begin_nested()
        with pytest.raises(Exception) as caught:  # noqa: PT011
            conn.execute(text(OUTBOX_INSERT), outbox_params(seed, attempt, payload=payload))
        savepoint.rollback()
        assert caught.value.orig.sqlstate == "23514", payload  # type: ignore[attr-defined]


def test_outbox_payload_is_stored_and_read_back_unchanged(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    event = new_id()
    expected = _good_payload(seed, attempt, event)
    insert_outbox(conn, seed, attempt, event_id=event, payload=json.dumps(expected))
    stored = conn.execute(
        text("SELECT dispatch_payload FROM execution_outbox WHERE event_id = :id"), {"id": event}
    ).scalar_one()
    assert stored == expected and len(stored) == 10


# -- result_inbox ----------------------------------------------------------------------------------


def test_inbox_positive_controls_and_database_clock_default(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    inbox_id = insert_inbox(conn, seed.job_id, attempt)
    row = conn.execute(
        text(
            "SELECT state, rejection_code, processed_at, received_at <= clock_timestamp(), "
            "received_at > clock_timestamp() - interval '1 minute' FROM result_inbox WHERE id = :id"
        ),
        {"id": inbox_id},
    ).one()
    assert tuple(row) == ("PENDING", None, None, True, True)


def test_inbox_received_at_default_reads_the_row_insert_instant_not_the_transaction_start(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    """D-17: ``DEFAULT clock_timestamp()`` advances inside one transaction (``now()`` would not)."""
    first = insert_inbox(conn, seed.job_id, attempt, result=new_id())
    conn.execute(text("SELECT pg_sleep(0.01)"))
    second = insert_inbox(conn, seed.job_id, attempt, result=new_id())
    ordered = conn.execute(
        text(
            "SELECT (SELECT received_at FROM result_inbox WHERE id = :first) < "
            "(SELECT received_at FROM result_inbox WHERE id = :second)"
        ),
        {"first": first, "second": second},
    ).scalar_one()
    assert ordered is True


def test_inbox_allows_several_rows_per_attempt_and_null_result_ids(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    for _ in range(2):
        insert_inbox(conn, seed.job_id, attempt, result=None)
    insert_inbox(conn, seed.job_id, attempt)  # a third row with a result_id
    assert conn.execute(text("SELECT count(*) FROM result_inbox")).scalar_one() == 3


def test_inbox_claimed_ids_are_untrusted_and_have_no_foreign_key(conn: Connection) -> None:
    insert_inbox(conn, new_id(), new_id(), bound_job=None, bound_attempt=None, state="REJECTED",
                 code="UNKNOWN_KEY", processed=FINISH_DUE_AT)


def test_inbox_result_id_is_unique_when_present(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    result_id = new_id()
    insert_inbox(conn, seed.job_id, attempt, result=result_id)
    code = violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, result=result_id))
    assert code == "uq_result_inbox_result_id"


def test_inbox_result_id_collision_across_jobs_is_still_one_row(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    other = seed_phase1(conn)
    other_attempt = insert_attempt(conn, other.job_id)
    result_id = new_id()
    insert_inbox(conn, seed.job_id, attempt, result=result_id)
    code = violated(conn, INBOX_INSERT, **inbox_params(other.job_id, other_attempt, result=result_id))
    assert code == "uq_result_inbox_result_id"


def test_inbox_bound_columns_come_as_a_pair(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    for bound_job, bound_attempt in ((seed.job_id, None), (None, attempt)):
        params = inbox_params(seed.job_id, attempt, bound_job=bound_job, bound_attempt=bound_attempt, state="REJECTED",
                              code="UNKNOWN_KEY", processed=FINISH_DUE_AT)
        assert violated(conn, INBOX_INSERT, **params) == "ck_result_inbox_bound_pair"


def test_inbox_pending_row_must_be_bound(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    params = inbox_params(seed.job_id, attempt, bound_job=None, bound_attempt=None)
    assert violated(conn, INBOX_INSERT, **params) == "ck_result_inbox_pending_bound"


def test_inbox_bound_pair_must_name_an_existing_attempt_of_that_job(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    other = seed_phase1(conn)
    other_attempt = insert_attempt(conn, other.job_id)
    # existing attempt, wrong Job
    params = inbox_params(seed.job_id, attempt, bound_job=seed.job_id, bound_attempt=other_attempt)
    assert violated(conn, INBOX_INSERT, **params) == "fk_result_inbox_bound_attempt"
    # unknown attempt
    params = inbox_params(seed.job_id, attempt, bound_attempt=new_id())
    assert violated(conn, INBOX_INSERT, **params) == "fk_result_inbox_bound_attempt"


def test_inbox_state_is_closed(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    params = inbox_params(seed.job_id, attempt, state="DONE", processed=FINISH_DUE_AT)
    assert violated(conn, INBOX_INSERT, **params) == "ck_result_inbox_state"


@pytest.mark.parametrize(
    "state, processed, code",
    [
        ("PENDING", FINISH_DUE_AT, None),
        ("ACCEPTED", None, None),
        ("REJECTED", None, "UNKNOWN_KEY"),
    ],
)
def test_inbox_processed_at_is_set_iff_the_state_is_not_pending(
    conn: Connection, seed: Phase1Seed, attempt: str, state: str, processed: object, code: object
) -> None:
    params = inbox_params(seed.job_id, attempt, state=state, processed=processed, code=code)
    assert violated(conn, INBOX_INSERT, **params) == "ck_result_inbox_processed_at"


def test_inbox_envelope_hash_must_be_32_bytes_and_match_the_stored_bytes(
    conn: Connection, seed: Phase1Seed, attempt: str
) -> None:
    assert violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, sha=bytes(31))) == "ck_result_inbox_sha256_len"
    assert violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, sha=bytes(33))) == "ck_result_inbox_sha256_len"
    assert violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, sha=bytes(32))) == "ck_result_inbox_sha256_matches"
    other_hash = hashlib.sha256(b"different bytes").digest()
    assert violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, sha=other_hash)) == "ck_result_inbox_sha256_matches"


def test_inbox_stores_the_original_bytes_exactly(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    raw = b'{"b":1,\n "a": 2 }\x00\xff trailing'
    inbox_id = insert_inbox(conn, seed.job_id, attempt, raw=raw)
    stored = conn.execute(text("SELECT original_envelope_raw FROM result_inbox WHERE id = :id"), {"id": inbox_id}).scalar_one()
    assert bytes(stored) == raw


def test_inbox_raw_and_hash_columns_are_not_null(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    assert violated(conn, INBOX_INSERT, **inbox_params(seed.job_id, attempt, sha=None)) == NOT_NULL
    params = inbox_params(seed.job_id, attempt)
    params["raw"] = None
    assert violated(conn, INBOX_INSERT, **params) == NOT_NULL


VERIFIER_CODES = ("UNKNOWN_KEY", "KEY_WORKER_MISMATCH", "CONTEXT_MISMATCH", "INVALID_SIGNATURE")
HOUSEKEEPING_CODES = ("NOT_SELECTED", "ALREADY_TERMINAL")


@pytest.mark.parametrize("code", VERIFIER_CODES + HOUSEKEEPING_CODES)
def test_inbox_accepts_exactly_the_six_rejection_codes_on_rejected_rows(
    conn: Connection, seed: Phase1Seed, attempt: str, code: str
) -> None:
    insert_inbox(conn, seed.job_id, attempt, state="REJECTED", code=code, processed=FINISH_DUE_AT)


@pytest.mark.parametrize(
    "code",
    [
        "INVALID_STRUCTURE",  # removed by TV3: a parse failure on admitted bytes is an invariant break
        "UNSUPPORTED_SCHEMA_VERSION",
        "unknown_key",  # case-sensitive
        "UNKNOWN_KEY ",
        "OTHER",
        "",
    ],
)
def test_inbox_refuses_every_other_rejection_code(conn: Connection, seed: Phase1Seed, attempt: str, code: str) -> None:
    params = inbox_params(seed.job_id, attempt, state="REJECTED", code=code, processed=FINISH_DUE_AT)
    assert violated(conn, INBOX_INSERT, **params) == "ck_result_inbox_rejection_code"


def test_inbox_rejection_code_is_present_iff_the_row_is_rejected(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    rejected_without_code = inbox_params(seed.job_id, attempt, state="REJECTED", code=None, processed=FINISH_DUE_AT)
    assert violated(conn, INBOX_INSERT, **rejected_without_code) == "ck_result_inbox_rejection_code"
    pending_with_code = inbox_params(seed.job_id, attempt, state="PENDING", code="UNKNOWN_KEY")
    assert violated(conn, INBOX_INSERT, **pending_with_code) == "ck_result_inbox_rejection_code"
    accepted_with_code = inbox_params(seed.job_id, attempt, state="ACCEPTED", code="UNKNOWN_KEY", processed=FINISH_DUE_AT)
    assert violated(conn, INBOX_INSERT, **accepted_with_code) == "ck_result_inbox_rejection_code"


def test_inbox_settling_a_pending_row_is_checked_on_update(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    inbox_id = insert_inbox(conn, seed.job_id, attempt)
    reject_without_code = "UPDATE result_inbox SET state = 'REJECTED', processed_at = :at WHERE id = :id"
    assert violated(conn, reject_without_code, id=inbox_id, at=FINISH_DUE_AT) == "ck_result_inbox_rejection_code"
    conn.execute(
        text("UPDATE result_inbox SET state = 'REJECTED', rejection_code = 'NOT_SELECTED', processed_at = :at WHERE id = :id"),
        {"id": inbox_id, "at": FINISH_DUE_AT},
    )


# -- signed_results --------------------------------------------------------------------------------


def test_signed_result_positive_control_and_failed_variant(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    insert_signed(conn, seed, attempt)
    other = seed_phase1(conn)
    other_attempt = insert_attempt(conn, other.job_id)
    insert_signed(conn, other, other_attempt, outcome="FAILED", reason="JOB_FAULT")
    third = seed_phase1(conn)
    third_attempt = insert_attempt(conn, third.job_id)
    insert_signed(conn, third, third_attempt, outcome="FAILED", reason="WORKER_FAULT")


def test_signed_result_schema_version_and_outcome_are_closed(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    assert violated(conn, SIGNED_INSERT, **signed_params(seed, attempt, version="2")) == "ck_signed_results_schema_version"
    assert violated(conn, SIGNED_INSERT, **signed_params(seed, attempt, outcome="PARTIAL")) == "ck_signed_results_outcome"


@pytest.mark.parametrize(
    "outcome, reason, expected",
    [
        ("SUCCESS", "WORKER_FAULT", "ck_signed_results_outcome_reason"),
        ("FAILED", None, "ck_signed_results_outcome_reason"),
        ("FAILED", "SYSTEM_FAULT", "ck_signed_results_failure_reason"),  # SYSTEM_FAULT has no signed Worker receipt
        ("FAILED", "OTHER", "ck_signed_results_failure_reason"),
    ],
)
def test_signed_result_failure_reason_rules(
    conn: Connection, seed: Phase1Seed, attempt: str, outcome: str, reason: object, expected: str
) -> None:
    params = signed_params(seed, attempt, outcome=outcome, reason=reason)
    assert violated(conn, SIGNED_INSERT, **params) == expected


@pytest.mark.parametrize(
    "digest, expected",
    [
        ("sha256:" + "A" * 64, "ck_signed_results_result_digest"),  # uppercase hex
        ("sha256:" + "a" * 63, "ck_signed_results_result_digest"),
        ("sha512:" + "a" * 64, "ck_signed_results_result_digest"),
        ("a" * 64, "ck_signed_results_result_digest"),
        ("sha256:" + "g" * 64, "ck_signed_results_result_digest"),
        ("sha256:" + "a" * 65, "22001"),  # 72 characters: refused by varchar(71) before the CHECK
    ],
)
def test_signed_result_digest_format(conn: Connection, seed: Phase1Seed, attempt: str, digest: str, expected: str) -> None:
    assert violated(conn, SIGNED_INSERT, **signed_params(seed, attempt, digest=digest)) == expected


@pytest.mark.parametrize("length", [0, 63, 65])
def test_signed_result_signature_is_exactly_64_bytes(conn: Connection, seed: Phase1Seed, attempt: str, length: int) -> None:
    code = violated(conn, SIGNED_INSERT, **signed_params(seed, attempt, signature=bytes(length)))
    assert code == "ck_signed_results_signature_len"


def test_signed_result_is_unique_per_job_and_per_result_id(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    first = insert_signed(conn, seed, attempt)
    assert violated(conn, SIGNED_INSERT, **signed_params(seed, attempt)) == "uq_signed_results_job_id"
    other = seed_phase1(conn)
    other_attempt = insert_attempt(conn, other.job_id)
    assert violated(conn, SIGNED_INSERT, **signed_params(other, other_attempt, result=first)) == "pk_signed_results"


def test_signed_result_attempt_must_belong_to_the_job(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    other = seed_phase1(conn)
    other_attempt = insert_attempt(conn, other.job_id)
    code = violated(conn, SIGNED_INSERT, **signed_params(seed, other_attempt))
    assert code == "fk_signed_results_attempt"


def test_signed_result_worker_and_listing_must_be_the_jobs(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    other = seed_phase1(conn)
    wrong_worker = signed_params(seed, attempt, worker=other.worker_id, key=other.key_id)
    assert violated(conn, SIGNED_INSERT, **wrong_worker) == "fk_signed_results_job_listing_worker"
    wrong_listing = signed_params(seed, attempt, listing=other.listing_id)
    assert violated(conn, SIGNED_INSERT, **wrong_listing) == "fk_signed_results_job_listing_worker"


def test_signed_result_key_must_be_registered_for_that_worker(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    other = seed_phase1(conn)
    code = violated(conn, SIGNED_INSERT, **signed_params(seed, attempt, key=other.key_id))
    assert code == "fk_signed_results_worker_key"


def test_signed_result_blocks_deleting_its_verification_key(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    insert_signed(conn, seed, attempt)
    code = violated(conn, "DELETE FROM worker_public_keys WHERE key_id = :key", key=seed.key_id)
    assert code == "fk_signed_results_worker_key"


def test_signed_result_keeps_its_own_byte_copies(conn: Connection, seed: Phase1Seed, attempt: str) -> None:
    """D-10: the accepted envelope is stored again, independent of the Inbox row's own life."""
    result_id = new_id()
    inbox_id = insert_inbox(conn, seed.job_id, attempt, result=result_id)
    insert_signed(conn, seed, attempt, result=result_id)
    conn.execute(text("DELETE FROM result_inbox WHERE id = :id"), {"id": inbox_id})
    stored = conn.execute(
        text("SELECT original_envelope_raw, payload_jcs_raw, signature_raw FROM signed_results WHERE result_id = :id"),
        {"id": result_id},
    ).one()
    assert tuple(bytes(value) for value in stored) == (
        b'{"example":"opaque-test-envelope"}',
        b"opaque-test-payload",
        bytes(range(64)),
    )


# -- job_reputation_contributions ------------------------------------------------------------------


def test_contribution_positive_controls(conn: Connection, seed: Phase1Seed) -> None:
    insert_contribution(conn, seed)
    for initial in ("WORKER_FAULT", "NONE"):
        other = seed_phase1(conn)
        insert_contribution(conn, other, initial=initial, effective=initial)


@pytest.mark.parametrize("column", ["initial", "effective"])
def test_contribution_categories_are_closed(conn: Connection, seed: Phase1Seed, column: str) -> None:
    params = contribution_params(seed, **{column: "SYSTEM_FAULT"})
    expected = {
        "initial": "ck_job_reputation_contributions_initial_category",
        "effective": "ck_job_reputation_contributions_effective_category",
    }[column]
    assert violated(conn, CONTRIBUTION_INSERT, **params) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 1},
        {"version": 1, "dispute": "00000000-0000-4000-8000-000000000001"},
        {"dispute": "00000000-0000-4000-8000-000000000001"},
        {"effective": "WORKER_FAULT"},
        {"initial": "WORKER_FAULT", "effective": "SUCCESS"},
        {"initial": "SUCCESS", "effective": "NONE"},
    ],
    ids=["version_1", "version_1_with_dispute", "dispute_only", "effective_changed", "swapped", "success_to_none"],
)
def test_p2b_drt_15_phase3_corrections_are_refused_by_the_transitional_check(
    conn: Connection, seed: Phase1Seed, overrides: dict[str, object]
) -> None:
    params = contribution_params(seed, **overrides)
    assert violated(conn, CONTRIBUTION_INSERT, **params) == "ck_job_reputation_contributions_phase2_no_correction"


def test_p2b_drt_15_updates_cannot_fake_a_correction_either(conn: Connection, seed: Phase1Seed) -> None:
    insert_contribution(conn, seed)
    for assignment in (
        "correction_version = 1",
        "corrected_by_dispute_id = gen_random_uuid()",
        "effective_category = 'WORKER_FAULT'",
        "correction_version = 1, corrected_by_dispute_id = gen_random_uuid(), effective_category = 'NONE'",
    ):
        code = violated(conn, f"UPDATE job_reputation_contributions SET {assignment} WHERE job_id = :job", job=seed.job_id)
        assert code == "ck_job_reputation_contributions_phase2_no_correction", assignment


def test_contribution_is_one_row_per_job_and_matches_the_jobs_worker(conn: Connection, seed: Phase1Seed) -> None:
    insert_contribution(conn, seed)
    assert violated(conn, CONTRIBUTION_INSERT, **contribution_params(seed)) == "pk_job_reputation_contributions"
    other = seed_phase1(conn)
    wrong_worker = contribution_params(other, worker=seed.worker_id)
    assert violated(conn, CONTRIBUTION_INSERT, **wrong_worker) == "fk_job_reputation_contributions_job_worker"


def test_contribution_requires_an_existing_job(conn: Connection, seed: Phase1Seed) -> None:
    params = contribution_params(seed, job=new_id())
    assert violated(conn, CONTRIBUTION_INSERT, **params) == "fk_job_reputation_contributions_job_id"


# -- P2B-FK-05: the guarded purge removes the whole evidence graph without orphans ------------------


def test_deleting_an_eligible_job_removes_its_whole_phase2_graph(conn: Connection) -> None:
    """The D3 guard (552 h after ``terminal_at``) lets the Job go; every child table follows by CASCADE."""
    kept = seed_graph(conn, seed_phase1(conn, status="RUNNING"))
    purged_seed = seed_phase1(conn, status="COMPLETED", terminal_age=timedelta(hours=553))
    purged = seed_graph(conn, purged_seed)
    before = row_counts(conn)
    assert set(before.values()) == {2}

    conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": purged_seed.job_id})

    assert row_counts(conn) == {table: 1 for table in before}
    remaining = conn.execute(
        text("SELECT count(*) FROM execution_attempts WHERE attempt_id = :attempt"), {"attempt": kept.attempt_id}
    ).scalar_one()
    assert remaining == 1
    orphans = conn.execute(
        text(
            "SELECT (SELECT count(*) FROM execution_attempts WHERE job_id = :job) + "
            "(SELECT count(*) FROM allocations WHERE job_id = :job) + "
            "(SELECT count(*) FROM signed_results WHERE job_id = :job) + "
            "(SELECT count(*) FROM job_reputation_contributions WHERE job_id = :job) + "
            "(SELECT count(*) FROM result_inbox WHERE bound_job_id = :job) + "
            "(SELECT count(*) FROM execution_outbox WHERE attempt_id = :attempt)"
        ),
        {"job": purged_seed.job_id, "attempt": purged.attempt_id},
    ).scalar_one()
    assert orphans == 0


def test_a_job_that_is_not_eligible_keeps_its_graph_because_the_guard_refuses_first(conn: Connection) -> None:
    graph = seed_graph(conn, seed_phase1(conn, status="COMPLETED", terminal_age=timedelta(hours=551)))
    code = violated(conn, "DELETE FROM jobs WHERE id = :id", id=graph.phase1.job_id)
    assert code == "trg_jobs_guard_delete"
    assert set(row_counts(conn).values()) == {1}


def test_deleting_an_attempt_cascades_to_outbox_inbox_and_signed_result_but_not_to_the_allocation(
    conn: Connection,
) -> None:
    graph = seed_graph(conn)
    conn.execute(text("DELETE FROM execution_attempts WHERE attempt_id = :id"), {"id": graph.attempt_id})
    assert row_counts(conn) == {
        "execution_attempts": 0,
        "allocations": 1,
        "execution_outbox": 0,
        "result_inbox": 0,
        "signed_results": 0,
        "job_reputation_contributions": 1,
    }


def test_p2b_fk_01_no_foreign_key_references_an_absent_disputes_table(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT count(*) FROM pg_constraint c WHERE c.contype = 'f' AND c.confrelid::regclass::text = 'disputes'"
        )
    ).scalar_one()
    assert rows == 0
    assert conn.execute(text("SELECT to_regclass('public.disputes') IS NULL")).scalar_one() is True
