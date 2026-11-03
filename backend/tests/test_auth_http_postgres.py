"""GPU-003-E: Auth HTTP routes and the shared principal dependency against real PostgreSQL.

The app below mounts only the Auth router and a probe route, wired to ``PostgresAccountReader``
the way ``api/app.py`` is expected to (the real mount is the team lead's). Rows are inserted as
the owner inside a rolled-back transaction; every request reads as ``gpm_api_rw``.
Covers the DB-backed parts of P1C-AC-01, P1C-AC-05 and P1C-AC-06.
"""

import json
import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from gpu_marketplace.common.database import create_engine
from gpu_marketplace.identity.dependencies import create_principal_dependency
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.router import create_auth_router
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.repositories.accounts import PostgresAccountReader
from identity_fakes import HASHER, PASSWORD, SECRET

CLIENT = UUID("0c6f2a1e-3b4d-4e5f-8a6b-7c8d9e0f1a21")
WORKER = UUID("1d7a3b2f-4c5e-4f60-9b7c-8d9e0f1a2b32")
ADMIN = UUID("2e8b4c3a-5d6f-4071-8c8d-9e0f1a2b3c43")
DISABLED = UUID("3f9c5d4b-6e7a-4182-9d9e-0f1a2b3c4d54")
NO_ROLE = UUID("4a0d6e5c-7f8b-4293-8eaf-1a2b3c4d5e65")
# Has no workers/jobs rows, so its role may be changed or removed (P1C-AC-05 composite-FK note).
TEMP = UUID("5b1e7f6d-8a9c-43a4-9fb0-2b3c4d5e6f76")

ACCOUNTS = [
    (CLIENT, "e_client_01", "ACTIVE", "CLIENT"),
    (WORKER, "e_worker_01", "ACTIVE", "WORKER"),
    (ADMIN, "e_admin_01", "ACTIVE", "ADMIN"),
    (DISABLED, "e_disabled_01", "DISABLED", "CLIENT"),
    (NO_ROLE, "e_no_role_01", "ACTIVE", None),
    (TEMP, "e_temp_01", "ACTIVE", "CLIENT"),
]


def build_app(sessions: sessionmaker[Session]) -> FastAPI:
    service = AuthService(PostgresAccountReader(sessions), AccessTokenCodec(SECRET), HASHER)
    app = FastAPI()
    app.include_router(create_auth_router(service=service))
    principal = create_principal_dependency(service)

    # Stand-in for a GPU-004/GPU-005 route consuming the shared dependency.
    @app.get("/probe")
    def probe(p: AuthenticatedPrincipal = Depends(principal)) -> dict[str, str]:
        return {"user_id": str(p.user_id), "role": p.role, "status": p.status}

    return app


@pytest.fixture
def password_hash() -> str:
    return HASHER.hash_password(PASSWORD)


@pytest.fixture
def client(conn: Connection, password_hash: str) -> Iterator[TestClient]:
    for user_id, login_name, status, role in ACCOUNTS:
        conn.execute(
            text("INSERT INTO users (id, login_name, password_hash, status) VALUES (:id, :name, :hash, :status)"),
            {"id": user_id, "name": login_name, "hash": password_hash, "status": status},
        )
        if role is not None:
            conn.execute(
                text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, :role)"), {"id": user_id, "role": role}
            )
    conn.execute(text("SET LOCAL ROLE gpm_api_rw"))
    # Sessions join the outer transaction through savepoints, so the fixture rollback undoes everything.
    with TestClient(build_app(sessionmaker(bind=conn, join_transaction_mode="create_savepoint"))) as test_client:
        yield test_client


def as_owner(conn: Connection, statement: str, **params: object) -> None:
    conn.execute(text("RESET ROLE"))
    conn.execute(text(statement), params)
    conn.execute(text("SET LOCAL ROLE gpm_api_rw"))


def login(client: TestClient, login_name: str, password: str = PASSWORD):
    body = json.dumps({"login_name": login_name, "password": password})
    return client.post("/api/v1/auth/login", content=body, headers={"Content-Type": "application/json"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_for(client: TestClient, login_name: str) -> str:
    response = login(client, login_name)
    assert response.status_code == 200
    return response.json()["access_token"]


def assert_private(response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert UUID(response.headers["X-Request-ID"]).version == 4


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert_private(response)


@pytest.mark.parametrize(
    ("login_name", "user_id", "role"),
    [("e_client_01", CLIENT, "CLIENT"), ("e_worker_01", WORKER, "WORKER"), ("e_admin_01", ADMIN, "ADMIN")],
)
def test_login_and_me_return_the_database_role(client: TestClient, login_name: str, user_id: UUID, role: str) -> None:
    response = login(client, f"  {login_name}\t")
    assert response.status_code == 200
    assert_private(response)
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert (body["token_type"], body["expires_in"]) == ("Bearer", 900)
    expected = {"id": str(user_id), "login_name": login_name, "role": role}
    assert body["user"] == expected

    me = client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json() == expected
    assert_private(me)
    probe = client.get("/probe", headers=bearer(body["access_token"]))
    assert probe.json() == {"user_id": str(user_id), "role": role, "status": "ACTIVE"}


@pytest.mark.parametrize(
    ("login_name", "password"),
    [
        ("e_client_01", "wrong password"),
        ("E_CLIENT_01", PASSWORD),
        ("nobody_here", PASSWORD),
        ("e_disabled_01", PASSWORD),
        ("e_no_role_01", PASSWORD),
    ],
)
def test_failed_logins_share_one_generic_401(client: TestClient, login_name: str, password: str) -> None:
    response = login(client, login_name, password)
    assert_error(response, 401, "INVALID_CREDENTIALS")
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["message"] == "Authentication failed."


def test_requests_read_as_the_api_runtime_role(conn: Connection, client: TestClient) -> None:
    assert login(client, "e_client_01").status_code == 200
    assert conn.execute(text("SELECT current_user")).scalar_one() == "gpm_api_rw"


def test_disabling_after_issuance_rejects_the_token(conn: Connection, client: TestClient) -> None:
    token = token_for(client, "e_worker_01")
    as_owner(conn, "UPDATE users SET status = 'DISABLED' WHERE id = :id", id=WORKER)

    assert_error(client.get("/api/v1/auth/me", headers=bearer(token)), 401, "UNAUTHORIZED")
    assert_error(client.post("/api/v1/auth/logout", headers=bearer(token)), 401, "UNAUTHORIZED")
    probe = client.get("/probe", headers=bearer(token))
    assert probe.status_code == 401 and probe.headers["WWW-Authenticate"] == "Bearer"


def test_role_change_after_issuance_follows_the_database(conn: Connection, client: TestClient) -> None:
    token = token_for(client, "e_temp_01")
    as_owner(conn, "UPDATE user_roles SET role_code = 'ADMIN' WHERE user_id = :id", id=TEMP)

    assert client.get("/api/v1/auth/me", headers=bearer(token)).json()["role"] == "ADMIN"
    assert client.get("/probe", headers=bearer(token)).json()["role"] == "ADMIN"


def test_role_removed_after_issuance_fails_closed(conn: Connection, client: TestClient) -> None:
    token = token_for(client, "e_temp_01")
    as_owner(conn, "DELETE FROM user_roles WHERE user_id = :id", id=TEMP)

    assert_error(client.get("/api/v1/auth/me", headers=bearer(token)), 401, "UNAUTHORIZED")
    assert client.get("/probe", headers=bearer(token)).status_code == 401


def test_logout_is_204_without_server_revocation(client: TestClient) -> None:
    token = token_for(client, "e_client_01")
    response = client.post("/api/v1/auth/logout", headers=bearer(token))
    assert response.status_code == 204 and response.content == b""
    assert_private(response)
    # API Contract §4.4: the JWT stays valid until expiry; the browser forgets it.
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200


def test_no_public_registration_route(client: TestClient) -> None:
    body = json.dumps({"login_name": "new_user", "password": PASSWORD, "role": "ADMIN"})
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/users"):
        assert client.post(path, content=body, headers={"Content-Type": "application/json"}).status_code == 404


def test_full_flow_logs_no_credentials(
    conn: Connection, client: TestClient, password_hash: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        token = token_for(client, "e_admin_01")
        client.get("/api/v1/auth/me", headers=bearer(token))
        client.post("/api/v1/auth/logout", headers=bearer(token))
        login(client, "e_admin_01", "wrong password")
        login(client, "e_disabled_01")
    logged = "\n".join(repr(vars(record)) for record in caplog.records)
    for leaked in (PASSWORD, "wrong password", password_hash, token, "e_admin_01", "e_disabled_01"):
        assert leaked not in logged


@pytest.fixture
def unreachable_client() -> Iterator[TestClient]:
    # Port 1 on loopback refuses connections; nothing is written anywhere.
    engine: Engine = create_engine("postgresql+psycopg://probe:secret-in-dsn@127.0.0.1:1/gpu_marketplace_probe")
    try:
        with TestClient(build_app(sessionmaker(bind=engine))) as test_client:
            yield test_client
    finally:
        engine.dispose()


def test_unreachable_database_is_a_sanitized_503(
    client: TestClient, unreachable_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = token_for(client, "e_client_01")
    with caplog.at_level(logging.DEBUG):
        assert_error(login(unreachable_client, "e_client_01"), 503, "DEPENDENCY_UNAVAILABLE")
        assert_error(unreachable_client.get("/api/v1/auth/me", headers=bearer(token)), 503, "DEPENDENCY_UNAVAILABLE")
        assert unreachable_client.get("/probe", headers=bearer(token)).status_code == 503
    logged = "\n".join(repr(vars(record)) for record in caplog.records)
    for leaked in ("secret-in-dsn", "127.0.0.1", "SELECT", "e_client_01", token):
        assert leaked not in logged
