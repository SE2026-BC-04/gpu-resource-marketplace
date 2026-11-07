"""Exercise the production API and frontend against a disposable PostgreSQL database.

The database fixtures refuse to run unless the target cluster is explicitly marked disposable.
This test connects the app as the native ``gpm_api_app`` login, not an owner session or fake
repository, and verifies the Worker → Listing → Client → Job lifecycle through HTTP and a browser.
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
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from gpu_marketplace.common.db_roles import bootstrap_roles
from gpu_marketplace.identity.passwords import ScryptPasswordHasher
from role_credentials import restored_login_role_credentials

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"
API_LOGIN = "gpm_api_app"
PASSWORD = "phase1-e2e-test-password"
JWT_SECRET = "phase1-e2e-jwt-secret-32-bytes-minimum-value"
LISTING_CURSOR_SECRET = "phase1-e2e-listing-cursor-secret-32-bytes"
JOBS_CURSOR_SECRET = "phase1-e2e-jobs-cursor-secret-32-bytes"
TEST_DATABASE_ENV_KEYS = (
    "GPU_MARKETPLACE_TEST_DATABASE_URL",
    "GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS",
    "GPU_MARKETPLACE_TEST_CLUSTER_TOKEN",
    "GPM_CI_PGPASSWORD",
)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _login(client: httpx.Client, name: str) -> tuple[str, dict[str, object]]:
    response = client.post(
        "/api/v1/auth/login",
        json={"login_name": name, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["login_name"] == name
    return body["access_token"], body["user"]


@pytest.fixture
def restored_e2e_role_credentials(
    migrated_database_with_teardown: Engine,
) -> Iterator[Engine]:
    """Restore both cluster-wide native login verifiers after all E2E processes stop."""
    with restored_login_role_credentials(migrated_database_with_teardown):
        yield migrated_database_with_teardown


def test_worker_client_job_lifecycle_over_http_browser_and_native_runtime_role(
    restored_e2e_role_credentials: Engine,
    test_database,
) -> None:
    owner_engine = restored_e2e_role_credentials
    api_password = secrets.token_hex(32)
    manager_password = secrets.token_hex(32)
    with owner_engine.begin() as connection:
        # Both the target URL and cluster have already passed db_safety's disposable markers.
        bootstrap_roles(
            connection,
            api_password,
            manager_password,
            rotate_password=True,
        )

    worker_id = uuid4()
    client_id = uuid4()
    worker_profile_id = uuid4()
    hasher = ScryptPasswordHasher()
    password_hash = hasher.hash_password(PASSWORD)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, login_name, password_hash, status) "
                "VALUES (:id, :name, :password_hash, 'ACTIVE')"
            ),
            {"id": worker_id, "name": f"e2e-worker-{worker_id.hex}", "password_hash": password_hash},
        )
        connection.execute(
            text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'WORKER')"),
            {"id": worker_id},
        )
        connection.execute(
            text("INSERT INTO workers (id, user_id, display_name) VALUES (:id, :user_id, 'E2E Worker')"),
            {"id": worker_profile_id, "user_id": worker_id},
        )
        connection.execute(
            text(
                "INSERT INTO users (id, login_name, password_hash, status) "
                "VALUES (:id, :name, :password_hash, 'ACTIVE')"
            ),
            {"id": client_id, "name": f"e2e-client-{client_id.hex}", "password_hash": password_hash},
        )
        connection.execute(
            text("INSERT INTO user_roles (user_id, role_code) VALUES (:id, 'CLIENT')"),
            {"id": client_id},
        )

    owner_url = make_url(test_database.url)
    runtime_url = owner_url.set(username=API_LOGIN, password=api_password).render_as_string(
        hide_password=False
    )
    runtime_engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        with runtime_engine.connect() as connection:
            identity = connection.execute(text("SELECT current_user, session_user")).one()
            privileges = connection.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
        assert tuple(identity) == (API_LOGIN, API_LOGIN)
        assert not any(privileges)
        with runtime_engine.connect() as connection:
            with pytest.raises(DBAPIError):
                connection.execute(text("SELECT seed_value FROM simulation_references LIMIT 1"))
    finally:
        # The runtime test engine is closed well before the role-restore fixture exits.
        runtime_engine.dispose()

    port = _free_loopback_port()
    frontend_port = _free_loopback_port()
    frontend_origin = f"http://127.0.0.1:{frontend_port}"
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "GPU_MARKETPLACE_API_HOST": "127.0.0.1",
            "GPU_MARKETPLACE_API_PORT": str(port),
            "GPU_MARKETPLACE_DATABASE_URL": runtime_url,
            "GPU_MARKETPLACE_JWT_SECRET": JWT_SECRET,
            "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": LISTING_CURSOR_SECRET,
            "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": JOBS_CURSOR_SECRET,
            "GPU_MARKETPLACE_CORS_ORIGINS": json.dumps([frontend_origin]),
        }
    )
    for test_secret_name in TEST_DATABASE_ENV_KEYS:
        process_environment.pop(test_secret_name, None)
    base_url = f"http://127.0.0.1:{port}"
    node_binary = shutil.which("node")
    assert node_binary is not None, "Node.js is required for the browser E2E test."
    vite_cli = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    playwright_cli = FRONTEND_ROOT / "node_modules" / "@playwright" / "test" / "cli.js"
    assert vite_cli.is_file(), "Install the frontend dependencies with npm ci before the PostgreSQL E2E test."
    assert playwright_cli.is_file(), "Install @playwright/test with npm ci before the PostgreSQL E2E test."

    frontend_environment = os.environ.copy()
    for test_secret_name in TEST_DATABASE_ENV_KEYS:
        frontend_environment.pop(test_secret_name, None)
    frontend_environment["VITE_API_BASE_URL"] = base_url
    build = subprocess.run(
        [node_binary, str(vite_cli), "build"],
        cwd=FRONTEND_ROOT,
        env=frontend_environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert build.returncode == 0, (
        "Production frontend build failed before browser E2E:\n"
        f"{build.stdout}\n{build.stderr}"
    )

    frontend_process: subprocess.Popen[bytes] | None = None
    with tempfile.TemporaryFile() as server_log, tempfile.TemporaryFile() as frontend_log:
        process = subprocess.Popen(
            [sys.executable, "-m", "gpu_marketplace.api"],
            cwd=BACKEND_ROOT,
            env=process_environment,
            stdout=server_log,
            stderr=server_log,
        )
        try:
            with httpx.Client(base_url=base_url, timeout=5.0, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        server_log.seek(0)
                        detail = server_log.read().decode("utf-8", errors="replace")
                        for secret in (api_password, manager_password, runtime_url, JWT_SECRET):
                            detail = detail.replace(secret, "[REDACTED]")
                        raise AssertionError(
                            f"Production API exited before readiness (exit={process.returncode}):\n{detail}"
                        )
                    try:
                        ready = client.get("/health/ready")
                        if ready.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise AssertionError("Production API did not become ready within 30 seconds")
                    time.sleep(0.25)

                worker_name = f"e2e-worker-{worker_id.hex}"
                client_name = f"e2e-client-{client_id.hex}"
                worker_token, worker_user = _login(client, worker_name)
                assert worker_user["role"] == "WORKER"
                worker_headers = {"Authorization": f"Bearer {worker_token}"}
                listing_response = client.post(
                    "/api/v1/gpu-listings",
                    headers=worker_headers,
                    json={
                        "gpu_model": "E2E Test GPU",
                        "vram_gb": 80,
                        "total_gpu_count": 4,
                    },
                )
                assert listing_response.status_code == 201, listing_response.text
                listing = listing_response.json()
                assert listing["status"] == "ACTIVE"
                assert listing["worker"]["id"] == str(worker_profile_id)
                listing_updated_response = client.patch(
                    f"/api/v1/gpu-listings/{listing['id']}",
                    headers=worker_headers,
                    json={"gpu_model": "E2E Test GPU Updated"},
                )
                assert listing_updated_response.status_code == 200
                assert listing_updated_response.json()["gpu_model"] == "E2E Test GPU Updated"
                assert client.post("/api/v1/auth/logout", headers=worker_headers).status_code == 204

                client_token, client_user = _login(client, client_name)
                assert client_user["role"] == "CLIENT"
                client_headers = {"Authorization": f"Bearer {client_token}"}
                browse = client.get("/api/v1/gpu-listings", headers=client_headers)
                assert browse.status_code == 200, browse.text
                assert [item["id"] for item in browse.json()["items"]] == [listing["id"]]

                request = {
                    "listing_id": listing["id"],
                    "gpu_count": 2,
                    "duration_seconds": 60,
                }
                submit_headers = {**client_headers, "Idempotency-Key": f"phase1-{uuid4()}"}
                submitted = client.post(
                    "/api/v1/jobs", headers=submit_headers, json=request
                )
                assert submitted.status_code == 201, submitted.text
                job = submitted.json()
                assert job["status"] == "QUEUED"
                assert job["listing_id"] == listing["id"]
                assert job["worker_id"] == str(worker_profile_id)
                assert all(
                    secret not in submitted.text
                    for secret in ("seed_value", "expected_digest", "simulation_references")
                )

                rejected_listing_update = client.patch(
                    f"/api/v1/gpu-listings/{listing['id']}",
                    headers=worker_headers,
                    json={"total_gpu_count": 1},
                )
                assert rejected_listing_update.status_code == 409

                replay = client.post("/api/v1/jobs", headers=submit_headers, json=request)
                assert replay.status_code == 200, replay.text
                assert replay.json()["id"] == job["id"]

                paused = client.post(
                    f"/api/v1/gpu-listings/{listing['id']}/pause",
                    headers=worker_headers,
                )
                assert paused.status_code == 200, paused.text
                retained_replay = client.post(
                    "/api/v1/jobs", headers=submit_headers, json=request
                )
                assert retained_replay.status_code == 200, retained_replay.text
                assert retained_replay.json()["id"] == job["id"]
                changed_replay = client.post(
                    "/api/v1/jobs",
                    headers=submit_headers,
                    json={**request, "duration_seconds": 61},
                )
                assert changed_replay.status_code == 409
                new_paused_submit = client.post(
                    "/api/v1/jobs",
                    headers={**client_headers, "Idempotency-Key": f"phase1-{uuid4()}"},
                    json=request,
                )
                assert new_paused_submit.status_code == 409
                resumed = client.post(
                    f"/api/v1/gpu-listings/{listing['id']}/resume",
                    headers=worker_headers,
                )
                assert resumed.status_code == 200, resumed.text
                paused_again = client.post(
                    f"/api/v1/gpu-listings/{listing['id']}/pause",
                    headers=worker_headers,
                )
                assert paused_again.status_code == 200, paused_again.text
                jobs = client.get("/api/v1/jobs", headers=client_headers)
                assert jobs.status_code == 200, jobs.text
                assert [item["id"] for item in jobs.json()["items"]] == [job["id"]]
                detail = client.get(f"/api/v1/jobs/{job['id']}", headers=client_headers)
                assert detail.status_code == 200 and detail.json()["status"] == "QUEUED"

                cancelled = client.post(
                    f"/api/v1/jobs/{job['id']}/cancel", headers=client_headers
                )
                assert cancelled.status_code == 200, cancelled.text
                assert cancelled.json()["status"] == "CANCELLED"
                assert cancelled.json()["terminal_at"] is not None
                final = client.get(f"/api/v1/jobs/{job['id']}", headers=client_headers)
                assert final.status_code == 200
                assert final.json()["status"] == "CANCELLED"
                cancel_rejected = client.post(
                    f"/api/v1/jobs/{job['id']}/cancel", headers=client_headers
                )
                assert cancel_rejected.status_code == 409

                frontend_url = frontend_origin
                frontend_process = subprocess.Popen(
                    [
                        node_binary,
                        str(vite_cli),
                        "preview",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(frontend_port),
                        "--strictPort",
                    ],
                    cwd=FRONTEND_ROOT,
                    env=frontend_environment,
                    stdout=frontend_log,
                    stderr=frontend_log,
                )
                frontend_deadline = time.monotonic() + 30
                with httpx.Client(timeout=2.0, trust_env=False) as frontend_probe:
                    while True:
                        if frontend_process.poll() is not None:
                            frontend_log.seek(0)
                            details = frontend_log.read().decode("utf-8", errors="replace")
                            raise AssertionError(
                                "Production frontend preview exited before readiness "
                                f"(exit={frontend_process.returncode}):\n{details}"
                            )
                        try:
                            preview = frontend_probe.get(frontend_url)
                            if preview.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if time.monotonic() >= frontend_deadline:
                            raise AssertionError(
                                "Production frontend preview did not become ready within 30 seconds"
                            )
                        time.sleep(0.25)

                with tempfile.TemporaryDirectory(prefix="gpu-marketplace-browser-e2e-") as result_directory:
                    browser_result_path = Path(result_directory) / "browser-result.json"
                    browser_environment = os.environ.copy()
                    for test_secret_name in TEST_DATABASE_ENV_KEYS:
                        browser_environment.pop(test_secret_name, None)
                    browser_environment.update(
                        {
                            "PHASE1_E2E_BASE_URL": frontend_url,
                            "PHASE1_E2E_WORKER_LOGIN": worker_name,
                            "PHASE1_E2E_CLIENT_LOGIN": client_name,
                            "PHASE1_E2E_PASSWORD": PASSWORD,
                            "PHASE1_E2E_RESULT_PATH": str(browser_result_path),
                        }
                    )
                    browser_run = subprocess.run(
                        [
                            node_binary,
                            str(playwright_cli),
                            "test",
                            "--config=playwright.config.ts",
                            "e2e/phase1-runtime.spec.ts",
                        ],
                        cwd=FRONTEND_ROOT,
                        env=browser_environment,
                        capture_output=True,
                        text=True,
                        timeout=240,
                        check=False,
                    )
                    assert browser_run.returncode == 0, (
                        "Browser E2E failed "
                        f"(exit={browser_run.returncode}):\n{browser_run.stdout}\n{browser_run.stderr}"
                    )
                    assert browser_result_path.is_file(), (
                        "Browser E2E did not produce its database-verification result."
                    )
                    browser_result = json.loads(browser_result_path.read_text(encoding="utf-8"))
                    assert browser_result["listingId"] != listing["id"]

            with owner_engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT j.id, j.status, j.terminal_at, count(sr.job_id) AS reference_count "
                        "FROM jobs AS j JOIN simulation_references AS sr ON sr.job_id = j.id "
                        "WHERE j.client_id = :client_id AND j.id IN (:http_job_id, :browser_job_id) "
                        "GROUP BY j.id"
                    ),
                    {
                        "client_id": client_id,
                        "http_job_id": UUID(job["id"]),
                        "browser_job_id": UUID(browser_result["jobId"]),
                    },
                ).mappings().all()
            assert {str(row["id"]) for row in rows} == {job["id"], browser_result["jobId"]}
            assert all(row["status"] == "CANCELLED" for row in rows)
            assert all(row["terminal_at"] is not None for row in rows)
            assert all(row["reference_count"] == 1 for row in rows)
            with owner_engine.connect() as connection:
                audit_rows = connection.execute(
                    text(
                        "SELECT actor_kind, actor_ref, correlation_id, subject_type, subject_id, "
                        "event_type, outcome, created_at, metadata_redacted "
                        "FROM audit_events WHERE subject_id = ANY(CAST(:subject_ids AS uuid[])) "
                        "ORDER BY created_at, id"
                    ),
                    {
                        "subject_ids": [
                            UUID(listing["id"]),
                            UUID(job["id"]),
                            UUID(browser_result["jobId"]),
                        ]
                    },
                ).mappings().all()
            def events(subject_id: str, event_type: str, outcome: str) -> list[object]:
                return [
                    row
                    for row in audit_rows
                    if str(row["subject_id"]) == subject_id
                    and row["event_type"] == event_type
                    and row["outcome"] == outcome
                ]

            listing_created = events(listing["id"], "LISTING_CREATE", "SUCCESS")
            listing_updated = events(listing["id"], "LISTING_UPDATE", "SUCCESS")
            rejected_listing_updates = events(listing["id"], "LISTING_UPDATE", "REJECTED")
            listing_paused = events(listing["id"], "LISTING_PAUSE", "SUCCESS")
            listing_resumed = events(listing["id"], "LISTING_RESUME", "SUCCESS")
            assert len(listing_created) == 1
            assert len(listing_updated) == 1
            assert len(rejected_listing_updates) == 1
            assert len(listing_paused) == 2
            assert len(listing_resumed) == 1
            assert str(listing_created[0]["correlation_id"]) == (
                listing_response.headers["X-Request-ID"]
            )
            assert str(listing_updated[0]["correlation_id"]) == (
                listing_updated_response.headers["X-Request-ID"]
            )
            assert str(rejected_listing_updates[0]["correlation_id"]) == (
                rejected_listing_update.headers["X-Request-ID"]
            )
            assert {str(row["correlation_id"]) for row in listing_paused} == {
                paused.headers["X-Request-ID"], paused_again.headers["X-Request-ID"]
            }
            assert str(listing_resumed[0]["correlation_id"]) == resumed.headers["X-Request-ID"]
            assert rejected_listing_updates[0]["metadata_redacted"] == {
                "reason_code": "LISTING_CAPACITY_BELOW_QUEUED_MAX"
            }
            assert len(events(job["id"], "JOB_SUBMIT", "SUCCESS")) == 1
            rejected_submits = events(listing["id"], "JOB_SUBMIT", "REJECTED")
            job_cancelled = events(job["id"], "JOB_CANCEL", "SUCCESS")
            rejected_cancels = events(job["id"], "JOB_CANCEL", "REJECTED")
            browser_submitted = events(browser_result["jobId"], "JOB_SUBMIT", "SUCCESS")
            browser_cancelled = events(browser_result["jobId"], "JOB_CANCEL", "SUCCESS")
            assert len(rejected_submits) == 2
            assert len(job_cancelled) == 1
            assert len(rejected_cancels) == 1
            assert len(browser_submitted) == 1
            assert len(browser_cancelled) == 1
            assert {str(row["correlation_id"]) for row in rejected_submits} == {
                changed_replay.headers["X-Request-ID"],
                new_paused_submit.headers["X-Request-ID"],
            }
            assert str(job_cancelled[0]["correlation_id"]) == cancelled.headers["X-Request-ID"]
            assert str(rejected_cancels[0]["correlation_id"]) == (
                cancel_rejected.headers["X-Request-ID"]
            )
            for audit_row in audit_rows:
                assert audit_row["actor_kind"] == "USER"
                assert audit_row["actor_ref"] in {str(worker_id), str(client_id)}
                assert audit_row["correlation_id"] is not None
                assert audit_row["created_at"] is not None
                metadata = audit_row["metadata_redacted"]
                assert not set(metadata) & {
                    "password", "token", "authorization", "dsn", "secret",
                    "seed_value", "expected_digest", "simulation_reference",
                    "idempotency_key", "request_sha256", "raw_body",
                }
        finally:
            if frontend_process is not None and frontend_process.poll() is None:
                frontend_process.terminate()
                try:
                    frontend_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    frontend_process.kill()
                    frontend_process.wait(timeout=10)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
