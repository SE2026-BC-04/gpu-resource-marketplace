from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import anyio
import pytest
from fastapi import FastAPI
from fastapi import HTTPException, Request
from fastapi import routing as fastapi_routing
from httpx import ASGITransport, AsyncClient
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
    Unauthenticated,
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
from gpu_marketplace.jobs.router import (
    _parse_job_id,
    _parse_limit,
    _request_id,
    create_jobs_router,
)
from gpu_marketplace.jobs.service import JobsReadService


CLIENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WORKER_USER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
WORKER_PROFILE_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_WORKER_USER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
OTHER_WORKER_PROFILE_ID = UUID("22222222-2222-4222-8222-222222222223")
ADMIN_ID = UUID("99999999-9999-4999-8999-999999999999")
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
        "worker_id": WORKER_PROFILE_ID,
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


def test_submit_request_mapping_accepts_canonical_uuid4_string() -> None:
    request = submit_request_from_mapping(
        {
            "listing_id": str(LISTING_ID),
            "gpu_count": 2,
            "duration_seconds": 60,
        }
    )
    assert request.listing_id == LISTING_ID


@pytest.mark.parametrize("field", ["gpu_count", "duration_seconds"])
@pytest.mark.parametrize("invalid_value", [True, 2.0, "2"])
def test_submit_request_helpers_reject_non_integer_json_values(
    field: str, invalid_value: object
) -> None:
    mapping_payload: dict[str, object] = {
        "listing_id": str(LISTING_ID),
        "gpu_count": 2,
        "duration_seconds": 60,
    }
    mapping_payload[field] = invalid_value
    with pytest.raises(ValidationFailed):
        submit_request_from_mapping(mapping_payload)

    json_payload = {
        "listing_id": str(LISTING_ID),
        "gpu_count": 2,
        "duration_seconds": 60,
    }
    json_payload[field] = invalid_value
    with pytest.raises(ValidationFailed):
        submit_request_from_json(json.dumps(json_payload))


@pytest.mark.parametrize(
    "listing_id",
    [
        "22222222-2222-1222-8222-222222222222",  # UUIDv1
        "22222222222242228222222222222222",  # no hyphens
        "abcdefab-cdef-4abc-8def-abcdefabcdef".upper(),
        "not-a-uuid",
    ],
)
@pytest.mark.parametrize("decoder_name", ["mapping", "json"])
def test_submit_request_helpers_reject_noncanonical_listing_uuid(
    listing_id: str, decoder_name: str
) -> None:
    mapping_payload = {
        "listing_id": listing_id,
        "gpu_count": 2,
        "duration_seconds": 60,
    }
    with pytest.raises(ValidationFailed):
        if decoder_name == "mapping":
            submit_request_from_mapping(mapping_payload)
        else:
            submit_request_from_json(json.dumps(mapping_payload))


@pytest.mark.parametrize("decoder_name", ["mapping", "json"])
def test_submit_request_helpers_forbid_extra_fields(decoder_name: str) -> None:
    payload = {
        "listing_id": str(LISTING_ID),
        "gpu_count": 2,
        "duration_seconds": 60,
        "worker_id": str(WORKER_PROFILE_ID),
    }
    with pytest.raises(UnknownField):
        if decoder_name == "mapping":
            submit_request_from_mapping(payload)
        else:
            submit_request_from_json(json.dumps(payload))


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
            worker_id=WORKER_PROFILE_ID,
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
    worker_view = project_job(record, principal=Principal(WORKER_USER_ID, "WORKER"))
    admin_view = project_job(record, principal=Principal(CLIENT_ID, "ADMIN"))

    assert isinstance(client_view, ClientJobResponse)
    assert client_view.worker_id == WORKER_PROFILE_ID
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
            worker_id=WORKER_PROFILE_ID,
            gpu_count=1,
            duration_seconds=5,
            status=JobStatus.FAILED,
            failure_reason=None,
            submitted_at=NOW,
            started_at=None,
            terminal_at=NOW,
        )


class FakeReader:
    def __init__(
        self,
        *,
        page: JobPage | None = None,
        record: JobRecord | None = None,
        worker_user_by_profile: dict[UUID, UUID] | None = None,
    ) -> None:
        self.page = page or JobPage(items=(), next_position=None)
        self.record = record
        # Mirrors workers.id -> workers.user_id; Job.worker_id references the
        # profile UUID, while an AuthenticatedPrincipal carries the user UUID.
        self.worker_user_by_profile = worker_user_by_profile or {
            WORKER_PROFILE_ID: WORKER_USER_ID,
            OTHER_WORKER_PROFILE_ID: OTHER_WORKER_USER_ID,
        }
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def list_visible(self, **kwargs: object) -> JobPage:
        self.list_calls.append(kwargs)
        principal = kwargs["principal"]
        visible_items = tuple(
            record for record in self.page.items if self._visible(record, principal)
        )
        return JobPage(items=visible_items, next_position=self.page.next_position)

    def get_visible(self, **kwargs: object) -> JobRecord | None:
        self.get_calls.append(kwargs)
        if (
            self.record is None
            or self.record.id != kwargs["job_id"]
            or not self._visible(self.record, kwargs["principal"])
        ):
            return None
        return self.record

    def _visible(self, record: JobRecord, principal: object) -> bool:
        role = JobRole(getattr(principal, "role"))
        user_id = getattr(principal, "user_id")
        if role is JobRole.CLIENT:
            return record.client_id == user_id
        if role is JobRole.WORKER:
            return self.worker_user_by_profile.get(record.worker_id) == user_id
        return role is JobRole.ADMIN


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


def make_test_app(
    *,
    role: str = "CLIENT",
    record: JobRecord | None = None,
    principal_provider=None,
    next_position: CursorPosition | None = None,
) -> FastAPI:
    principal_id = {
        "CLIENT": CLIENT_ID,
        "WORKER": WORKER_USER_ID,
        "ADMIN": ADMIN_ID,
    }[role]
    principal = Principal(principal_id, role)
    reader = FakeReader(
        page=JobPage(
            items=(record,) if record is not None else (),
            next_position=next_position,
        ),
        record=record,
    )
    service = JobsReadService(
        reader=reader,
        cursor_codec=HmacCursorCodec(b"test-only-jobs-cursor-key-0123456789"),
    )
    app = FastAPI()
    if principal_provider is None:
        async def principal_provider():
            return principal

    app.include_router(
        create_jobs_router(service=service, principal_provider=principal_provider)
    )
    app.state.test_reader = reader
    return app


def http_get(
    app: FastAPI,
    path: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str] | None = None,
    raise_app_exceptions: bool = True,
):
    async def run_sync_inline(target, *args, **kwargs):
        # This sandbox's AnyIO worker portal deadlocks for all sync FastAPI
        # endpoints. Keep the test's synchronous fake service inline while
        # exercising the actual ASGI router and serialization path.
        return target(*args, **kwargs)

    monkeypatch.setattr(fastapi_routing, "run_in_threadpool", run_sync_inline)

    async def send_request():
        async with AsyncClient(
            transport=ASGITransport(
                app=app, raise_app_exceptions=raise_app_exceptions
            ),
            base_url="http://jobs.test",
        ) as client:
            return await client.get(path, headers=headers)

    return anyio.run(send_request)


def assert_server_request_headers(response: object, supplied_request_id: str) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    parsed_request_id = UUID(headers["X-Request-ID"])
    assert parsed_request_id.version == 4
    assert str(parsed_request_id) == headers["X-Request-ID"]
    assert headers["X-Request-ID"] != supplied_request_id
    assert headers["Cache-Control"] == "no-store"


def test_router_list_asgi_returns_safe_client_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_test_app(record=make_record())
    supplied_id = "caller-chosen-request-id"
    response = http_get(
        app, "/api/v1/jobs", monkeypatch=monkeypatch, headers={"X-Request-ID": supplied_id}
    )

    assert response.status_code == 200
    assert_server_request_headers(response, supplied_id)
    payload = response.json()
    assert payload["items"][0]["worker_id"] == str(WORKER_PROFILE_ID)
    assert not {"client_id", "seed_value", "expected_digest"}.intersection(
        payload["items"][0]
    )


def test_router_detail_asgi_serializes_client_worker_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_test_app(record=make_record())
    supplied_id = "caller-chosen-request-id"
    response = http_get(
        app,
        f"/api/v1/jobs/{JOB_ID}",
        monkeypatch=monkeypatch,
        headers={"X-Request-ID": supplied_id},
    )

    assert response.status_code == 200
    assert_server_request_headers(response, supplied_id)
    payload = response.json()
    assert payload["worker_id"] == str(WORKER_PROFILE_ID)
    assert not {"client_id", "seed_value", "expected_digest"}.intersection(payload)


def test_router_detail_returns_404_when_visible_record_id_differs_from_requested_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_test_app(record=make_record())
    requested_id = UUID("33333333-3333-4333-8333-333333333334")

    response = http_get(
        app,
        f"/api/v1/jobs/{requested_id}",
        monkeypatch=monkeypatch,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert response.headers["Cache-Control"] == "no-store"
    assert app.state.test_reader.get_calls[-1]["job_id"] == requested_id


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/v1/jobs?limit=0", 422),
        ("/api/v1/jobs?cursor=invalid", 400),
        ("/api/v1/jobs?scope=all", 403),
        ("/api/v1/jobs/33333333-3333-4333-8333-333333333334", 404),
    ],
)
def test_router_asgi_maps_read_errors(
    path: str, expected_status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_test_app(record=None)
    supplied_id = "caller-chosen-request-id"
    response = http_get(
        app, path, monkeypatch=monkeypatch, headers={"X-Request-ID": supplied_id}
    )

    assert response.status_code == expected_status
    assert_server_request_headers(response, supplied_id)


def test_router_asgi_maps_invalid_cursor_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_test_app(record=make_record())
    response = http_get(app, "/api/v1/jobs?cursor=invalid", monkeypatch=monkeypatch)
    assert response.status_code == 400
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("failure", ["missing", "invalid", "expired", "domain"])
def test_dependency_auth_failures_map_to_401_without_reader_access(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def principal_provider(request: Request):
        # Test double models missing, invalid, and expired bearer credentials;
        # production JWT validation remains owned by GPU-003.
        authorization = request.headers.get("authorization")
        assert authorization == {
            "missing": None,
            "invalid": "Bearer invalid-test-token",
            "expired": "Bearer expired-test-token",
            "domain": None,
        }[failure]
        raise Unauthenticated()

    app = make_test_app(principal_provider=principal_provider)
    headers = {
        "invalid": {"Authorization": "Bearer invalid-test-token"},
        "expired": {"Authorization": "Bearer expired-test-token"},
    }.get(failure, {}) | {"X-Request-ID": "caller-controlled-id"}
    response = http_get(
        app,
        "/api/v1/jobs",
        monkeypatch=monkeypatch,
        headers=headers,
    )

    assert response.status_code == 401
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    assert request_id != "caller-controlled-id"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "UNAUTHENTICATED",
            "message": "Authentication is required.",
            "request_id": request_id,
        }
    }
    assert "token" not in response.text.lower()
    assert app.state.test_reader.list_calls == []
    assert app.state.test_reader.get_calls == []


def test_http_auth_exceptions_are_mapped_and_internal_detail_is_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unauthorized_provider():
        raise HTTPException(
            status_code=401,
            detail="private token verifier detail",
            headers={"www-authenticate": "Bearer"},
        )

    app = make_test_app(principal_provider=unauthorized_provider)
    response = http_get(app, "/api/v1/jobs", monkeypatch=monkeypatch)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert "private token" not in response.text
    assert app.state.test_reader.list_calls == []


def test_dependency_403_maps_to_forbidden_not_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_provider():
        raise HTTPException(status_code=403, detail="private policy detail")

    app = make_test_app(principal_provider=forbidden_provider)
    response = http_get(app, "/api/v1/jobs", monkeypatch=monkeypatch)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert response.headers["Cache-Control"] == "no-store"
    assert "private policy" not in response.text
    assert app.state.test_reader.list_calls == []


def test_dependency_503_maps_to_dependency_unavailable_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable_provider():
        raise HTTPException(status_code=503, detail="private storage failure")

    app = make_test_app(principal_provider=unavailable_provider)
    response = http_get(
        app,
        "/api/v1/jobs",
        monkeypatch=monkeypatch,
        headers={"X-Request-ID": "caller-controlled-id"},
    )

    assert response.status_code == 503
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    assert request_id != "caller-controlled-id"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "DEPENDENCY_UNAVAILABLE",
            "message": "A required dependency is unavailable.",
            "request_id": request_id,
        }
    }
    assert "private storage failure" not in response.text
    assert app.state.test_reader.list_calls == []
    assert app.state.test_reader.get_calls == []


def test_unexpected_dependency_error_is_not_misclassified_as_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_provider():
        raise RuntimeError("private provider failure")

    app = make_test_app(principal_provider=broken_provider)
    response = http_get(
        app,
        "/api/v1/jobs",
        monkeypatch=monkeypatch,
        raise_app_exceptions=False,
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "private provider failure" not in response.text
    assert app.state.test_reader.list_calls == []


@pytest.mark.parametrize(
    ("role", "scope", "expected_worker", "expected_status"),
    [
        ("CLIENT", "mine", True, 200),
        ("WORKER", "assigned", False, 200),
        ("ADMIN", "all", False, 200),
    ],
)
def test_router_list_role_visibility_and_projection(
    role: str,
    scope: str,
    expected_worker: bool,
    expected_status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_test_app(role=role, record=make_record())
    response = http_get(
        app, f"/api/v1/jobs?scope={scope}", monkeypatch=monkeypatch
    )

    assert response.status_code == expected_status
    item = response.json()["items"][0]
    assert ("worker_id" in item) is expected_worker
    assert "client_id" not in item
    assert not {"seed_value", "expected_digest"}.intersection(item)


@pytest.mark.parametrize(
    ("role", "scope"),
    [("CLIENT", "assigned"), ("WORKER", "mine"), ("ADMIN", "mine")],
)
def test_router_rejects_cross_role_scope(
    role: str, scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_test_app(role=role, record=make_record())
    response = http_get(
        app, f"/api/v1/jobs?scope={scope}", monkeypatch=monkeypatch
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("role", "record_client", "record_worker", "expected_status"),
    [
        ("CLIENT", CLIENT_ID, WORKER_PROFILE_ID, 200),
        (
            "CLIENT",
            UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            WORKER_PROFILE_ID,
            404,
        ),
        ("WORKER", CLIENT_ID, WORKER_PROFILE_ID, 200),
        (
            "WORKER",
            CLIENT_ID,
            OTHER_WORKER_PROFILE_ID,
            404,
        ),
        ("ADMIN", CLIENT_ID, WORKER_PROFILE_ID, 200),
    ],
)
def test_router_detail_role_visibility(
    role: str,
    record_client: UUID,
    record_worker: UUID,
    expected_status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(client_id=record_client, worker_id=record_worker)
    app = make_test_app(role=role, record=record)
    response = http_get(
        app, f"/api/v1/jobs/{JOB_ID}", monkeypatch=monkeypatch
    )
    assert response.status_code == expected_status
    if expected_status == 200:
        payload = response.json()
        assert "client_id" not in payload
        assert not {"seed_value", "expected_digest"}.intersection(payload)


@pytest.mark.parametrize(
    ("principal_user_id", "expected_status"),
    [
        (WORKER_USER_ID, 200),
        (OTHER_WORKER_USER_ID, 404),
        (WORKER_PROFILE_ID, 404),
    ],
)
def test_worker_visibility_resolves_profile_to_account_identity(
    principal_user_id: UUID,
    expected_status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert WORKER_USER_ID != WORKER_PROFILE_ID

    async def principal_provider():
        return Principal(principal_user_id, "WORKER")

    app = make_test_app(
        role="WORKER",
        record=make_record(worker_id=WORKER_PROFILE_ID),
        principal_provider=principal_provider,
    )
    response = http_get(
        app, f"/api/v1/jobs/{JOB_ID}", monkeypatch=monkeypatch
    )
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["id"] == str(JOB_ID)
    else:
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


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


def test_server_cursor_encoding_failure_is_not_mapped_to_client_invalid_cursor() -> None:
    class FailingEncoder:
        def decode(self, token: str, *, context: CursorContext) -> CursorPosition:
            raise AssertionError("first-page request must not decode a client cursor")

        def encode(self, position: CursorPosition, *, context: CursorContext) -> str:
            raise ValueError("private server cursor serialization detail")

    position = CursorPosition(submitted_at=NOW, job_id=JOB_ID)
    service = JobsReadService(
        reader=FakeReader(page=JobPage(items=(), next_position=position)),
        cursor_codec=FailingEncoder(),
    )

    with pytest.raises(ValueError, match="private server cursor serialization detail"):
        service.list_jobs(principal=Principal(CLIENT_ID, "CLIENT"), cursor=None)


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
