import pytest

from identity_fakes import A1, C1, NUL_PASSWORD, PASSWORD, T0_US, W1, build_service
from gpu_marketplace.identity.principal import AuthenticatedPrincipal
from gpu_marketplace.identity.service import (
    AuthUnavailable,
    InvalidCredentials,
    InvalidLoginName,
    NotAuthenticated,
)


@pytest.mark.parametrize(
    ("login_name", "user_id", "role"),
    [("demo_client_01", C1, "CLIENT"), ("demo_worker_01", W1, "WORKER"), ("demo_admin_01", A1, "ADMIN")],
)
def test_login_three_roles(login_name, user_id, role) -> None:
    service, *_ = build_service()
    result = service.login(login_name, PASSWORD)
    assert result.identity.user_id == user_id
    assert result.identity.role == role
    assert result.expires_in == 900
    assert service.authenticate(result.access_token) == AuthenticatedPrincipal(user_id=user_id, role=role)


def test_login_trims_ascii_edges_and_is_case_sensitive() -> None:
    service, *_ = build_service()
    assert service.login(" \t\r\ndemo_client_01\n ", PASSWORD).identity.user_id == C1
    with pytest.raises(InvalidCredentials):
        service.login("Demo_Client_01", PASSWORD)
    with pytest.raises(InvalidCredentials):
        service.login(chr(0xA0) + "demo_client_01", PASSWORD)


def test_unknown_login_spends_a_dummy_verification() -> None:
    service, _, _, hasher = build_service()
    with pytest.raises(InvalidCredentials):
        service.login("nobody", PASSWORD)
    assert hasher.burned == 1


@pytest.mark.parametrize(
    ("login_name", "password"),
    [
        ("demo_client_01", "wrong"),
        ("demo_client_01", " " + PASSWORD),  # passwords are never trimmed
        ("demo_disabled_01", PASSWORD),
        ("demo_no_role", PASSWORD),
        ("demo_bad_role", PASSWORD),
        ("demo_client_01", chr(0xD800)),  # CR R3: surrogate password is a plain mismatch
    ],
)
def test_every_login_failure_is_the_same_error(login_name: str, password: str) -> None:
    service, *_ = build_service()
    with pytest.raises(InvalidCredentials) as excinfo:
        service.login(login_name, password)
    assert str(excinfo.value) == ""


def test_nul_password_is_hashed_exactly_without_truncation() -> None:
    service, *_ = build_service()
    assert service.login("demo_nul_password", NUL_PASSWORD).identity.role == "CLIENT"
    with pytest.raises(InvalidCredentials):
        service.login("demo_nul_password", "ab")


@pytest.mark.parametrize(
    "login_name",
    ["", "   ", "a" * 129, chr(0) + "demo", "demo" + chr(0), "de" + chr(0xD800) + "mo", chr(0xDFFF)],
)
def test_invalid_login_name_is_rejected_before_any_database_read(login_name: str) -> None:
    service, reader, _, hasher = build_service()
    with pytest.raises(InvalidLoginName):
        service.login(login_name, PASSWORD)
    assert reader.reads == 0  # CR R1: no database query
    assert hasher.burned == 0


def test_store_unavailable_is_reported_as_unavailable() -> None:
    service, reader, *_ = build_service()
    reader.unavailable = True
    with pytest.raises(AuthUnavailable):
        service.login("demo_client_01", PASSWORD)


def test_token_expires_at_exactly_900_seconds() -> None:
    service, _, clock, _ = build_service()
    token = service.login("demo_client_01", PASSWORD).access_token
    clock.now_us = T0_US + 899_999_999
    assert service.current_identity(token).user_id == C1
    clock.now_us = T0_US + 900_000_000
    with pytest.raises(NotAuthenticated):
        service.current_identity(token)


def test_account_state_is_reread_on_every_request() -> None:
    service, reader, *_ = build_service()
    token = service.login("demo_client_01", PASSWORD).access_token

    reader.set(C1, role="ADMIN")
    assert service.authenticate(token).role == "ADMIN"  # DB role wins over anything in the token

    reader.set(C1, role=None)
    with pytest.raises(NotAuthenticated):
        service.authenticate(token)

    reader.set(C1, role="CLIENT", status="DISABLED")
    with pytest.raises(NotAuthenticated):
        service.authenticate(token)


def test_deleted_account_and_garbage_token_are_not_authenticated() -> None:
    service, reader, *_ = build_service()
    token = service.login("demo_client_01", PASSWORD).access_token
    with pytest.raises(NotAuthenticated):
        service.authenticate("not-a-token")
    del reader.by_id[C1]
    with pytest.raises(NotAuthenticated):
        service.authenticate(token)


@pytest.mark.parametrize("login_name", ["demo_client_01", "nobody"])
def test_full_hashing_slots_are_unavailable_not_wrong_password(login_name: str) -> None:
    # C1 (PR #18): the concurrency cap must not be reported as invalid credentials.
    service, _, _, hasher = build_service()
    hasher.busy = True
    with pytest.raises(AuthUnavailable):
        service.login(login_name, PASSWORD)
