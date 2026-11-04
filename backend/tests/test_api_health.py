from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings

JWT_SECRET = "api-health-tests-only-secret-32-bytes-minimum"


def settings() -> Settings:
    return Settings(_env_file=None, jwt_secret=JWT_SECRET)


def test_liveness_does_not_require_database() -> None:
    app = create_app(settings(), database_probe=lambda: False)

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_requires_database() -> None:
    app = create_app(settings(), database_probe=lambda: False)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "unavailable"},
    }


def test_readiness_reports_database_probe_success() -> None:
    app = create_app(settings(), database_probe=lambda: True, auth_schema_probe=lambda: True)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "components": {"database": "ok"}}


def test_readiness_fails_when_auth_schema_is_missing() -> None:
    app = create_app(settings(), database_probe=lambda: True, auth_schema_probe=lambda: False)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "ok", "auth_schema": "unavailable"},
    }


def test_unexpected_errors_do_not_expose_exception_details(capsys) -> None:
    app = create_app(settings(), database_probe=lambda: True)

    @app.get("/test-failure")
    def fail():
        raise RuntimeError("do-not-log-sensitive-details")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-failure")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "do-not-log-sensitive-details" not in capsys.readouterr().out
