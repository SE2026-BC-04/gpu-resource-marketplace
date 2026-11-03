from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity_fakes import C1, SECRET, build_service
from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.jobs.cursor import HmacCursorCodec
from gpu_marketplace.jobs.ports import JobPage
from gpu_marketplace.jobs.router import create_jobs_router
from gpu_marketplace.jobs.service import JobsReadService


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


def make_auth_jobs_client(*, account_store_unavailable: bool = False):
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
