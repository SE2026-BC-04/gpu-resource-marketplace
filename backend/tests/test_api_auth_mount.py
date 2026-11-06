import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from gpu_marketplace.api.app import create_app
from gpu_marketplace.common.config import Settings

JWT_SECRET = "api-mount-tests-only-secret-at-least-32-bytes"
LISTING_CURSOR_SECRET = "api-mount-tests-listing-cursor-secret-32-bytes"


def app_settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=JWT_SECRET,
        listing_cursor_secret=LISTING_CURSOR_SECRET,
    )


def test_create_app_mounts_auth_and_returns_private_bearer_401() -> None:
    app = create_app(app_settings(), database_probe=lambda: True)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"X-Request-ID": "client-supplied-value"},
        )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4
    assert request_id != "client-supplied-value"
    assert response.json()["error"]["request_id"] == request_id


def test_create_app_fails_closed_without_jwt_secret() -> None:
    with pytest.raises(ValueError, match="GPU_MARKETPLACE_JWT_SECRET"):
        create_app(Settings(_env_file=None), database_probe=lambda: True)


def test_create_app_fails_closed_without_listing_cursor_secret() -> None:
    with pytest.raises(ValueError, match="GPU_MARKETPLACE_LISTING_CURSOR_SECRET"):
        create_app(
            Settings(_env_file=None, jwt_secret=JWT_SECRET),
            database_probe=lambda: True,
        )


def test_unexpected_auth_error_keeps_private_headers_and_contract_envelope(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(app_settings(), database_probe=lambda: True)

    def fail_closed(_: str) -> None:
        raise RuntimeError("jwt-secret-sentinel-do-not-return-or-log")

    monkeypatch.setattr(app.state.auth_service, "current_identity", fail_closed)
    with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": "Bearer opaque-test-token",
                "X-Request-ID": "client-supplied-value",
                "Origin": "http://localhost:5173",
            },
        )

    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    exposed = response.headers["ACCESS-CONTROL-EXPOSE-HEADERS"].lower()
    assert exposed == "x-request-id"
    assert "authorization" not in exposed
    assert response.headers["Vary"] == "Origin"
    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4 and request_id != "client-supplied-value"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error.",
            "request_id": request_id,
        }
    }
    secret = "jwt-secret-sentinel-do-not-return-or-log"
    assert secret not in response.text
    assert secret not in caplog.text
    assert "opaque-test-token" not in response.text
    assert secret not in str(response.headers)


def test_unexpected_auth_error_does_not_reflect_disallowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(app_settings(), database_probe=lambda: True)

    def fail_closed(_: str) -> None:
        raise RuntimeError("test-only-failure")

    monkeypatch.setattr(app.state.auth_service, "current_identity", fail_closed)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer opaque-test-token", "Origin": "https://evil.example"},
        )

    assert response.status_code == 500
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Expose-Headers" not in response.headers
