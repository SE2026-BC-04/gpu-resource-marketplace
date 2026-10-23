"""Composable read-only Jobs router; intentionally not registered in api/app.py."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute

from gpu_marketplace.jobs.errors import (
    Forbidden,
    JobDomainError,
    Unauthenticated,
    ValidationFailed,
    job_error_response,
)
from gpu_marketplace.jobs.models import JobCollectionResponse, PublicJobResponse
from gpu_marketplace.jobs.ports import JobPrincipal, PrincipalProvider
from gpu_marketplace.jobs.service import JobsReadService


class JobsAPIRoute(APIRoute):
    """Translate typed auth failures raised during FastAPI dependency solving."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except JobDomainError as exc:
                return job_error_response(exc, request_id=_request_id(request))
            except HTTPException as exc:
                if exc.status_code == 401:
                    challenge = next(
                        (
                            value
                            for name, value in (exc.headers or {}).items()
                            if name.lower() == "www-authenticate"
                        ),
                        None,
                    )
                    return job_error_response(
                        Unauthenticated(),
                        request_id=_request_id(request),
                        www_authenticate=challenge,
                    )
                if exc.status_code == 403:
                    return job_error_response(
                        Forbidden(), request_id=_request_id(request)
                    )
                raise

        return route_handler


def create_jobs_router(
    *, service: JobsReadService, principal_provider: PrincipalProvider
) -> APIRouter:
    """Build GET routes only; submission/cancellation await their transaction gates."""
    router = APIRouter(
        prefix="/api/v1/jobs", tags=["jobs"], route_class=JobsAPIRoute
    )

    @router.get("", response_model=JobCollectionResponse)
    def list_jobs(
        request: Request,
        response: Response,
        scope: str | None = None,
        status: str | None = None,
        limit: str = "20",
        cursor: str | None = None,
        principal: JobPrincipal = Depends(principal_provider),
    ) -> JobCollectionResponse:
        request_id = _request_id(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
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
        response: Response,
        principal: JobPrincipal = Depends(principal_provider),
    ) -> PublicJobResponse:
        request_id = _request_id(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        try:
            parsed_id = _parse_job_id(job_id)
        except ValueError:
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


def _parse_job_id(raw: str) -> UUID:
    try:
        value = UUID(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Job ID must be UUIDv4") from exc
    if value.version != 4 or str(value) != raw:
        raise ValueError("Job ID must be canonical UUIDv4")
    return value


def _request_id(request: Request) -> str:
    # Only trust a UUIDv4 previously attached by server middleware. Never echo
    # the caller-controlled X-Request-ID header as a server correlation ID.
    candidate = getattr(request.state, "request_id", None)
    if isinstance(candidate, str):
        try:
            parsed = UUID(candidate)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.version == 4 and str(parsed) == candidate:
            return candidate
    return str(uuid4())
