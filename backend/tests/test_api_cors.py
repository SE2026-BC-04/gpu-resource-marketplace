from fastapi import Header
from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings


ALLOWED_ORIGIN = "http://localhost:5173"


def _client() -> TestClient:
    app = create_app(
        Settings(_env_file=None, cors_origins=[ALLOWED_ORIGIN]),
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

    return TestClient(app)


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
