"""CR-GPU-004-BODY-01: real HTTP/parser helpers, test-only Listing persistence."""

from dataclasses import replace
import json
import logging
import tracemalloc

import pytest

from .test_http_integration import BASE, forbid_uow, invoke

LIMIT = 16_384


def path(env, method):
    return BASE if method == "POST" else f"{BASE}/{env.store.l1.id}"


def valid_body(method, size=None):
    value = (
        {"gpu_model": "GPU mô phỏng", "vram_gb": 80, "total_gpu_count": 8}
        if method == "POST"
        else {"mock_price_per_hour": "1.00"}
    )
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return raw if size is None else raw + b" " * (size - len(raw))


def assert_rejected(env, result, status, code):
    assert result.status == status
    request_id = result.headers["x-request-id"]
    assert result.body == {
        "error": {
            "code": code,
            "message": result.body["error"]["message"],
            "request_id": request_id,
        }
    }
    assert result.headers["cache-control"] == "no-store"
    assert env.store.commits == env.store.rollbacks == 0
    assert env.store.events == []


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("layout", ["single", "multiple", "leading-zeros"])
def test_exact_byte_limit_is_inclusive_and_valid(env, method, layout):
    body = valid_body(method, LIMIT)
    assert len(body) == LIMIT
    parts = [body[:8192], body[8192:]] if layout == "multiple" else [body]
    length = "0" * 5000 + str(LIMIT) if layout == "leading-zeros" else str(LIMIT)
    result = invoke(env.app, method, path(env, method), chunks=parts, length=length)
    assert result.status == (201 if method == "POST" else 200)
    assert env.store.commits == 1


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "case",
    [
        "declared",
        "absent",
        "understated",
        "false-zero",
        "multiple",
        "huge-digits",
        "leading-zeros",
    ],
)
def test_oversize_and_extreme_lengths_are_413_before_uow(
    env, monkeypatch, method, case
):
    forbid_uow(env, monkeypatch)
    body = valid_body(method, LIMIT + 1)
    parts = [body]
    length = None
    if case == "declared":
        length = str(LIMIT + 1)
    elif case == "understated":
        length = "1"
    elif case == "false-zero":
        length = "0"
    elif case == "multiple":
        parts = [body[:8192], body[8192:LIMIT], body[LIMIT:], b"must-not-be-read"]
    elif case == "huge-digits":
        length = "9" * 5000
    elif case == "leading-zeros":
        length = "0" * 5000 + str(LIMIT + 1)
    result = invoke(env.app, method, path(env, method), chunks=parts, length=length)
    assert_rejected(env, result, 413, "PAYLOAD_TOO_LARGE")
    assert result.reads == (
        0
        if case in {"declared", "huge-digits", "leading-zeros"}
        else 3
        if case == "multiple"
        else 1
    )


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "length",
    ["", "-1", "+1", " 1", "1,1", "12x", "１"],
    ids=["empty", "negative", "plus", "space", "combined", "nondigit", "unicode"],
)
def test_malformed_length_is_400_without_reading(env, monkeypatch, method, length):
    forbid_uow(env, monkeypatch)
    result = invoke(
        env.app, method, path(env, method), body=valid_body(method), length=length
    )
    assert_rejected(env, result, 400, "INVALID_JSON")
    assert result.reads == 0


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_oversized_single_chunk_is_checked_before_copy(env, monkeypatch, method):
    forbid_uow(env, monkeypatch)
    chunk = b"x" * (
        4 * 1024 * 1024
    )  # Preallocated outside the measured application work.
    tracemalloc.start()
    try:
        result = invoke(env.app, method, path(env, method), chunks=[chunk, b"not-read"])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert_rejected(env, result, 413, "PAYLOAD_TOO_LARGE")
    assert result.reads == 1
    assert peak < 1024 * 1024


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("depth,status", [(8, 422), (9, 400)])
def test_depth_counts_root_and_rejects_before_parser(
    env, monkeypatch, method, depth, status
):
    forbid_uow(env, monkeypatch)
    raw = '{"gpu_model":' + "[" * (depth - 1) + "0" + "]" * (depth - 1) + "}"
    original = json.loads
    parsed = []

    def observed(value, *args, **kwargs):
        if value == raw:
            parsed.append(True)
        return original(value, *args, **kwargs)

    monkeypatch.setattr("gpu_marketplace.identity.request_body.json.loads", observed)
    result = invoke(env.app, method, path(env, method), body=raw.encode())
    assert_rejected(
        env, result, status, "INVALID_JSON" if status == 400 else "VALIDATION_ERROR"
    )
    assert parsed == ([True] if depth == 8 else [])


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_brackets_quotes_and_escapes_inside_strings_do_not_count(env, method):
    model = 'GPU " [{ \\ ' + "[" * 30 + "]}" * 5
    if method == "PATCH":
        env.store.records[env.store.l1.id] = replace(env.store.l1, gpu_model=model)
    value = {
        "gpu_model": model,
        **({"vram_gb": 80, "total_gpu_count": 8} if method == "POST" else {}),
    }
    result = invoke(env.app, method, path(env, method), body=json.dumps(value).encode())
    assert result.status == (201 if method == "POST" else 200)
    assert result.body["gpu_model"] == model


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    "raw",
    [
        b'{"gpu_model":"private-body-canary-FF\xff"}',
        b'{"gpu_model":"private-body-canary","gpu_model":"other"}',
        b'{"vram_gb":NaN}',
        b'{"vram_gb":Infinity}',
        b'{"vram_gb":-Infinity}',
        b'{"gpu_model":',
        b'{"vram_gb":' + b"9" * 5000 + b"}",
        b"",
    ],
    ids=[
        "utf8",
        "duplicate",
        "nan",
        "infinity",
        "negative-infinity",
        "malformed",
        "huge-integer",
        "empty",
    ],
)
def test_strict_json_failures_are_safe_400(env, monkeypatch, caplog, method, raw):
    forbid_uow(env, monkeypatch)
    caplog.set_level(logging.INFO, logger="gpu_marketplace.listings.router")
    result = invoke(env.app, method, path(env, method), body=raw)
    assert_rejected(env, result, 400, "INVALID_JSON")
    assert "private-body-canary" not in json.dumps(result.body)
    assert "private-body-canary" not in caplog.text


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("actor,status", [(None, 401), ("client", 403), ("admin", 403)])
@pytest.mark.parametrize("length", [str(LIMIT + 1), "not-a-length"])
def test_auth_then_worker_role_precede_body_validation(
    env, monkeypatch, method, actor, status, length
):
    forbid_uow(env, monkeypatch)
    env.store.actor = getattr(env.store, actor) if actor else None
    result = invoke(env.app, method, path(env, method), body=b"not-read", length=length)
    assert_rejected(
        env, result, status, "UNAUTHORIZED" if status == 401 else "FORBIDDEN"
    )
    assert result.reads == 0
    if status == 401:
        assert result.headers["www-authenticate"] == "Bearer"
