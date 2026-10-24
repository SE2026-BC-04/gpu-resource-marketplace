"""The three approved Auth routes (API Contract §4.2–4.4).

Not registered in ``api/app.py``: the team lead integrates the router together with
the JWT secret configuration and the GPU-002 account adapter.
"""

from collections.abc import Callable
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from gpu_marketplace.identity.dependencies import BEARER_CHALLENGE, bearer_token
from gpu_marketplace.identity.service import (
    AuthError,
    AuthService,
    AuthUnavailable,
    CurrentIdentity,
    InvalidCredentials,
    InvalidLoginName,
    NotAuthenticated,
)

logger = logging.getLogger(__name__)

# API Contract §4 does not name the 401 code for /me and /logout; §7.9 uses UNAUTHORIZED and
# §8 uses UNAUTHENTICATED. Pending the team lead's decision, keep it in this one constant.
TOKEN_REJECTED_CODE = "UNAUTHORIZED"

_LOGIN_FIELDS = frozenset({"login_name", "password"})


class _RequestError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


def _auth_error(exc: AuthError) -> _RequestError:
    if isinstance(exc, InvalidCredentials):
        return _RequestError(401, "INVALID_CREDENTIALS", "Authentication failed.")
    if isinstance(exc, InvalidLoginName):
        return _RequestError(422, "VALIDATION_ERROR", "The request contains invalid values.")
    if isinstance(exc, NotAuthenticated):
        return _RequestError(401, TOKEN_REJECTED_CODE, "Authentication required.")
    if isinstance(exc, AuthUnavailable):
        return _RequestError(503, "DEPENDENCY_UNAVAILABLE", "Service temporarily unavailable.")
    return _RequestError(500, "INTERNAL_ERROR", "Internal server error.")


def _request_id(request: Request) -> str:
    # Trust only a UUIDv4 attached by server middleware, never the caller's X-Request-ID header.
    candidate = getattr(request.state, "request_id", None)
    if isinstance(candidate, str):
        try:
            parsed = UUID(candidate)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.version == 4 and str(parsed) == candidate:
            return candidate
    return str(uuid4())


def _private_headers(request_id: str) -> dict[str, str]:
    return {"X-Request-ID": request_id, "Cache-Control": "no-store"}


class AuthRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            request_id = _request_id(request)
            try:
                response = await original(request)
            except _RequestError as exc:
                headers = _private_headers(request_id)
                if exc.status == 401:
                    headers.update(BEARER_CHALLENGE)
                logger.info("auth_request_rejected", extra={"request_id": request_id})
                return JSONResponse(
                    status_code=exc.status,
                    content={"error": {"code": exc.code, "message": exc.message, "request_id": request_id}},
                    headers=headers,
                )
            response.headers.update(_private_headers(request_id))
            return response

        return handler


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


async def _login_body(request: Request) -> tuple[str, str]:
    try:
        data = json.loads(
            (await request.body()).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError) as exc:
        raise _RequestError(400, "INVALID_JSON", "The request body is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise _RequestError(422, "VALIDATION_ERROR", "The request contains invalid values.")
    if set(data) - _LOGIN_FIELDS:
        raise _RequestError(400, "UNKNOWN_FIELD", "The request contains an unsupported field.")
    login_name, password = data.get("login_name"), data.get("password")
    if not isinstance(login_name, str) or not isinstance(password, str) or not password:
        raise _RequestError(422, "VALIDATION_ERROR", "The request contains invalid values.")
    return login_name, password


def _identity_json(identity: CurrentIdentity) -> dict[str, str]:
    return {"id": str(identity.user_id), "login_name": identity.login_name, "role": identity.role}


def create_auth_router(*, service: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"], route_class=AuthRoute)

    def token_or_reject(request: Request) -> str:
        token = bearer_token(request.headers.get("authorization"))
        if token is None:
            raise _RequestError(401, TOKEN_REJECTED_CODE, "Authentication required.")
        return token

    async def call(function: Callable[..., Any], *args: Any) -> Any:
        try:
            return await run_in_threadpool(function, *args)
        except AuthError as exc:
            raise _auth_error(exc) from exc

    @router.post("/login")
    async def login(request: Request) -> JSONResponse:
        login_name, password = await _login_body(request)
        result = await call(service.login, login_name, password)
        return JSONResponse(
            {
                "access_token": result.access_token,
                "token_type": "Bearer",
                "expires_in": result.expires_in,
                "user": _identity_json(result.identity),
            }
        )

    @router.get("/me")
    async def me(request: Request) -> JSONResponse:
        identity = await call(service.current_identity, token_or_reject(request))
        return JSONResponse(_identity_json(identity))

    @router.post("/logout", status_code=204)
    async def logout(request: Request) -> Response:
        # Validates the caller only; an issued JWT is not revoked server-side (API Contract §4.4).
        await call(service.current_identity, token_or_reject(request))
        return Response(status_code=204)

    return router
