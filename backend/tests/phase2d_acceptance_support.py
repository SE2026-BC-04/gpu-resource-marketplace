"""Read-only prerequisites for Phase 2D native-session acceptance tests."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection

from db_safety import TestDatabase, verify_cluster


class Phase2DAcceptanceSetupError(RuntimeError):
    """A bound test fixture does not meet the Phase 2D acceptance prerequisites."""


SESSION_QUERY = text(
    "SELECT current_database(), current_user, session_user, pg_backend_pid(), "
    "current_setting('server_version_num')::integer, inet_server_addr()::text, "
    "inet_server_port(), pg_postmaster_start_time()"
)


@dataclass(frozen=True, slots=True)
class SessionSample:
    database: str
    current_role: str
    login_role: str
    pid: int
    version: int
    address: str | None
    port: int | None
    started_at: datetime

    @property
    def cluster_identity(self) -> tuple[str | None, int | None, datetime]:
        return self.address, self.port, self.started_at


def require_phase2d_acceptance_sessions(
    target: TestDatabase,
    *,
    expected_revision: str,
    operator: Connection,
    api: Connection,
    managers: tuple[Connection, Connection],
) -> tuple[SessionSample, ...]:
    """Check one guarded cluster and three distinct native actors before a race."""
    verify_cluster(operator, target)
    local = SessionSample(*operator.execute(SESSION_QUERY).one())
    if not 160000 <= local.version < 170000:
        raise Phase2DAcceptanceSetupError("Phase 2D acceptance requires PostgreSQL 16")
    revisions = tuple(operator.execute(text("SELECT version_num FROM public.alembic_version")).scalars())
    if revisions != (expected_revision,):
        raise Phase2DAcceptanceSetupError("unexpected or multiple Alembic revisions")

    actors = []
    for connection, role in (
        (api, "gpm_api_app"),
        (managers[0], "gpm_manager_app"),
        (managers[1], "gpm_manager_app"),
    ):
        sample = SessionSample(*connection.execute(SESSION_QUERY).one())
        if sample.current_role != role or sample.login_role != role:
            raise Phase2DAcceptanceSetupError(f"expected a native {role} login")
        if (
            sample.database != target.database
            or sample.cluster_identity != local.cluster_identity
            or sample.version != local.version
        ):
            raise Phase2DAcceptanceSetupError("actor does not use the guarded PostgreSQL database")
        actors.append(sample)

    if len({local.pid, *(actor.pid for actor in actors)}) != 4:
        raise Phase2DAcceptanceSetupError("need separate operator, API and Manager backends")
    return tuple(actors)
