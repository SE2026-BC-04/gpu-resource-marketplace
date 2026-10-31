"""Application use case for cancelling a Client-owned QUEUED Job."""

from __future__ import annotations

from uuid import UUID

from gpu_marketplace.jobs.cancel_ports import (
    CancelGuardReason,
    CancelGuardRejected,
    JobCancelUnitOfWork,
    JobLocatorReader,
)
from gpu_marketplace.jobs.errors import (
    Forbidden,
    JobNotCancellable,
    JobNotFound,
    Unauthenticated,
)
from gpu_marketplace.jobs.models import JobRole, JobStatus, PublicJobResponse
from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord
from gpu_marketplace.jobs.projections import project_job


class JobCancelService:
    """Coordinate the TX-CANCEL policy; persistence owns locks and DB time."""

    def __init__(self, *, locator_reader: JobLocatorReader, uow: JobCancelUnitOfWork) -> None:
        self._locator_reader = locator_reader
        self._uow = uow

    def cancel(self, *, principal: JobPrincipal, job_id: UUID) -> PublicJobResponse:
        try:
            role = JobRole(principal.role)
        except (ValueError, TypeError) as exc:
            raise Unauthenticated() from exc
        if role is not JobRole.CLIENT:
            raise Forbidden()

        # This read discovers the lock order only. No authorization or status
        # decision relies on it; every mutable predicate is rechecked under lock.
        locator = self._locator_reader.get_locator(job_id=job_id)
        if locator is None:
            raise JobNotFound()

        try:
            with self._uow.transaction(principal=principal) as tx:
                tx.lock_listing(listing_id=locator.listing_id)
                locked = tx.lock_job(job_id=job_id)
                if locked is None:
                    raise JobNotFound()
                self._recheck_locked_job(
                    locked,
                    job_id=job_id,
                    listing_id=locator.listing_id,
                    client_id=principal.user_id,
                )

                updated = tx.cancel_queued(
                    job_id=job_id,
                    listing_id=locator.listing_id,
                    client_id=principal.user_id,
                )
                self._validate_cancelled_row(
                    updated,
                    job_id=job_id,
                    listing_id=locator.listing_id,
                    client_id=principal.user_id,
                )
                response = project_job(updated, principal=principal)
                tx.commit()
                return response
        except CancelGuardRejected as exc:
            if exc.reason in {CancelGuardReason.MISSING, CancelGuardReason.NOT_OWNER}:
                raise JobNotFound() from exc
            if exc.reason is CancelGuardReason.NOT_QUEUED:
                raise JobNotCancellable() from exc
            raise RuntimeError("TX-CANCEL adapter returned an unsupported guard reason") from exc

    def _recheck_locked_job(
        self, record: JobRecord, *, job_id: UUID, listing_id: UUID, client_id: UUID
    ) -> None:
        # Uniform 404 for absent/foreign Jobs; do not reveal owner or listing.
        if record.id != job_id or record.listing_id != listing_id or record.client_id != client_id:
            raise JobNotFound()
        if record.status is not JobStatus.QUEUED:
            raise JobNotCancellable()

    @staticmethod
    def _validate_cancelled_row(
        record: JobRecord, *, job_id: UUID, listing_id: UUID, client_id: UUID
    ) -> None:
        if (
            record.id != job_id
            or record.listing_id != listing_id
            or record.client_id != client_id
            or record.status is not JobStatus.CANCELLED
            or record.terminal_at is None
            or record.started_at is not None
            or record.failure_reason is not None
        ):
            raise RuntimeError("TX-CANCEL adapter returned a row outside its contract")
