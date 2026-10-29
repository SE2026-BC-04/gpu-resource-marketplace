from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from gpu_marketplace.jobs.cancel import JobCancelService
from gpu_marketplace.jobs.cancel_ports import JobLocator
from gpu_marketplace.jobs.errors import Forbidden, JobNotCancellable, JobNotFound
from gpu_marketplace.jobs.models import FailureReason, JobRole, JobStatus
from gpu_marketplace.jobs.ports import JobRecord


CLIENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_CLIENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
WORKER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
LISTING_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_LISTING_ID = UUID("22222222-2222-4222-8222-222222222222")
JOB_ID = UUID("33333333-3333-4333-8333-333333333333")
SUBMITTED_AT = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
DB_TERMINAL_AT = datetime(2026, 10, 28, 10, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str


def job_record(**overrides: object) -> JobRecord:
    values: dict[str, object] = {
        "id": JOB_ID,
        "client_id": CLIENT_ID,
        "worker_id": WORKER_ID,
        "listing_id": LISTING_ID,
        "requested_gpu_count": 2,
        "duration_seconds": 60,
        "status": JobStatus.QUEUED,
        "failure_reason": None,
        "submitted_at": SUBMITTED_AT,
        "started_at": None,
        "terminal_at": None,
    }
    values.update(overrides)
    return JobRecord(**values)  # type: ignore[arg-type]


class FakeLocatorReader:
    def __init__(
        self, record: JobRecord | None, events: list[str], *, listing_id: UUID = LISTING_ID
    ) -> None:
        self.record = record
        self.events = events
        self.listing_id = listing_id

    def get_locator(self, *, job_id: UUID) -> JobLocator | None:
        self.events.append("lookup")
        if self.record is None or self.record.id != job_id:
            return None
        return JobLocator(listing_id=self.listing_id)


class FakeTransaction:
    def __init__(
        self,
        record: JobRecord,
        events: list[str],
        *,
        listing_paused: bool = False,
        fail_update: bool = False,
        locked_job_missing: bool = False,
    ) -> None:
        self.record = record
        self.events = events
        self.listing_paused = listing_paused
        self.fail_update = fail_update
        self.locked_job_missing = locked_job_missing
        self.commits = 0
        self.rollbacks = 0
        self.mutations = 0

    def lock_listing(self, *, listing_id: UUID) -> None:
        self.events.append("lock_listing")
        assert listing_id == LISTING_ID
        # Paused state intentionally does not prohibit cancellation.
        _ = self.listing_paused

    def lock_job(self, *, job_id: UUID) -> JobRecord | None:
        self.events.append("lock_job")
        if self.locked_job_missing:
            return None
        return self.record if self.record.id == job_id else None

    def cancel_queued(
        self, *, job_id: UUID, listing_id: UUID, client_id: UUID
    ) -> JobRecord:
        self.events.append("update")
        if self.fail_update:
            raise RuntimeError("simulated persistence failure")
        assert (job_id, listing_id, client_id) == (
            self.record.id,
            self.record.listing_id,
            self.record.client_id,
        )
        assert self.record.status is JobStatus.QUEUED
        self.mutations += 1
        self.record = replace(
            self.record,
            status=JobStatus.CANCELLED,
            terminal_at=DB_TERMINAL_AT,
            failure_reason=None,
            started_at=None,
        )
        return self.record

    def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1

    def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1


class FakeUnitOfWork:
    def __init__(self, tx: FakeTransaction, events: list[str]) -> None:
        self.tx = tx
        self.events = events
        self.begins = 0

    def begin(self, *, principal: Principal) -> FakeTransaction:
        self.events.append("begin")
        self.begins += 1
        return self.tx


class TracingCancelService(JobCancelService):
    def __init__(
        self,
        *,
        locator_reader: FakeLocatorReader,
        uow: FakeUnitOfWork,
        events: list[str],
    ) -> None:
        super().__init__(locator_reader=locator_reader, uow=uow)
        self.events = events

    def _recheck_locked_job(
        self, record: JobRecord, *, job_id: UUID, listing_id: UUID, client_id: UUID
    ) -> None:
        self.events.append("recheck")
        super()._recheck_locked_job(
            record, job_id=job_id, listing_id=listing_id, client_id=client_id
        )


def setup(
    record: JobRecord | None = None, *, listing_paused: bool = False, fail_update: bool = False
) -> tuple[JobCancelService, FakeTransaction, list[str]]:
    events: list[str] = []
    initial = record or job_record()
    locator = FakeLocatorReader(initial, events)
    tx = FakeTransaction(
        initial,
        events,
        listing_paused=listing_paused,
        fail_update=fail_update,
    )
    uow = FakeUnitOfWork(tx, events)
    return TracingCancelService(locator_reader=locator, uow=uow, events=events), tx, events


def test_client_cancels_own_queued_job_in_contract_order_and_gets_safe_response() -> None:
    service, tx, events = setup()
    response = service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)

    assert response.id == JOB_ID
    assert response.status is JobStatus.CANCELLED
    assert response.worker_id == WORKER_ID
    assert response.terminal_at == DB_TERMINAL_AT
    assert response.failure_reason is None and response.started_at is None
    protected_fields = {
        "client_id",
        "idempotency_key",
        "request_sha256",
        "seed_value",
        "expected_digest",
    }
    assert not protected_fields & set(response.model_dump())
    assert events == [
        "lookup", "begin", "lock_listing", "lock_job", "recheck", "update", "commit"
    ]
    assert tx.commits == 1 and tx.rollbacks == 0 and tx.mutations == 1


@pytest.mark.parametrize("role", [JobRole.WORKER, JobRole.ADMIN])
def test_non_client_is_forbidden_before_locator_or_transaction(role: JobRole) -> None:
    service, tx, events = setup()
    with pytest.raises(Forbidden):
        service.cancel(principal=Principal(CLIENT_ID, role), job_id=JOB_ID)
    assert events == []
    assert tx.mutations == tx.commits == tx.rollbacks == 0


def test_missing_job_is_uniform_404_without_transaction() -> None:
    service, tx, events = _setup_missing()
    with pytest.raises(JobNotFound):
        service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert events == ["lookup"]
    assert tx.mutations == tx.commits == tx.rollbacks == 0


def _setup_missing() -> tuple[JobCancelService, FakeTransaction, list[str]]:
    events: list[str] = []
    tx = FakeTransaction(job_record(), events)
    locator = FakeLocatorReader(None, events)
    uow = FakeUnitOfWork(tx, events)
    return JobCancelService(locator_reader=locator, uow=uow), tx, events


def test_foreign_client_job_is_uniform_404_without_mutation() -> None:
    service, tx, events = setup(job_record(client_id=OTHER_CLIENT_ID))
    with pytest.raises(JobNotFound):
        service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert events == ["lookup", "begin", "lock_listing", "lock_job", "recheck", "rollback"]
    assert tx.mutations == tx.commits == 0 and tx.rollbacks == 1


@pytest.mark.parametrize(
    "status",
    [JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_non_queued_state_is_conflict_without_mutation(status: JobStatus) -> None:
    reason = FailureReason.JOB_FAULT if status is JobStatus.FAILED else None
    service, tx, events = setup(
        job_record(
            status=status,
            failure_reason=reason,
            started_at=(
                SUBMITTED_AT
                if status in {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED}
                else None
            ),
            terminal_at=(
                SUBMITTED_AT
                if status
                in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
                else None
            ),
        )
    )
    with pytest.raises(JobNotCancellable):
        service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert events[-1] == "rollback"
    assert "update" not in events
    assert tx.mutations == tx.commits == 0 and tx.rollbacks == 1


def test_listing_paused_does_not_prevent_queued_job_cancellation() -> None:
    service, tx, _ = setup(listing_paused=True)
    response = service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert response.status is JobStatus.CANCELLED
    assert tx.commits == 1


def test_owner_or_listing_recheck_mismatch_is_404_without_mutation() -> None:
    for changed in (job_record(client_id=OTHER_CLIENT_ID), job_record(listing_id=OTHER_LISTING_ID)):
        events: list[str] = []
        tx = FakeTransaction(changed, events)
        locator = FakeLocatorReader(changed, events, listing_id=LISTING_ID)
        uow = FakeUnitOfWork(tx, events)
        service = TracingCancelService(locator_reader=locator, uow=uow, events=events)
        with pytest.raises(JobNotFound):
            service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
        assert "update" not in events
        assert tx.mutations == tx.commits == 0


def test_job_disappearing_after_locator_is_404_and_rolls_back() -> None:
    events: list[str] = []
    record = job_record()
    locator = FakeLocatorReader(record, events)
    tx = FakeTransaction(record, events, locked_job_missing=True)
    service = TracingCancelService(
        locator_reader=locator,
        uow=FakeUnitOfWork(tx, events),
        events=events,
    )
    with pytest.raises(JobNotFound):
        service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert events == ["lookup", "begin", "lock_listing", "lock_job", "rollback"]
    assert tx.mutations == tx.commits == 0 and tx.rollbacks == 1


def test_repeated_cancel_returns_conflict_on_second_attempt() -> None:
    service, tx, _ = setup()
    principal = Principal(CLIENT_ID, JobRole.CLIENT)
    assert service.cancel(principal=principal, job_id=JOB_ID).status is JobStatus.CANCELLED
    with pytest.raises(JobNotCancellable):
        service.cancel(principal=principal, job_id=JOB_ID)
    assert tx.mutations == tx.commits == 1


def test_persistence_failure_rolls_back_and_does_not_commit() -> None:
    service, tx, events = setup(fail_update=True)
    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)
    assert events[-1] == "rollback"
    assert tx.rollbacks == 1 and tx.commits == tx.mutations == 0
