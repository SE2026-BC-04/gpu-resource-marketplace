"""Real GPU-003 JWT/dependency + Listings; account and UoW are test doubles.

This is consumer integration evidence, not PostgreSQL, shared-app or E2E PASS.
"""

import base64
from dataclasses import replace
import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from gpu_marketplace.identity.ports import AccountRecord, AccountStoreUnavailable
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec
from gpu_marketplace.listings.cursors import ListingCursorCodec
from gpu_marketplace.listings.router import create_authenticated_listing_router
from gpu_marketplace.listings.service import ListingService

from .fakes import Store

BASE = "/api/v1/gpu-listings"
TEST_JWT_KEY = b"test-only-user-signing-key-000000"
ROUTES = [
    ("GET", "", None, 200),
    ("GET", "/{id}", None, 200),
    (
        "POST",
        "",
        {"gpu_model": "A100", "vram_gb": 80, "total_gpu_count": 8},
        201,
    ),
    ("PATCH", "/{id}", {"mock_price_per_hour": "1.00"}, 200),
    ("POST", "/{id}/pause", None, 200),
    ("POST", "/{id}/resume", None, 200),
]


class Accounts:
    def __init__(self, store):
        self.records = {
            actor.user_id: AccountRecord(
                actor.user_id, name, "unused-test-hash", actor.status, actor.role
            )
            for name, actor in (
                ("worker-one", store.w1),
                ("worker-two", store.w2),
                ("client", store.client),
                ("admin", store.admin),
            )
        }
        self.reads = 0
        self.unavailable = False

    def get_by_id(self, user_id):
        self.reads += 1
        if self.unavailable:
            raise AccountStoreUnavailable()
        return self.records.get(user_id)

    def find_by_login_name(self, _):
        pytest.fail("Protected routes must look up the verified user UUID")


class NoPasswordWork:
    def hash_password(self, _):
        pytest.fail("Protected routes must not hash passwords")

    def verify_password(self, *_):
        pytest.fail("Protected routes must not verify passwords")

    def burn_verification(self, _):
        pytest.fail("Protected routes must not run dummy password work")


@pytest.fixture
def authenticated_env():
    store = Store()
    accounts = Accounts(store)
    clock = SimpleNamespace(now_us=1_792_041_000_123_456)
    codec = AccessTokenCodec(TEST_JWT_KEY, clock=lambda: clock.now_us)
    auth = AuthService(accounts, codec, NoPasswordWork())
    calls = SimpleNamespace(uow=0)

    def open_uow():
        calls.uow += 1
        return store.open()

    listings = ListingService(
        open_uow, ListingCursorCodec(b"test-only-cursor-signing-key-0000")
    )
    app = FastAPI()
    app.include_router(
        create_authenticated_listing_router(service=listings, auth_service=auth)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(
            store=store,
            accounts=accounts,
            clock=clock,
            codec=codec,
            calls=calls,
            client=client,
        )


def send(env, route, token):
    method, suffix, body, _ = route
    return env.client.request(
        method,
        BASE + suffix.format(id=env.store.l1.id),
        headers={"Authorization": "Bearer " + token} if token else {},
        **({"json": body} if body is not None else {}),
    )


def invalid_signed_claim(token, *, missing):
    """Test-only malformed token, signed so the real codec must validate claims."""
    header, payload, _ = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if missing:
        del data["iss"]
    else:
        data["sub"] = 42
    encoded = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    wire = header + "." + encoded
    signature = (
        base64.urlsafe_b64encode(
            hmac.digest(TEST_JWT_KEY, wire.encode(), hashlib.sha256)
        )
        .decode()
        .rstrip("=")
    )
    return wire + "." + signature


@pytest.mark.parametrize("route", ROUTES)
def test_real_principal_is_accepted_on_all_six_routes(authenticated_env, route):
    env = authenticated_env
    token = env.codec.issue(env.store.w1.user_id).token
    response = send(env, route, token)
    assert response.status_code == route[3]
    assert env.accounts.reads == 1
    assert env.calls.uow == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "tampered",
        "missing-claim",
        "wrong-claim-type",
        "expired",
        "disabled",
        "missing-role",
        "store-unavailable",
    ],
)
def test_real_auth_rejections_never_enter_listing_uow(authenticated_env, route, case):
    env = authenticated_env
    token = env.codec.issue(env.store.w1.user_id).token
    status, code = 401, "UNAUTHORIZED"
    if case == "missing":
        token = None
    elif case == "tampered":
        token += "x"
    elif case in {"missing-claim", "wrong-claim-type"}:
        token = invalid_signed_claim(token, missing=case == "missing-claim")
    elif case == "expired":
        env.clock.now_us += 900_000_000
    elif case == "disabled":
        record = env.accounts.records[env.store.w1.user_id]
        env.accounts.records[record.user_id] = replace(record, status="DISABLED")
    elif case == "missing-role":
        record = env.accounts.records[env.store.w1.user_id]
        env.accounts.records[record.user_id] = replace(record, role=None)
    else:
        env.accounts.unavailable = True
        status, code = 503, "DEPENDENCY_UNAVAILABLE"

    before = dict(env.store.records)
    response = send(env, route, token)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert env.calls.uow == 0
    assert env.store.records == before
    assert env.store.events == [] and env.store.commits == env.store.rollbacks == 0
    assert "unused-test-hash" not in response.text
    assert "AccountStoreUnavailable" not in response.text


@pytest.mark.parametrize("role", ["CLIENT", "ADMIN"])
@pytest.mark.parametrize("route", ROUTES[2:])
def test_changed_role_is_reloaded_before_worker_mutations(
    authenticated_env, route, role
):
    env = authenticated_env
    token = env.codec.issue(env.store.w1.user_id).token
    record = env.accounts.records[env.store.w1.user_id]
    env.accounts.records[record.user_id] = replace(record, role=role)
    response = send(env, route, token)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert env.accounts.reads == 1 and env.calls.uow == 0


@pytest.mark.parametrize("route", ROUTES[3:])
def test_authenticated_other_worker_cannot_mutate_owner_listing(
    authenticated_env, route
):
    env = authenticated_env
    token = env.codec.issue(env.store.w2.user_id).token
    response = send(env, route, token)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LISTING_NOT_FOUND"
    assert env.store.commits == 0
