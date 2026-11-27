"""Tests for the explicitly invoked, isolated Phase 2 Manager config gate."""

import importlib

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from gpu_marketplace.common import database
from gpu_marketplace.common.config import Settings
from gpu_marketplace.manager import config as manager_config


_TOKEN = "A" * 32  # Synthetic fixture; this test does not claim entropy.
_DATABASE_URL = (
    "postgresql+psycopg://gpm_manager_app:dsn-password-sentinel"
    "@localhost:5432/gpu_marketplace"
)


def _valid_values() -> dict[str, str]:
    return {"dispatch_token": _TOKEN, "database_url": _DATABASE_URL}


def test_cfg01_phase1_settings_remain_valid_without_phase2_credentials() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url
    assert "dispatch_token" not in Settings.model_fields


def test_cfg02_explicit_manager_configuration_is_accepted() -> None:
    config = manager_config.validate_manager_phase2_config(_valid_values())

    assert config.dispatch_token.get_secret_value() == _TOKEN
    assert config.database_url.get_secret_value() == _DATABASE_URL


def test_cfg03_missing_dispatch_credential_fails_closed() -> None:
    values = {"database_url": _DATABASE_URL}

    with pytest.raises(ValidationError, match="dispatch_token"):
        manager_config.validate_manager_phase2_config(values)


@pytest.mark.parametrize("token", ["", "   ", "\t\r\n"])
def test_cfg04_empty_or_whitespace_dispatch_credential_is_rejected(
    token: str,
) -> None:
    values = {**_valid_values(), "dispatch_token": token}

    with pytest.raises(ValidationError):
        manager_config.validate_manager_phase2_config(values)


def test_cfg05_dispatch_credential_below_minimum_representation_is_rejected() -> None:
    values = {**_valid_values(), "dispatch_token": "A" * 31}

    with pytest.raises(ValidationError, match="dispatch token"):
        manager_config.validate_manager_phase2_config(values)


@pytest.mark.parametrize(
    "token",
    ["A" * 30 + "\r\n", "A" * 30 + " B", "A" * 30 + ":x", "A" * 30 + "é"],
)
def test_cfg06_dispatch_credential_must_be_safe_bearer_header_value(
    token: str,
) -> None:
    values = {**_valid_values(), "dispatch_token": token}

    with pytest.raises(ValidationError):
        manager_config.validate_manager_phase2_config(values)


def test_cfg07_dispatch_credential_round_trips_without_normalization() -> None:
    token = "AbC123._~+/" * 3 + "=="
    values = {**_valid_values(), "dispatch_token": token}

    config = manager_config.validate_manager_phase2_config(values)

    assert config.dispatch_token.get_secret_value() == token


def test_cfg08_repr_and_validation_errors_do_not_disclose_credentials() -> None:
    token = "dispatch-token-sentinel-should-not-leak-0123456789!"
    dsn_password = "dsn-password-sentinel"
    values = {
        "dispatch_token": token,
        "database_url": (
            "postgresql+psycopg://gpm_manager_app:"
            f"{dsn_password}@localhost:5432/gpu_marketplace"
        ),
    }

    with pytest.raises(ValidationError) as error:
        manager_config.validate_manager_phase2_config(values)

    assert token not in str(error.value)
    assert token not in repr(error.value)
    assert dsn_password not in str(error.value)
    assert dsn_password not in repr(error.value)

    valid_config = manager_config.validate_manager_phase2_config(_valid_values())
    assert _TOKEN not in repr(valid_config)
    assert "dsn-password-sentinel" not in repr(valid_config)


def test_cfg12_unresolved_resource_budgets_have_no_fabricated_defaults() -> None:
    fields = manager_config.ManagerPhase2Config.model_fields

    assert set(fields) == {"dispatch_token", "database_url"}
    assert all(field.is_required() for field in fields.values())


def test_cfg14_manager_config_rejects_other_owners_credentials() -> None:
    callback_token = "callback-token-sentinel-should-not-be-retained-012345"
    values = {
        **_valid_values(),
        "simulator_callback_token": callback_token,
        "jwt_secret": callback_token,
        "worker_private_key": callback_token,
    }

    with pytest.raises(ValidationError) as error:
        manager_config.validate_manager_phase2_config(values)

    assert callback_token not in str(error.value)
    assert callback_token not in repr(error.value)
    assert set(manager_config.ManagerPhase2Config.model_fields) == {
        "dispatch_token",
        "database_url",
    }


@pytest.mark.parametrize(
    "database_url",
    [
        "not-a-dsn-dsn-password-sentinel",
        "sqlite:///not-approved.db",
        "postgresql+psycopg://api_role:secret-sentinel@localhost/gpu_marketplace",
        "postgresql+psycopg://gpm_manager_app:secret-sentinel@localhost",
    ],
)
def test_cfg15_invalid_or_wrong_manager_dsn_is_rejected_without_leaking_password(
    database_url: str,
) -> None:
    values = {**_valid_values(), "database_url": database_url}

    with pytest.raises(ValidationError) as error:
        manager_config.validate_manager_phase2_config(values)

    assert "secret-sentinel" not in str(error.value)
    assert "secret-sentinel" not in repr(error.value)
    assert "dsn-password-sentinel" not in str(error.value)


def test_cfg16_explicit_validator_does_not_read_environment_or_touch_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GPU_MARKETPLACE_MANAGER_DISPATCH_TOKEN", "environment-token")
    monkeypatch.setenv(
        "GPU_MARKETPLACE_MANAGER_DATABASE_URL",
        "postgresql+psycopg://gpm_manager_app:env@localhost:5432/ignored",
    )

    def fail_if_database_is_touched(*args: object, **kwargs: object) -> None:
        raise AssertionError("configuration validation must not touch PostgreSQL")

    monkeypatch.setattr(database, "create_engine", fail_if_database_is_touched)
    monkeypatch.setattr(Engine, "connect", fail_if_database_is_touched)

    reloaded = importlib.reload(manager_config)

    with pytest.raises(ValidationError):
        reloaded.validate_manager_phase2_config({})

    config = reloaded.validate_manager_phase2_config(_valid_values())
    assert config.database_url.get_secret_value() == _DATABASE_URL
    assert config.dispatch_token.get_secret_value() == _TOKEN
