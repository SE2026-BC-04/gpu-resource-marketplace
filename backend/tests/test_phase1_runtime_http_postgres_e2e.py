"""Real HTTP Phase 1 happy path using the production app and disposable PostgreSQL.

The database fixtures refuse to run unless the target cluster is explicitly marked disposable.
This test connects the app as the native ``gpm_api_app`` login, not an owner session or fake
repository, and exercises Worker Login → Listing → Client Login → Submit/View/Cancel.
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from gpu_marketplace.common.db_roles import bootstrap_roles
from gpu_marketplace.identity.passwords import ScryptPasswordHasher

BACKEND_ROOT = Path(__file__).resolve().parents[1]
API_LOGIN = "gpm_api_app"
PASSWORD = "phase1-e2e-test-password"
JWT_SECRET = "phase1-e2e-jwt-secret-32-bytes-minimum-value"
LISTING_CURSOR_SECRET = "phase1-e2e-listing-cursor-secret-32-bytes"
JOBS_CURSOR_SECRET = "phase1-e2e-jobs-cursor-secret-32-bytes"


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


def test_worker_client_job_lifecycle_over_http_and_native_runtime_role(
    migrated_database_with_teardown: Engine,
    test_database,
) -> None:
    owner_engine = migrated_database_with_teardown
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

    port = _free_loopback_port()
    process_environment = os.environ.copy()
    process_environment.update(
        {
            "GPU_MARKETPLACE_API_HOST": "127.0.0.1",
            "GPU_MARKETPLACE_API_PORT": str(port),
            "GPU_MARKETPLACE_DATABASE_URL": runtime_url,
            "GPU_MARKETPLACE_JWT_SECRET": JWT_SECRET,
            "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": LISTING_CURSOR_SECRET,
            "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": JOBS_CURSOR_SECRET,
            "GPU_MARKETPLACE_CORS_ORIGINS": '["http://127.0.0.1:5173"]',
        }
    )
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile() as server_log:
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

                replay = client.post("/api/v1/jobs", headers=submit_headers, json=request)
                assert replay.status_code == 200, replay.text
                assert replay.json()["id"] == job["id"]
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

            with owner_engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT j.status, j.terminal_at, count(sr.job_id) AS reference_count "
                        "FROM jobs AS j JOIN simulation_references AS sr ON sr.job_id = j.id "
                        "WHERE j.client_id = :client_id GROUP BY j.id"
                    ),
                    {"client_id": client_id},
                ).mappings().all()
            assert len(rows) == 1
            assert rows[0]["status"] == "CANCELLED"
            assert rows[0]["terminal_at"] is not None
            assert rows[0]["reference_count"] == 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            runtime_engine.dispose()
