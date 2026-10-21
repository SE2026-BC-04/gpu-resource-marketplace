import asyncio
import signal

from gpu_marketplace.common.config import Settings
from gpu_marketplace.common.database import create_engine, database_is_ready
from gpu_marketplace.common.logging import configure_logging
from gpu_marketplace.manager.service import run_manager


async def run() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if signum is not None:
            try:
                loop.add_signal_handler(signum, stop_event.set)
            except (NotImplementedError, RuntimeError):
                # Windows' event loop may not support SIGTERM handlers.
                if signum == signal.SIGINT:
                    signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop_event.set))
    try:
        await run_manager(
            settings=settings,
            database_probe=lambda: database_is_ready(engine),
            stop_event=stop_event,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
