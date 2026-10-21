import asyncio
import logging
from collections.abc import Callable

from gpu_marketplace.common.config import Settings

logger = logging.getLogger(__name__)


async def _foundation_idle_runner(stop_event: asyncio.Event) -> None:
    """Keep the service stoppable; no scheduling or business transaction runs in GPU-001."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except TimeoutError:
            logger.debug("manager_foundation_idle")


async def run_manager(
    *,
    settings: Settings | None = None,
    database_probe: Callable[[], bool],
    stop_event: asyncio.Event | None = None,
) -> None:
    resolved_settings = settings or Settings()
    _ = resolved_settings  # Shared validated config is the handoff point for future runners.
    resolved_stop_event = stop_event or asyncio.Event()

    database_available = await asyncio.to_thread(database_probe)
    if not database_available:
        raise RuntimeError("Manager cannot start while PostgreSQL readiness fails")

    logger.info("manager_started")
    idle_runner = asyncio.create_task(_foundation_idle_runner(resolved_stop_event))
    try:
        await resolved_stop_event.wait()
    finally:
        resolved_stop_event.set()
        await idle_runner
        logger.info("manager_stopped")
