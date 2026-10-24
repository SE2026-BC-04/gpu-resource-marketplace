"""FastAPI dependency that other modules use to obtain the trusted principal.

Error convention agreed on PR #15 and PR #17: ``HTTPException(401)`` with a Bearer
challenge, or ``HTTPException(503)``; never 403 and no error code in the detail, so
each router maps the status to its own contract section.
"""

from collections.abc import Callable

from fastapi import HTTPException, Request

from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.service import AuthService, AuthUnavailable, NotAuthenticated
from gpu_marketplace.identity.tokens import MAX_TOKEN_LENGTH

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def bearer_token(authorization: str | None) -> str | None:
    """Return the token of ``Authorization: Bearer <token>`` or None for any other shape.

    C4 (PR #18): a token over MAX_TOKEN_LENGTH or with non-ASCII characters is refused here,
    before the codec, so oversized headers never reach base64/JSON parsing.
    """
    if authorization is None or len(authorization) > MAX_TOKEN_LENGTH + len("Bearer ") or not authorization.isascii():
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def create_principal_dependency(service: AuthService) -> Callable[[Request], AuthenticatedPrincipal]:
    # Synchronous on purpose: FastAPI runs it in the threadpool because it reads the database.
    def require_authenticated_principal(request: Request) -> AuthenticatedPrincipal:
        token = bearer_token(request.headers.get("authorization"))
        if token is None:
            raise HTTPException(status_code=401, headers=BEARER_CHALLENGE)
        try:
            return service.authenticate(token)
        except NotAuthenticated as exc:
            raise HTTPException(status_code=401, headers=BEARER_CHALLENGE) from exc
        except AuthUnavailable as exc:
            raise HTTPException(status_code=503) from exc

    return require_authenticated_principal
