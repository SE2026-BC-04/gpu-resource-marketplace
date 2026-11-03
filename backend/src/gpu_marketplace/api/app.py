from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from gpu_marketplace.common.config import Settings
from gpu_marketplace.common.database import create_engine, database_is_ready
from gpu_marketplace.common.logging import configure_logging
from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.passwords import ScryptPasswordHasher
from gpu_marketplace.identity.router import create_auth_router
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.repositories.accounts import PostgresAccountReader

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    database_probe: Callable[[], bool] | None = None,
    account_sessions: sessionmaker[Session] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if resolved_settings.jwt_secret is None:
        raise ValueError("GPU_MARKETPLACE_JWT_SECRET must be configured for the API")
    configure_logging(resolved_settings.log_level)

    engine: Engine | None = None
    if account_sessions is None:
        engine = create_engine(resolved_settings.database_url)
        account_sessions = sessionmaker(bind=engine)
    elif database_probe is None:
        raise ValueError("database_probe is required when injecting account_sessions")
    if database_probe is None:
        assert engine is not None
        database_probe = lambda: database_is_ready(engine)
    assert account_sessions is not None

    auth_service = AuthService(
        PostgresAccountReader(account_sessions),
        AccessTokenCodec(resolved_settings.jwt_secret.get_secret_value().encode("utf-8")),
        ScryptPasswordHasher(),
    )
    principal_dependency = create_principal_dependency(auth_service)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("api_started")
        try:
            yield
        finally:
            logger.info("api_stopped")
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="GPU Resource Marketplace API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.auth_service = auth_service
    app.state.require_authenticated_principal = principal_dependency
    app.include_router(create_auth_router(service=auth_service))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False, response_model=None)
    def ready() -> JSONResponse | dict[str, Any]:
        if not database_probe():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "components": {"database": "unavailable"}},
            )
        return {"status": "ready", "components": {"database": "ok"}}

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Keep response and log fields free of exception text, which can contain secrets.
        if request.url.path.startswith("/api/v1/auth/"):
            request_id = getattr(request.state, "request_id", None)
            if not isinstance(request_id, str):
                request_id = str(uuid4())
            logger.error(
                "unhandled_api_exception",
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
        logger.error("unhandled_api_exception", extra={"exception_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app
