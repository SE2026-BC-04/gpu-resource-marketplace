"""GPU-003-E2: P1C-AC-07 browser checks for Auth and the shared frontend session.

Runs the production API as the native ``gpm_api_app`` login against a disposable, safety-marked
PostgreSQL database, builds and previews the production frontend, then drives Chromium with
``frontend/e2e/auth-session.spec.ts``. The general Phase 1 journey lives in
``test_phase1_runtime_http_postgres_e2e.py``; this test covers token handling, reload, storage,
console, CORS request IDs, expiry, account switching and an account disabled mid-session.

Every secret here is generated per run and only passed through process environments. Failure
output is redacted before it is shown.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from gpu_marketplace.common.db_roles import bootstrap_roles
from gpu_marketplace.identity.passwords import ScryptPasswordHasher

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"
API_LOGIN = "gpm_api_app"
# Inherited variables with these prefixes are never passed to a child process. They cover the
# application settings (including the owner DSN that conftest's ``alembic_config`` sets in
# GPU_MARKETPLACE_DATABASE_URL), the test-cluster markers and libpq routing/credentials (PG*).
# Each child gets back only the settings it needs, explicitly.
INHERITED_ENV_PREFIXES = ("GPU_MARKETPLACE_", "GPM_", "PG")
INHERITED_ENV_NAMES = ("DATABASE_URL",)
STARTUP_SECONDS = 30
BROWSER_SECONDS = 300
EXPECTED_BROWSER_TESTS = 7


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_environment(extra: dict[str, str], forbidden: Iterable[str]) -> dict[str, str]:
    """Builds a child environment that cannot contain any ``forbidden`` value.

    Inherited database/application variables are dropped by name, and any other inherited
    variable whose value contains a forbidden value is dropped too. ``extra`` is then checked
    the same way, so a mistake in the caller fails the test instead of reaching the child.
    """
    blocked = [value for value in forbidden if value]
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(INHERITED_ENV_PREFIXES)
        and name.upper() not in INHERITED_ENV_NAMES
        and not any(secret in value for secret in blocked)
    }
    environment.update(extra)
    leaking = sorted(name for name, value in environment.items() if any(secret in value for secret in blocked))
    assert leaking == [], f"Forbidden credentials would reach a child process through: {leaking}"
    return environment


def _owner_credentials(owner_url: str) -> list[str]:
    """The owner URL and password, plus the values of the test-cluster variables."""
    values = [owner_url, make_url(owner_url).password or ""]
    values += [value for name, value in os.environ.items() if name.upper().startswith(("GPM_", "GPU_MARKETPLACE_TEST_"))]
    # Short flag values such as "1" are not credentials and would match unrelated variables.
    return [value for value in values if len(value) >= 8]


def test_child_environments_never_receive_owner_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for the #42 review: conftest puts the owner DSN in GPU_MARKETPLACE_DATABASE_URL.
    owner_password = secrets.token_hex(16)
    owner_url = f"postgresql+psycopg://postgres:{owner_password}@127.0.0.1:55432/gpu_marketplace_test"
    runtime_url = f"postgresql+psycopg://{API_LOGIN}:{secrets.token_hex(16)}@127.0.0.1:55432/gpu_marketplace_test"
    monkeypatch.setenv("GPU_MARKETPLACE_DATABASE_URL", owner_url)
    monkeypatch.setenv("GPU_MARKETPLACE_TEST_DATABASE_URL", owner_url)
    monkeypatch.setenv("GPM_CI_PGPASSWORD", owner_password)
    monkeypatch.setenv("PGPASSWORD", owner_password)
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("DATABASE_URL", owner_url)
    monkeypatch.setenv("UNRELATED_TOOL_SETTING", f"dsn={owner_url}")
    owner = _owner_credentials(owner_url)

    browser = _child_environment({"AUTH_E2E_BASE_URL": "http://127.0.0.1:1"}, owner + [runtime_url])
    api = _child_environment({"GPU_MARKETPLACE_DATABASE_URL": runtime_url}, owner)

    for environment in (browser, api):
        assert not any(owner_password in value for value in environment.values())
        assert not any(name.upper().startswith("PG") or name.upper() == "DATABASE_URL" for name in environment)
        assert "UNRELATED_TOOL_SETTING" not in environment
    assert not any(name.upper().startswith(("GPU_MARKETPLACE_", "GPM_")) for name in browser)
    assert [name for name in api if name.upper().startswith(("GPU_MARKETPLACE_", "GPM_"))] == [
        "GPU_MARKETPLACE_DATABASE_URL"
    ]
    assert api["GPU_MARKETPLACE_DATABASE_URL"] == runtime_url
    with pytest.raises(AssertionError, match="GPU_MARKETPLACE_DATABASE_URL"):
        _child_environment({"GPU_MARKETPLACE_DATABASE_URL": owner_url}, owner)


def _redact(output: str, values: Iterable[str]) -> str:
    for value in values:
        if value:
            output = output.replace(value, "[REDACTED]")
    return output


def _wait_until_ready(process: subprocess.Popen[bytes], url: str, log, name: str, hidden: list[str]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    with httpx.Client(timeout=2.0, trust_env=False) as probe:
        while True:
            if process.poll() is not None:
                log.seek(0)
                detail = _redact(log.read().decode("utf-8", errors="replace"), hidden)
                raise AssertionError(f"{name} exited before readiness (exit={process.returncode}):\n{detail}")
            try:
                if probe.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise AssertionError(f"{name} did not become ready within {STARTUP_SECONDS} seconds")
            time.sleep(0.25)


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _insert_account(connection, user_id: UUID, login_name: str, password_hash: str, role: str) -> None:
    connection.execute(
        text(
            "INSERT INTO users (id, login_name, password_hash, status) "
            "VALUES (:id, :login_name, :password_hash, 'ACTIVE')"
        ),
        {"id": user_id, "login_name": login_name, "password_hash": password_hash},
    )
    connection.execute(
        text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, :role)"),
        {"id": user_id, "role": role},
    )


def test_auth_session_in_a_real_browser_against_postgres_and_native_runtime_role(
    migrated_database_with_teardown: Engine,
    test_database,
) -> None:
    owner_engine = migrated_database_with_teardown
    api_password = secrets.token_hex(32)
    manager_password = secrets.token_hex(32)
    jwt_secret = secrets.token_hex(32)
    listing_cursor_secret = secrets.token_hex(32)
    jobs_cursor_secret = secrets.token_hex(32)
    account_password = secrets.token_urlsafe(24)
    with owner_engine.begin() as connection:
        # db_safety has already vetted this URL and cluster as disposable.
        bootstrap_roles(connection, api_password, manager_password, rotate_password=True)

    run = uuid4().hex[:12]
    client_id, worker_id, disabled_id, worker_profile_id = uuid4(), uuid4(), uuid4(), uuid4()
    client_login = f"e2-client-{run}"
    worker_login = f"e2-worker-{run}"
    # A Client with no Worker profile or Job, so it can be disabled (P1C-AC-05 ON DELETE RESTRICT note).
    disabled_login = f"e2-disable-{run}"
    password_hash = ScryptPasswordHasher().hash_password(account_password)
    with owner_engine.begin() as connection:
        _insert_account(connection, client_id, client_login, password_hash, "CLIENT")
        _insert_account(connection, worker_id, worker_login, password_hash, "WORKER")
        connection.execute(
            text("INSERT INTO workers (id, user_id, display_name) VALUES (:id, :user_id, 'E2 Worker')"),
            {"id": worker_profile_id, "user_id": worker_id},
        )
        _insert_account(connection, disabled_id, disabled_login, password_hash, "CLIENT")

    runtime_url = (
        make_url(test_database.url)
        .set(username=API_LOGIN, password=api_password)
        .render_as_string(hide_password=False)
    )
    owner = _owner_credentials(test_database.url)
    # Server-side values: only the API process may receive them.
    server_only = [
        api_password,
        manager_password,
        jwt_secret,
        listing_cursor_secret,
        jobs_cursor_secret,
        runtime_url,
    ]
    # The browser needs the account password; the API, the build and the preview do not.
    hidden = [*owner, *server_only, account_password]

    node = shutil.which("node")
    assert node is not None, "Node.js is required for the browser E2E test."
    vite_cli = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    playwright_cli = FRONTEND_ROOT / "node_modules" / "@playwright" / "test" / "cli.js"
    assert vite_cli.is_file(), "Install the frontend dependencies with npm ci before the browser E2E test."
    assert playwright_cli.is_file(), "Install @playwright/test with npm ci before the browser E2E test."

    api_port = _free_loopback_port()
    frontend_port = _free_loopback_port()
    api_url = f"http://127.0.0.1:{api_port}"
    frontend_origin = f"http://127.0.0.1:{frontend_port}"
    server_secrets = {
        "GPU_MARKETPLACE_DATABASE_URL": runtime_url,
        "GPU_MARKETPLACE_JWT_SECRET": jwt_secret,
        "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": listing_cursor_secret,
        "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": jobs_cursor_secret,
    }

    # E2-13: build with server-secret variables present in the environment. Vite may only inline
    # VITE_* variables, so none of these values may appear in the shipped bundle. The build gets
    # random canaries under the same names, never a real credential.
    canaries = {
        "GPU_MARKETPLACE_DATABASE_URL": (
            f"postgresql+psycopg://canary:{secrets.token_hex(32)}@127.0.0.1:1/canary"
        ),
        "GPU_MARKETPLACE_JWT_SECRET": secrets.token_hex(32),
        "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": secrets.token_hex(32),
        "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": secrets.token_hex(32),
    }
    build = subprocess.run(
        [node, str(vite_cli), "build"],
        cwd=FRONTEND_ROOT,
        env=_child_environment({**canaries, "VITE_API_BASE_URL": api_url}, hidden),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert build.returncode == 0, "Production frontend build failed:\n" + _redact(
        build.stdout + build.stderr, hidden
    )
    leaked = [
        path.relative_to(FRONTEND_ROOT).as_posix()
        for path in (FRONTEND_ROOT / "dist").rglob("*")
        if path.is_file() and any(value.encode() in path.read_bytes() for value in [*canaries.values(), *hidden])
    ]
    assert leaked == [], f"Server secrets leaked into the frontend build: {leaked}"

    api_process: subprocess.Popen[bytes] | None = None
    frontend_process: subprocess.Popen[bytes] | None = None
    runtime_engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        with runtime_engine.connect() as connection:
            identity = connection.execute(text("SELECT current_user, session_user")).one()
        assert tuple(identity) == (API_LOGIN, API_LOGIN)

        with tempfile.TemporaryFile() as api_log, tempfile.TemporaryFile() as frontend_log:
            api_process = subprocess.Popen(
                [sys.executable, "-m", "gpu_marketplace.api"],
                cwd=BACKEND_ROOT,
                env=_child_environment(
                    {
                        **server_secrets,
                        "GPU_MARKETPLACE_API_HOST": "127.0.0.1",
                        "GPU_MARKETPLACE_API_PORT": str(api_port),
                        "GPU_MARKETPLACE_CORS_ORIGINS": json.dumps([frontend_origin]),
                    },
                    # The API connects as gpm_api_app only; it never needs the owner or Manager.
                    [*owner, manager_password, account_password],
                ),
                stdout=api_log,
                stderr=api_log,
            )
            _wait_until_ready(api_process, f"{api_url}/health/ready", api_log, "Production API", hidden)

            frontend_process = subprocess.Popen(
                [node, str(vite_cli), "preview", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
                cwd=FRONTEND_ROOT,
                env=_child_environment({"VITE_API_BASE_URL": api_url}, hidden),
                stdout=frontend_log,
                stderr=frontend_log,
            )
            _wait_until_ready(frontend_process, frontend_origin, frontend_log, "Frontend preview", hidden)

            with tempfile.TemporaryDirectory(prefix="gpm-auth-e2e-") as control, tempfile.TemporaryFile() as browser_log:
                control_dir = Path(control)
                browser = subprocess.Popen(
                    [node, str(playwright_cli), "test", "--config=e2e/auth-session.config.ts"],
                    cwd=FRONTEND_ROOT,
                    env=_child_environment(
                        {
                            "AUTH_E2E_BASE_URL": frontend_origin,
                            "AUTH_E2E_API_URL": api_url,
                            "AUTH_E2E_CLIENT_LOGIN": client_login,
                            "AUTH_E2E_WORKER_LOGIN": worker_login,
                            "AUTH_E2E_DISABLE_LOGIN": disabled_login,
                            "AUTH_E2E_PASSWORD": account_password,
                            "AUTH_E2E_CONTROL_DIR": str(control_dir),
                        },
                        [*owner, *server_only],
                    ),
                    stdout=browser_log,
                    stderr=browser_log,
                )
                disabled = False
                deadline = time.monotonic() + BROWSER_SECONDS
                try:
                    while browser.poll() is None:
                        # The spec asks for the account to be disabled after it has signed in.
                        if not disabled and (control_dir / "disable.request").exists():
                            with owner_engine.begin() as connection:
                                connection.execute(
                                    text("UPDATE users SET status = 'DISABLED' WHERE id = :id"),
                                    {"id": disabled_id},
                                )
                            (control_dir / "disable.done").write_text("1", encoding="utf-8")
                            disabled = True
                        if time.monotonic() >= deadline:
                            raise AssertionError(f"Browser E2E did not finish within {BROWSER_SECONDS} seconds")
                        time.sleep(0.1)
                finally:
                    _stop(browser)
                browser_log.seek(0)
                output = browser_log.read().decode("utf-8", errors="replace")

                assert browser.returncode == 0, (
                    f"Browser E2E failed (exit={browser.returncode}):\n{_redact(output, hidden)}"
                )
                assert disabled, "The spec never asked for the account to be disabled."
                # Guard against a config or filter change that silently runs fewer checks.
                assert f"{EXPECTED_BROWSER_TESTS} passed" in output, _redact(output, hidden)

            # The server log must not contain any secret, the password or a token-shaped value.
            api_log.seek(0)
            server_output = api_log.read().decode("utf-8", errors="replace")
            assert not any(value in server_output for value in hidden), "A secret appeared in the API log."
            assert "eyJ" not in server_output, "A JWT-shaped value appeared in the API log."
    finally:
        _stop(frontend_process)
        _stop(api_process)
        runtime_engine.dispose()

    with owner_engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM users WHERE id = :id"), {"id": disabled_id}
        ).scalar_one()
    assert status == "DISABLED"
