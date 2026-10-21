from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from gpu_marketplace.common.config import Settings
from gpu_marketplace.common.database import create_engine, database_is_ready
from gpu_marketplace.common.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    database_probe: Callable[[], bool] | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)

    engine: Engine | None = None
    if database_probe is None:
        engine = create_engine(resolved_settings.database_url)
        database_probe = lambda: database_is_ready(engine)

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
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        # Keep response and log fields free of exception text, which can contain secrets.
        logger.error("unhandled_api_exception", extra={"exception_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app
