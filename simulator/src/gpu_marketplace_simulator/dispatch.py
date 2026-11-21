"""Simulator-local authenticated Manager dispatch boundary (TV5-P2E-07)."""
from __future__ import annotations

from datetime import datetime, timedelta
import hmac
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)


logger = logging.getLogger(__name__)
_MAX_INT32 = (1 << 31) - 1
_TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    workload_profile: str

    @field_validator("workload_profile")
    @classmethod
    def only_demo_profile(cls, value: str) -> str:
        if value != "demo-v1":
            raise ValueError("unsupported workload profile")
        return value


PositiveInt32 = Annotated[StrictInt, Field(gt=0, le=_MAX_INT32)]


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    outbox_event_id: str
    job_id: str
    attempt_id: str
    worker_id: str
    listing_id: str
    gpu_count: PositiveInt32
    duration_seconds: PositiveInt32
    simulation_input: SimulationInput
    finish_due_at: str
    hard_deadline_at: str

    @field_validator("outbox_event_id", "job_id", "attempt_id", "worker_id", "listing_id")
    @classmethod
    def canonical_uuid4(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as error:
            raise ValueError("identifier must be canonical UUIDv4") from error
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("identifier must be canonical UUIDv4")
        return value

    @field_validator("finish_due_at", "hard_deadline_at")
    @classmethod
    def canonical_utc_timestamp(cls, value: str) -> str:
        if _TIMESTAMP_PATTERN.fullmatch(value) is None:
            raise ValueError("timestamp must be exact UTC with six fractional digits")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("timestamp is not a valid calendar instant") from error
        return value

    @model_validator(mode="after")
    def deadline_is_adr005_derived(self) -> DispatchRequest:
        finish_due = datetime.fromisoformat(self.finish_due_at.replace("Z", "+00:00"))
        hard_deadline = datetime.fromisoformat(self.hard_deadline_at.replace("Z", "+00:00"))
        if hard_deadline != finish_due + timedelta(seconds=120):
            raise ValueError("hard_deadline_at must be finish_due_at plus 120 seconds")
        return self


class DispatchAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    accepted: bool = True


class AttemptAdmissionConflict(Exception):
    """The retained attempt is bound to a different immutable dispatch."""


class AttemptAdmissionUnavailable(Exception):
    """Admission is unavailable; scoped G2-A maps it to retryable HTTP 503."""


@dataclass(frozen=True, slots=True)
class AttemptAdmissionOutcome:
    """Internal admission result; never serialized into the dispatch response."""

    attempt_id: str
    state: Literal["IN_FLIGHT", "FINISHED"]
    newly_admitted: bool
    producer_registered: bool
    receipt: object | None = field(repr=False)
    cache_admission: object = field(repr=False)

    def __post_init__(self) -> None:
        if self.state not in {"IN_FLIGHT", "FINISHED"}:
            raise ValueError("unsupported attempt state")
        if type(self.newly_admitted) is not bool or type(self.producer_registered) is not bool:
            raise ValueError("admission flags must be booleans")
        if self.newly_admitted and self.state != "IN_FLIGHT":
            raise ValueError("a new admission must be IN_FLIGHT")
        if self.state == "FINISHED" and self.receipt is None:
            raise ValueError("a FINISHED admission requires its retained receipt")


class DispatchBodyTooLarge(ValueError):
    """The request exceeds the configured bounded dispatch body size."""


class AttemptAdmissionPort(Protocol):
    def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
        """Register one bounded producer or return a valid retained duplicate."""


class AdmissionExecutionPort(Protocol):
    async def run(self, operation: Callable[..., object], *args: object) -> object:
        """Execute one synchronous operation without blocking the event loop."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


async def _read_bounded_body(request: Request, max_bytes: int) -> bytes:
    """Read chunks only while the accumulated body remains within the bound."""
    content_lengths = request.headers.getlist("content-length")
    if len(content_lengths) > 1:
        raise ValueError("multiple Content-Length headers")
    if content_lengths:
        declared = content_lengths[0]
        if not declared.isascii() or not declared.isdecimal():
            raise ValueError("invalid Content-Length")
        if int(declared) > max_bytes:
            raise DispatchBodyTooLarge

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise DispatchBodyTooLarge
        body.extend(chunk)
    return bytes(body)


def _error(
    request_id: str,
    status: int,
    code: str,
    message: str,
    *,
    bearer_challenge: bool = False,
) -> JSONResponse:
    headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if bearer_challenge:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def create_dispatch_router(
    *,
    manager_token: SecretStr | None,
    admission: AttemptAdmissionPort | None,
    max_request_body_bytes: int | None,
    admission_executor: AdmissionExecutionPort | None = None,
) -> APIRouter:
    if (max_request_body_bytes is not None
            and (type(max_request_body_bytes) is not int or max_request_body_bytes <= 0)):
        raise ValueError("max_request_body_bytes must be a positive integer")
    router = APIRouter()

    @router.post("/internal/v1/executions", include_in_schema=False)
    async def accept_execution(request: Request) -> JSONResponse:
        request_id = str(uuid4())

        if manager_token is None or not manager_token.get_secret_value():
            # Fail closed when the required environment-injected secret is absent.
            # The exact outage mapping remains subject to owner review.
            return _error(
                request_id, 503, "DEPENDENCY_UNAVAILABLE",
                "Service temporarily unavailable.",
            )

        if max_request_body_bytes is None:
            return _error(
                request_id, 503, "DEPENDENCY_UNAVAILABLE",
                "Service temporarily unavailable.",
            )

        auth = request.headers.get("authorization", "")
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return _error(
                request_id, 401, "UNAUTHENTICATED", "Manager authentication is required.",
                bearer_challenge=True,
            )
        supplied_token = auth[len(prefix):]
        expected_token = manager_token.get_secret_value()
        if (not supplied_token or any(character.isspace() for character in supplied_token)
                or not hmac.compare_digest(
                    supplied_token.encode("utf-8"), expected_token.encode("utf-8")
                )):
            return _error(
                request_id, 401, "UNAUTHENTICATED", "Manager authentication is required.",
                bearer_challenge=True,
            )

        content_type = request.headers.get("content-type", "")
        media_type, *parameters = content_type.split(";")
        if media_type.strip().lower() != "application/json":
            return _error(request_id, 422, "VALIDATION_ERROR", "Invalid dispatch payload.")
        if any(parameter.strip().lower() not in {"charset=utf-8", 'charset="utf-8"'}
               for parameter in parameters):
            return _error(request_id, 422, "VALIDATION_ERROR", "Invalid dispatch payload.")

        try:
            raw_body = await _read_bounded_body(request, max_request_body_bytes)
            payload = json.loads(
                raw_body.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_json_constant,
            )
            dispatch = DispatchRequest.model_validate(payload, strict=True)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            DispatchBodyTooLarge,
            ValueError,
            ValidationError,
            RecursionError,
        ):
            return _error(request_id, 422, "VALIDATION_ERROR", "Invalid dispatch payload.")

        if admission is None or admission_executor is None:
            return _error(
                request_id, 503, "DEPENDENCY_UNAVAILABLE",
                "Service temporarily unavailable.",
            )

        try:
            outcome = await admission_executor.run(admission.admit, dispatch)
        except AttemptAdmissionConflict:
            return _error(
                request_id, 409, "EXECUTION_CONFLICT",
                "This attempt ID is already bound to another dispatch.",
            )
        except AttemptAdmissionUnavailable:
            return _error(
                request_id, 503, "DEPENDENCY_UNAVAILABLE",
                "Service temporarily unavailable.",
            )
        except Exception:  # fail closed without returning internal details
            logger.error("dispatch_admission_failed", extra={"request_id": request_id})
            return _error(
                request_id, 500, "INTERNAL_ERROR", "Internal server error."
            )

        if (not isinstance(outcome, AttemptAdmissionOutcome)
                or outcome.attempt_id != dispatch.attempt_id
                or not outcome.producer_registered):
            return _error(
                request_id, 503, "DEPENDENCY_UNAVAILABLE",
                "Service temporarily unavailable.",
            )

        accepted = DispatchAccepted(attempt_id=dispatch.attempt_id)
        return JSONResponse(
            status_code=202,
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
            content=accepted.model_dump(mode="json"),
        )

    return router
