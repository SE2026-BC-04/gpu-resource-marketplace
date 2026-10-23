"""Stable Jobs-domain errors and the shared API error-envelope adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fastapi.responses import JSONResponse
from pydantic import ValidationError

from gpu_marketplace.jobs.models import SubmitJobRequest


class JobErrorCode(StrEnum):
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    INVALID_JSON = "INVALID_JSON"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    INVALID_FILTER = "INVALID_FILTER"
    INVALID_CURSOR = "INVALID_CURSOR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    LISTING_NOT_FOUND = "LISTING_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    LISTING_PAUSED = "LISTING_PAUSED"
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    JOB_GPU_EXCEEDS_LISTING_TOTAL = "JOB_GPU_EXCEEDS_LISTING_TOTAL"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


_ERRORS: dict[JobErrorCode, tuple[int, str]] = {
    JobErrorCode.IDEMPOTENCY_KEY_REQUIRED: (400, "Idempotency-Key is required."),
    JobErrorCode.INVALID_JSON: (400, "The request body is not valid JSON."),
    JobErrorCode.UNKNOWN_FIELD: (400, "The request contains an unsupported field."),
    JobErrorCode.INVALID_FILTER: (400, "A Jobs filter is invalid."),
    JobErrorCode.INVALID_CURSOR: (400, "The pagination cursor is invalid."),
    JobErrorCode.UNAUTHENTICATED: (401, "Authentication is required."),
    JobErrorCode.FORBIDDEN: (403, "This operation is not permitted."),
    JobErrorCode.LISTING_NOT_FOUND: (404, "The Listing was not found."),
    JobErrorCode.JOB_NOT_FOUND: (404, "The Job was not found."),
    JobErrorCode.LISTING_PAUSED: (409, "The Listing is paused."),
    JobErrorCode.JOB_NOT_CANCELLABLE: (409, "The Job is not cancellable."),
    JobErrorCode.IDEMPOTENCY_KEY_REUSED: (409, "The idempotency key was used for another request."),
    JobErrorCode.VALIDATION_ERROR: (422, "The request contains invalid values."),
    JobErrorCode.JOB_GPU_EXCEEDS_LISTING_TOTAL: (
        422,
        "Requested GPUs exceed the Listing's total capacity.",
    ),
    JobErrorCode.DEPENDENCY_UNAVAILABLE: (503, "A required dependency is unavailable."),
}


@dataclass(eq=False)
class JobDomainError(Exception):
    code: JobErrorCode

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code.value)


class Unauthenticated(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.UNAUTHENTICATED)


class Forbidden(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.FORBIDDEN)


class JobNotFound(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.JOB_NOT_FOUND)


class InvalidFilter(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.INVALID_FILTER)


class InvalidJson(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.INVALID_JSON)


class InvalidCursor(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.INVALID_CURSOR)


class ValidationFailed(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.VALIDATION_ERROR)


class UnknownField(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.UNKNOWN_FIELD)


class IdempotencyKeyRequired(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.IDEMPOTENCY_KEY_REQUIRED)


class DependencyUnavailable(JobDomainError):
    def __init__(self) -> None:
        super().__init__(JobErrorCode.DEPENDENCY_UNAVAILABLE)


def submit_request_from_mapping(payload: object) -> SubmitJobRequest:
    """Validate a decoded payload and translate errors to the §8 taxonomy."""
    try:
        return SubmitJobRequest.model_validate(payload, strict=True)
    except ValidationError as exc:
        if any(error.get("type") == "json_invalid" for error in exc.errors()):
            raise InvalidJson() from exc
        if any(error.get("type") == "extra_forbidden" for error in exc.errors()):
            raise UnknownField() from exc
        raise ValidationFailed() from exc


def submit_request_from_json(payload: str | bytes) -> SubmitJobRequest:
    """Parse and validate the exact public JSON body without coercing numbers."""
    try:
        return SubmitJobRequest.model_validate_json(payload, strict=True)
    except ValidationError as exc:
        if any(error.get("type") == "json_invalid" for error in exc.errors()):
            raise InvalidJson() from exc
        if any(error.get("type") == "extra_forbidden" for error in exc.errors()):
            raise UnknownField() from exc
        raise ValidationFailed() from exc
    except ValueError as exc:
        raise InvalidJson() from exc


def validate_idempotency_key(value: str | None) -> str:
    """Apply API §8's proposed required printable-ASCII key policy."""
    if value is None or value == "":
        raise IdempotencyKeyRequired()
    if not 8 <= len(value) <= 128 or any(not 0x20 <= ord(char) <= 0x7E for char in value):
        raise ValidationFailed()
    return value


def job_error_response(error: JobDomainError, *, request_id: str) -> JSONResponse:
    status_code, message = _ERRORS[error.code]
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code.value,
                "message": message,
                "request_id": request_id,
            }
        },
        headers={"X-Request-ID": request_id},
    )
