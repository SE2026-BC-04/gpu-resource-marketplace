import json
from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from identity_fakes import C1, NUL_PASSWORD, PASSWORD, T0_US, build_service
from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.router import TOKEN_REJECTED_CODE, create_auth_router


@pytest.fixture
def env():
    service, reader, clock, hasher = build_service()
    app = FastAPI()
    app.include_router(create_auth_router(service=service))
    principal = create_principal_dependency(service)

    # Stand-in for a GPU-004/GPU-005 route consuming the shared dependency.
    @app.get("/probe")
    def probe(p: AuthenticatedPrincipal = Depends(principal)) -> dict[str, str]:
        return {"user_id": str(p.user_id), "role": p.role, "status": p.status}

    return TestClient(app), reader, clock


def login(client: TestClient, body: object, raw: str | None = None):
    content = raw if raw is not None else json.dumps(body)
    return client.post("/api/v1/auth/login", content=content, headers={"Content-Type": "application/json"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_private(response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-ID"]).version == 4


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert_private(response)


def test_login_success_contract(env) -> None:
    client, *_ = env
    response = login(client, {"login_name": "  demo_client_01  ", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    assert body["user"] == {"id": str(C1), "login_name": "demo_client_01", "role": "CLIENT"}
    assert "password" not in response.text and "scrypt$" not in response.text
    assert_private(response)


@pytest.mark.parametrize(
    "body",
    [
        {"login_name": "nobody", "password": PASSWORD},
        {"login_name": "demo_client_01", "password": "wrong"},
        {"login_name": "demo_disabled_01", "password": PASSWORD},
        {"login_name": "demo_no_role", "password": PASSWORD},
        {"login_name": "demo_client_01", "password": chr(0xD800)},  # CR R3
    ],
)
def test_login_failures_are_generic_401(env, body) -> None:
    client, *_ = env
    response = login(client, body)
    assert_error(response, 401, "INVALID_CREDENTIALS")
    assert response.json()["error"]["message"] == "Authentication failed."
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("{not json", "INVALID_JSON"),
        ('{"login_name": "a", "login_name": "b", "password": "x"}', "INVALID_JSON"),
        ('{"login_name": "a", "password": NaN}', "INVALID_JSON"),
        ('{"login_name": "demo_client_01", "password": "x", "role": "ADMIN"}', "UNKNOWN_FIELD"),
    ],
)
def test_login_bad_body_is_400(env, raw: str, code: str) -> None:
    client, reader, _ = env
    assert_error(login(client, None, raw=raw), 400, code)
    assert reader.reads == 0


@pytest.mark.parametrize(
    "body",
    [
        {"password": PASSWORD},
        {"login_name": "demo_client_01"},
        {"login_name": "demo_client_01", "password": ""},
        {"login_name": 7, "password": PASSWORD},
        {"login_name": "   ", "password": PASSWORD},
        ["demo_client_01", PASSWORD],
    ],
)
def test_login_invalid_fields_are_422(env, body) -> None:
    client, *_ = env
    assert_error(login(client, body), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    "login_name",
    [chr(0) + "demo_client_01", "demo" + chr(0) + "client", "demo_client_01" + chr(0), chr(0xD800), "a" + chr(0xDFFF)],
)
def test_unstorable_login_name_is_422_without_database_access(env, login_name: str) -> None:
    client, reader, _ = env
    response = login(client, {"login_name": login_name, "password": PASSWORD})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert reader.reads == 0  # CR R1
    assert "demo" not in response.text  # CR R5: no echo of the input


def test_nul_password_round_trips_over_http(env) -> None:
    client, *_ = env
    assert login(client, {"login_name": "demo_nul_password", "password": NUL_PASSWORD}).status_code == 200
    assert login(client, {"login_name": "demo_nul_password", "password": "ab"}).status_code == 401


def test_store_unavailable_is_503(env) -> None:
    client, reader, _ = env
    reader.unavailable = True
    assert_error(login(client, {"login_name": "demo_client_01", "password": PASSWORD}), 503, "DEPENDENCY_UNAVAILABLE")


def token_for(client: TestClient) -> str:
    return login(client, {"login_name": "demo_client_01", "password": PASSWORD}).json()["access_token"]


def test_me_returns_current_identity(env) -> None:
    client, *_ = env
    response = client.get("/api/v1/auth/me", headers=bearer(token_for(client)))
    assert response.status_code == 200
    assert response.json() == {"id": str(C1), "login_name": "demo_client_01", "role": "CLIENT"}
    assert_private(response)


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, {"Authorization": "Bearer a b"}, bearer("x.y.z")],
)
def test_me_without_valid_bearer_is_401(env, headers) -> None:
    client, *_ = env
    response = client.get("/api/v1/auth/me", headers=headers)
    assert_error(response, 401, TOKEN_REJECTED_CODE)
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_rechecks_account_and_expiry(env) -> None:
    client, reader, clock = env
    token = token_for(client)
    reader.set(C1, status="DISABLED")
    assert_error(client.get("/api/v1/auth/me", headers=bearer(token)), 401, TOKEN_REJECTED_CODE)
    reader.set(C1, status="ACTIVE")
    clock.now_us = T0_US + 900_000_000
    assert_error(client.get("/api/v1/auth/me", headers=bearer(token)), 401, TOKEN_REJECTED_CODE)


def test_logout_is_204_twice_and_does_not_revoke(env) -> None:
    client, *_ = env
    token = token_for(client)
    for _ in range(2):
        response = client.post("/api/v1/auth/logout", headers=bearer(token))
        assert response.status_code == 204 and response.content == b""
        assert_private(response)
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200  # API Contract §4.4


def test_logout_without_token_is_401(env) -> None:
    client, *_ = env
    assert_error(client.post("/api/v1/auth/logout"), 401, TOKEN_REJECTED_CODE)


def test_no_public_signup_or_role_routes(env) -> None:
    client, *_ = env
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/auth/role"):
        assert client.post(path, json={}).status_code == 404


def test_shared_dependency_follows_agreed_convention(env) -> None:
    client, reader, _ = env
    token = token_for(client)
    assert client.get("/probe", headers=bearer(token)).json() == {
        "user_id": str(C1),
        "role": "CLIENT",
        "status": "ACTIVE",
    }
    rejected = client.get("/probe", headers=bearer("x.y.z"))
    assert rejected.status_code == 401 and rejected.headers["WWW-Authenticate"] == "Bearer"
    reader.unavailable = True
    assert client.get("/probe", headers=bearer(token)).status_code == 503
