from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from db_safety import TestDatabase, UnsafeTestDatabase
import phase2d_acceptance_support as support


DATABASE = "gpu_marketplace_test_phase2d"
REVISION = "accepted_phase2_revision"
STARTED = datetime(2026, 11, 28, tzinfo=UTC)


def sample(
    pid: int, role: str, *, login: str | None = None, database: str = DATABASE,
    version: int = 160015, port: int = 5432,
) -> tuple:
    return (database, role, login or role, pid, version, "127.0.0.1", port, STARTED)


def connection(row: tuple, *, revisions: tuple[str, ...] = (REVISION,)) -> Mock:
    conn = Mock()
    conn.execute.return_value.one.return_value = row
    conn.execute.return_value.scalars.return_value = revisions
    return conn


@pytest.fixture
def fixture_inputs(monkeypatch: pytest.MonkeyPatch):
    target = TestDatabase("test-only", DATABASE, "127.0.0.1", 55432, "test-marker")
    guard = Mock()
    monkeypatch.setattr(support, "verify_cluster", guard)
    kwargs = {
        "expected_revision": REVISION,
        "operator": connection(sample(1, "migration_owner")),
        "api": connection(sample(2, "gpm_api_app")),
        "managers": (
            connection(sample(3, "gpm_manager_app")),
            connection(sample(4, "gpm_manager_app")),
        ),
    }
    return target, guard, kwargs


def test_returns_distinct_native_actor_samples(fixture_inputs) -> None:
    target, guard, kwargs = fixture_inputs

    actors = support.require_phase2d_acceptance_sessions(target, **kwargs)

    assert [actor.pid for actor in actors] == [2, 3, 4]
    guard.assert_called_once_with(kwargs["operator"], target)


def test_rejected_cluster_stops_before_probing_any_actor(fixture_inputs) -> None:
    target, guard, kwargs = fixture_inputs
    guard.side_effect = UnsafeTestDatabase("fixture marker does not match")

    with pytest.raises(UnsafeTestDatabase):
        support.require_phase2d_acceptance_sessions(target, **kwargs)

    kwargs["operator"].execute.assert_not_called()
    kwargs["api"].execute.assert_not_called()
    kwargs["managers"][0].execute.assert_not_called()


@pytest.mark.parametrize(
    ("bad_sample", "error"),
    [
        (sample(4, "gpm_manager_app", login="migration_owner"), "native gpm_manager_app"),
        (sample(4, "gpm_manager_app", database="wrong"), "guarded PostgreSQL"),
        (sample(4, "gpm_manager_app", port=5433), "guarded PostgreSQL"),
        (sample(3, "gpm_manager_app"), "separate operator, API and Manager"),
    ],
)
def test_rejects_incompatible_manager_connection(fixture_inputs, bad_sample: tuple, error: str) -> None:
    target, _, kwargs = fixture_inputs
    kwargs["managers"][1].execute.return_value.one.return_value = bad_sample

    with pytest.raises(support.Phase2DAcceptanceSetupError, match=error):
        support.require_phase2d_acceptance_sessions(target, **kwargs)


@pytest.mark.parametrize("revisions", [(), ("0005_listing_d7",), (REVISION, "parallel")])
def test_requires_one_expected_migration_head(fixture_inputs, revisions: tuple[str, ...]) -> None:
    target, _, kwargs = fixture_inputs
    kwargs["operator"].execute.return_value.scalars.return_value = revisions

    with pytest.raises(support.Phase2DAcceptanceSetupError, match="Alembic revisions"):
        support.require_phase2d_acceptance_sessions(target, **kwargs)

    kwargs["api"].execute.assert_not_called()


def test_requires_postgresql_16(fixture_inputs) -> None:
    target, _, kwargs = fixture_inputs
    kwargs["operator"].execute.return_value.one.return_value = sample(1, "migration_owner", version=170000)

    with pytest.raises(support.Phase2DAcceptanceSetupError, match="PostgreSQL 16"):
        support.require_phase2d_acceptance_sessions(target, **kwargs)
