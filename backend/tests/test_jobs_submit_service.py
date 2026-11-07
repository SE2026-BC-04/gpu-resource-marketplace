from contextlib import AbstractContextManager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from gpu_marketplace.jobs.errors import IdempotencyKeyReused, ListingPaused
from gpu_marketplace.jobs.models import JobRole, JobStatus, SubmitJobRequest
from gpu_marketplace.jobs.ports import JobRecord
from gpu_marketplace.jobs.submit import JobSubmitService, request_fingerprint
from gpu_marketplace.jobs.submit_ports import (
    ListingAdmission,
    SimulationReference,
    StoredSubmission,
)

CLIENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
LISTING_ID = UUID("22222222-2222-4222-8222-222222222222")
WORKER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("33333333-3333-4333-8333-333333333333")
REQUEST = SubmitJobRequest(
    listing_id=LISTING_ID,
    gpu_count=2,
    duration_seconds=60,
)


class Principal:
    user_id = CLIENT_ID
    role = JobRole.CLIENT


def make_job() -> JobRecord:
    return JobRecord(
        id=JOB_ID,
        client_id=CLIENT_ID,
        worker_id=WORKER_ID,
        listing_id=LISTING_ID,
        requested_gpu_count=2,
        duration_seconds=60,
        status=JobStatus.QUEUED,
        failure_reason=None,
        submitted_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        started_at=None,
        terminal_at=None,
    )


class FakeTransaction(AbstractContextManager):
    def __init__(
        self,
        *,
        listing_status: str = "ACTIVE",
        existing: StoredSubmission | None = None,
    ) -> None:
        self.listing_status = listing_status
        self.existing = existing
        self.references: list[SimulationReference] = []
        self.inserted = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def lock_listing(self, *, listing_id: UUID):
        if listing_id != LISTING_ID:
            return None
        return ListingAdmission(
            listing_id=LISTING_ID,
            worker_id=WORKER_ID,
            status=self.listing_status,
            total_gpu_count=4,
        )

    def find_existing(self, *, client_id: UUID, idempotency_key: str):
        assert client_id == CLIENT_ID
        assert idempotency_key == "client-request-0001"
        return self.existing

    def insert_job(self, **kwargs):
        assert kwargs["client_id"] == CLIENT_ID
        assert kwargs["listing"].worker_id == WORKER_ID
        assert kwargs["request"] == REQUEST
        self.inserted = True
        return make_job()

    def insert_reference(self, *, job_id: UUID, reference: SimulationReference) -> None:
        assert job_id == JOB_ID
        self.references.append(reference)

    def commit(self) -> None:
        self.committed = True


class FakeStore:
    def __init__(
        self,
        *,
        transaction: FakeTransaction,
        outside_existing: StoredSubmission | None = None,
    ) -> None:
        self.tx = transaction
        self.outside_existing = outside_existing
        self.lookup_calls = 0

    def find_existing(self, *, client_id: UUID, idempotency_key: str):
        self.lookup_calls += 1
        assert client_id == CLIENT_ID
        assert idempotency_key == "client-request-0001"
        return self.outside_existing

    def transaction(self, *, principal: Principal):
        assert principal.user_id == CLIENT_ID
        return self.tx


def existing_submission() -> StoredSubmission:
    return StoredSubmission(job=make_job(), request_sha256=request_fingerprint(REQUEST))


def test_request_fingerprint_hashes_normalized_logical_fields() -> None:
    same_request = SubmitJobRequest.model_validate(
        {"duration_seconds": 60, "gpu_count": 2, "listing_id": str(LISTING_ID)}
    )
    assert request_fingerprint(REQUEST) == request_fingerprint(same_request)
    assert len(request_fingerprint(REQUEST)) == 32


def test_same_key_body_replays_before_paused_state_check() -> None:
    tx = FakeTransaction(listing_status="PAUSED", existing=existing_submission())
    service = JobSubmitService(store=FakeStore(transaction=tx))

    result = service.submit(
        principal=Principal(),
        idempotency_key="client-request-0001",
        request=REQUEST,
        correlation_id=UUID("44444444-4444-4444-8444-444444444444"),
    )

    assert result.replayed is True
    assert result.job.id == JOB_ID
    assert not tx.inserted
    assert not tx.committed


def test_existing_key_with_changed_body_returns_conflict_before_listing() -> None:
    changed = SubmitJobRequest(
        listing_id=LISTING_ID,
        gpu_count=2,
        duration_seconds=61,
    )
    tx = FakeTransaction(listing_status="PAUSED")
    store = FakeStore(transaction=tx, outside_existing=existing_submission())
    service = JobSubmitService(store=store)

    with pytest.raises(IdempotencyKeyReused):
        service.submit(
            principal=Principal(),
            idempotency_key="client-request-0001",
            request=changed,
            correlation_id=UUID("44444444-4444-4444-8444-444444444444"),
        )
    assert store.lookup_calls == 1
    assert not tx.inserted


def test_new_key_on_paused_listing_is_rejected_without_mutation() -> None:
    tx = FakeTransaction(listing_status="PAUSED")
    service = JobSubmitService(store=FakeStore(transaction=tx))
    with pytest.raises(ListingPaused):
        service.submit(
            principal=Principal(),
            idempotency_key="client-request-0001",
            request=REQUEST,
            correlation_id=UUID("44444444-4444-4444-8444-444444444444"),
        )
    assert not tx.inserted
    assert not tx.references
    assert not tx.committed


def test_new_submit_inserts_one_job_and_protected_reference_atomically() -> None:
    tx = FakeTransaction()
    service = JobSubmitService(store=FakeStore(transaction=tx))
    result = service.submit(
        principal=Principal(),
        idempotency_key="client-request-0001",
        request=REQUEST,
        correlation_id=UUID("44444444-4444-4444-8444-444444444444"),
    )

    assert result.replayed is False
    assert result.job.id == JOB_ID
    assert tx.inserted and tx.committed
    assert len(tx.references) == 1
    assert tx.references[0].algorithm_version == "demo-v1-public1"
    assert tx.references[0].expected_digest.startswith("sha256:")
