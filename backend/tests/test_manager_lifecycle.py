import asyncio

import pytest

from gpu_marketplace.common.config import Settings
from gpu_marketplace.manager.service import run_manager


def test_manager_runs_and_stops_cleanly() -> None:
    async def scenario() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_manager(
                settings=Settings(_env_file=None),
                database_probe=lambda: True,
                stop_event=stop_event,
            )
        )
        await asyncio.sleep(0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_manager_refuses_start_when_database_probe_fails() -> None:
    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="PostgreSQL readiness"):
            await run_manager(
                settings=Settings(_env_file=None),
                database_probe=lambda: False,
            )

    asyncio.run(scenario())
