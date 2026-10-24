"""Six Listing routes, explicitly wired to trusted GPU-003/GPU-002 adapters.

No default principal, memory database, JWT implementation or public debug route
is installed. The integration owner includes this router only with real adapters.
"""

from collections.abc import Callable
import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import UUID4, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.service import AuthService

from .errors import ListingDependencyUnavailable, ListingError, invalid_fields
from .models import TrustedPrincipal
from .policy import MUTABLE_FIELDS
from .schemas import ListingCreate, ListingDTO, ListingPageDTO, ListingPatch
from .service import ListingService, require_principal, require_worker

logger = logging.getLogger(__name__)


def _error(request_id: str, status: int, code: str, message: str) -> JSONResponse:
    logger.info("listing_request_rejected", extra={"request_id": request_id})
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers=headers,
    )


class ListingRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            # Never trust an incoming request ID as an actor or trusted correlation ID.
            request_id = str(uuid4())
            try:
                response = await original(request)
            except ListingError as exc:
                return _error(request_id, exc.status_code, exc.code, exc.message)
            except RequestValidationError:
                return _error(
                    request_id, 422, "VALIDATION_ERROR", "Invalid request parameters."
                )
            except ListingDependencyUnavailable:
                return _error(
                    request_id,
                    503,
                    "DEPENDENCY_UNAVAILABLE",
                    "Service temporarily unavailable.",
                )
            except HTTPException as exc:
                codes = {
                    401: "UNAUTHORIZED",
                    403: "FORBIDDEN",
                    503: "DEPENDENCY_UNAVAILABLE",
                }
                return _error(
                    request_id,
                    exc.status_code,
                    codes.get(exc.status_code, "INVALID_REQUEST"),
                    "Request could not be accepted.",
                )
            except Exception:
                # Adapter failures may contain a DSN, token or SQL. Never return/log them here.
                return _error(
                    request_id, 500, "INTERNAL_ERROR", "Internal server error."
                )
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            logger.info("listing_request_completed", extra={"request_id": request_id})
            return response

        return handler


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


async def _body(
    request: Request, schema: type[ListingCreate] | type[ListingPatch]
) -> ListingPatch:
    try:
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise ValueError("JSON media type required")
        data = json.loads(
            (await request.body()).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (ValueError, UnicodeError) as exc:
        raise ListingError(400, "INVALID_JSON", "Invalid JSON request.") from exc
    if not isinstance(data, dict):
        raise invalid_fields()
    if set(data) - MUTABLE_FIELDS:
        raise ListingError(
            400, "UNKNOWN_FIELD", "Request contains an unsupported field."
        )
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise invalid_fields() from exc


def create_listing_router(
    *,
    service: ListingService,
    principal_dependency: Callable[..., TrustedPrincipal],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/gpu-listings", tags=["Listings"], route_class=ListingRoute
    )

    @router.get("", response_model=ListingPageDTO)
    async def browse(
        request: Request, principal=Depends(principal_dependency)
    ) -> ListingPageDTO:
        require_principal(principal)
        params = request.query_params
        allowed = {"scope", "status", "limit", "cursor"}
        if set(params) - allowed or any(
            len(params.getlist(key)) != 1 for key in params
        ):
            raise ListingError(400, "INVALID_FILTER", "Invalid Listing filter.")
        raw_limit = params.get("limit", "20")
        normalized_limit = raw_limit.lstrip("0") or "0"
        if (
            not raw_limit.isascii()
            or not raw_limit.isdecimal()
            or len(normalized_limit) > 3
        ):
            raise ListingError(422, "VALIDATION_ERROR", "Invalid page size.")
        page = await run_in_threadpool(
            service.browse,
            principal,
            scope=params.get("scope", "marketplace"),
            status=params.get("status"),
            limit=int(normalized_limit),
            cursor=params.get("cursor"),
        )
        return ListingPageDTO(
            items=[ListingDTO.from_record(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @router.get("/{listing_id}", response_model=ListingDTO)
    async def detail(
        listing_id: UUID4, principal=Depends(principal_dependency)
    ) -> ListingDTO:
        record = await run_in_threadpool(service.detail, principal, listing_id)
        return ListingDTO.from_record(record)

    @router.post("", status_code=201, response_model=ListingDTO)
    async def create(
        request: Request, response: Response, principal=Depends(principal_dependency)
    ) -> ListingDTO:
        require_worker(principal)
        body = await _body(request, ListingCreate)
        record = await run_in_threadpool(service.create, principal, body.changes())
        response.headers["Location"] = f"/api/v1/gpu-listings/{record.id}"
        return ListingDTO.from_record(record)

    @router.patch("/{listing_id}", response_model=ListingDTO)
    async def patch(
        listing_id: UUID4, request: Request, principal=Depends(principal_dependency)
    ) -> ListingDTO:
        require_worker(principal)
        body = await _body(request, ListingPatch)
        record = await run_in_threadpool(
            service.patch, principal, listing_id, body.changes()
        )
        return ListingDTO.from_record(record)

    async def change_status(
        listing_id: UUID4, request: Request, principal: TrustedPrincipal, target: str
    ) -> ListingDTO:
        require_worker(principal)
        if await request.body():
            raise ListingError(
                400, "INVALID_JSON", "This command does not accept a body."
            )
        record = await run_in_threadpool(
            service.set_status, principal, listing_id, target
        )
        return ListingDTO.from_record(record)

    @router.post("/{listing_id}/pause", response_model=ListingDTO)
    async def pause(
        listing_id: UUID4, request: Request, principal=Depends(principal_dependency)
    ) -> ListingDTO:
        return await change_status(listing_id, request, principal, "PAUSED")

    @router.post("/{listing_id}/resume", response_model=ListingDTO)
    async def resume(
        listing_id: UUID4, request: Request, principal=Depends(principal_dependency)
    ) -> ListingDTO:
        return await change_status(listing_id, request, principal, "ACTIVE")

    return router


def create_authenticated_listing_router(
    *, service: ListingService, auth_service: AuthService
) -> APIRouter:
    """Connect Listings to GPU-003's real JWT/current-account dependency.

    The integration owner supplies the shared AuthService and a real Listing
    UoW, then registers this router. No secret, engine, account adapter or test
    principal is created here; production app registration remains separate.
    """
    return create_listing_router(
        service=service,
        principal_dependency=create_principal_dependency(auth_service),
    )
