from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from gpu_marketplace.common.local_demo_accounts import (
    validate_local_database_identity,
    validate_local_owner_url,
)


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql+psycopg://owner:secret@127.0.0.1:5432/gpu_marketplace",
        "postgresql+psycopg://owner:secret@localhost:25432/gpu_marketplace",
        "postgresql+psycopg://owner:secret@[::1]:5432/gpu_marketplace",
    ],
)
def test_local_demo_provisioner_accepts_only_loopback_postgresql(raw_url: str) -> None:
    assert validate_local_owner_url(raw_url) == make_url(raw_url)


@pytest.mark.parametrize(
    "raw_url",
    [
        "postgresql+psycopg://owner:secret@db.example/gpu_marketplace",
        "postgresql+psycopg://owner:secret@127.0.0.1/postgres",
        "postgresql://owner:secret@127.0.0.1/gpu_marketplace",
    ],
)
def test_local_demo_provisioner_rejects_nonlocal_or_wrong_database(raw_url: str) -> None:
    with pytest.raises(ValueError):
        validate_local_owner_url(raw_url)


@pytest.mark.parametrize(
    ("database", "current_user", "owner"),
    [
        ("production", "gpu_marketplace", "gpu_marketplace"),
        ("gpu_marketplace", "gpm_api_app", "gpu_marketplace"),
    ],
)
def test_local_demo_provisioner_rejects_wrong_db_or_non_owner(
    database: str, current_user: str, owner: str
) -> None:
    with pytest.raises(ValueError):
        validate_local_database_identity(database, current_user, owner)


def test_local_demo_provisioner_accepts_expected_owner_database() -> None:
    validate_local_database_identity("gpu_marketplace", "gpu_marketplace", "gpu_marketplace")
