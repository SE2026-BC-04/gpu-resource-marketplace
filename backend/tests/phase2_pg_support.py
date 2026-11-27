"""Seed helpers for the Phase 2B R1 schema tests (``0006_phase2b_schema``).

Use only with the disposable PostgreSQL fixtures from ``conftest.py`` (``db_safety.py`` guards).
Every helper writes through the caller's connection, so the callers decide between a rolled-back
transaction (``conn``) and a committed fixture (``clean_database``).

The envelope and signature bytes are opaque test values: R1 stores bytes and checks lengths and the
SHA-256 relation only. No cryptographic verification happens in this schema revision.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Connection

from test_schema_constraints import add_job, add_listing, add_user, add_worker, new_id

PHASE2_TABLE_ORDER = (
    "execution_attempts",
    "allocations",
    "execution_outbox",
    "result_inbox",
    "signed_results",
    "job_reputation_contributions",
)
PHASE2_TABLES_REVERSE = tuple(reversed(PHASE2_TABLE_ORDER))

DIGEST = "sha256:" + "a" * 64
ENVELOPE = b'{"example":"opaque-test-envelope"}'
SIGNATURE = bytes(range(64))
PAYLOAD_JCS = b"opaque-test-payload"
STARTED_AT = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
FINISH_DUE_AT = STARTED_AT + timedelta(seconds=60)
HARD_DEADLINE_AT = FINISH_DUE_AT + timedelta(seconds=120)


def wire_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class Phase1Seed:
    client_id: str
    worker_user_id: str
    worker_id: str
    listing_id: str
    job_id: str
    key_id: str


@dataclass(frozen=True)
class Graph:
    phase1: Phase1Seed
    attempt_id: str
    event_id: str
    allocation_id: str
    inbox_id: str
    result_id: str


def seed_phase1(connection: Connection, *, status: str = "RUNNING", terminal_age: timedelta | None = None) -> Phase1Seed:
    """Client, Worker, Listing, one Job and one Worker key (the Phase 1 rows R1 builds on)."""
    client_id = add_user(connection, "CLIENT")
    worker_user_id, worker_id = add_worker(connection)
    listing_id = add_listing(connection, worker_id)
    extra: dict[str, object] = {}
    if status != "QUEUED":
        extra["status"] = status
        extra["started_at"] = STARTED_AT
    if status in ("COMPLETED", "FAILED", "CANCELLED"):
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        extra["terminal_at"] = now - (terminal_age or timedelta(0))
    if status == "FAILED":
        extra["failure_reason"] = "WORKER_FAULT"
    job_id = add_job(connection, client_id, listing_id, worker_id, extra or None)
    key_id = new_id()
    connection.execute(
        text("INSERT INTO worker_public_keys (key_id, worker_id, public_key_raw) VALUES (:key, :worker, :raw)"),
        {"key": key_id, "worker": worker_id, "raw": bytes(32)},
    )
    return Phase1Seed(client_id, worker_user_id, worker_id, listing_id, job_id, key_id)


def dispatch_payload(
    *,
    event_id: str,
    attempt_id: str,
    job_id: str,
    worker_id: str,
    listing_id: str,
    gpu_count: int = 1,
    duration_seconds: int = 60,
) -> dict[str, object]:
    """The approved ten-key P1 dispatch payload (D-05/D-13)."""
    return {
        "outbox_event_id": event_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "worker_id": worker_id,
        "listing_id": listing_id,
        "gpu_count": gpu_count,
        "duration_seconds": duration_seconds,
        "simulation_input": {"workload_profile": "demo-v1"},
        "finish_due_at": wire_time(FINISH_DUE_AT),
        "hard_deadline_at": wire_time(HARD_DEADLINE_AT),
    }


def insert_attempt(connection: Connection, job_id: str, attempt_id: str | None = None, **overrides: object) -> str:
    params: dict[str, object] = {
        "attempt": attempt_id or new_id(),
        "job": job_id,
        "started": STARTED_AT,
        "finish": FINISH_DUE_AT,
        "hard": HARD_DEADLINE_AT,
    }
    params.update(overrides)
    connection.execute(
        text(
            "INSERT INTO execution_attempts (attempt_id, job_id, started_at, finish_due_at, hard_deadline_at) "
            "VALUES (:attempt, :job, :started, :finish, :hard)"
        ),
        params,
    )
    return str(params["attempt"])


def insert_allocation(connection: Connection, job_id: str, listing_id: str, **overrides: object) -> str:
    params: dict[str, object] = {
        "id": new_id(),
        "job": job_id,
        "listing": listing_id,
        "gpus": 1,
        "state": "ACTIVE",
        "allocated": STARTED_AT,
        "released": None,
    }
    params.update(overrides)
    connection.execute(
        text(
            "INSERT INTO allocations (id, job_id, listing_id, gpu_count, state, allocated_at, released_at) "
            "VALUES (:id, :job, :listing, :gpus, :state, :allocated, :released)"
        ),
        params,
    )
    return str(params["id"])


OUTBOX_INSERT = (
    "INSERT INTO execution_outbox (event_id, attempt_id, event_type, dispatch_payload, state, delivery_attempts, "
    "next_retry_at, lease_owner, lease_until, lease_version, acked_at) "
    "VALUES (:event, :attempt, :event_type, CAST(:payload AS jsonb), :state, :deliveries, :next_retry, "
    ":lease_owner, :lease_until, :lease_version, :acked_at)"
)


def outbox_params(seed: Phase1Seed, attempt_id: str, event_id: str | None = None, **overrides: object) -> dict[str, object]:
    event = event_id or new_id()
    params: dict[str, object] = {
        "event": event,
        "attempt": attempt_id,
        "event_type": "EXECUTE_JOB",
        "payload": json.dumps(
            dispatch_payload(
                event_id=event,
                attempt_id=attempt_id,
                job_id=seed.job_id,
                worker_id=seed.worker_id,
                listing_id=seed.listing_id,
            )
        ),
        "state": "PENDING",
        "deliveries": 0,
        "next_retry": STARTED_AT,
        "lease_owner": None,
        "lease_until": None,
        "lease_version": 0,
        "acked_at": None,
    }
    params.update(overrides)
    return params


def insert_outbox(connection: Connection, seed: Phase1Seed, attempt_id: str, event_id: str | None = None, **overrides: object) -> str:
    params = outbox_params(seed, attempt_id, event_id, **overrides)
    connection.execute(text(OUTBOX_INSERT), params)
    return str(params["event"])


INBOX_INSERT = (
    "INSERT INTO result_inbox (id, result_id, claimed_job_id, claimed_attempt_id, bound_job_id, bound_attempt_id, "
    "original_envelope_raw, envelope_sha256, state, rejection_code, processed_at) "
    "VALUES (:id, :result, :claimed_job, :claimed_attempt, :bound_job, :bound_attempt, :raw, :sha, :state, :code, :processed)"
)


def inbox_params(job_id: str | None, attempt_id: str | None, **overrides: object) -> dict[str, object]:
    raw = overrides.pop("raw", ENVELOPE)
    params: dict[str, object] = {
        "id": new_id(),
        "result": new_id(),
        "claimed_job": job_id,
        "claimed_attempt": attempt_id,
        "bound_job": job_id,
        "bound_attempt": attempt_id,
        "raw": raw,
        "sha": hashlib.sha256(raw).digest(),  # type: ignore[arg-type]
        "state": "PENDING",
        "code": None,
        "processed": None,
    }
    params.update(overrides)
    return params


def insert_inbox(connection: Connection, job_id: str | None, attempt_id: str | None, **overrides: object) -> str:
    params = inbox_params(job_id, attempt_id, **overrides)
    connection.execute(text(INBOX_INSERT), params)
    return str(params["id"])


SIGNED_INSERT = (
    "INSERT INTO signed_results (result_id, job_id, attempt_id, worker_id, listing_id, key_id, schema_version, outcome, "
    "failure_reason, result_digest, finished_at_wire, payload_jcs_raw, original_envelope_raw, signature_raw, "
    "verified_at, accepted_at) VALUES (:result, :job, :attempt, :worker, :listing, :key, :version, :outcome, :reason, "
    ":digest, :wire, :payload, :raw, :signature, :verified, :accepted)"
)


def signed_params(seed: Phase1Seed, attempt_id: str, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "result": new_id(),
        "job": seed.job_id,
        "attempt": attempt_id,
        "worker": seed.worker_id,
        "listing": seed.listing_id,
        "key": seed.key_id,
        "version": "1",
        "outcome": "SUCCESS",
        "reason": None,
        "digest": DIGEST,
        "wire": wire_time(FINISH_DUE_AT),
        "payload": PAYLOAD_JCS,
        "raw": ENVELOPE,
        "signature": SIGNATURE,
        "verified": FINISH_DUE_AT,
        "accepted": FINISH_DUE_AT,
    }
    params.update(overrides)
    return params


def insert_signed(connection: Connection, seed: Phase1Seed, attempt_id: str, **overrides: object) -> str:
    params = signed_params(seed, attempt_id, **overrides)
    connection.execute(text(SIGNED_INSERT), params)
    return str(params["result"])


CONTRIBUTION_INSERT = (
    "INSERT INTO job_reputation_contributions (job_id, worker_id, initial_category, effective_category, "
    "corrected_by_dispute_id, correction_version, applied_at, updated_at) "
    "VALUES (:job, :worker, :initial, :effective, :dispute, :version, :applied, :updated)"
)


def contribution_params(seed: Phase1Seed, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "job": seed.job_id,
        "worker": seed.worker_id,
        "initial": "SUCCESS",
        "effective": "SUCCESS",
        "dispute": None,
        "version": 0,
        "applied": FINISH_DUE_AT,
        "updated": FINISH_DUE_AT,
    }
    params.update(overrides)
    return params


def insert_contribution(connection: Connection, seed: Phase1Seed, **overrides: object) -> None:
    connection.execute(text(CONTRIBUTION_INSERT), contribution_params(seed, **overrides))


def seed_graph(connection: Connection, seed: Phase1Seed | None = None) -> Graph:
    """One complete valid evidence graph for one Job: every one of the six tables holds one row."""
    seed = seed or seed_phase1(connection)
    attempt_id = insert_attempt(connection, seed.job_id)
    allocation_id = insert_allocation(connection, seed.job_id, seed.listing_id)
    event_id = insert_outbox(connection, seed, attempt_id)
    result_id = new_id()
    inbox_id = insert_inbox(connection, seed.job_id, attempt_id, result=result_id)
    insert_signed(connection, seed, attempt_id, result=result_id)
    insert_contribution(connection, seed)
    return Graph(seed, attempt_id, event_id, allocation_id, inbox_id, result_id)


def row_counts(connection: Connection) -> dict[str, int]:
    return {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608 (fixed names)
        for table in PHASE2_TABLE_ORDER
    }


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False
