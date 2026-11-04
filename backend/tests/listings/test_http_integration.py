"""Trusted ASGI-state/body boundary checks; Listing persistence remains a double."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
import pytest

BASE = "/api/v1/gpu-listings"
CLIENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MIDDLEWARE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def invoke(
    app,
    method,
    path,
    *,
    body=b"",
    length=None,
    more_body=False,
    state=None,
    chunks=None,
):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-request-id", CLIENT_ID.encode()),
        ],
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "state": {} if state is None else state,
    }
    if length is not None:
        scope["headers"].append((b"content-length", length.encode()))
    messages = []
    reads = 0
    parts = [body] if chunks is None else chunks

    async def receive():
        nonlocal reads
        reads += 1
        if reads > len(parts):
            raise RuntimeError("The command must not consume the remaining body")
        return {
            "type": "http.request",
            "body": parts[reads - 1],
            "more_body": reads < len(parts) or more_body,
        }

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    data = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return SimpleNamespace(
        status=start["status"],
        body=json.loads(data),
        headers={key.decode(): value.decode() for key, value in start["headers"]},
        state=scope["state"],
        reads=reads,
    )


def forbid_uow(env, monkeypatch):
    def unexpected():
        pytest.fail("Rejected HTTP input must not enter a Listing UoW")

    monkeypatch.setattr(env.service, "_uow", unexpected)


@pytest.mark.parametrize("suffix", ["pause", "resume"])
@pytest.mark.parametrize(
    "length",
    [None, "0", "1", "9" * 5000, "-1", "oops", "1,1"],
    ids=[
        "missing",
        "zero",
        "positive",
        "huge-digits",
        "negative",
        "nondigit",
        "combined",
    ],
)
def test_commands_reject_body_without_reading_the_remaining_stream(
    env, monkeypatch, suffix, length
):
    forbid_uow(env, monkeypatch)
    result = invoke(
        env.app,
        "POST",
        f"{BASE}/{env.store.l1.id}/{suffix}",
        body=b"x" * 65536,
        length=length,
        more_body=True,
    )
    assert result.status == 400
    assert result.body["error"]["code"] == "INVALID_JSON"
    assert result.reads == (1 if length in {None, "0"} else 0)
    assert env.store.events == [] and env.store.commits == env.store.rollbacks == 0


@pytest.mark.parametrize("suffix", ["pause", "resume"])
@pytest.mark.parametrize("length", [None, "0"])
def test_commands_still_accept_an_empty_body(env, suffix, length):
    result = invoke(
        env.app, "POST", f"{BASE}/{env.store.l1.id}/{suffix}", length=length
    )
    assert result.status == 200


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_deep_json_is_rejected_without_500_or_uow(env, monkeypatch, method):
    forbid_uow(env, monkeypatch)
    path = BASE if method == "POST" else f"{BASE}/{env.store.l1.id}"
    result = invoke(env.app, method, path, body=b"[" * 2000 + b"]" * 2000)
    # CR-GPU-004-BODY-01 now rejects depth > 8 before invoking the parser.
    assert result.status == 400
    assert result.body["error"]["code"] == "INVALID_JSON"


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_parser_recursion_exception_is_a_controlled_400(env, monkeypatch, method):
    forbid_uow(env, monkeypatch)
    original = json.loads

    def exhausted(value, *args, **kwargs):
        if value == "[[[]]]":
            raise RecursionError("test-only-parser-detail")
        return original(value, *args, **kwargs)

    monkeypatch.setattr("gpu_marketplace.identity.request_body.json.loads", exhausted)
    path = BASE if method == "POST" else f"{BASE}/{env.store.l1.id}"
    result = invoke(env.app, method, path, body=b"[[[]]]")
    assert result.status == 400
    assert result.body["error"]["code"] == "INVALID_JSON"
    assert "test-only-parser-detail" not in json.dumps(result.body)


@pytest.mark.parametrize("trusted", [None, MIDDLEWARE_ID])
@pytest.mark.parametrize(
    "case,status",
    [
        ("success", 200),
        ("validation", 422),
        ("auth", 401),
        ("dependency", 503),
        ("unexpected", 500),
    ],
)
def test_trusted_request_id_matches_state_headers_and_error_envelope(
    env, monkeypatch, trusted, case, status
):
    path = BASE
    if case == "validation":
        path += "/bad-uuid"
    elif case == "auth":
        env.store.actor = None
    elif case == "dependency":

        def unavailable():
            raise HTTPException(503)

        env.app.dependency_overrides[env.principal_dependency] = unavailable
    elif case == "unexpected":

        def broken(*_args, **_kwargs):
            raise RuntimeError("test-only-private-driver-detail")

        monkeypatch.setattr(env.service, "browse", broken)
    result = invoke(env.app, "GET", path, state={"request_id": trusted})
    assert result.status == status
    request_id = result.headers["x-request-id"]
    assert request_id == result.state["request_id"]
    assert UUID(request_id).version == 4 and str(UUID(request_id)) == request_id
    assert request_id != CLIENT_ID
    if trusted:
        assert request_id == trusted
    if status != 200:
        assert result.body["error"]["request_id"] == request_id
        assert "test-only-private-driver-detail" not in json.dumps(result.body)


@pytest.mark.parametrize(
    "invalid",
    [
        MIDDLEWARE_ID.upper(),
        UUID(MIDDLEWARE_ID).hex,
        "abcdef01-2345-1678-9abc-def012345678",
        42,
        {},
    ],
)
def test_invalid_middleware_ids_are_replaced_not_echoed(env, invalid):
    result = invoke(env.app, "GET", BASE, state={"request_id": invalid})
    assert result.status == 200
    request_id = result.headers["x-request-id"]
    assert UUID(request_id).version == 4 and str(UUID(request_id)) == request_id
    assert request_id != invalid and request_id != CLIENT_ID
    assert result.state["request_id"] == request_id
