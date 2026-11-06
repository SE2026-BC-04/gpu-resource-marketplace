from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity_fakes import C1, SECRET, build_service
from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.jobs.cursor import HmacCursorCodec
from gpu_marketplace.jobs.cancel_ports import CommitOutcomeUnknown
from gpu_marketplace.jobs.models import ClientJobResponse, JobStatus
from gpu_marketplace.jobs.ports import JobPage, JobRecord
from gpu_marketplace.jobs.router import create_jobs_router
from gpu_marketplace.jobs.service import JobsReadService
from gpu_marketplace.jobs.submit_ports import SubmissionResult


class SpyJobReader:
    def __init__(self) -> None:
        self.list_calls: list[object] = []
        self.get_calls: list[object] = []

    def list_visible(self, **kwargs: object) -> JobPage:
        self.list_calls.append(kwargs.get("principal"))
        return JobPage(items=(), next_position=None)

    def get_visible(self, **kwargs: object) -> None:
        self.get_calls.append(kwargs.get("principal"))
        return None


class SpyCancelService:
    def __init__(self, *, unknown_commit: bool = False) -> None:
        self.calls: list[tuple[object, UUID]] = []
        self.unknown_commit = unknown_commit

    def cancel(self, *, principal: object, job_id: UUID) -> ClientJobResponse:
        self.calls.append((principal, job_id))
        if self.unknown_commit:
            raise CommitOutcomeUnknown()
        now = datetime.now(timezone.utc)
        return ClientJobResponse(
            id=job_id,
            listing_id=UUID("22222222-2222-4222-8222-222222222222"),
            worker_id=UUID("11111111-1111-4111-8111-111111111111"),
            gpu_count=1,
            duration_seconds=60,
            status=JobStatus.CANCELLED,
            failure_reason=None,
            submitted_at=now,
            started_at=None,
            terminal_at=now,
        )


class SpySubmitService:
    def __init__(self, *, replayed: bool = False, failure: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.replayed = replayed
        self.failure = failure

    def submit(self, **kwargs: object) -> SubmissionResult:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        now = datetime.now(timezone.utc)
        return SubmissionResult(
            job=JobRecord(
                id=UUID("33333333-3333-4333-8333-333333333333"),
                client_id=C1,
                worker_id=UUID("11111111-1111-4111-8111-111111111111"),
                listing_id=UUID("22222222-2222-4222-8222-222222222222"),
                requested_gpu_count=2,
                duration_seconds=60,
                status=JobStatus.QUEUED,
                failure_reason=None,
                submitted_at=now,
                started_at=None,
                terminal_at=None,
            ),
            replayed=self.replayed,
        )


def make_auth_jobs_client(
    *, account_store_unavailable: bool = False, submit_service: SpySubmitService | None = None
):
    auth_service, account_reader, clock, _ = build_service()
    token = AccessTokenCodec(SECRET, clock=clock).issue(C1).token
    account_reader.unavailable = account_store_unavailable

    job_reader = SpyJobReader()
    jobs_service = JobsReadService(
        reader=job_reader,
        cursor_codec=HmacCursorCodec(b"test-only-jobs-cursor-key-0123456789"),
    )
    app = FastAPI()
    app.include_router(
        create_jobs_router(
            service=jobs_service,
            submit_service=submit_service,  # type: ignore[arg-type]
            principal_provider=create_principal_dependency(auth_service),
        )
    )
    return TestClient(app), token, job_reader


def assert_private_headers(response, supplied_request_id: str) -> str:
    request_id = response.headers["X-Request-ID"]
    parsed = UUID(request_id)
    assert parsed.version == 4
    assert str(parsed) == request_id
    assert request_id != supplied_request_id
    assert response.headers["Cache-Control"] == "no-store"
    return request_id


def assert_auth_error(response, *, status: int, code: str, request_id: str) -> None:
    message = {
        "UNAUTHENTICATED": "Authentication is required.",
        "DEPENDENCY_UNAVAILABLE": "A required dependency is unavailable.",
    }[code]
    assert response.status_code == status
    assert response.json() == {
        "error": {"code": code, "message": message, "request_id": request_id}
    }


def test_jobs_http_accepts_valid_client_through_real_auth_dependency() -> None:
    client, token, job_reader = make_auth_jobs_client()
    supplied_request_id = "caller-controlled-request-id"

    response = client.get(
        "/api/v1/jobs",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": supplied_request_id,
        },
    )

    assert response.status_code == 200
    assert_private_headers(response, supplied_request_id)
    assert response.json() == {"items": [], "next_cursor": None}
    assert len(job_reader.list_calls) == 1
    principal = job_reader.list_calls[0]
    assert isinstance(principal, AuthenticatedPrincipal)
    assert principal.user_id == C1
    assert principal.role == "CLIENT"
    assert job_reader.get_calls == []


def test_jobs_http_missing_and_invalid_tokens_return_401_before_job_reader() -> None:
    client, _, job_reader = make_auth_jobs_client()
    supplied_request_id = "caller-controlled-request-id"
    requests = (
        {"X-Request-ID": supplied_request_id},
        {
            "Authorization": "Bearer invalid-test-token",
            "X-Request-ID": supplied_request_id,
        },
    )

    for headers in requests:
        response = client.get("/api/v1/jobs", headers=headers)
        request_id = assert_private_headers(response, supplied_request_id)
        assert_auth_error(
            response,
            status=401,
            code="UNAUTHENTICATED",
            request_id=request_id,
        )
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert "invalid-test-token" not in response.text

    assert job_reader.list_calls == []
    assert job_reader.get_calls == []


def test_jobs_http_unavailable_account_store_returns_503_before_job_reader() -> None:
    client, token, job_reader = make_auth_jobs_client(account_store_unavailable=True)
    supplied_request_id = "caller-controlled-request-id"

    response = client.get(
        "/api/v1/jobs",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": supplied_request_id,
        },
    )
    request_id = assert_private_headers(response, supplied_request_id)

    assert_auth_error(
        response,
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        request_id=request_id,
    )
    assert "database unavailable" not in response.text
    assert job_reader.list_calls == []
    assert job_reader.get_calls == []


def test_jobs_http_cancel_uses_authenticated_principal_and_private_headers() -> None:
    auth_service, _account_reader, clock, _ = build_service()
    token = AccessTokenCodec(SECRET, clock=clock).issue(C1).token
    cancellation = SpyCancelService()
    router = create_jobs_router(
        service=JobsReadService(
            reader=SpyJobReader(),
            cursor_codec=HmacCursorCodec(b"test-only-jobs-cursor-key-0123456789"),
        ),
        cancel_service=cancellation,  # type: ignore[arg-type]
        principal_provider=create_principal_dependency(auth_service),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    job_id = UUID("33333333-3333-4333-8333-333333333333")
    response = client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "client-value"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(job_id)
    assert response.json()["status"] == "CANCELLED"
    assert_private_headers(response, "client-value")
    assert len(cancellation.calls) == 1
    principal, called_job = cancellation.calls[0]
    assert isinstance(principal, AuthenticatedPrincipal)
    assert principal.user_id == C1
    assert called_job == job_id


def test_jobs_http_unknown_cancel_commit_returns_503_without_retry() -> None:
    auth_service, _account_reader, clock, _ = build_service()
    token = AccessTokenCodec(SECRET, clock=clock).issue(C1).token
    cancellation = SpyCancelService(unknown_commit=True)
    router = create_jobs_router(
        service=JobsReadService(
            reader=SpyJobReader(),
            cursor_codec=HmacCursorCodec(b"test-only-jobs-cursor-key-0123456789"),
        ),
        cancel_service=cancellation,  # type: ignore[arg-type]
        principal_provider=create_principal_dependency(auth_service),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post(
        "/api/v1/jobs/33333333-3333-4333-8333-333333333333/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert len(cancellation.calls) == 1


@pytest.mark.parametrize(("replayed", "expected_status"), [(False, 201), (True, 200)])
def test_jobs_http_submit_uses_shared_authenticated_principal_and_idempotency(
    replayed: bool, expected_status: int
) -> None:
    submitter = SpySubmitService(replayed=replayed)
    client, token, _job_reader = make_auth_jobs_client(submit_service=submitter)
    response = client.post(
        "/api/v1/jobs",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "client-request-0001",
            "X-Request-ID": "caller-controlled-request-id",
        },
        json={
            "listing_id": "22222222-2222-4222-8222-222222222222",
            "gpu_count": 2,
            "duration_seconds": 60,
        },
    )

    assert response.status_code == expected_status
    assert response.headers["Location"] == "/api/v1/jobs/33333333-3333-4333-8333-333333333333"
    assert_private_headers(response, "caller-controlled-request-id")
    payload = response.json()
    assert payload["status"] == "QUEUED"
    assert payload["worker_id"] == "11111111-1111-4111-8111-111111111111"
    assert "simulation_reference" not in payload
    assert len(submitter.calls) == 1
    call = submitter.calls[0]
    assert call["idempotency_key"] == "client-request-0001"
    assert isinstance(call["principal"], AuthenticatedPrincipal)
    assert call["principal"].user_id == C1  # type: ignore[union-attr]


def test_jobs_http_submit_requires_idempotency_key_before_body_or_store() -> None:
    submitter = SpySubmitService()
    client, token, _job_reader = make_auth_jobs_client(submit_service=submitter)
    response = client.post(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "listing_id": "22222222-2222-4222-8222-222222222222",
            "gpu_count": 2,
            "duration_seconds": 60,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert_private_headers(response, "")
    assert submitter.calls == []


def test_jobs_http_unexpected_submit_failure_is_sanitized() -> None:
    secret = "sql-dsn-secret-sentinel"
    submitter = SpySubmitService(failure=RuntimeError(secret))
    client, token, _job_reader = make_auth_jobs_client(submit_service=submitter)
    response = client.post(
        "/api/v1/jobs",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "client-request-0001",
        },
        json={
            "listing_id": "22222222-2222-4222-8222-222222222222",
            "gpu_count": 2,
            "duration_seconds": 60,
        },
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert secret not in response.text
