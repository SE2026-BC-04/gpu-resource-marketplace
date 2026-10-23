from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from gpu_marketplace.jobs.errors import (
    DependencyUnavailable,
    Forbidden,
    IdempotencyKeyRequired,
    InvalidCursor,
    InvalidFilter,
    InvalidJson,
    JobErrorCode,
    JobNotFound,
    UnknownField,
    ValidationFailed,
    job_error_response,
    submit_request_from_json,
    submit_request_from_mapping,
    validate_idempotency_key,
)
from gpu_marketplace.jobs.cursor import HmacCursorCodec
from gpu_marketplace.jobs.models import (
    ClientJobResponse,
    FailureReason,
    JobRole,
    JobStatus,
    SubmitJobRequest,
)
from gpu_marketplace.jobs.ports import (
    CursorContext,
    CursorPosition,
    JobPage,
    JobRecord,
)
from gpu_marketplace.jobs.projections import project_job
from gpu_marketplace.jobs.router import _parse_job_id, _parse_limit, _request_id
from gpu_marketplace.jobs.service import JobsReadService


CLIENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WORKER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
LISTING_ID = UUID("22222222-2222-4222-8222-222222222222")
JOB_ID = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 10, 24, 8, 30, 0, 123456, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str


def make_record(**overrides: object) -> JobRecord:
    fields: dict[str, object] = {
        "id": JOB_ID,
        "client_id": CLIENT_ID,
        "worker_id": WORKER_ID,
        "listing_id": LISTING_ID,
        "requested_gpu_count": 2,
        "duration_seconds": 60,
        "status": JobStatus.QUEUED,
        "failure_reason": None,
        "submitted_at": NOW,
        "started_at": None,
        "terminal_at": None,
    }
    fields.update(overrides)
    return JobRecord(**fields)  # type: ignore[arg-type]


def test_submit_request_accepts_only_wire_fields_and_strict_positive_integers() -> None:
    request = submit_request_from_json(
        b'{"listing_id":"22222222-2222-4222-8222-222222222222",'
        b'"gpu_count":2,"duration_seconds":60}'
    )
    assert request == SubmitJobRequest(
        listing_id=LISTING_ID,
        gpu_count=2,
        duration_seconds=60,
    )

    for invalid in (
        {"listing_id": str(LISTING_ID), "gpu_count": True, "duration_seconds": 60},
        {"listing_id": str(LISTING_ID), "gpu_count": 2.0, "duration_seconds": 60},
        {"listing_id": str(LISTING_ID), "gpu_count": "2", "duration_seconds": 60},
        {"listing_id": str(LISTING_ID), "gpu_count": 0, "duration_seconds": 60},
        {"listing_id": str(LISTING_ID), "gpu_count": 2, "duration_seconds": 2**31},
    ):
        with pytest.raises(ValidationFailed):
            submit_request_from_mapping(invalid)


@pytest.mark.parametrize(
    "field",
    [
        "client_id",
        "worker_id",
        "status",
        "failure_reason",
        "started_at",
        "terminal_at",
        "enqueue_seq",
        "idempotency_key",
        "request_sha256",
        "simulation_reference",
        "seed_value",
        "expected_digest",
        "algorithm_version",
    ],
)
def test_submit_request_rejects_server_owned_and_oracle_fields(field: str) -> None:
    payload = {
        "listing_id": str(LISTING_ID),
        "gpu_count": 2,
        "duration_seconds": 60,
        field: "injected",
    }
    with pytest.raises(UnknownField):
        submit_request_from_mapping(payload)


def test_submit_request_maps_malformed_json_to_bad_request_domain_error() -> None:
    with pytest.raises(InvalidJson):
        submit_request_from_json(b'{"listing_id":')


def test_submit_request_requires_uuid_v4_listing_id() -> None:
    with pytest.raises(ValidationFailed):
        submit_request_from_json(
            b'{"listing_id":"22222222-2222-1222-8222-222222222222",'
            b'"gpu_count":2,"duration_seconds":60}'
        )


def test_idempotency_key_validation_is_ascii_and_length_bounded() -> None:
    assert validate_idempotency_key("retry-01") == "retry-01"
    with pytest.raises(IdempotencyKeyRequired):
        validate_idempotency_key(None)
    with pytest.raises(IdempotencyKeyRequired):
        validate_idempotency_key("")
    for invalid in ("short", "x" * 129, "unicode-é", "line\nbreak"):
        with pytest.raises(ValidationFailed):
            validate_idempotency_key(invalid)


def test_pydantic_model_directly_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SubmitJobRequest.model_validate(
            {
                "listing_id": str(LISTING_ID),
                "gpu_count": 1,
                "duration_seconds": 5,
                "client_id": str(CLIENT_ID),
            }
        )


def test_response_public_ids_must_be_uuid_v4() -> None:
    with pytest.raises(ValidationError):
        ClientJobResponse(
            id=UUID("33333333-3333-1333-8333-333333333333"),
            listing_id=LISTING_ID,
            worker_id=WORKER_ID,
            gpu_count=1,
            duration_seconds=5,
            status=JobStatus.QUEUED,
            failure_reason=None,
            submitted_at=NOW,
            started_at=None,
            terminal_at=None,
        )


def test_projection_exposes_worker_id_only_to_job_owner_client() -> None:
    record = make_record()
    client_view = project_job(record, principal=Principal(CLIENT_ID, "CLIENT"))
    worker_view = project_job(record, principal=Principal(WORKER_ID, "WORKER"))
    admin_view = project_job(record, principal=Principal(CLIENT_ID, "ADMIN"))

    assert isinstance(client_view, ClientJobResponse)
    assert client_view.worker_id == WORKER_ID
    assert not hasattr(client_view, "client_id")
    assert not hasattr(client_view, "simulation_reference")
    assert "seed_value" not in client_view.model_dump()
    assert "expected_digest" not in client_view.model_dump()
    assert not hasattr(worker_view, "worker_id")
    assert not hasattr(worker_view, "client_id")
    assert not hasattr(admin_view, "client_id")
    assert "worker_id" not in worker_view.model_dump()
    with pytest.raises(JobNotFound):
        project_job(
            record,
            principal=Principal(
                UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"), "CLIENT"
            ),
        )


def test_response_formats_utc_microseconds_and_failure_reason_consistently() -> None:
    response = project_job(make_record(), principal=Principal(CLIENT_ID, "CLIENT"))
    payload = response.model_dump(mode="json")
    assert payload["submitted_at"] == "2026-10-24T08:30:00.123456Z"

    failed = project_job(
        make_record(status=JobStatus.FAILED, failure_reason=FailureReason.JOB_FAULT),
        principal=Principal(CLIENT_ID, "CLIENT"),
    )
    assert failed.failure_reason is FailureReason.JOB_FAULT

    with pytest.raises(ValidationError):
        ClientJobResponse(
            id=JOB_ID,
            listing_id=LISTING_ID,
            worker_id=WORKER_ID,
            gpu_count=1,
            duration_seconds=5,
            status=JobStatus.FAILED,
            failure_reason=None,
            submitted_at=NOW,
            started_at=None,
            terminal_at=NOW,
        )


class FakeReader:
    def __init__(self, *, page: JobPage | None = None, record: JobRecord | None = None) -> None:
        self.page = page or JobPage(items=(), next_position=None)
        self.record = record
        self.list_calls: list[dict[str, object]] = []

    def list_visible(self, **kwargs: object) -> JobPage:
        self.list_calls.append(kwargs)
        return self.page

    def get_visible(self, **_: object) -> JobRecord | None:
        return self.record


class FakeCursorCodec:
    def __init__(self) -> None:
        self.decoded: list[tuple[str, CursorContext]] = []
        self.encoded: list[tuple[CursorPosition, CursorContext]] = []

    def decode(self, token: str, *, context: CursorContext) -> CursorPosition:
        self.decoded.append((token, context))
        if token != self._token(context):
            raise ValueError("invalid or context-mismatched cursor")
        return CursorPosition(submitted_at=NOW, job_id=JOB_ID)

    def encode(self, position: CursorPosition, *, context: CursorContext) -> str:
        self.encoded.append((position, context))
        return self._token(context)

    @staticmethod
    def _token(context: CursorContext) -> str:
        status = context.status.value if context.status is not None else "none"
        return f"cursor:{context.user_id}:{context.role.value}:{context.scope}:{status}"


def test_pagination_uses_role_default_and_context_binds_cursor() -> None:
    position = CursorPosition(submitted_at=NOW, job_id=JOB_ID)
    reader = FakeReader(page=JobPage(items=(make_record(),), next_position=position))
    codec = FakeCursorCodec()
    service = JobsReadService(reader=reader, cursor_codec=codec)

    first = service.list_jobs(
        principal=Principal(CLIENT_ID, "CLIENT"), status="QUEUED", limit=20
    )
    second = service.list_jobs(
        principal=Principal(CLIENT_ID, "CLIENT"),
        status="QUEUED",
        limit=10,
        cursor=first.next_cursor,
    )

    assert first.next_cursor is not None
    assert second.next_cursor == first.next_cursor
    assert codec.decoded[0][1] == CursorContext(CLIENT_ID, JobRole.CLIENT, "mine", JobStatus.QUEUED)
    assert reader.list_calls[0]["principal"].role == "CLIENT"
    assert reader.list_calls[1]["after"] == position
    assert codec.encoded[0][1].scope == "mine"
    with pytest.raises(InvalidCursor):
        service.list_jobs(
            principal=Principal(CLIENT_ID, "CLIENT"),
            status="FAILED",
            cursor=first.next_cursor,
        )


def test_hmac_cursor_codec_round_trip_tamper_and_context_binding() -> None:
    # Public test-only key. Never use a production signing key in tests.
    codec = HmacCursorCodec(b"test-only-cursor-key-0123456789abcdef")
    context = CursorContext(CLIENT_ID, JobRole.CLIENT, "mine", JobStatus.QUEUED)
    position = CursorPosition(submitted_at=NOW, job_id=JOB_ID)
    token = codec.encode(position, context=context)

    assert codec.decode(token, context=context) == position
    payload_part = token.split(".", maxsplit=1)[0]
    decoded_payload = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
    assert str(CLIENT_ID).encode() not in decoded_payload
    assert b'"role"' not in decoded_payload
    assert b'"scope"' not in decoded_payload
    assert b'"status"' not in decoded_payload
    with pytest.raises(ValueError):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"), context=context)
    with pytest.raises(ValueError):
        codec.decode(
            token,
            context=CursorContext(CLIENT_ID, JobRole.CLIENT, "mine", JobStatus.FAILED),
        )
    with pytest.raises(ValueError):
        HmacCursorCodec(b"short")


@pytest.mark.parametrize(
    ("role", "scope"),
    [("CLIENT", "all"), ("WORKER", "mine"), ("ADMIN", "assigned")],
)
def test_scope_escalation_is_forbidden(role: str, scope: str) -> None:
    service = JobsReadService(reader=FakeReader(), cursor_codec=FakeCursorCodec())
    with pytest.raises(Forbidden):
        service.list_jobs(principal=Principal(CLIENT_ID, role), scope=scope)


def test_unknown_scope_is_forbidden_per_jobs_contract() -> None:
    service = JobsReadService(reader=FakeReader(), cursor_codec=FakeCursorCodec())
    with pytest.raises(Forbidden):
        service.list_jobs(principal=Principal(CLIENT_ID, "CLIENT"), scope="other")


def test_invalid_status_cursor_and_limits_have_stable_domain_errors() -> None:
    service = JobsReadService(reader=FakeReader(), cursor_codec=FakeCursorCodec())
    with pytest.raises(InvalidFilter):
        service.list_jobs(principal=Principal(CLIENT_ID, "CLIENT"), status="OTHER")
    with pytest.raises(InvalidCursor):
        service.list_jobs(principal=Principal(CLIENT_ID, "CLIENT"), cursor="tampered")
    for limit in (0, 101, True):
        with pytest.raises(ValidationFailed):
            service.list_jobs(principal=Principal(CLIENT_ID, "CLIENT"), limit=limit)  # type: ignore[arg-type]
    with pytest.raises(JobNotFound):
        service.get_job(principal=Principal(CLIENT_ID, "CLIENT"), job_id=JOB_ID)


@pytest.mark.parametrize("raw,expected", [("20", 20), ("1", 1), ("100", 100)])
def test_router_limit_parser_accepts_contract_range(raw: str, expected: int) -> None:
    assert _parse_limit(raw) == expected


@pytest.mark.parametrize("raw", ["0", "101", "1.5", " 2", "٢"])
def test_router_limit_parser_rejects_invalid_input(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        _parse_limit(raw)


def test_router_job_id_parser_requires_canonical_uuid_v4() -> None:
    assert _parse_job_id(str(JOB_ID)) == JOB_ID
    for invalid in (
        "33333333-3333-1333-8333-333333333333",
        "33333333333343338333333333333333",
        "not-a-uuid",
    ):
        with pytest.raises(ValueError):
            _parse_job_id(invalid)


def test_request_id_ignores_caller_supplied_header(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    server_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    monkeypatch.setattr("gpu_marketplace.jobs.router.uuid4", lambda: UUID(server_id))
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/jobs",
            "raw_path": b"/api/v1/jobs",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"x-request-id", b"attacker-chosen")],
            "client": ("test", 1),
            "server": ("test", 80),
            "state": {},
        }
    )
    assert _request_id(request) == server_id


def test_http_error_adapter_uses_contract_envelope_without_internal_details() -> None:
    request_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    response = job_error_response(InvalidCursor(), request_id=request_id)
    body = json.loads(response.body)
    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["Cache-Control"] == "no-store"
    assert body == {
        "error": {
            "code": JobErrorCode.INVALID_CURSOR.value,
            "message": "The pagination cursor is invalid.",
            "request_id": request_id,
        }
    }
    assert "secret" not in response.body.decode().lower()


def test_dependency_error_maps_to_service_unavailable() -> None:
    response = job_error_response(
        DependencyUnavailable(), request_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    )
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
