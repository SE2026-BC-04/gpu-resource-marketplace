"""Ports for the atomic TX-SUBMIT transaction."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Protocol, Self
from uuid import UUID

from gpu_marketplace.jobs.models import SubmitJobRequest
from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord


@dataclass(frozen=True)
class ListingAdmission:
    listing_id: UUID
    worker_id: UUID
    status: str
    total_gpu_count: int


@dataclass(frozen=True)
class StoredSubmission:
    job: JobRecord
    request_sha256: bytes


@dataclass(frozen=True)
class SimulationReference:
    seed_value: int
    algorithm_version: str
    expected_outcome: str
    expected_failure_reason: str | None
    expected_digest: str


@dataclass(frozen=True)
class SubmissionResult:
    job: JobRecord
    replayed: bool


class IdempotencyCollision(Exception):
    """A concurrent TX-SUBMIT won the retained Client/key unique constraint."""


class JobSubmissionTransaction(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False] | None: ...

    def lock_listing(self, *, listing_id: UUID) -> ListingAdmission | None: ...

    def find_existing(
        self, *, client_id: UUID, idempotency_key: str
    ) -> StoredSubmission | None: ...

    def insert_job(
        self,
        *,
        client_id: UUID,
        listing: ListingAdmission,
        request: SubmitJobRequest,
        idempotency_key: str,
        request_sha256: bytes,
        correlation_id: UUID,
    ) -> JobRecord: ...

    def insert_reference(
        self, *, job_id: UUID, reference: SimulationReference
    ) -> None: ...

    def commit(self) -> None: ...


class JobSubmissionStore(Protocol):
    def find_existing(
        self, *, client_id: UUID, idempotency_key: str
    ) -> StoredSubmission | None: ...

    def transaction(self, *, principal: JobPrincipal) -> JobSubmissionTransaction: ...
