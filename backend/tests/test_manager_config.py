"""Tests for the explicitly invoked, isolated Phase 2 Manager config gate."""

import importlib
from dataclasses import MISSING, fields

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import make_url
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

    with pytest.raises(
        manager_config.ManagerConfigValidationError,
        match="dispatch_token",
    ):
        manager_config.validate_manager_phase2_config(values)


@pytest.mark.parametrize("token", ["", "   ", "\t\r\n"])
def test_cfg04_empty_or_whitespace_dispatch_credential_is_rejected(
    token: str,
) -> None:
    values = {**_valid_values(), "dispatch_token": token}

    with pytest.raises(manager_config.ManagerConfigValidationError):
        manager_config.validate_manager_phase2_config(values)


def test_cfg05_dispatch_credential_below_minimum_representation_is_rejected() -> None:
    values = {**_valid_values(), "dispatch_token": "A" * 31}

    with pytest.raises(
        manager_config.ManagerConfigValidationError,
        match="dispatch_token",
    ):
        manager_config.validate_manager_phase2_config(values)


@pytest.mark.parametrize(
    "token",
    ["A" * 30 + "\r\n", "A" * 30 + " B", "A" * 30 + ":x", "A" * 30 + "é"],
)
def test_cfg06_dispatch_credential_must_be_safe_bearer_header_value(
    token: str,
) -> None:
    values = {**_valid_values(), "dispatch_token": token}

    with pytest.raises(manager_config.ManagerConfigValidationError):
        manager_config.validate_manager_phase2_config(values)


def test_cfg07_dispatch_credential_round_trips_without_normalization() -> None:
    token = "AbC123._~+/" * 3 + "=="
    values = {**_valid_values(), "dispatch_token": token}

    config = manager_config.validate_manager_phase2_config(values)

    assert config.dispatch_token.get_secret_value() == token


@pytest.mark.parametrize(
    "token",
    [
        "A" + "=" * 31,
        "A" * 31 + "=",
        "=" * 32,
        "A" * 16 + "=" + "B" * 16,
        "A" * 32 + "\r\n",
        "A" * 32 + " B",
        "A" * 31 + "é",
    ],
)
def test_cfg17_token_requires_32_non_padding_characters_and_complete_token68(
    token: str,
) -> None:
    with pytest.raises(manager_config.ManagerConfigValidationError):
        manager_config.validate_manager_phase2_config(
            {**_valid_values(), "dispatch_token": token}
        )


def test_cfg18_token_accepts_32_non_padding_characters_and_trailing_padding() -> None:
    for token in ("A" * 32, "A" * 32 + "=="):
        config = manager_config.validate_manager_phase2_config(
            {**_valid_values(), "dispatch_token": token}
        )
        assert config.dispatch_token.get_secret_value() == token


def test_cfg19_psycopg_dialect_applies_url_query_user_override_offline() -> None:
    url = make_url(
        "postgresql+psycopg://gpm_manager_app@localhost/gpu_marketplace?user=postgres"
    )

    positional, keyword = PGDialect_psycopg().create_connect_args(url)

    assert positional == []
    assert keyword["user"] == "postgres"


@pytest.mark.parametrize(
    ("query", "effective_key", "effective_value"),
    [
        ("user=postgres", "user", "postgres"),
        ("host=remote.example", "host", "remote.example"),
        ("hostaddr=203.0.113.7", "hostaddr", "203.0.113.7"),
        ("port=6543", "port", "6543"),
        ("dbname=other_database", "dbname", "other_database"),
        ("password=override-password-sentinel", "password", "override-password-sentinel"),
        ("service=external", "service", "external"),
        (
            "servicefile=%2Ftmp%2Fexternal-pg-service.conf",
            "servicefile",
            "/tmp/external-pg-service.conf",
        ),
        ("options=-c%20role%3Dpostgres", "options", "-c role=postgres"),
        ("role=postgres", "role", "postgres"),
        ("user=manager&user=postgres", "user", ("manager", "postgres")),
        ("%75ser=postgres", "user", "postgres"),
        ("application_name=unapproved-client", "application_name", "unapproved-client"),
    ],
)
def test_cfg20_manager_dsn_rejects_query_overrides_without_leaking_values(
    query: str,
    effective_key: str,
    effective_value: object,
) -> None:
    dsn = f"{_DATABASE_URL}?{query}"
    # Demonstrate the effective psycopg args are formed by SQLAlchemy, including
    # percent-decoded and repeated query keys, without opening a DB connection.
    effective = PGDialect_psycopg().create_connect_args(make_url(dsn))[1]
    assert effective
    assert effective[effective_key] == effective_value

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(
            {**_valid_values(), "database_url": dsn}
        )

    assert query not in str(error.value)
    assert "override-password-sentinel" not in str(error.value)
    assert dsn not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_cfg21_missing_database_url_has_stable_safe_diagnostic() -> None:
    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(
            {"dispatch_token": _TOKEN}
        )

    assert "database_url" in str(error.value)
    assert "required" in str(error.value)


def test_cfg22_unknown_sensitive_field_name_and_value_are_not_echoed() -> None:
    field_name = "unknown-secret-field-name-sentinel"
    field_value = "unknown-secret-field-value-sentinel"

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(
            {**_valid_values(), field_name: field_value}
        )

    for secret in (field_name, field_value):
        assert secret not in str(error.value)
        assert secret not in repr(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [("dispatch_token", 12345), ("database_url", {"password": "type-secret"})],
)
def test_cfg23_wrong_credential_types_have_safe_diagnostics(
    field: str,
    value: object,
) -> None:
    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(
            {**_valid_values(), field: value}
        )

    assert field in str(error.value)
    assert "12345" not in str(error.value)
    assert "type-secret" not in str(error.value)


def test_cfg24_multiple_validation_errors_are_reported_without_input_values() -> None:
    token_secret = "bad-token-sensitive-sentinel"
    password_secret = "bad-dsn-sensitive-sentinel"
    dsn = f"postgresql+psycopg://gpm_manager_app:{password_secret}@localhost/db?user=postgres"

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(
            {"dispatch_token": token_secret, "database_url": dsn}
        )

    message = str(error.value)
    assert "dispatch_token" in message
    assert "database_url" in message
    assert token_secret not in message
    assert password_secret not in message
    assert "user=postgres" not in message


def test_cfg25_untrusted_validator_message_is_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "validator-message-secret-sentinel"
    synthetic = ValidationError.from_exception_data(
        "SyntheticConfigModel",
        [
            {
                "type": "value_error",
                "loc": ("dispatch_token",),
                "input": secret,
                "ctx": {"error": ValueError(secret)},
            }
        ],
    )

    def raise_synthetic(cls: type, values: object) -> object:
        raise synthetic

    monkeypatch.setattr(
        manager_config._ManagerPhase2ConfigModel,
        "model_validate",
        classmethod(raise_synthetic),
    )

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(_valid_values())

    assert secret not in str(error.value)
    assert secret not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_cfg26_unrecognized_validation_category_uses_generic_safe_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthetic = ValidationError.from_exception_data(
        "SyntheticConfigModel",
        [
            {
                "type": "int_parsing",
                "loc": ("dispatch_token",),
                "input": "category-secret-sentinel",
            }
        ],
    )

    def raise_synthetic(cls: type, values: object) -> object:
        raise synthetic

    monkeypatch.setattr(
        manager_config._ManagerPhase2ConfigModel,
        "model_validate",
        classmethod(raise_synthetic),
    )

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(_valid_values())

    assert str(error.value) == (
        "Invalid Manager Phase 2 configuration: configuration is invalid"
    )
    assert "category-secret-sentinel" not in str(error.value)


def test_cfg27_unexpected_programming_failure_is_not_sanitized_as_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_programming_error(cls: type, values: object) -> object:
        raise RuntimeError("unexpected-programming-failure")

    monkeypatch.setattr(
        manager_config._ManagerPhase2ConfigModel,
        "model_validate",
        classmethod(raise_programming_error),
    )

    with pytest.raises(RuntimeError, match="unexpected-programming-failure"):
        manager_config.validate_manager_phase2_config(_valid_values())


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

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(values)

    assert token not in str(error.value)
    assert token not in repr(error.value)
    assert dsn_password not in str(error.value)
    assert dsn_password not in repr(error.value)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    assert not hasattr(error.value, "errors")

    valid_config = manager_config.validate_manager_phase2_config(_valid_values())
    assert _TOKEN not in repr(valid_config)
    assert "dsn-password-sentinel" not in repr(valid_config)

    with pytest.raises(
        manager_config.ManagerConfigValidationError
    ) as constructor_error:
        manager_config.ManagerPhase2Config(
            dispatch_token=token,
            database_url=values["database_url"],
        )
    assert token not in repr(constructor_error.value)
    assert constructor_error.value.__context__ is None


def test_cfg12_unresolved_resource_budgets_have_no_fabricated_defaults() -> None:
    config_fields = fields(manager_config.ManagerPhase2Config)

    assert {item.name for item in config_fields} == {"dispatch_token", "database_url"}
    assert all(item.default is MISSING for item in config_fields)


def test_cfg14_manager_config_rejects_other_owners_credentials() -> None:
    callback_token = "callback-token-sentinel-should-not-be-retained-012345"
    values = {
        **_valid_values(),
        "simulator_callback_token": callback_token,
        "jwt_secret": callback_token,
        "worker_private_key": callback_token,
    }

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
        manager_config.validate_manager_phase2_config(values)

    assert callback_token not in str(error.value)
    assert callback_token not in repr(error.value)
    assert {item.name for item in fields(manager_config.ManagerPhase2Config)} == {
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

    with pytest.raises(manager_config.ManagerConfigValidationError) as error:
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

    with pytest.raises(manager_config.ManagerConfigValidationError):
        reloaded.validate_manager_phase2_config({})

    config = reloaded.validate_manager_phase2_config(_valid_values())
    assert config.database_url.get_secret_value() == _DATABASE_URL
    assert config.dispatch_token.get_secret_value() == _TOKEN
