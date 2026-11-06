"""Application use case for idempotent Client Job submission."""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

from gpu_marketplace.jobs.cancel_ports import CommitOutcomeUnknown
from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    Forbidden,
    IdempotencyKeyRequired,
    IdempotencyKeyReused,
    JobGpuExceedsListingTotal,
    ListingNotFound,
    ListingPaused,
    Unauthenticated,
    validate_idempotency_key,
)
from gpu_marketplace.jobs.models import JobRole, SubmitJobRequest
from gpu_marketplace.jobs.ports import JobPrincipal
from gpu_marketplace.jobs.reference import create_simulation_reference
from gpu_marketplace.jobs.submit_ports import (
    IdempotencyCollision,
    JobSubmissionStore,
    SubmissionResult,
    StoredSubmission,
)


class JobSubmitService:
    """Apply API §8 admission rules and atomically create Job plus reference."""

    def __init__(self, *, store: JobSubmissionStore) -> None:
        self._store = store

    def submit(
        self,
        *,
        principal: JobPrincipal,
        idempotency_key: str | None,
        request: SubmitJobRequest,
        correlation_id: UUID,
    ) -> SubmissionResult:
        try:
            role = JobRole(principal.role)
        except (TypeError, ValueError) as exc:
            raise Unauthenticated() from exc
        if role is not JobRole.CLIENT:
            raise Forbidden()
        if idempotency_key is None:
            raise IdempotencyKeyRequired()
        key = validate_idempotency_key(idempotency_key)
        fingerprint = request_fingerprint(request)

        # Existing retained keys are resolved before Listing state. TX-SUBMIT's
        # Listing lock still serializes new admissions and rechecks races below.
        existing = self._store.find_existing(
            client_id=principal.user_id, idempotency_key=key
        )
        if existing is not None:
            return self._replay(existing, fingerprint)

        try:
            with self._store.transaction(principal=principal) as tx:
                listing = tx.lock_listing(listing_id=request.listing_id)
                if listing is None:
                    raise ListingNotFound()

                # Another request may have committed while this one waited for the
                # Listing lock. Check retained idempotency before status/capacity so
                # exact retries replay even after a concurrent pause.
                existing = tx.find_existing(
                    client_id=principal.user_id, idempotency_key=key
                )
                if existing is not None:
                    return self._replay(existing, fingerprint)
                if listing.status != "ACTIVE":
                    raise ListingPaused()
                if request.gpu_count > listing.total_gpu_count:
                    raise JobGpuExceedsListingTotal()

                job = tx.insert_job(
                    client_id=principal.user_id,
                    listing=listing,
                    request=request,
                    idempotency_key=key,
                    request_sha256=fingerprint,
                    correlation_id=correlation_id,
                )
                reference = create_simulation_reference(
                    job_id=job.id,
                    listing_id=listing.listing_id,
                    worker_id=listing.worker_id,
                    requested_gpu_count=request.gpu_count,
                    duration_seconds=request.duration_seconds,
                )
                tx.insert_reference(job_id=job.id, reference=reference)
                tx.commit()
                return SubmissionResult(job=job, replayed=False)
        except IdempotencyCollision:
            # A request with the same key may have won on another Listing. The
            # failed transaction has rolled back before this fresh read.
            existing = self._store.find_existing(
                client_id=principal.user_id, idempotency_key=key
            )
            if existing is None:
                raise DependencyUnavailable() from None
            return self._replay(existing, fingerprint)

    @staticmethod
    def _replay(existing: StoredSubmission, fingerprint: bytes) -> SubmissionResult:
        if not hmac.compare_digest(existing.request_sha256, fingerprint):
            raise IdempotencyKeyReused()
        return SubmissionResult(job=existing.job, replayed=True)


def request_fingerprint(request: SubmitJobRequest) -> bytes:
    """Hash the canonical normalized three-field logical request."""
    normalized = {
        "duration_seconds": request.duration_seconds,
        "gpu_count": request.gpu_count,
        "listing_id": str(request.listing_id),
    }
    canonical = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(canonical).digest()
