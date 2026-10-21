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
