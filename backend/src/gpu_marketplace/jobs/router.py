"""Composable read-only Jobs router; intentionally not registered in api/app.py."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request

from gpu_marketplace.jobs.errors import (
    JobDomainError,
    ValidationFailed,
    job_error_response,
)
from gpu_marketplace.jobs.models import JobCollectionResponse, PublicJobResponse
from gpu_marketplace.jobs.ports import JobPrincipal, PrincipalProvider
from gpu_marketplace.jobs.service import JobsReadService


def create_jobs_router(
    *, service: JobsReadService, principal_provider: PrincipalProvider
) -> APIRouter:
    """Build GET routes only; submission/cancellation await their transaction gates."""
    router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

    @router.get("", response_model=JobCollectionResponse)
    def list_jobs(
        request: Request,
        scope: str | None = None,
        status: str | None = None,
        limit: str = "20",
        cursor: str | None = None,
        principal: JobPrincipal = Depends(principal_provider),
    ) -> JobCollectionResponse:
        request_id = _request_id(request)
        try:
            parsed_limit = _parse_limit(limit)
            return service.list_jobs(
                principal=principal,
                scope=scope,
                status=status,
                limit=parsed_limit,
                cursor=cursor,
            )
        except JobDomainError as exc:
            return job_error_response(exc, request_id=request_id)  # type: ignore[return-value]

    @router.get("/{job_id}", response_model=PublicJobResponse)
    def get_job(
        job_id: str,
        request: Request,
        principal: JobPrincipal = Depends(principal_provider),
    ) -> PublicJobResponse:
        request_id = _request_id(request)
        try:
            parsed_id = UUID(job_id)
        except (ValueError, TypeError, AttributeError):
            return job_error_response(ValidationFailed(), request_id=request_id)  # type: ignore[return-value]
        try:
            return service.get_job(principal=principal, job_id=parsed_id)
        except JobDomainError as exc:
            return job_error_response(exc, request_id=request_id)  # type: ignore[return-value]

    return router


def _parse_limit(raw: str) -> int:
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValidationFailed()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationFailed() from exc
    if not 1 <= value <= 100:
        raise ValidationFailed()
    return value


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID")
    return supplied if supplied else str(uuid4())
