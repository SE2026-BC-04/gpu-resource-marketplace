"""DB/HTTP-free values exchanged with the GPU-002/GPU-003 adapters."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, TypedDict
from uuid import UUID

ListingStatus = Literal["ACTIVE", "PAUSED"]
ListingScope = Literal["marketplace", "mine", "all"]
UserRole = Literal["CLIENT", "WORKER", "ADMIN"]


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("adapter must return timezone-aware DB timestamps")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


class TrustedPrincipal(Protocol):
    """Produced by GPU-003 after JWT + current ACTIVE account/role checks.

    This is a consumption interface, not an authentication implementation.
    Never construct this from request headers, JSON or query parameters.
    """

    @property
    def user_id(self) -> UUID: ...

    @property
    def role(self) -> str: ...

    @property
    def status(self) -> str: ...


@dataclass(frozen=True)
class WorkerProfile:
    id: UUID
    display_name: str


@dataclass(frozen=True)
class ListingRecord:
    id: UUID
    worker: WorkerProfile
    gpu_model: str
    vram_gb: int
    total_gpu_count: int
    allocated_gpu_count: int
    status: ListingStatus
    mock_price_per_hour: Decimal | None
    created_at: datetime
    updated_at: datetime
    successful_jobs: int = 0
    worker_fault_jobs: int = 0


class ListingChanges(TypedDict, total=False):
    gpu_model: str
    vram_gb: int
    total_gpu_count: int
    mock_price_per_hour: Decimal | None


@dataclass(frozen=True)
class ListingPosition:
    created_at: datetime
    id: UUID


@dataclass(frozen=True)
class ListingQuery:
    status: ListingStatus | None
    worker_id: UUID | None = None


@dataclass(frozen=True)
class ListingPage:
    items: tuple[ListingRecord, ...]
    next_cursor: str | None
