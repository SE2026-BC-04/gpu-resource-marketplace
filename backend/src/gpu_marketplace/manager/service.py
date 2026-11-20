import asyncio
import logging
from collections.abc import Callable, Mapping

from gpu_marketplace.common.config import Settings
from gpu_marketplace.manager.supervisor import (
    GroupRunner,
    ManagerGroup,
    ManagerSupervisor,
    ManagerSupervisorError,
)

logger = logging.getLogger(__name__)


async def run_manager(
    *,
    settings: Settings | None = None,
    database_probe: Callable[[], bool],
    stop_event: asyncio.Event | None = None,
    group_runners: Mapping[ManagerGroup, GroupRunner] | None = None,
) -> None:
    _resolved_settings = settings or Settings()
    resolved_stop_event = stop_event or asyncio.Event()

    # shield the sync probe's worker so cancelling its async caller cannot
    # race the Engine disposal in manager.__main__.
    probe_task = asyncio.create_task(
        asyncio.to_thread(database_probe), name="manager:db-probe"
    )
    try:
        database_available = await asyncio.shield(probe_task)
    except asyncio.CancelledError:
        await _wait_for_probe_after_cancellation(probe_task)
        raise
    if not database_available:
        raise RuntimeError("Manager cannot start while PostgreSQL readiness fails")

    logger.info("manager_process_started")
    supervisor = ManagerSupervisor(
        runners=group_runners,
        stop_event=resolved_stop_event,
    )
    for group, snapshot in supervisor.snapshot().items():
        if snapshot.dependency_status == "BLOCKED_BY_DEPENDENCY":
            logger.warning(
                "manager_group_blocked",
                extra={
                    "manager_group": group.value,
                    "status": snapshot.dependency_status,
                },
            )
    try:
        await supervisor.run()
    except asyncio.CancelledError:
        raise
    except ManagerSupervisorError as error:
        logger.error(
            "manager_supervisor_failed",
            extra={
                "manager_group": error.group.value,
                "error_type": error.cause_type,
            },
        )
        raise
    logger.info("manager_stopped")


async def _wait_for_probe_after_cancellation(probe_task: asyncio.Task[bool]) -> None:
    """Wait for the synchronous readiness probe before caller cleanup runs."""
    while not probe_task.done():
        try:
            await asyncio.shield(probe_task)
        except asyncio.CancelledError:
            continue
    try:
        await probe_task
    except BaseException:
        # Preserve the caller's cancellation while still waiting for the
        # worker thread; the normal, non-cancelled path reports probe errors.
        pass
