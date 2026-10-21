from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    logger = logging.getLogger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("simulator_started")
        try:
            yield
        finally:
            logger.info("simulator_stopped")

    app = FastAPI(
        title="GPU Marketplace Simulator Runtime",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app
