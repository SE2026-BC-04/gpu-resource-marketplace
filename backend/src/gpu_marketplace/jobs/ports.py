"""Narrow ports for later GPU-002/003/004 integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from gpu_marketplace.jobs.models import FailureReason, JobRole, JobStatus


class JobPrincipal(Protocol):
    """Structural view of GPU-003's authenticated principal; no JWT code here."""

    @property
    def user_id(self) -> UUID: ...

    @property
    def role(self) -> str: ...


@dataclass(frozen=True)
class JobRecord:
    """Read-side data required for projection; deliberately has no oracle fields."""

    id: UUID
    client_id: UUID
    worker_id: UUID
    listing_id: UUID
    requested_gpu_count: int
    duration_seconds: int
    status: JobStatus
    failure_reason: FailureReason | None
    submitted_at: datetime
    started_at: datetime | None
    terminal_at: datetime | None


@dataclass(frozen=True)
class CursorPosition:
    submitted_at: datetime
    job_id: UUID


@dataclass(frozen=True)
class CursorContext:
    user_id: UUID
    role: JobRole
    scope: str
    status: JobStatus | None


@dataclass(frozen=True)
class JobPage:
    items: tuple[JobRecord, ...]
    next_position: CursorPosition | None


class JobReader(Protocol):
    """TV2 adapter owns visibility and keyset ordering in the query itself.

    Client reads filter on client_id; Worker reads join Listing ownership to the
    authenticated account; Admin reads are read-only. All lists sort by
    submitted_at DESC, id DESC and apply the supplied cursor before LIMIT.
    Adapters should translate expected storage outages to DependencyUnavailable.
    """

    def list_visible(
        self,
        *,
        principal: JobPrincipal,
        status: JobStatus | None,
        after: CursorPosition | None,
        limit: int,
    ) -> JobPage: ...

    def get_visible(self, *, principal: JobPrincipal, job_id: UUID) -> JobRecord | None:
        """Return None for both missing and non-visible Jobs (uniform 404)."""
        ...


class CursorCodec(Protocol):
    """Integration supplies an opaque, tamper-evident, context-bound codec."""

    def decode(self, token: str, *, context: CursorContext) -> CursorPosition: ...

    def encode(self, position: CursorPosition, *, context: CursorContext) -> str: ...


class PrincipalProvider(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> JobPrincipal: ...


class JobScope(StrEnum):
    MINE = "mine"
    ASSIGNED = "assigned"
    ALL = "all"
