import asyncio
import json
import tracemalloc
from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from identity_fakes import C1, NUL_PASSWORD, PASSWORD, T0_US, build_service
from gpu_marketplace.identity.dependencies import bearer_token, create_principal_dependency
from gpu_marketplace.identity.tokens import MAX_TOKEN_LENGTH
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.request_body import (
    MAX_JSON_DEPTH,
    MAX_LOGIN_BODY_BYTES,
    BodyTooLarge,
    UnexpectedBody,
    read_bounded_body,
    require_empty_body,
)
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

    return TestClient(app), reader, clock, hasher


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
    client, reader, *_ = env
    assert_error(login(client, None, raw=raw), 400, code)
    assert reader.reads == 0


VALID_BODY = json.dumps({"login_name": "demo_client_01", "password": PASSWORD})


def post_login(client: TestClient, content, headers: dict[str, str]):
    return client.post("/api/v1/auth/login", content=content, headers=headers)


@pytest.mark.parametrize(
    "content_type",
    [None, "text/plain", "application/jsonx", "application/x-www-form-urlencoded", "application/json; charset=latin-1"],
)
def test_login_requires_json_media_type(env, content_type: str | None) -> None:
    client, reader, *_ = env
    headers = {} if content_type is None else {"Content-Type": content_type}
    assert_error(post_login(client, VALID_BODY, headers), 400, "INVALID_JSON")
    assert reader.reads == 0


@pytest.mark.parametrize("content_type", ["application/json; charset=UTF-8", "Application/JSON", 'application/json;charset="utf-8"'])
def test_login_accepts_json_media_type_variants(env, content_type: str) -> None:
    client, *_ = env
    assert post_login(client, VALID_BODY, {"Content-Type": content_type}).status_code == 200


def padded_body(size: int) -> bytes:
    # A valid Login body padded with JSON whitespace to exactly ``size`` bytes.
    body = VALID_BODY.encode()
    return body + b" " * (size - len(body))


def test_login_body_at_the_limit_is_accepted(env) -> None:
    client, *_ = env
    response = post_login(client, padded_body(MAX_LOGIN_BODY_BYTES), {"Content-Type": "application/json"})
    assert response.status_code == 200


def chunks(body: bytes, size: int = 1024):
    for start in range(0, len(body), size):
        yield body[start : start + size]


@pytest.mark.parametrize(
    ("content", "extra_headers"),
    [
        (padded_body(MAX_LOGIN_BODY_BYTES + 1), {}),  # declared Content-Length over the limit
        (chunks(padded_body(4 * MAX_LOGIN_BODY_BYTES)), {}),  # chunked: no Content-Length at all
        (padded_body(4 * MAX_LOGIN_BODY_BYTES), {"Content-Length": "10"}),  # misleading Content-Length
    ],
    ids=["declared", "chunked", "misleading-length"],
)
def test_oversized_login_body_is_413_without_account_read(env, content, extra_headers) -> None:
    client, reader, *_ = env
    response = post_login(client, content, {"Content-Type": "application/json", **extra_headers})
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    assert reader.reads == 0
    assert "demo_client" not in response.text and PASSWORD not in response.text


@pytest.mark.parametrize(
    "raw",
    [
        b'{"login_name": "demo_client_01", "password": ' + b"[" * 5000 + b"]" * 5000 + b"}",
        b"[" * MAX_LOGIN_BODY_BYTES,
        b'{"login_name": "demo_client_01", "password": "x"' + b"}" * 3000,
        b'{"login_name": "demo_client_01", "password": "' + bytes([0xFF]) + b'"}',
        b'{"login_name": "demo_client_01", "password": ' + b"9" * 5000 + b"}",
        b"",
    ],
    ids=["deep-value", "deep-only-brackets", "unbalanced", "invalid-utf8", "huge-integer", "empty"],
)
def test_adversarial_login_json_is_controlled(env, raw: bytes) -> None:
    client, reader, *_ = env
    response = post_login(client, raw, {"Content-Type": "application/json"})
    assert_error(response, 400, "INVALID_JSON")  # never 500
    assert reader.reads == 0
    assert "demo_client" not in response.text


def test_nesting_limit_rejects_before_parsing(env) -> None:
    client, reader, *_ = env
    nested = "[" * (MAX_JSON_DEPTH + 1) + "]" * (MAX_JSON_DEPTH + 1)
    assert_error(login(client, None, raw='{"login_name": "demo_client_01", "password": ' + nested + "}"), 400, "INVALID_JSON")
    allowed = "[" * (MAX_JSON_DEPTH - 1) + "]" * (MAX_JSON_DEPTH - 1)
    assert_error(login(client, None, raw='{"login_name": "demo_client_01", "password": ' + allowed + "}"), 422, "VALIDATION_ERROR")
    assert reader.reads == 0


def test_brackets_inside_strings_do_not_count_as_nesting(env) -> None:
    client, *_ = env
    password = "[{" * 100 + '\\"' + "[" * 100  # escaped quote and backslash inside a string
    response = login(client, {"login_name": "demo_client_01", "password": password})
    assert_error(response, 401, "INVALID_CREDENTIALS")


def test_malformed_content_length_is_400(env) -> None:
    client, reader, *_ = env
    response = post_login(client, VALID_BODY, {"Content-Type": "application/json", "Content-Length": "12abc"})
    assert_error(response, 400, "INVALID_JSON")
    assert reader.reads == 0


HUGE_LENGTH = "9" * 5000  # past Python's int() digit limit (review P2-02)


def test_very_long_content_length_is_413_not_500(env) -> None:
    client, reader, *_ = env
    response = post_login(client, VALID_BODY, {"Content-Type": "application/json", "Content-Length": HUGE_LENGTH})
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    assert reader.reads == 0
    assert "99999" not in response.text  # the header is not echoed


def test_leading_zero_content_length_is_parsed(env) -> None:
    client, *_ = env
    body = VALID_BODY.encode()
    length = "0" * 5000 + str(len(body))
    response = post_login(client, body, {"Content-Type": "application/json", "Content-Length": length})
    assert response.status_code == 200
    over = "0" * 5000 + str(MAX_LOGIN_BODY_BYTES + 1)
    assert_error(post_login(client, body, {"Content-Type": "application/json", "Content-Length": over}), 413, "PAYLOAD_TOO_LARGE")


def asgi_request(parts: list[bytes], headers: dict[str, str] | None = None) -> Request:
    """A raw ASGI request that delivers ``parts`` as separate http.request messages."""
    queue = list(parts)

    async def receive() -> dict:
        body = queue.pop(0) if queue else b""
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw_headers}, receive)


@pytest.mark.parametrize(
    ("parts", "accepted"),
    [
        ([b"x" * MAX_LOGIN_BODY_BYTES], True),
        ([b"x" * (MAX_LOGIN_BODY_BYTES - 10), b"x" * 10], True),
        ([b"x" * (MAX_LOGIN_BODY_BYTES + 1)], False),
        ([b"x" * (MAX_LOGIN_BODY_BYTES - 10), b"x" * 11], False),
        ([b"x" * 100, b"x" * 100, b"x" * MAX_LOGIN_BODY_BYTES], False),
    ],
    ids=["one-chunk-at-limit", "last-chunk-reaches-limit", "one-chunk-over", "last-chunk-crosses", "third-chunk-crosses"],
)
def test_stream_limit_by_chunk(parts: list[bytes], accepted: bool) -> None:
    request = asgi_request(parts)
    if accepted:
        assert asyncio.run(read_bounded_body(request, MAX_LOGIN_BODY_BYTES)) == b"".join(parts)
    else:
        with pytest.raises(BodyTooLarge):
            asyncio.run(read_bounded_body(request, MAX_LOGIN_BODY_BYTES))


def test_oversized_chunk_is_rejected_before_it_is_copied() -> None:
    # One 64 MiB ASGI chunk: if it were appended before the check, the buffer would
    # allocate about 64 MiB. Rejecting before the copy keeps the new allocations tiny.
    chunk = b"x" * (64 * 1024 * 1024)
    request = asgi_request([chunk])
    tracemalloc.start()
    try:
        with pytest.raises(BodyTooLarge):
            asyncio.run(read_bounded_body(request, MAX_LOGIN_BODY_BYTES))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024 * 1024


@pytest.mark.parametrize("length", [HUGE_LENGTH, "1", "0" * 5000 + "1"], ids=["5000-digits", "one", "leading-zeros"])
def test_empty_body_check_rejects_any_declared_length(length: str) -> None:
    with pytest.raises(UnexpectedBody):
        asyncio.run(require_empty_body(asgi_request([], {"Content-Length": length})))


def test_empty_body_check_accepts_zero_length() -> None:
    asyncio.run(require_empty_body(asgi_request([], {"Content-Length": "0" * 5000})))


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
    client, reader, *_ = env
    response = login(client, {"login_name": login_name, "password": PASSWORD})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert reader.reads == 0  # CR R1
    assert "demo" not in response.text  # CR R5: no echo of the input


def test_nul_password_round_trips_over_http(env) -> None:
    client, *_ = env
    assert login(client, {"login_name": "demo_nul_password", "password": NUL_PASSWORD}).status_code == 200
    assert login(client, {"login_name": "demo_nul_password", "password": "ab"}).status_code == 401


def test_store_unavailable_is_503(env) -> None:
    client, reader, *_ = env
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
    client, reader, clock, _ = env
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


@pytest.mark.parametrize(
    ("content", "headers"),
    [
        (b"{}", {"Content-Type": "application/json"}),
        (b'{"token": "x"}', {"Content-Type": "application/json"}),
        (b"x", {}),
        (chunks(b"{}", 1), {"Content-Type": "application/json"}),
    ],
    ids=["empty-object", "json", "text", "chunked"],
)
def test_logout_with_a_body_is_400(env, content, headers) -> None:
    client, reader, *_ = env
    token = token_for(client)
    reads = reader.reads
    response = client.post("/api/v1/auth/logout", content=content, headers={**bearer(token), **headers})
    assert_error(response, 400, "INVALID_JSON")
    assert reader.reads == reads  # rejected before the account is read


def test_logout_with_huge_content_length_is_400(env) -> None:
    client, reader, *_ = env
    token = token_for(client)
    reads = reader.reads
    response = client.post("/api/v1/auth/logout", content=b"", headers={**bearer(token), "Content-Length": HUGE_LENGTH})
    assert_error(response, 400, "INVALID_JSON")
    assert reader.reads == reads
    assert "99999" not in response.text


def test_logout_accepts_an_explicit_empty_body(env) -> None:
    client, *_ = env
    token = token_for(client)
    response = client.post("/api/v1/auth/logout", content=b"", headers={**bearer(token), "Content-Length": "0"})
    assert response.status_code == 204


def test_no_public_signup_or_role_routes(env) -> None:
    client, *_ = env
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/auth/role"):
        assert client.post(path, json={}).status_code == 404


def test_shared_dependency_follows_agreed_convention(env) -> None:
    client, reader, *_ = env
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


def test_hashing_busy_is_503(env) -> None:
    client, _, _, hasher = env
    hasher.busy = True
    assert_error(login(client, {"login_name": "demo_client_01", "password": PASSWORD}), 503, "DEPENDENCY_UNAVAILABLE")


def test_bearer_extraction_enforces_the_c4_limit() -> None:
    assert bearer_token("Bearer " + "a" * MAX_TOKEN_LENGTH) == "a" * MAX_TOKEN_LENGTH
    assert bearer_token("Bearer " + "a" * (MAX_TOKEN_LENGTH + 1)) is None
    assert bearer_token("Bearer abc" + chr(0xE9)) is None


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/probe"])
def test_oversized_authorization_header_is_401(env, path: str) -> None:
    client, *_ = env
    response = client.get(path, headers={"Authorization": "Bearer " + "a" * (MAX_TOKEN_LENGTH + 1)})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
