"""Adapt complete synchronous Outbox UoW ports to async Outbox ports.

The claim and settlement callables each run as one bounded-executor
operation. The asynchronous transport port remains outside this adapter and
must never run in a database worker. This adapter does not provide persistence,
retry, outcome reconciliation, or production executor sizing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from gpu_marketplace.manager.bounded_executor import BoundedExecutor
from gpu_marketplace.manager.outbox import ClaimOneCommitted, Settle

ClaimT = TypeVar("ClaimT")
TransportOutcomeT = TypeVar("TransportOutcomeT")


class OutboxExecutorAdapter(Generic[ClaimT, TransportOutcomeT]):
    """Wrap synchronous claim/settlement UoWs for existing async Outbox ports.

    Each port invocation submits its complete synchronous callable exactly
    once. Executor capacity/admission errors and worker failures propagate
    unchanged. Cancellation propagates to the async caller while the injected
    ``BoundedExecutor`` retains the accepted worker and its capacity slot until
    actual completion. Cancellation does not imply worker termination, a
    rollback, or a known transaction outcome; this adapter never retries or
    reconciles an operation.
    """

    def __init__(self, executor: BoundedExecutor) -> None:
        self._executor = executor

    def wrap_claim(
        self,
        operation: Callable[[], ClaimT | None],
    ) -> ClaimOneCommitted[ClaimT]:
        """Adapt one complete synchronous claim/commit/close operation."""

        async def claim_one_committed() -> ClaimT | None:
            handle = self._executor.submit(operation)
            return await handle.wait()

        return claim_one_committed

    def wrap_settlement(
        self,
        operation: Callable[[ClaimT, TransportOutcomeT], None],
    ) -> Settle[ClaimT, TransportOutcomeT]:
        """Adapt one complete synchronous settlement/commit/close operation."""

        async def settle(claim: ClaimT, outcome: TransportOutcomeT) -> None:
            handle = self._executor.submit(operation, claim, outcome)
            await handle.wait()

        return settle
