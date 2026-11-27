"""TV5-P2E-07 Simulator-local dispatch contract and security tests."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock
from uuid import UUID

from fastapi import FastAPI
import httpx
import pytest
from pydantic import SecretStr, ValidationError

from gpu_marketplace_simulator.app import create_app
from gpu_marketplace_simulator.config import Settings
from gpu_marketplace_simulator.dispatch import (
    AttemptAdmissionConflict,
    AttemptAdmissionOutcome,
    AttemptAdmissionUnavailable,
    DispatchRequest,
)


MANAGER_TOKEN = "manager-test-token-0123456789abcdef"
CALLBACK_TOKEN = "callback-test-token-0123456789abcdef"
USER_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature"
ATTEMPT = "44444444-4444-4444-8444-444444444444"
_NO_BODY = object()


class LocalASGIClient:
    """Sync facade over HTTPX ASGITransport; avoids the local TestClient hang."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://simulator.test"
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", path, **kwargs)


def payload() -> dict[str, object]:
    return {
        "outbox_event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "job_id": "33333333-3333-4333-8333-333333333333",
        "attempt_id": ATTEMPT,
        "worker_id": "11111111-1111-4111-8111-111111111111",
        "listing_id": "22222222-2222-4222-8222-222222222222",
        "gpu_count": 2,
        "duration_seconds": 60,
        "simulation_input": {"workload_profile": "demo-v1"},
        "finish_due_at": "2026-10-18T08:01:00.000000Z",
        "hard_deadline_at": "2026-10-18T08:03:00.000000Z",
    }


class InMemoryAdmission:
    """Test double only; it does not represent the unmerged production cache."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.requests: dict[str, dict[str, object]] = {}
        self.calls = 0
        self.new_producers = 0

    def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
        request = dispatch.model_dump(mode="json")
        with self.lock:
            self.calls += 1
            original = self.requests.get(dispatch.attempt_id)
            if original is None:
                self.requests[dispatch.attempt_id] = request
                self.new_producers += 1
            elif original != request:
                raise AttemptAdmissionConflict
            return AttemptAdmissionOutcome(
                attempt_id=dispatch.attempt_id,
                state="IN_FLIGHT",
                newly_admitted=original is None,
                producer_registered=True,
                receipt=None,
                cache_admission=None,
            )


def app_for(port: InMemoryAdmission | None = None, token: str | None = MANAGER_TOKEN):
    settings = Settings(
        manager_dispatch_token=SecretStr(token) if token else None,
        dispatch_max_body_bytes=4096,
        admission_executor_workers=4,
        admission_max_outstanding=16,
    )
    return create_app(settings, admission_port=port)


def post(client: LocalASGIClient, body: object = _NO_BODY, *, token: str = MANAGER_TOKEN):
    headers = {"Authorization": f"Bearer {token}"}
    if body is _NO_BODY:
        body = payload()
    return client.post("/internal/v1/executions", headers=headers, json=body)


def test_valid_dispatch_returns_only_approved_ack_and_calls_port_once() -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = post(client)
    assert response.status_code == 202
    assert response.json() == {"attempt_id": ATTEMPT, "accepted": True}
    assert set(response.json()) == {"attempt_id", "accepted"}
    assert response.headers["cache-control"] == "no-store"
    request_id = UUID(response.headers["x-request-id"])
    assert request_id.version == 4
    assert admission.calls == 1
    assert admission.new_producers == 1


@pytest.mark.parametrize(
    "token",
    ["", "wrong-manager-secret", CALLBACK_TOKEN, USER_JWT, "bearer lowercase", "Bearer  token"],
)
def test_invalid_or_wrong_direction_auth_is_401_before_admission(token: str) -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = post(client, token=token)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert admission.calls == 0
    assert MANAGER_TOKEN not in response.text
    assert CALLBACK_TOKEN not in response.text


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "bEaReR"])
def test_bearer_scheme_is_case_insensitive_but_token_remains_exact(scheme: str) -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = client.post(
        "/internal/v1/executions",
        headers={"Authorization": f"{scheme} {MANAGER_TOKEN}"},
        json=payload(),
    )

    assert response.status_code == 202
    assert response.json() == {"attempt_id": ATTEMPT, "accepted": True}
    assert admission.calls == 1


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer",
        "Bearer ",
        "Bearer  " + MANAGER_TOKEN,
        " Bearer " + MANAGER_TOKEN,
        "Bearer " + MANAGER_TOKEN + " ",
        "Bearer\t" + MANAGER_TOKEN,
        "Bearer wrong-manager-secret",
    ],
)
def test_malformed_or_wrong_bearer_header_is_rejected_before_admission(
    authorization: str,
) -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = client.post(
        "/internal/v1/executions",
        headers={"Authorization": authorization},
        json=payload(),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert admission.calls == 0


def test_multiple_authorization_headers_are_rejected_before_admission() -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = client.request(
        "POST",
        "/internal/v1/executions",
        headers=[
            ("Authorization", f"Bearer {MANAGER_TOKEN}"),
            ("authorization", f"Bearer {CALLBACK_TOKEN}"),
        ],
        json=payload(),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert admission.calls == 0


def test_authentication_rejection_does_not_read_request_body() -> None:
    class TrackingBody(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.iterated = False

        async def __aiter__(self):
            self.iterated = True
            yield json.dumps(payload()).encode("utf-8")

    admission = InMemoryAdmission()
    app = app_for(admission)
    body = TrackingBody()

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://simulator.test"
        ) as client:
            return await client.post(
                "/internal/v1/executions",
                headers={"Authorization": f"bearer {CALLBACK_TOKEN}"},
                content=body,
            )

    response = asyncio.run(send())

    assert response.status_code == 401
    assert body.iterated is False
    assert admission.calls == 0


def test_missing_authorization_is_401_before_admission() -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    response = client.post("/internal/v1/executions", json=payload())
    assert response.status_code == 401
    assert admission.calls == 0


def test_missing_server_token_fails_closed_without_admission() -> None:
    admission = InMemoryAdmission()
    response = post(LocalASGIClient(app_for(admission, token=None)))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert admission.calls == 0


def test_config_rejects_dispatch_tokens_shorter_than_256_bit_length_floor() -> None:
    with pytest.raises(ValidationError):
        Settings(manager_dispatch_token=SecretStr("too-short"))


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_config_rejects_invalid_dispatch_body_limit(limit: object) -> None:
    with pytest.raises(ValidationError):
        Settings(dispatch_max_body_bytes=limit)


@pytest.mark.parametrize("field", list(payload()))
def test_each_required_field_is_mandatory(field: str) -> None:
    body = payload()
    del body[field]
    admission = InMemoryAdmission()
    response = post(LocalASGIClient(app_for(admission)), body)
    assert response.status_code == 422
    assert admission.calls == 0


def test_extra_top_level_and_nested_fields_are_rejected() -> None:
    body = payload()
    body["client_id"] = "99999999-9999-4999-8999-999999999999"
    response = post(LocalASGIClient(app_for(InMemoryAdmission())), body)
    assert response.status_code == 422

    body = payload()
    body["simulation_input"] = {"workload_profile": "demo-v1", "command": "unsafe"}
    response = post(LocalASGIClient(app_for(InMemoryAdmission())), body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "simulation_input",
    [{}, {"workload_profile": "demo-v2"}, {"workload_profile": True}, {"seed_value": 1}],
)
def test_only_exact_demo_v1_simulation_input_is_accepted(simulation_input: object) -> None:
    body = payload()
    body["simulation_input"] = simulation_input
    admission = InMemoryAdmission()
    response = post(LocalASGIClient(app_for(admission)), body)
    assert response.status_code == 422
    assert admission.calls == 0


@pytest.mark.parametrize(
    "bad_uuid",
    [
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        "11111111-1111-1111-8111-111111111111",
        "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa",
        "not-a-uuid",
    ],
)
def test_noncanonical_or_non_v4_uuid_is_rejected(bad_uuid: str) -> None:
    body = payload()
    body["job_id"] = bad_uuid
    admission = InMemoryAdmission()
    assert post(LocalASGIClient(app_for(admission)), body).status_code == 422
    assert admission.calls == 0


@pytest.mark.parametrize("field", ["gpu_count", "duration_seconds"])
@pytest.mark.parametrize("bad_number", [True, False, 0, -1, 1.0, "2", 2**31])
def test_numeric_fields_are_strict_positive_int32(field: str, bad_number: object) -> None:
    body = payload()
    body[field] = bad_number
    admission = InMemoryAdmission()
    assert post(LocalASGIClient(app_for(admission)), body).status_code == 422
    assert admission.calls == 0


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-10-18T08:01:00Z",
        "2026-10-18T08:01:00.000Z",
        "2026-10-18T09:01:00.000000+01:00",
        "2026-02-30T08:01:00.000000Z",
        "not-a-time",
    ],
)
def test_invalid_or_noncanonical_timestamp_is_rejected(timestamp: str) -> None:
    body = payload()
    body["finish_due_at"] = timestamp
    admission = InMemoryAdmission()
    assert post(LocalASGIClient(app_for(admission)), body).status_code == 422
    assert admission.calls == 0


def test_hard_deadline_must_match_adr005_offset() -> None:
    body = payload()
    body["hard_deadline_at"] = "2026-10-18T08:04:00.000000Z"
    admission = InMemoryAdmission()
    assert post(LocalASGIClient(app_for(admission)), body).status_code == 422
    assert admission.calls == 0


def test_duplicate_json_keys_are_rejected_without_admission() -> None:
    raw = json.dumps(payload(), separators=(",", ":"))
    raw = raw.replace('"gpu_count":2', '"gpu_count":2,"gpu_count":3')
    admission = InMemoryAdmission()
    response = LocalASGIClient(app_for(admission)).post(
        "/internal/v1/executions",
        headers={"Authorization": f"Bearer {MANAGER_TOKEN}", "Content-Type": "application/json"},
        content=raw,
    )
    assert response.status_code == 422
    assert admission.calls == 0


@pytest.mark.parametrize("body", [[], None, "text", 4])
def test_wrong_json_root_type_is_rejected(body: object) -> None:
    admission = InMemoryAdmission()
    response = post(LocalASGIClient(app_for(admission)), body)
    assert response.status_code == 422
    assert admission.calls == 0


def test_unsupported_content_type_is_rejected_safely() -> None:
    admission = InMemoryAdmission()
    response = LocalASGIClient(app_for(admission)).post(
        "/internal/v1/executions",
        headers={"Authorization": f"Bearer {MANAGER_TOKEN}", "Content-Type": "text/plain"},
        content=json.dumps(payload()),
    )
    assert response.status_code == 422
    assert admission.calls == 0


def test_oversized_content_length_is_rejected_before_stream_read() -> None:
    admission = InMemoryAdmission()
    response = LocalASGIClient(app_for(admission)).post(
        "/internal/v1/executions",
        headers={
            "Authorization": f"Bearer {MANAGER_TOKEN}",
            "Content-Type": "application/json",
            "Content-Length": "4097",
        },
        content=b"{}",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["cache-control"] == "no-store"
    assert admission.calls == 0


def test_streaming_reader_stops_before_buffering_oversized_body() -> None:
    from starlette.requests import Request
    from gpu_marketplace_simulator.dispatch import _read_bounded_body, DispatchBodyTooLarge

    received = 0
    chunks = [b"1234", b"56", b"unread"]

    async def receive():
        nonlocal received
        chunk = chunks[received]
        received += 1
        return {"type": "http.request", "body": chunk, "more_body": received < len(chunks)}

    request = Request(
        {"type": "http", "asgi": {"version": "3.0"}, "method": "POST", "path": "/",
         "headers": [], "query_string": b"", "server": ("test", 80), "client": ("test", 1),
         "scheme": "http", "http_version": "1.1"},
        receive,
    )

    async def read():
        return await _read_bounded_body(request, 5)

    with pytest.raises(DispatchBodyTooLarge):
        asyncio.run(read())
    assert received == 2


def test_missing_body_limit_fails_closed_after_auth_without_reading_body() -> None:
    admission = InMemoryAdmission()
    settings = Settings(manager_dispatch_token=SecretStr(MANAGER_TOKEN))
    response = LocalASGIClient(create_app(settings, admission_port=admission)).post(
        "/internal/v1/executions",
        headers={"Authorization": f"Bearer {MANAGER_TOKEN}"},
        json=payload(),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert admission.calls == 0


def test_identical_duplicate_is_acknowledged_without_second_producer() -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    first = post(client)
    repeated = post(client)
    assert first.status_code == repeated.status_code == 202
    assert first.json() == repeated.json()
    assert admission.calls == 2
    assert admission.new_producers == 1


def test_retained_conflicting_dispatch_returns_409_without_replacing_original() -> None:
    admission = InMemoryAdmission()
    client = LocalASGIClient(app_for(admission))
    original = payload()
    assert post(client, original).status_code == 202
    altered = payload()
    altered["gpu_count"] = 3
    response = post(client, altered)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXECUTION_CONFLICT"
    assert set(response.json()["error"]) == {"code", "message", "request_id"}
    assert admission.requests[ATTEMPT] == DispatchRequest.model_validate(original).model_dump(mode="json")
    assert admission.new_producers == 1


def test_admission_unavailable_fails_closed_with_pending_mapping_code() -> None:
    class UnavailableAdmission:
        def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
            raise AttemptAdmissionUnavailable

    response = post(LocalASGIClient(app_for(UnavailableAdmission())))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "temporarily unavailable" in response.json()["error"]["message"]


def test_unexpected_admission_error_is_redacted_as_internal_error() -> None:
    class BrokenAdmission:
        def admit(self, dispatch: DispatchRequest) -> AttemptAdmissionOutcome:
            raise RuntimeError("private adapter detail")

    response = post(LocalASGIClient(app_for(BrokenAdmission())))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private adapter detail" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_http_concurrent_identical_posts_authorize_one_producer() -> None:
    admission = InMemoryAdmission()
    app = app_for(admission)
    gate = Barrier(16)

    def send(_: int) -> int:
        gate.wait(timeout=5)
        return post(LocalASGIClient(app)).status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(send, range(16)))
    assert statuses == [202] * 16
    assert admission.new_producers == 1


def test_http_concurrent_contradictory_posts_have_one_retained_identity() -> None:
    admission = InMemoryAdmission()
    app = app_for(admission)
    gate = Barrier(12)

    def send(index: int) -> int:
        body = payload()
        if index >= 6:
            body["gpu_count"] = 3
        gate.wait(timeout=5)
        return post(LocalASGIClient(app), body).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(send, range(12)))
    assert set(statuses) == {202, 409}
    assert statuses.count(202) == statuses.count(409) == 6
    assert admission.new_producers == 1


def test_unauthorized_request_racing_with_authorized_request_never_admits_unauthorized() -> None:
    admission = InMemoryAdmission()
    app = app_for(admission)
    gate = Barrier(2)

    def send(token: str) -> int:
        gate.wait(timeout=5)
        return post(LocalASGIClient(app), token=token).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, (MANAGER_TOKEN, CALLBACK_TOKEN)))
    assert sorted(statuses) == [202, 401]
    assert admission.calls == 1
    assert admission.new_producers == 1


def test_invalid_payload_error_is_redacted_and_has_private_headers() -> None:
    admission = InMemoryAdmission()
    body = payload()
    body["secret"] = "DO_NOT_ECHO"
    response = post(LocalASGIClient(app_for(admission)), body)
    assert response.status_code == 422
    assert "DO_NOT_ECHO" not in response.text
    assert "traceback" not in response.text.lower()
    assert response.headers["cache-control"] == "no-store"
    assert UUID(response.headers["x-request-id"]).version == 4
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_internal_route_remains_outside_public_docs_and_health_configuration() -> None:
    app = app_for(InMemoryAdmission())
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None
    route_paths = {
        route.path for route in app.routes if getattr(route, "path", None) is not None
    }
    assert "/health/live" in route_paths
    assert "/health/ready" in route_paths
