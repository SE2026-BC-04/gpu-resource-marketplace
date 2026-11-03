import importlib

import pytest
from pydantic import ValidationError

from gpu_marketplace.common.config import Settings


@pytest.mark.parametrize(
    "module_name",
    [
        "gpu_marketplace.api.app",
        "gpu_marketplace.manager.service",
        "gpu_marketplace.domain.base",
        "gpu_marketplace.repositories",
        "gpu_marketplace.identity",
        "gpu_marketplace.listings",
        "gpu_marketplace.jobs",
    ],
)
def test_backend_modules_import(module_name: str) -> None:
    assert importlib.import_module(module_name)


def test_database_configuration_requires_psycopg_url() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(_env_file=None, database_url="sqlite:///not-approved.db")


def test_local_cors_configuration_is_validated() -> None:
    with pytest.raises(ValidationError, match="CORS origins"):
        Settings(_env_file=None, cors_origins=["http://localhost:5173/path"])


def test_port_configuration_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_port=70000)


def test_jwt_secret_must_contain_at_least_256_bits() -> None:
    Settings(_env_file=None, jwt_secret="x" * 32)
    short_secret = "x" * 31
    with pytest.raises(ValidationError, match="at least 256 bits") as error:
        Settings(_env_file=None, jwt_secret=short_secret)
    assert short_secret not in str(error.value)


def test_jwt_secret_is_redacted_from_settings_repr() -> None:
    secret = "do-not-print-this-signing-secret-0123456789"
    assert secret not in repr(Settings(_env_file=None, jwt_secret=secret))
