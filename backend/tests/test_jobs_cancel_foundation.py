from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Literal
from uuid import UUID

import pytest

import gpu_marketplace.jobs.cancel as cancel_module
from gpu_marketplace.jobs.cancel import JobCancelService
from gpu_marketplace.jobs.cancel_ports import (
    CancelGuardReason,
    CancelGuardRejected,
    CommitOutcomeUnknown,
    JobLocator,
)
from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    Forbidden,
    JobDomainError,
    JobNotCancellable,
    JobNotFound,
    JobErrorCode,
    job_error_response,
)
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
        self,
        record: JobRecord | None,
        events: list[str],
        *,
        listing_id: UUID = LISTING_ID,
        error: Exception | None = None,
    ) -> None:
        self.record = record
        self.events = events
        self.listing_id = listing_id
        self.error = error

    def get_locator(self, *, job_id: UUID) -> JobLocator | None:
        self.events.append("lookup")
        if self.error is not None:
            raise self.error
        if self.record is None or self.record.id != job_id:
            return None
        return JobLocator(listing_id=self.listing_id)


class FakeTransaction:
    """Transactional fake: only commit publishes pending state durably."""

    def __init__(
        self,
        record: JobRecord,
        events: list[str],
        *,
        listing_paused: bool = False,
        fail_begin: bool = False,
        fail_update: Exception | None = None,
        fail_after_stage: bool = False,
        guard_rejection: CancelGuardReason | None = None,
        locked_job_missing: bool = False,
        fail_commit: Exception | None = None,
        commit_outcome_unknown: bool = False,
        fail_rollback: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.durable_record = record
        self.pending_record: JobRecord | None = None
        self.events = events
        self.listing_paused = listing_paused
        self.fail_begin = fail_begin
        self.fail_update = fail_update
        self.fail_after_stage = fail_after_stage
        self.guard_rejection = guard_rejection
        self.locked_job_missing = locked_job_missing
        self.fail_commit = fail_commit
        self.commit_outcome_unknown = commit_outcome_unknown
        self.fail_rollback = fail_rollback
        self.fail_close = fail_close
        self.resource_open = False
        self.entered = False
        self.exit_result: Literal[False] | None = None
        self.closed = 0
        self.commits = 0
        self.commit_confirmed = False
        self.rollbacks = 0
        self.update_calls = 0
        self.effects = {"allocations": 0, "listing_counter": 0, "results": 0, "reputation": 0, "references": 0}

    def __enter__(self) -> FakeTransaction:
        self.events.append("begin")
        if self.entered:
            raise RuntimeError("transaction context is single-use")
        self.entered = True
        self.resource_open = True
        if self.fail_begin:
            try:
                raise DependencyUnavailable()
            except BaseException:
                self._close_preserving_active_exception()
                raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self.events.append("exit")
        has_original_error = exc is not None
        rollback_error: BaseException | None = None
        close_error: BaseException | None = None
        if not self.commit_confirmed and not self.commit_outcome_unknown:
            try:
                self.rollback()
            except BaseException as error:
                rollback_error = error
        try:
            self.close()
        except BaseException as error:
            close_error = error
        if has_original_error:
            # Returning False preserves the body exception and makes cleanup
            # failures secondary, while close has already been attempted.
            self.exit_result = False
            return False
        if rollback_error is not None:
            # Prefer rollback as the primary transaction-finalization failure;
            # close was attempted in all cases above.
            raise rollback_error
        if close_error is not None:
            raise close_error
        self.exit_result = False
        return False

    def _close_preserving_active_exception(self) -> None:
        try:
            self.close()
        except BaseException:
            # Keep the begin failure as the exception visible to the caller.
            pass

    def close(self) -> None:
        self.events.append("cleanup")
        self.closed += 1
        self.resource_open = False
        if self.fail_close:
            raise RuntimeError("cleanup failure")

    def lock_listing(self, *, listing_id: UUID) -> None:
        assert self.resource_open
        self.events.append("lock_listing")
        assert listing_id == LISTING_ID
        # PAUSED is intentionally not an admission condition for cancellation.
        _ = self.listing_paused

    def lock_job(self, *, job_id: UUID) -> JobRecord | None:
        assert self.resource_open
        self.events.append("lock_job")
        if self.locked_job_missing:
            return None
        return self.durable_record if self.durable_record.id == job_id else None

    def cancel_queued(
        self,
        *,
        job_id: UUID,
        listing_id: UUID,
        client_id: UUID,
    ) -> JobRecord:
        assert self.resource_open
        self.events.append("update")
        self.update_calls += 1
        if self.fail_update is not None:
            raise self.fail_update
        if self.guard_rejection is not None:
            raise CancelGuardRejected(self.guard_rejection)
        current = self.pending_record or self.durable_record
        assert (job_id, listing_id, client_id) == (
            current.id,
            current.listing_id,
            current.client_id,
        )
        assert current.status is JobStatus.QUEUED
        self.pending_record = replace(
            current,
            status=JobStatus.CANCELLED,
            terminal_at=DB_TERMINAL_AT,
            failure_reason=None,
            started_at=None,
        )
        if self.fail_after_stage:
            raise RuntimeError("failure after staging update")
        return self.pending_record

    def commit(self) -> None:
        assert self.resource_open
        if self.commits:
            raise RuntimeError("transaction commit is single-use")
        self.events.append("commit")
        self.commits += 1
        if self.fail_commit is not None:
            raise self.fail_commit
        if self.commit_outcome_unknown:
            # Model the allowed uncertain case: durable state may have committed,
            # but the caller receives no success and must not retry.
            if self.pending_record is not None:
                self.durable_record = self.pending_record
                self.pending_record = None
            raise CommitOutcomeUnknown("commit acknowledgement was lost")
        if self.pending_record is None:
            raise RuntimeError("commit called without a staged update")
        self.durable_record = self.pending_record
        self.pending_record = None
        self.commit_confirmed = True

    def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1
        self.pending_record = None
        if self.fail_rollback:
            raise RuntimeError("rollback cleanup failure")


class FakeUnitOfWork:
    def __init__(self, tx: FakeTransaction, events: list[str], *, fail_factory: Exception | None = None) -> None:
        self.tx = tx
        self.events = events
        self.fail_factory = fail_factory
        self.transaction_requests = 0

    def transaction(self, *, principal: Principal) -> FakeTransaction:
        self.transaction_requests += 1
        if self.fail_factory is not None:
            raise self.fail_factory
        return self.tx


class TracingCancelService(JobCancelService):
    def __init__(self, *, locator_reader: FakeLocatorReader, uow: FakeUnitOfWork, events: list[str]) -> None:
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
    record: JobRecord | None = None,
    *,
    listing_paused: bool = False,
    **tx_options: object,
) -> tuple[JobCancelService, FakeTransaction, list[str]]:
    events: list[str] = []
    initial = record or job_record()
    locator = FakeLocatorReader(initial, events)
    tx = FakeTransaction(initial, events, listing_paused=listing_paused, **tx_options)
    uow = FakeUnitOfWork(tx, events)
    return TracingCancelService(locator_reader=locator, uow=uow, events=events), tx, events


def invoke(service: JobCancelService) -> object:
    return service.cancel(principal=Principal(CLIENT_ID, JobRole.CLIENT), job_id=JOB_ID)


def test_success_commits_once_cleans_once_and_publishes_safe_cancelled_record() -> None:
    service, tx, events = setup()
    response = invoke(service)

    assert response.status is JobStatus.CANCELLED
    assert response.worker_id == WORKER_ID
    assert response.terminal_at == DB_TERMINAL_AT
    assert response.failure_reason is None and response.started_at is None
    assert not {"client_id", "idempotency_key", "request_sha256", "seed_value", "expected_digest"} & set(
        response.model_dump()
    )
    assert tx.durable_record.status is JobStatus.CANCELLED
    assert tx.pending_record is None
    assert events == [
        "lookup", "begin", "lock_listing", "lock_job", "recheck", "update", "commit", "exit", "cleanup"
    ]
    assert tx.commits == 1 and tx.rollbacks == 0 and tx.closed == 1
    assert tx.exit_result is False
    assert all(value == 0 for value in tx.effects.values())


def test_context_manager_returns_false_on_normal_uncommitted_exit() -> None:
    tx = FakeTransaction(job_record(), [])
    assert tx.__enter__() is tx
    assert tx.__exit__(None, None, None) is False
    assert tx.rollbacks == 1 and tx.closed == 1


def test_context_manager_does_not_suppress_body_exception() -> None:
    tx = FakeTransaction(job_record(), [])
    with pytest.raises(RuntimeError, match="body failure"):
        with tx:
            raise RuntimeError("body failure")
    assert tx.exit_result is False
    assert tx.rollbacks == 1 and tx.closed == 1


@pytest.mark.parametrize("role", [JobRole.WORKER, JobRole.ADMIN])
def test_non_client_is_forbidden_before_storage_access(role: JobRole) -> None:
    service, tx, events = setup()
    with pytest.raises(Forbidden):
        service.cancel(principal=Principal(CLIENT_ID, role), job_id=JOB_ID)
    assert events == []
    assert tx.commits == tx.rollbacks == tx.closed == 0


def test_missing_job_is_uniform_404_without_transaction() -> None:
    events: list[str] = []
    tx = FakeTransaction(job_record(), events)
    service = JobCancelService(
        locator_reader=FakeLocatorReader(None, events),
        uow=FakeUnitOfWork(tx, events),
    )
    with pytest.raises(JobNotFound):
        invoke(service)
    assert events == ["lookup"]
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.commits == tx.rollbacks == tx.closed == 0


def test_foreign_client_gets_404_and_transaction_is_rolled_back_and_closed() -> None:
    service, tx, events = setup(job_record(client_id=OTHER_CLIENT_ID))
    with pytest.raises(JobNotFound):
        invoke(service)
    assert events == ["lookup", "begin", "lock_listing", "lock_job", "recheck", "exit", "rollback", "cleanup"]
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


@pytest.mark.parametrize(
    "status",
    [JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_non_queued_state_is_409_and_has_no_durable_mutation(status: JobStatus) -> None:
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
                if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
                else None
            ),
        )
    )
    with pytest.raises(JobNotCancellable):
        invoke(service)
    assert "update" not in events
    assert tx.durable_record.status is status
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1
    assert tx.events[-2:] == ["rollback", "cleanup"]


def test_paused_listing_does_not_prevent_queued_job_cancel() -> None:
    service, tx, _ = setup(listing_paused=True)
    invoke(service)
    assert tx.durable_record.status is JobStatus.CANCELLED
    assert tx.commits == 1


def test_listing_mismatch_or_owner_mismatch_is_404_and_zero_durable_mutation() -> None:
    for record in (
        job_record(client_id=OTHER_CLIENT_ID),
        job_record(listing_id=OTHER_LISTING_ID),
    ):
        events: list[str] = []
        tx = FakeTransaction(record, events)
        service = TracingCancelService(
            locator_reader=FakeLocatorReader(record, events, listing_id=LISTING_ID),
            uow=FakeUnitOfWork(tx, events),
            events=events,
        )
        with pytest.raises(JobNotFound):
            invoke(service)
        assert tx.durable_record == record
        assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


def test_job_missing_after_locator_is_404_and_cleanup_runs() -> None:
    events: list[str] = []
    tx = FakeTransaction(job_record(), events, locked_job_missing=True)
    service = JobCancelService(
        locator_reader=FakeLocatorReader(job_record(), events),
        uow=FakeUnitOfWork(tx, events),
    )
    with pytest.raises(JobNotFound):
        invoke(service)
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.rollbacks == 1 and tx.closed == 1


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (CancelGuardReason.MISSING, JobNotFound),
        (CancelGuardReason.NOT_OWNER, JobNotFound),
        (CancelGuardReason.NOT_QUEUED, JobNotCancellable),
    ],
)
def test_zero_row_guard_conflict_maps_to_typed_domain_error(
    reason: CancelGuardReason, expected: type[Exception]
) -> None:
    service, tx, _ = setup(guard_rejection=reason)
    with pytest.raises(expected):
        invoke(service)
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.pending_record is None
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


def test_database_unavailable_maps_to_existing_safe_503_domain_error() -> None:
    service, tx, _ = setup(fail_update=DependencyUnavailable())
    with pytest.raises(DependencyUnavailable) as caught:
        invoke(service)
    assert caught.value.code.value == "DEPENDENCY_UNAVAILABLE"
    response = job_error_response(
        caught.value,
        request_id="44444444-4444-4444-8444-444444444444",
    )
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "database" not in response.body.decode().lower()
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.rollbacks == 1 and tx.closed == 1


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (JobNotFound(), 404, JobErrorCode.JOB_NOT_FOUND.value),
        (JobNotCancellable(), 409, JobErrorCode.JOB_NOT_CANCELLABLE.value),
    ],
)
def test_cancel_domain_errors_keep_approved_http_mapping(
    error: JobDomainError, status: int, code: str
) -> None:
    response = job_error_response(
        error,
        request_id="44444444-4444-4444-8444-444444444444",
    )
    assert response.status_code == status
    assert json.loads(response.body)["error"]["code"] == code


def test_unexpected_programming_error_is_not_rewritten_as_domain_conflict() -> None:
    failure = RuntimeError("unexpected adapter bug")
    service, tx, _ = setup(fail_update=failure)
    with pytest.raises(RuntimeError, match="unexpected adapter bug"):
        invoke(service)
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.rollbacks == 1 and tx.closed == 1


def test_failure_after_staging_update_rolls_back_durable_state() -> None:
    service, tx, _ = setup(fail_after_stage=True)
    with pytest.raises(RuntimeError, match="failure after staging update"):
        invoke(service)
    assert tx.pending_record is None
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


def test_post_update_validation_failure_rolls_back_durable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_row(*args: object, **kwargs: object) -> None:
        raise RuntimeError("post-update validation failed")

    monkeypatch.setattr(JobCancelService, "_validate_cancelled_row", staticmethod(reject_row))
    service, tx, _ = setup()
    with pytest.raises(RuntimeError, match="post-update validation failed"):
        invoke(service)
    assert tx.pending_record is None
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


def test_projection_failure_after_stage_rolls_back_durable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_projection(*args: object, **kwargs: object) -> None:
        raise RuntimeError("projection failed")

    monkeypatch.setattr(cancel_module, "project_job", reject_projection)
    service, tx, _ = setup()
    with pytest.raises(RuntimeError, match="projection failed"):
        invoke(service)
    assert tx.pending_record is None
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.commits == 0 and tx.rollbacks == 1 and tx.closed == 1


def test_commit_failure_rolls_back_best_effort_and_always_cleans_up() -> None:
    service, tx, _ = setup(fail_commit=DependencyUnavailable())
    with pytest.raises(DependencyUnavailable):
        invoke(service)
    assert tx.durable_record.status is JobStatus.QUEUED
    assert tx.pending_record is None
    assert tx.commits == 1 and tx.rollbacks == 1 and tx.closed == 1


def test_unknown_commit_outcome_is_not_success_and_is_never_retried() -> None:
    service, tx, _ = setup(commit_outcome_unknown=True)
    with pytest.raises(CommitOutcomeUnknown):
        invoke(service)
    # The durable outcome may be either state; the fake chooses committed to
    # demonstrate why callers must not retry an uncertain commit.
    assert tx.durable_record.status is JobStatus.CANCELLED
    assert tx.update_calls == 1 and tx.commits == 1
    assert tx.closed == 1


def test_begin_failure_cleans_acquired_resource_without_masking_original() -> None:
    service, tx, _ = setup(fail_begin=True, fail_close=True)
    with pytest.raises(DependencyUnavailable):
        invoke(service)
    assert tx.closed == 1 and not tx.resource_open
    assert tx.commits == tx.rollbacks == 0


def test_cleanup_errors_do_not_mask_original_transaction_exception() -> None:
    service, tx, _ = setup(fail_update=RuntimeError("primary failure"), fail_rollback=True, fail_close=True)
    with pytest.raises(RuntimeError, match="primary failure"):
        invoke(service)
    assert tx.rollbacks == 1 and tx.closed == 1
    assert tx.durable_record.status is JobStatus.QUEUED


def test_rollback_failure_without_body_exception_still_closes_then_raises_rollback() -> None:
    tx = FakeTransaction(job_record(), [], fail_rollback=True)
    tx.__enter__()
    tx.pending_record = replace(
        tx.durable_record,
        status=JobStatus.CANCELLED,
        terminal_at=DB_TERMINAL_AT,
    )
    with pytest.raises(RuntimeError, match="rollback cleanup failure"):
        tx.__exit__(None, None, None)
    assert tx.rollbacks == 1 and tx.closed == 1
    assert tx.events[-2:] == ["rollback", "cleanup"]
    assert tx.durable_record.status is JobStatus.QUEUED and tx.pending_record is None


def test_close_failure_does_not_mask_original_body_exception() -> None:
    tx = FakeTransaction(job_record(), [], fail_close=True)
    with pytest.raises(RuntimeError, match="body failure"):
        with tx:
            raise RuntimeError("body failure")
    assert tx.rollbacks == 1 and tx.closed == 1


def test_rollback_and_close_fail_without_body_error_prefers_rollback_after_close() -> None:
    tx = FakeTransaction(job_record(), [], fail_rollback=True, fail_close=True)
    tx.__enter__()
    tx.pending_record = replace(
        tx.durable_record,
        status=JobStatus.CANCELLED,
        terminal_at=DB_TERMINAL_AT,
    )
    with pytest.raises(RuntimeError, match="rollback cleanup failure"):
        tx.__exit__(None, None, None)
    assert tx.rollbacks == 1 and tx.closed == 1
    assert tx.events[-2:] == ["rollback", "cleanup"]
    assert tx.durable_record.status is JobStatus.QUEUED and tx.pending_record is None


def test_repeated_cancel_first_commits_and_second_gets_409() -> None:
    service, tx, _ = setup()
    principal = Principal(CLIENT_ID, JobRole.CLIENT)
    first = service.cancel(principal=principal, job_id=JOB_ID)
    assert first.status is JobStatus.CANCELLED
    second_service, second_tx, _ = setup(tx.durable_record)
    with pytest.raises(JobNotCancellable):
        second_service.cancel(principal=principal, job_id=JOB_ID)
    assert tx.durable_record.status is JobStatus.CANCELLED
    assert tx.commits == 1 and tx.closed == 1
    assert tx.update_calls == 1
    assert second_tx.commits == 0 and second_tx.rollbacks == 1 and second_tx.closed == 1
    assert second_tx.update_calls == 0


def test_locator_database_unavailable_is_safe_503_and_allocates_no_transaction() -> None:
    events: list[str] = []
    tx = FakeTransaction(job_record(), events)
    service = JobCancelService(
        locator_reader=FakeLocatorReader(job_record(), events, error=DependencyUnavailable()),
        uow=FakeUnitOfWork(tx, events),
    )
    with pytest.raises(DependencyUnavailable):
        invoke(service)
    assert events == ["lookup"]
    assert tx.closed == tx.commits == tx.rollbacks == 0


def test_transaction_factory_database_unavailable_has_no_open_resource() -> None:
    events: list[str] = []
    tx = FakeTransaction(job_record(), events)
    service = JobCancelService(
        locator_reader=FakeLocatorReader(job_record(), events),
        uow=FakeUnitOfWork(tx, events, fail_factory=DependencyUnavailable()),
    )
    with pytest.raises(DependencyUnavailable):
        invoke(service)
    assert tx.closed == tx.commits == tx.rollbacks == 0
