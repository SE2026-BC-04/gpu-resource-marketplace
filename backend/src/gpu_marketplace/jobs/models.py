"""Transport DTOs for the public Jobs API; no persistence models live here."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


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


class SubmitJobRequest(StrictDTO):
    """Exact three-field public submit body (not a submission use case)."""

    # UUID is a JSON string in the wire contract; Pydantic strict mode still
    # rejects coercions for numeric fields while accepting this UUID spelling.
    listing_id: UUID = Field(strict=False)
    gpu_count: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]
    duration_seconds: Annotated[int, Field(gt=0, le=MAX_POSTGRES_INTEGER)]


class JobResponse(BaseModel):
    """Safe common Job projection; excludes private Client/Worker/oracle data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID
    listing_id: UUID
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

    worker_id: UUID


# Put the subtype first so response-model union selection does not erase the
# Client-only worker_id field when FastAPI serializes a ClientJobResponse.
PublicJobResponse = ClientJobResponse | JobResponse


class JobCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[PublicJobResponse]
    next_cursor: str | None
