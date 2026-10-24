"""Transport DTOs for the public Jobs API; no persistence models live here."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    UUID4,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)


MAX_POSTGRES_INTEGER = 2_147_483_647


class JobRole(StrEnum):
    CLIENT = "CLIENT"
    WORKER = "WORKER"
    ADMIN = "ADMIN"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureReason(StrEnum):
    WORKER_FAULT = "WORKER_FAULT"
    JOB_FAULT = "JOB_FAULT"
    SYSTEM_FAULT = "SYSTEM_FAULT"


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _canonical_uuid4(value: object) -> object:
    """Validate public UUID text before Pydantic's UUID parser normalizes it."""
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("value must be a canonical UUIDv4") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("value must be a lowercase canonical UUIDv4")
        return parsed
    if isinstance(value, UUID) and value.version == 4:
        return value
    raise ValueError("value must be a canonical UUIDv4 string")


CanonicalUUID4 = Annotated[UUID4, BeforeValidator(_canonical_uuid4)]


class SubmitJobRequest(StrictDTO):
    """Exact three-field public submit body (not a submission use case)."""

    # Public IDs use canonical lowercase UUIDv4 wire strings. Numeric fields
    # remain strict under the base model configuration.
    listing_id: CanonicalUUID4 = Field(strict=False)
    gpu_count: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]
    duration_seconds: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]


class JobResponse(BaseModel):
    """Safe common Job projection; excludes private Client/Worker/oracle data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID4
    listing_id: UUID4
    gpu_count: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]
    duration_seconds: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]
    status: JobStatus
    failure_reason: FailureReason | None
    submitted_at: datetime
    started_at: datetime | None
    terminal_at: datetime | None

    @model_validator(mode="after")
    def validate_failure_reason(self) -> JobResponse:
        if (self.status is JobStatus.FAILED) != (self.failure_reason is not None):
            raise ValueError("failure_reason must be present exactly for FAILED Jobs")
        return self

    @field_serializer("submitted_at", "started_at", "terminal_at", when_used="json")
    def serialize_utc_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Job timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )


class ClientJobResponse(JobResponse):
    """Client's own Job view includes the assigned Worker ID per API §8."""

    worker_id: UUID4


# Put the subtype first so response-model union selection does not erase the
# Client-only worker_id field when FastAPI serializes a ClientJobResponse.
PublicJobResponse = ClientJobResponse | JobResponse


class JobCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[PublicJobResponse]
    next_cursor: str | None
