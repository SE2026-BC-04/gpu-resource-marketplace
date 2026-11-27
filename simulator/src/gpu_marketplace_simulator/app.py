from contextlib import asynccontextmanager
import logging
from collections.abc import Callable
from typing import Protocol

from fastapi import FastAPI

from gpu_marketplace_simulator.admission_executor import BoundedAdmissionExecutor
from gpu_marketplace_simulator.attempt_cache import AttemptCache
from gpu_marketplace_simulator.attempt_cache_adapter import (
    AttemptCacheAdmissionAdapter,
    ProducerRegistrationPort,
)
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.dispatch import AttemptAdmissionPort, create_dispatch_router
from gpu_marketplace_simulator.logging import configure_logging


class RuntimeLifecycle(Protocol):
    """Optional Simulator-local resource owner; absent in normal production startup."""

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


def create_app(settings: Settings | None = None, *,
               admission_port: AttemptAdmissionPort | None = None,
               producer_registrar: ProducerRegistrationPort | None = None,
               runtime_lifecycle: RuntimeLifecycle | None = None,
               attempt_cache_clock: Callable[[], float] | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    logger = logging.getLogger(__name__)

    attempt_cache: AttemptCache | None = None
    adapter: AttemptCacheAdmissionAdapter | None = None
    admission_executor: BoundedAdmissionExecutor | None = None
    if producer_registrar is not None:
        if admission_port is not None:
            raise ValueError("pass either admission_port or producer_registrar, not both")
        required = (
            resolved_settings.dispatch_max_body_bytes,
            resolved_settings.attempt_cache_max_entries,
            resolved_settings.attempt_cache_ttl_seconds,
            resolved_settings.producer_concurrency_limit,
            resolved_settings.shutdown_drain_timeout_seconds,
            resolved_settings.admission_executor_workers,
            resolved_settings.admission_max_outstanding,
        )
        if any(value is None for value in required):
            raise ValueError("Simulator-local cache integration requires explicit finite limits")
        attempt_cache = AttemptCache(
            max_entries=resolved_settings.attempt_cache_max_entries,
            ttl_seconds=resolved_settings.attempt_cache_ttl_seconds,
            **({"clock": attempt_cache_clock} if attempt_cache_clock is not None else {}),
        )
        adapter = AttemptCacheAdmissionAdapter(
            cache=attempt_cache,
            producer=producer_registrar,
            max_concurrent_producers=resolved_settings.producer_concurrency_limit,
        )
        admission_port = adapter

    if admission_port is not None:
        if (resolved_settings.admission_executor_workers is not None
                and resolved_settings.admission_max_outstanding is not None):
            admission_executor = BoundedAdmissionExecutor(
                workers=resolved_settings.admission_executor_workers,
                max_outstanding=resolved_settings.admission_max_outstanding,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("simulator_started")
        try:
            if runtime_lifecycle is not None:
                await runtime_lifecycle.startup()
            yield
        finally:
            if admission_executor is not None:
                timeout = resolved_settings.shutdown_drain_timeout_seconds or 0

                def close_and_drain() -> bool:
                    if adapter is None:
                        return True
                    adapter.close()
                    return adapter.drain(timeout)

                drained = await admission_executor.shutdown(
                    close_and_drain if adapter is not None else None,
                    timeout_seconds=timeout,
                )
                if adapter is not None and drained is not True:
                    logger.warning("simulator_producer_drain_timed_out")
            if runtime_lifecycle is not None:
                await runtime_lifecycle.shutdown()
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
        admission_executor=admission_executor,
    ))
    app.state.attempt_cache = attempt_cache
    app.state.admission_port = admission_port
    app.state.admission_executor = admission_executor

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app
