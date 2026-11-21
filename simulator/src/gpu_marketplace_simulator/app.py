from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from gpu_marketplace_simulator.attempt_cache import AttemptCache
from gpu_marketplace_simulator.attempt_cache_adapter import (
    AttemptCacheAdmissionAdapter,
    ProducerRegistrationPort,
)
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.dispatch import AttemptAdmissionPort, create_dispatch_router
from gpu_marketplace_simulator.logging import configure_logging


def create_app(settings: Settings | None = None, *,
               admission_port: AttemptAdmissionPort | None = None,
               producer_registrar: ProducerRegistrationPort | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    logger = logging.getLogger(__name__)

    attempt_cache: AttemptCache | None = None
    adapter: AttemptCacheAdmissionAdapter | None = None
    if producer_registrar is not None:
        if admission_port is not None:
            raise ValueError("pass either admission_port or producer_registrar, not both")
        required = (
            resolved_settings.dispatch_max_body_bytes,
            resolved_settings.attempt_cache_max_entries,
            resolved_settings.attempt_cache_ttl_seconds,
            resolved_settings.producer_concurrency_limit,
            resolved_settings.shutdown_drain_timeout_seconds,
        )
        if any(value is None for value in required):
            raise ValueError("Simulator-local cache integration requires explicit finite limits")
        attempt_cache = AttemptCache(
            max_entries=resolved_settings.attempt_cache_max_entries,
            ttl_seconds=resolved_settings.attempt_cache_ttl_seconds,
        )
        adapter = AttemptCacheAdmissionAdapter(
            cache=attempt_cache,
            producer=producer_registrar,
            max_concurrent_producers=resolved_settings.producer_concurrency_limit,
        )
        admission_port = adapter

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("simulator_started")
        try:
            yield
        finally:
            if adapter is not None:
                adapter.close()
                drained = adapter.drain(
                    resolved_settings.shutdown_drain_timeout_seconds or 0
                )
                if not drained:
                    logger.warning("simulator_producer_drain_timed_out")
            logger.info("simulator_stopped")

    app = FastAPI(
        title="GPU Marketplace Simulator Runtime",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(create_dispatch_router(
        manager_token=resolved_settings.manager_dispatch_token,
        admission=admission_port,
        max_request_body_bytes=resolved_settings.dispatch_max_body_bytes,
    ))
    app.state.attempt_cache = attempt_cache
    app.state.admission_port = admission_port

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app
