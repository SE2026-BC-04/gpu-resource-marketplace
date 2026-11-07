from uuid import uuid4

from fastapi import Header
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings


ALLOWED_ORIGIN = "http://localhost:5173"
JWT_SECRET = "api-cors-tests-only-secret-32-bytes-minimum"
LISTING_CURSOR_SECRET = "api-cors-listing-cursor-key-at-least-32-bytes"
JOBS_CURSOR_SECRET = "api-cors-jobs-cursor-key-at-least-32-bytes"


def _client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = create_app(
        Settings(
            _env_file=None,
            cors_origins=[ALLOWED_ORIGIN],
            jwt_secret=JWT_SECRET,
            listing_cursor_secret=LISTING_CURSOR_SECRET,
            jobs_cursor_secret=JOBS_CURSOR_SECRET,
        ),
        database_probe=lambda: True,
    )

    # These test-only routes exercise browser headers without implementing
    # Authentication or Job Submission as part of the foundation.
    @app.get("/test/authenticated")
    def authenticated(authorization: str = Header()):
        return {"authorization": authorization}

    @app.post("/test/jobs")
    def submit_job(idempotency_key: str = Header(alias="Idempotency-Key")):
        return {"idempotency_key": idempotency_key}

    @app.get("/test/forbidden")
    def forbidden():
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "FORBIDDEN"}},
            headers={"X-Request-ID": str(uuid4())},
        )

    @app.get("/api/v1/auth/test-unexpected-error", include_in_schema=False)
    def unexpected_auth_error():
        raise RuntimeError("test-only exception detail")

    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _normalized_headers(response) -> dict[str, str]:
    return {name.lower(): value for name, value in response.headers.items()}


def test_allowed_origin_can_read_request_id_on_401_403_and_422() -> None:
    with _client() as client:
        responses = [
            client.get("/api/v1/auth/me", headers={"Origin": ALLOWED_ORIGIN}),
            client.get("/test/forbidden", headers={"Origin": ALLOWED_ORIGIN}),
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": ALLOWED_ORIGIN},
                json={"login_name": 42, "password": "test-only"},
            ),
        ]

    assert [response.status_code for response in responses] == [401, 403, 422]
    for response in responses:
        headers = _normalized_headers(response)
        assert headers["access-control-allow-origin"] == ALLOWED_ORIGIN
        assert headers["access-control-expose-headers"].lower() == "x-request-id"
        assert "x-request-id" in headers
        assert "authorization" not in headers["access-control-expose-headers"].lower()
        assert headers.get("vary", "").lower().split(", ").count("origin") == 1
        assert "access-control-allow-credentials" not in headers

    assert responses[0].headers["WWW-Authenticate"] == "Bearer"
    assert responses[0].headers["Cache-Control"] == "no-store"
    assert responses[2].json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_post_preflight_allows_contract_methods_and_content_type() -> None:
    with _client() as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    allowed_methods = response.headers["access-control-allow-methods"]
    assert all(method in allowed_methods for method in ("GET", "POST", "PATCH"))
    assert "DELETE" not in allowed_methods
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_authenticated_get_preflight_and_request_allow_authorization() -> None:
    with _client() as client:
        preflight = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization, x-request-id",
            },
        )
        response = client.get(
            "/test/authenticated",
            headers={"Origin": ALLOWED_ORIGIN, "Authorization": "Bearer test-token"},
        )

    assert preflight.status_code == 200
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert "x-request-id" in preflight.headers["access-control-allow-headers"].lower()
    assert response.status_code == 200
    assert response.json() == {"authorization": "Bearer test-token"}
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_job_submission_preflight_allows_idempotency_key() -> None:
    with _client() as client:
        preflight = client.options(
            "/api/v1/jobs",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type, idempotency-key",
            },
        )
        response = client.post(
            "/test/jobs",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Idempotency-Key": "smoke-submit-key-01",
            },
        )

    assert preflight.status_code == 200
    allowed_headers = preflight.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "idempotency-key" in allowed_headers
    assert response.status_code == 200
    assert response.json() == {"idempotency_key": "smoke-submit-key-01"}
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_preflight_rejects_origin_outside_the_configured_allowlist() -> None:
    with _client() as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers

    with _client() as client:
        response = client.get("/api/v1/auth/me", headers={"Origin": "https://untrusted.example"})

    headers = _normalized_headers(response)
    assert response.status_code == 401
    assert "access-control-allow-origin" not in headers
    assert "access-control-expose-headers" not in headers


def test_expose_header_lookup_is_case_insensitive() -> None:
    with _client() as client:
        response = client.get("/api/v1/auth/me", headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers.get("ACCESS-CONTROL-EXPOSE-HEADERS", "").lower() == "x-request-id"


def test_unexpected_auth_failure_keeps_cors_and_private_error_headers() -> None:
    with _client(raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/auth/test-unexpected-error",
            headers={"Origin": ALLOWED_ORIGIN},
        )

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    assert response.headers["Vary"] == "Origin"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert "test-only exception detail" not in response.text
