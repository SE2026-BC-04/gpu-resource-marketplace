"""Role-safe public projections from persistence-neutral Job records."""

from gpu_marketplace.jobs.errors import JobNotFound
from gpu_marketplace.jobs.models import ClientJobResponse, JobResponse, JobRole
from gpu_marketplace.jobs.ports import JobPrincipal, JobRecord


def project_job(record: JobRecord, *, principal: JobPrincipal) -> JobResponse:
    role = JobRole(principal.role)
    common = {
        "id": record.id,
        "listing_id": record.listing_id,
        "gpu_count": record.requested_gpu_count,
        "duration_seconds": record.duration_seconds,
        "status": record.status,
        "failure_reason": record.failure_reason,
        "submitted_at": record.submitted_at,
        "started_at": record.started_at,
        "terminal_at": record.terminal_at,
    }
    if role is JobRole.CLIENT:
        if record.client_id != principal.user_id:
            raise JobNotFound()
        return ClientJobResponse(**common, worker_id=record.worker_id)
    # Worker and Admin projections intentionally omit client_id and worker_id.
    return JobResponse(**common)
