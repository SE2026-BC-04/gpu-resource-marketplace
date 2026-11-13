"""Composable Jobs router; mounted with explicit production services by the app."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    Forbidden,
    IdempotencyKeyRequired,
    InvalidFilter,
    InvalidJson,
    JobDomainError,
    Unauthenticated,
    ValidationFailed,
    job_error_response,
    submit_request_from_mapping,
)
from gpu_marketplace.jobs.cancel_ports import CommitOutcomeUnknown
from gpu_marketplace.jobs.models import JobCollectionResponse, JobRole, PublicJobResponse
from gpu_marketplace.jobs.ports import JobPrincipal, PrincipalProvider
from gpu_marketplace.jobs.cancel import JobCancelService
from gpu_marketplace.jobs.projections import project_job
from gpu_marketplace.jobs.service import JobsReadService
from gpu_marketplace.jobs.submit import JobSubmitService
from gpu_marketplace.identity.request_body import (
    BodyTooLarge,
    InvalidBody,
    UnexpectedBody,
    parse_json,
    read_bounded_body,
    require_json_media_type,
    require_empty_body,
)

MAX_SUBMIT_BODY_BYTES = 16_384
logger = logging.getLogger(__name__)


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
                if exc.status_code == 503:
                    return job_error_response(
                        DependencyUnavailable(), request_id=_request_id(request)
                    )
                raise
            except Exception as exc:  # noqa: BLE001 - sanitize unexpected adapter failures
                request_id = _request_id(request)
                logger.error(
                    "unhandled_jobs_api_exception",
                    extra={"exception_type": type(exc).__name__, "request_id": request_id},
                )
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "Internal server error.",
                            "request_id": request_id,
                        }
                    },
                    headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
                )

        return route_handler


def create_jobs_router(
    *,
    service: JobsReadService,
    principal_provider: PrincipalProvider,
    cancel_service: JobCancelService | None = None,
    submit_service: JobSubmitService | None = None,
) -> APIRouter:
    """Build role-scoped read routes and the approved QUEUED-only cancel route.

    Submission is mounted only when a real TX-SUBMIT service is supplied.
    """
    router = APIRouter(
        prefix="/api/v1/jobs", tags=["jobs"], route_class=JobsAPIRoute
    )

    if submit_service is not None:

        @router.post("", response_model=PublicJobResponse)
        async def submit_job(
            request: Request,
            response: Response,
            principal: JobPrincipal = Depends(principal_provider),
        ) -> PublicJobResponse:
            request_id = _request_id(request)
            request.state.request_id = request_id
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            try:
                role = JobRole(principal.role)
            except (TypeError, ValueError) as exc:
                raise Unauthenticated() from exc
            if role is not JobRole.CLIENT:
                raise Forbidden()

            keys = request.headers.getlist("Idempotency-Key")
            if not keys:
                raise IdempotencyKeyRequired()
            if len(keys) != 1:
                raise ValidationFailed()
            try:
                require_json_media_type(request.headers.get("content-type"))
                body_bytes = await read_bounded_body(request, MAX_SUBMIT_BODY_BYTES)
                payload = parse_json(body_bytes)
            except (BodyTooLarge, InvalidBody, ClientDisconnect) as exc:
                raise InvalidJson() from exc
            body = submit_request_from_mapping(payload)
            try:
                result = await run_in_threadpool(
                    submit_service.submit,
                    principal=principal,
                    idempotency_key=keys[0],
                    request=body,
                    correlation_id=UUID(request_id),
                )
            except CommitOutcomeUnknown:
                # Never retry an uncertain transaction. The client reconciles by
                # listing its Jobs and retries only with the same idempotency key.
                return job_error_response(
                    DependencyUnavailable(), request_id=request_id
                )  # type: ignore[return-value]
            response.status_code = 200 if result.replayed else 201
            response.headers["Location"] = f"/api/v1/jobs/{result.job.id}"
            return project_job(result.job, principal=principal)

    @router.get("", response_model=JobCollectionResponse)
    def list_jobs(
        request: Request,
        response: Response,
        scope: str | None = None,
        status: str | None = None,
        limit: str = "20",
        cursor: str | None = None,
        listing_id: str | None = None,
        principal: JobPrincipal = Depends(principal_provider),
    ) -> JobCollectionResponse:
        request_id = _request_id(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        try:
            parsed_limit = _parse_limit(limit)
            parsed_listing_id = _parse_listing_id_filter(request, listing_id)
            return service.list_jobs(
                principal=principal,
                scope=scope,
                status=status,
                limit=parsed_limit,
                cursor=cursor,
                listing_id=parsed_listing_id,
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

    if cancel_service is not None:

        @router.post("/{job_id}/cancel", response_model=PublicJobResponse)
        async def cancel_job(
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
                await require_empty_body(request)
            except (InvalidBody, UnexpectedBody):
                return job_error_response(InvalidJson(), request_id=request_id)  # type: ignore[return-value]
            try:
                return await run_in_threadpool(
                    cancel_service.cancel,
                    principal=principal,
                    job_id=parsed_id,
                    correlation_id=UUID(request_id),
                )
            except JobDomainError as exc:
                return job_error_response(exc, request_id=request_id)  # type: ignore[return-value]
            except CommitOutcomeUnknown:
                # The transaction adapter cannot prove whether COMMIT was durable.
                # Return a controlled outage response; clients must reconcile with GET,
                # never automatically replay the mutation.
                return job_error_response(
                    DependencyUnavailable(), request_id=request_id
                )  # type: ignore[return-value]

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


def _parse_listing_id_filter(request: Request, declared_value: str | None) -> UUID | None:
    values = request.query_params.getlist("listing_id")
    if not values:
        return None
    if len(values) != 1:
        raise InvalidFilter()
    raw = values[0]
    if raw != declared_value:
        raise InvalidFilter()
    try:
        value = UUID(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidFilter() from exc
    if value.version != 4 or str(value) != raw:
        raise InvalidFilter()
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
