from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from gpu_marketplace.listings.errors import ListingDependencyUnavailable, ListingError

BASE = "/api/v1/gpu-listings"
VALID = {
    "gpu_model": " A100 simulated ",
    "vram_gb": 80,
    "total_gpu_count": 8,
    "mock_price_per_hour": "12.50",
}


def test_create_uses_trusted_owner_and_server_defaults(env):
    response = env.client.post(BASE, json=VALID)
    assert response.status_code == 201
    data = response.json()
    assert UUID(data["id"]).version == 4
    assert response.headers["location"] == f"{BASE}/{data['id']}"
    assert data["worker"]["id"] == str(env.store.l1.worker.id)
    assert data["gpu_model"] == "A100 simulated"
    assert data["status"] == "ACTIVE" and data["allocated_gpu_count"] == 0
    assert data["available_gpu_count"] == 8 and data["accepting_jobs"] is True
    assert data["mock_price_per_hour"] == "12.50"
    assert data["created_at"] == "2026-10-24T09:00:00.000000Z"
    assert len(env.store.records) == 3
    assert env.store.events[0][0] == "insert"
    assert set(env.store.events[0][1]) == set(VALID)
    assert data["worker"]["reputation"]["success_rate"] is None


@pytest.mark.parametrize("price", ["0.00", "9999999999.99", None])
def test_price_boundaries_are_exact(env, price):
    response = env.client.post(BASE, json={**VALID, "mock_price_per_hour": price})
    assert response.status_code == 201
    assert response.json()["mock_price_per_hour"] == price


def test_create_does_not_invent_idempotency(env):
    first = env.client.post(BASE, json=VALID)
    second = env.client.post(BASE, json=VALID)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(env.store.records) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("gpu_model", ""),
        ("gpu_model", " " * 3),
        ("gpu_model", "a" * 161),
        ("gpu_model", 123),
        ("gpu_model", None),
        ("vram_gb", 0),
        ("vram_gb", True),
        ("vram_gb", 1.0),
        ("vram_gb", "80"),
        ("vram_gb", 2**31),
        ("total_gpu_count", 0),
        ("total_gpu_count", -1),
        ("total_gpu_count", False),
        ("total_gpu_count", "8"),
        ("total_gpu_count", 2**31),
        ("mock_price_per_hour", "-1.00"),
        ("mock_price_per_hour", "1.001"),
        ("mock_price_per_hour", "1.0"),
        ("mock_price_per_hour", 12.50),
        ("mock_price_per_hour", "10000000000.00"),
        ("mock_price_per_hour", "1e2"),
    ],
)
def test_strict_create_validation_does_not_insert(env, field, value):
    response = env.client.post(BASE, json={**VALID, field: value})
    assert response.status_code == 422
    assert len(env.store.records) == 2 and env.store.commits == 0


@pytest.mark.parametrize("field", ["gpu_model", "vram_gb", "total_gpu_count"])
def test_required_create_field(env, field):
    payload = dict(VALID)
    del payload[field]
    assert env.client.post(BASE, json=payload).status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "worker_id",
        "allocated_gpu_count",
        "status",
        "updated_at",
        "created_at",
        "role",
        "surprise",
    ],
)
def test_unknown_and_managed_fields_are_rejected(env, field):
    response = env.client.post(BASE, json={**VALID, field: "injected"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_FIELD"
    assert env.store.commits == 0


@pytest.mark.parametrize(
    "body",
    [
        '{"gpu_model":',
        '{"vram_gb":1,"vram_gb":2}',
        '{"vram_gb":NaN}',
        '{"vram_gb":Infinity}',
        "",
    ],
)
def test_invalid_json_and_duplicate_keys(env, body):
    response = env.client.post(
        BASE, content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_JSON"


@pytest.mark.parametrize("body", [[], None, "text", 12])
def test_nonobject_json(env, body):
    import json

    response = env.client.post(
        BASE, content=json.dumps(body), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("role", ["client", "admin"])
def test_worker_mutations_reject_other_roles(env, role):
    env.store.actor = getattr(env.store, role)
    for method, path, kwargs in [
        ("post", BASE, {"json": VALID}),
        ("patch", f"{BASE}/{env.store.l1.id}", {"json": {"total_gpu_count": 8}}),
        ("post", f"{BASE}/{env.store.l1.id}/pause", {}),
        ("post", f"{BASE}/{env.store.l1.id}/resume", {}),
    ]:
        assert getattr(env.client, method)(path, **kwargs).status_code == 403
    assert env.store.commits == 0


def test_all_six_routes_require_authentication(env):
    env.store.actor = None
    for method, path in [
        ("get", BASE),
        ("get", f"{BASE}/{env.store.l1.id}"),
        ("post", BASE),
        ("patch", f"{BASE}/{env.store.l1.id}"),
        ("post", f"{BASE}/{env.store.l1.id}/pause"),
        ("post", f"{BASE}/{env.store.l1.id}/resume"),
    ]:
        response = getattr(env.client, method)(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("rejection", ["missing-claim", "wrong-claim-type", "expired"])
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("GET", "", None),
        ("GET", "/{id}", None),
        ("POST", "", VALID),
        ("PATCH", "/{id}", {"total_gpu_count": 8}),
        ("POST", "/{id}/pause", None),
        ("POST", "/{id}/resume", None),
    ],
)
def test_upstream_auth_rejection_never_enters_listing_uow(
    env, monkeypatch, method, suffix, body, rejection
):
    """Consumer-boundary regression only, NOT a JWT validation test.

    GPU-003 owns the real DEC-P1-03 decoder and rejects these credentials.
    Here a server-injected dependency proves Listings propagates that rejection
    safely before any domain transaction, even for a mutation with a valid body.
    """
    private_detail = f"test-only-auth-detail:{rejection}"

    def rejected_principal():
        raise HTTPException(401, detail=private_detail)

    def unexpected_uow():
        pytest.fail("Rejected authentication must not open a Listing UoW")

    env.app.dependency_overrides[env.principal_dependency] = rejected_principal
    monkeypatch.setattr(env.service, "_uow", unexpected_uow)
    before = dict(env.store.records)
    response = env.client.request(
        method,
        BASE + suffix.format(id=env.store.l1.id),
        **({"json": body} if body is not None else {}),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "Request could not be accepted.",
            "request_id": response.headers["x-request-id"],
        }
    }
    assert UUID(response.headers["x-request-id"]).version == 4
    assert private_detail not in response.text
    assert env.store.records == before
    assert env.store.events == []
    assert env.store.commits == env.store.rollbacks == 0


def test_disabled_and_unrecognized_roles_fail_closed(env):
    for actor in [
        replace(env.store.w1, status="DISABLED"),
        replace(env.store.w1, role="OWNER"),
    ]:
        env.store.actor = actor
        assert env.client.get(BASE).status_code == 401


def test_marketplace_mine_admin_and_paused_detail(env):
    assert [row["id"] for row in env.client.get(BASE).json()["items"]] == [
        str(env.store.l1.id)
    ]
    assert [
        row["id"] for row in env.client.get(BASE + "?scope=mine").json()["items"]
    ] == [str(env.store.l1.id)]
    env.store.actor = env.store.w2
    mine = env.client.get(BASE + "?scope=mine").json()["items"]
    assert [row["id"] for row in mine] == [str(env.store.l2.id)]
    env.store.actor = env.store.admin
    assert len(env.client.get(BASE + "?scope=all").json()["items"]) == 2
    detail = env.client.get(f"{BASE}/{env.store.l2.id}")
    assert detail.status_code == 200
    assert detail.json()["accepting_jobs"] is False
    assert env.client.get(f"{BASE}/{uuid4()}").status_code == 404
    assert env.client.get(BASE + "/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("GET", "", None),
        ("PATCH", "", {"mock_price_per_hour": "1.00"}),
        ("POST", "/pause", None),
        ("POST", "/resume", None),
    ],
)
@pytest.mark.parametrize(
    "spelling",
    ["canonical", "hex", "uppercase", "braces", "urn", "version", "variant", "invalid"],
)
def test_listing_id_requires_canonical_uuid4(
    env, monkeypatch, method, suffix, body, spelling
):
    canonical = "abcdef01-2345-4678-9abc-def012345678"
    listing_id = UUID(canonical)
    env.store.records[listing_id] = replace(env.store.l1, id=listing_id)
    path_id = {
        "canonical": canonical,
        "hex": listing_id.hex,
        "uppercase": canonical.upper(),
        "braces": "{" + canonical + "}",
        "urn": "urn:uuid:" + canonical,
        "version": "abcdef01-2345-1678-9abc-def012345678",
        "variant": "abcdef01-2345-4678-7abc-def012345678",
        "invalid": "not-a-uuid",
    }[spelling]
    calls = []

    def open_uow():
        calls.append(True)
        return env.store.open()

    monkeypatch.setattr(env.service, "_uow", open_uow)
    before = dict(env.store.records)
    response = env.client.request(
        method,
        BASE + "/" + path_id + suffix,
        **({"json": body} if body is not None else {}),
    )
    if spelling == "canonical":
        assert response.status_code == 200
        assert calls == [True]
    else:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert (
            response.json()["error"]["request_id"] == response.headers["x-request-id"]
        )
        assert calls == []
        assert env.store.records == before
        assert env.store.events == []
        assert env.store.commits == env.store.rollbacks == 0


@pytest.mark.parametrize(
    "role,scope",
    [("client", "mine"), ("client", "all"), ("w1", "all"), ("admin", "mine")],
)
def test_forbidden_read_scope(env, role, scope):
    env.store.actor = getattr(env.store, role)
    assert env.client.get(BASE + f"?scope={scope}").status_code == 403


@pytest.mark.parametrize(
    "query,status",
    [
        ("status=PAUSED", 400),
        ("scope=unknown", 400),
        ("status=unknown", 400),
        ("limit=0", 422),
        ("limit=101", 422),
        ("limit=1.5", 422),
        ("limit=two", 422),
        ("limit=1&limit=2", 400),
        ("worker_id=injected", 400),
        ("cursor=", 400),
    ],
)
def test_query_validation(env, query, status):
    assert env.client.get(BASE + "?" + query).status_code == status


def test_missing_worker_profile(env):
    del env.store.workers[env.store.w1.user_id]
    assert (
        env.client.post(BASE, json=VALID).json()["error"]["code"]
        == "WORKER_PROFILE_MISSING"
    )
    assert env.client.get(BASE + "?scope=mine").json() == {
        "items": [],
        "next_cursor": None,
    }
    assert env.client.post(f"{BASE}/{env.store.l1.id}/pause").status_code == 404


@pytest.mark.parametrize(
    "body", [{}, {"gpu_model": None}, {"vram_gb": None}, {"total_gpu_count": None}]
)
def test_patch_requires_a_valid_field(env, body):
    assert env.client.patch(f"{BASE}/{env.store.l1.id}", json=body).status_code == 422


def test_price_patch_preserves_other_fields_and_can_clear(env):
    path = f"{BASE}/{env.store.l1.id}"
    response = env.client.patch(path, json={"mock_price_per_hour": "10.00"})
    assert response.status_code == 200
    assert response.json()["mock_price_per_hour"] == "10.00"
    assert env.store.records[env.store.l1.id] == replace(
        env.store.l1, mock_price_per_hour=Decimal("10.00")
    )
    assert not any(event[0].startswith("jobs_") for event in env.store.events)
    assert (
        env.client.patch(path, json={"mock_price_per_hour": None}).json()[
            "mock_price_per_hour"
        ]
        is None
    )


def test_worker_owner_is_enforced_for_all_mutations(env):
    env.store.actor = env.store.w2
    for identity in [env.store.l1.id, uuid4()]:
        for method, suffix, kwargs in [
            ("patch", "", {"json": {"mock_price_per_hour": "1.00"}}),
            ("post", "/pause", {}),
            ("post", "/resume", {}),
        ]:
            response = getattr(env.client, method)(
                f"{BASE}/{identity}{suffix}", **kwargs
            )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "LISTING_NOT_FOUND"
    assert env.store.records[env.store.l1.id] == env.store.l1


@pytest.mark.parametrize(
    "changes,code",
    [
        (
            {"gpu_model": "Different", "mock_price_per_hour": "1.00"},
            "LISTING_HARDWARE_LOCKED",
        ),
        ({"vram_gb": 40}, "LISTING_HARDWARE_LOCKED"),
        (
            {"total_gpu_count": 2, "mock_price_per_hour": "1.00"},
            "LISTING_CAPACITY_BELOW_ALLOCATED",
        ),
        (
            {"total_gpu_count": 5, "mock_price_per_hour": "1.00"},
            "LISTING_CAPACITY_BELOW_QUEUED_MAX",
        ),
    ],
)
def test_guard_failure_prevents_partial_writes_and_locks_first(env, changes, code):
    response = env.client.patch(f"{BASE}/{env.store.l1.id}", json=changes)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert env.store.records[env.store.l1.id] == env.store.l1
    assert env.store.events[0] == ("lock", env.store.l1.id)
    assert not any(event[0] == "update" for event in env.store.events)
    assert env.store.rollbacks == 1


def test_same_hardware_noop_and_queued_max_not_sum(env):
    path = f"{BASE}/{env.store.l1.id}"
    assert (
        env.client.patch(
            path, json={"gpu_model": env.store.l1.gpu_model, "vram_gb": 80}
        ).status_code
        == 200
    )
    env.store.job_rows[env.store.l1.id] = [("RUNNING", 3), ("QUEUED", 6), ("QUEUED", 6)]
    response = env.client.patch(path, json={"total_gpu_count": 6})
    assert response.status_code == 200 and response.json()["total_gpu_count"] == 6
    assert response.json()["allocated_gpu_count"] == 3


@pytest.mark.parametrize("terminal_state", ["COMPLETED", "FAILED", "CANCELLED"])
def test_hardware_change_without_nonterminal_jobs(env, terminal_state):
    # These are the terminal states in Database Design and ck_jobs_status.
    env.store.job_rows[env.store.l1.id] = [(terminal_state, 8)]
    assert (
        env.client.patch(
            f"{BASE}/{env.store.l1.id}", json={"gpu_model": "New model", "vram_gb": 40}
        ).status_code
        == 200
    )


def test_pause_resume_are_idempotent_and_do_not_change_jobs_or_allocation(env):
    path = f"{BASE}/{env.store.l1.id}"
    for command, expected in [
        ("pause", "PAUSED"),
        ("pause", "PAUSED"),
        ("resume", "ACTIVE"),
        ("resume", "ACTIVE"),
    ]:
        response = env.client.post(path + "/" + command)
        assert response.status_code == 200 and response.json()["status"] == expected
        assert response.json()["allocated_gpu_count"] == 3
    assert [event[0] for event in env.store.events].count("status") == 2
    assert env.store.job_rows[env.store.l1.id] == [("RUNNING", 3), ("QUEUED", 6)]
    assert env.client.post(path + "/pause", json={}).status_code == 400


def test_error_correlation_redaction_and_commit_rollback(env):
    env.store.fail_commit = ListingDependencyUnavailable("password=do-not-expose")
    response = env.client.post(BASE, json=VALID, headers={"X-Request-ID": "untrusted"})
    assert response.status_code == 503 and len(env.store.records) == 2
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    request_id = response.json()["error"]["request_id"]
    assert (
        UUID(request_id).version == 4 and response.headers["x-request-id"] == request_id
    )
    assert request_id != "untrusted" and "do-not-expose" not in response.text
    assert response.headers["cache-control"] == "no-store"
    env.store.fail_commit = RuntimeError("secret-connection-string")
    response = env.client.post(BASE, json=VALID)
    assert (
        response.status_code == 500 and "secret-connection-string" not in response.text
    )
    assert len(env.store.records) == 2


def test_service_also_rejects_managed_fields(env):
    with pytest.raises(ListingError) as error:
        env.service.patch(env.store.w1, env.store.l1.id, {"allocated_gpu_count": 7})
    assert error.value.code == "UNKNOWN_FIELD"


def test_owner_is_resolved_against_post_lock_worker_mapping(env):
    from gpu_marketplace.listings.cursors import ListingCursorCodec
    from gpu_marketplace.listings.models import WorkerProfile
    from gpu_marketplace.listings.service import ListingService

    def changed_mapping_uow():
        uow = env.store.open()
        lock = uow.listings.get_for_update

        def acquire_and_change_mapping(identity):
            record = lock(identity)
            env.store.workers[env.store.w1.user_id] = WorkerProfile(
                uuid4(), "Different profile"
            )
            return record

        uow.listings.get_for_update = acquire_and_change_mapping
        return uow

    service = ListingService(
        changed_mapping_uow, ListingCursorCodec(b"test-only-cursor-key-not-a-secret")
    )
    with pytest.raises(ListingError) as failure:
        service.patch(env.store.w1, env.store.l1.id, {"total_gpu_count": 8})
    assert failure.value.status_code == 404
    assert env.store.records[env.store.l1.id] == env.store.l1
    assert env.store.commits == 0


def test_reputation_and_snapshot_are_exact_public_projections(env):
    data = env.client.get(f"{BASE}/{env.store.l1.id}").json()
    assert data["worker"]["reputation"] == {
        "successful_jobs": 7,
        "worker_fault_jobs": 3,
        "success_rate": "0.7000",
    }
    assert data["available_gpu_count"] == 5
    assert set(data) == {
        "id",
        "worker",
        "gpu_model",
        "vram_gb",
        "total_gpu_count",
        "allocated_gpu_count",
        "available_gpu_count",
        "status",
        "accepting_jobs",
        "mock_price_per_hour",
        "created_at",
        "updated_at",
    }


def test_keyset_paging_ties_tampering_and_context(env):
    env.store.records = {
        identity: replace(env.store.l1, id=identity)
        for identity in [uuid4() for _ in range(120)]
    }
    seen = []
    cursor = None
    first_cursor = None
    while True:
        params = {"limit": 20, "scope": "mine"}
        if cursor:
            params["cursor"] = cursor
        response = env.client.get(BASE, params=params)
        assert response.status_code == 200
        page = response.json()
        seen.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
        first_cursor = first_cursor or cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 120
    assert seen == sorted(seen, reverse=True)
    for params in [
        {"scope": "mine", "cursor": first_cursor + "x"},
        {"scope": "marketplace", "cursor": first_cursor},
        {"scope": "mine", "status": "ACTIVE", "cursor": first_cursor},
    ]:
        assert (
            env.client.get(BASE, params=params).json()["error"]["code"]
            == "INVALID_CURSOR"
        )
    env.store.actor = env.store.w2
    assert (
        env.client.get(
            BASE, params={"scope": "mine", "cursor": first_cursor}
        ).status_code
        == 400
    )
