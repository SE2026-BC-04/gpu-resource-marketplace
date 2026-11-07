"""Run an isolated five-service smoke project and verify public boundaries."""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg


ROOT = Path(__file__).resolve().parents[1]
PROJECT = f"gpu-marketplace-smoke-{uuid.uuid4().hex}"
LOCAL_PROJECT = "gpu-resource-marketplace"
EXPECTED_SERVICES = {"frontend", "api", "manager", "simulator", "postgres"}


def compose(
    env_file: Path,
    project: str,
    *args: str,
    process_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    # Docker Compose gives the caller's process environment precedence over --env-file.
    # Clear keys defined by the isolated smoke file so ambient CI/local secrets or port
    # overrides cannot leak into the smoke project. Explicit per-command overrides are
    # applied last (for example the disposable owner DSN used only by Alembic).
    for name in read_env_values(env_file):
        child_env.pop(name, None)
    if process_env:
        child_env.update(process_env)
    return subprocess.run(
        [
            "docker", "compose", "--env-file", str(env_file),
            "-p", project, "-f", "compose.yaml", *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=child_env,
    )


def docker_resource_ids(project: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return container, network and volume identities carrying a Compose project label."""
    resources: list[tuple[str, ...]] = []
    for resource, format_string in (
        ("ps -a", "{{.ID}}"),
        ("network ls", "{{.ID}}"),
        ("volume ls", "{{.Name}}"),
    ):
        command = ["docker", *resource.split(), "--filter", f"label=com.docker.compose.project={project}", "--format", format_string]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Could not inspect Docker {resource} for project {project}: {result.stderr.strip()}")
        resources.append(tuple(sorted(line.strip() for line in result.stdout.splitlines() if line.strip())))
    return resources[0], resources[1], resources[2]


def parse_services(raw: str) -> list[dict[str, object]]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def available_port(used: set[int]) -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in used:
            used.add(port)
            return port


def make_smoke_env_file(values: dict[str, str | int]) -> Path:
    source = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^{re.escape(name)}=.*$")
        replacement = f"{name}={value}"
        source, replacements = pattern.subn(replacement, source)
        if replacements == 0:
            source = f"{source.rstrip()}\n{replacement}\n"

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", prefix="gpu-marketplace-smoke-",
        suffix=".env", delete=False,
    ) as env_file:
        env_file.write(source)
        return Path(env_file.name)


def read_env_values(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def check_http(url: str) -> bytes:
    last_error: OSError | None = None
    for _ in range(10):
        try:
            with urlopen(url, timeout=8) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP check failed for {url}: status {response.status}")
                return response.read()
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Host HTTP check failed for {url}: {last_error}") from last_error


def http_response(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=8) as response:
            response_headers = {name.lower(): value for name, value in response.headers.items()}
            return response.status, response_headers, response.read()
    except HTTPError as response:
        response_headers = {name.lower(): value for name, value in response.headers.items()}
        return response.code, response_headers, response.read()


def expect_http_status(
    url: str,
    expected: int,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, str], bytes]:
    last_error: OSError | None = None
    for _ in range(20):
        try:
            status, response_headers, response_body = http_response(
                url, method=method, body=body, headers=headers
            )
            if status != expected:
                raise RuntimeError(f"HTTP check failed for {url}: expected {expected}, received {status}")
            return response_headers, response_body
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"HTTP check could not reach {url}: {type(last_error).__name__}")


def require_compose_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode:
        # Compose stderr may echo environment values; report only the operation and exit code.
        raise RuntimeError(f"Smoke-only {action} failed (exit {result.returncode})")


def verify_runtime_role(env_file: Path, service: str, expected_role: str) -> None:
    probe = (
        "import os; from sqlalchemy import create_engine, text; "
        "engine=create_engine(os.environ['GPU_MARKETPLACE_DATABASE_URL']); "
        "connection=engine.connect(); "
        "row=connection.execute(text(\"SELECT current_user, session_user, "
        "(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()), "
        "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls "
        " FROM pg_roles WHERE rolname=current_user), "
        "has_database_privilege(current_user,current_database(),'CREATE'), "
        "has_schema_privilege(current_user,'public','CREATE')\")).one(); "
        "connection.close(); engine.dispose(); "
        f"assert row[0] == '{expected_role}' and row[1] == '{expected_role}' and "
        "row[2] != row[0] and not any(row[3:]), 'runtime role privilege check failed'; "
        "print('runtime_role_ok')"
    )
    result = compose(env_file, PROJECT, "exec", "--no-TTY", service, "python", "-c", probe)
    if result.returncode or result.stdout.strip() != "runtime_role_ok":
        raise RuntimeError(f"{service} runtime database-role verification failed")


def verify_runtime_roles_from_host(port: int, env_file: Path) -> None:
    """Run the README's native-login verifier through the isolated loopback host port."""
    values = read_env_values(env_file)
    process_env = os.environ.copy()
    process_env.update(
        {
            "POSTGRES_DB": values["POSTGRES_DB"],
            "POSTGRES_HOST_PORT": str(port),
            "GPU_MARKETPLACE_API_DATABASE_URL": values["GPU_MARKETPLACE_API_DATABASE_URL"],
            "GPU_MARKETPLACE_MANAGER_DATABASE_URL": values["GPU_MARKETPLACE_MANAGER_DATABASE_URL"],
        }
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_runtime_roles.py")],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )
    expected = (
        "PASS: API native session_user and restricted privileges verified\n"
        "PASS: Manager native session_user and restricted privileges verified"
    )
    if result.returncode or result.stdout.strip() != expected:
        raise RuntimeError("Host native API/Manager runtime-role verification failed")


def create_restart_persistence_marker(port: int, env_file: Path) -> str:
    """Commit a synthetic Client row to the isolated smoke DB before Compose recreation."""
    values = read_env_values(env_file)
    login_name = f"restart-smoke-{uuid.uuid4().hex}"
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname=values["POSTGRES_DB"],
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            connect_timeout=5,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (login_name, password_hash, status) "
                    "VALUES (%s, %s, 'ACTIVE') RETURNING id",
                    (login_name, "scrypt$compose-restart-smoke-marker"),
                )
                user_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO user_roles (user_id, role_code) VALUES (%s, 'CLIENT')",
                    (user_id,),
                )
    except Exception as exc:
        raise RuntimeError(f"Could not commit Compose restart marker ({type(exc).__name__})") from None
    return login_name


def verify_restart_persistence(port: int, env_file: Path, login_name: str) -> None:
    """Read the committed marker after Compose down/up without deleting the named volume."""
    values = read_env_values(env_file)
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname=values["POSTGRES_DB"],
            user=values["POSTGRES_USER"],
            password=values["POSTGRES_PASSWORD"],
            connect_timeout=5,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM users AS u "
                    "JOIN user_roles AS ur ON ur.user_id = u.id "
                    "WHERE u.login_name = %s AND ur.role_code = 'CLIENT'",
                    (login_name,),
                )
                count = cursor.fetchone()[0]
    except Exception as exc:
        raise RuntimeError(f"Could not verify Compose restart marker ({type(exc).__name__})") from None
    if count != 1:
        raise RuntimeError("Committed smoke data was not preserved after Compose recreation")


def published_host_port(
    services: list[dict[str, object]], service_name: str, container_port: int, project: str
) -> int:
    service = next(
        (
            item for item in services
            if item.get("Service") == service_name
            or item.get("Name") == f"{project}-{service_name}-1"
        ),
        None,
    )
    if service is None:
        raise RuntimeError(f"Could not inspect running Compose service {service_name}: {services}")

    publishers = service.get("Publishers")
    if isinstance(publishers, list):
        for publisher in publishers:
            if not isinstance(publisher, dict) or int(publisher.get("TargetPort", -1)) != container_port:
                continue
            if publisher.get("URL") != "127.0.0.1":
                raise RuntimeError(f"{service_name} is not bound to loopback only: {publisher}")
            return int(publisher["PublishedPort"])

    # Retain compatibility with Compose versions that expose a Ports string instead
    # of the structured Publishers array in `ps --format json`.
    ports_text = str(service.get("Ports", ""))
    match = re.search(rf"127\.0\.0\.1:(\d+)->{container_port}/tcp", ports_text)
    if match:
        return int(match.group(1))
    raise RuntimeError(
        f"No loopback host mapping found for {service_name}:{container_port}; service state: {service}"
    )


def check_postgres_from_host(port: int, env_file: Path) -> None:
    config = read_env_values(env_file)
    last_error = "no connection attempt"
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=3):
                pass
            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                dbname=config["POSTGRES_DB"],
                user=config["POSTGRES_USER"],
                password=config["POSTGRES_PASSWORD"],
                connect_timeout=3,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    if cursor.fetchone() != (1,):
                        raise RuntimeError("Host PostgreSQL SELECT 1 returned an unexpected result")
            return
        except (OSError, psycopg.OperationalError) as exc:
            # Do not include connection exception text, which can contain DSN details.
            last_error = type(exc).__name__
            time.sleep(0.5)
    raise RuntimeError(f"Host PostgreSQL SELECT 1 failed on the allocated loopback port ({last_error})")


def main() -> int:
    smoke_env: Path | None = None
    inspect_env: Path | None = None
    smoke_project_created = False
    local_resources_before: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None = None
    exit_code = 1
    try:
        # Inspect the normal local project first. It is never started, stopped, or cleaned here.
        # Compose validates required interpolation even for `ps`; this one-use key only
        # renders the existing project config and is never passed to a started service.
        inspect_env = make_smoke_env_file(
            {
                "GPU_MARKETPLACE_JWT_SECRET": secrets.token_hex(32),
                "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": secrets.token_hex(32),
                "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": secrets.token_hex(32),
            }
        )
        local = compose(inspect_env, LOCAL_PROJECT, "ps", "--all", "--format", "json")
        if local.returncode:
            raise RuntimeError(f"Could not inspect the existing local Compose stack: {local.stderr.strip()}")
        local_services = parse_services(local.stdout)
        local_resources_before = docker_resource_ids(LOCAL_PROJECT)
        running_local = [
            str(service.get("Service") or service.get("Name"))
            for service in local_services
            if service.get("State") == "running"
        ]
        if running_local:
            print(f"Existing local stack detected ({', '.join(running_local)}); smoke uses separate host ports.")
        else:
            print("No running default local stack detected before smoke startup.")

        # Reserve distinct loopback ports dynamically so the smoke stack cannot claim
        # the developer defaults 5173, 8000, or 5432.
        used_ports: set[int] = set()
        ports = {
            "FRONTEND_HOST_PORT": available_port(used_ports),
            "API_HOST_PORT": available_port(used_ports),
            "POSTGRES_HOST_PORT": available_port(used_ports),
        }
        print(f"Smoke host ports reserved: {ports}", flush=True)
        database_name = "gpu_marketplace_smoke"
        owner_password = secrets.token_hex(24)
        api_password = secrets.token_hex(24)
        manager_password = secrets.token_hex(24)
        owner_database_url = (
            f"postgresql+psycopg://gpu_marketplace:{owner_password}@postgres:5432/{database_name}"
        )
        api_database_url = f"postgresql+psycopg://gpm_api_app:{api_password}@postgres:5432/{database_name}"
        manager_database_url = (
            f"postgresql+psycopg://gpm_manager_app:{manager_password}@postgres:5432/{database_name}"
        )
        smoke_env = make_smoke_env_file(
            {
                **ports,
                "POSTGRES_DB": database_name,
                "POSTGRES_USER": "gpu_marketplace",
                "POSTGRES_PASSWORD": owner_password,
                "GPU_MARKETPLACE_API_DATABASE_URL": api_database_url,
                "GPU_MARKETPLACE_MANAGER_DATABASE_URL": manager_database_url,
                "GPU_MARKETPLACE_JWT_SECRET": secrets.token_hex(32),
                "GPU_MARKETPLACE_LISTING_CURSOR_SECRET": secrets.token_hex(32),
                "GPU_MARKETPLACE_JOBS_CURSOR_SECRET": secrets.token_hex(32),
                "GPU_MARKETPLACE_CORS_ORIGINS": f'["http://localhost:{ports["FRONTEND_HOST_PORT"]}"]',
            }
        )

        rendered = compose(smoke_env, PROJECT, "config", "--format", "json")
        if rendered.returncode:
            raise RuntimeError(f"Compose config validation failed: {rendered.stderr.strip()}")
        rendered_config = json.loads(rendered.stdout)
        expected_api_url = f"http://localhost:{ports['API_HOST_PORT']}"
        configured_api_url = rendered_config["services"]["frontend"]["build"]["args"]["VITE_API_BASE_URL"]
        if configured_api_url != expected_api_url:
            raise RuntimeError(
                f"Frontend build-time API URL {configured_api_url!r} does not match API host port {expected_api_url!r}"
            )
        expected_origins = f'["http://localhost:{ports["FRONTEND_HOST_PORT"]}"]'
        configured_origins = rendered_config["services"]["api"]["environment"]["GPU_MARKETPLACE_CORS_ORIGINS"]
        if configured_origins != expected_origins:
            raise RuntimeError(
                f"API CORS origins {configured_origins!r} do not match isolated frontend origin {expected_origins!r}"
            )
        smoke_values = read_env_values(smoke_env)
        api_environment = rendered_config["services"]["api"]["environment"]
        if (
            api_environment["GPU_MARKETPLACE_LISTING_CURSOR_SECRET"]
            != smoke_values["GPU_MARKETPLACE_LISTING_CURSOR_SECRET"]
            or smoke_values["GPU_MARKETPLACE_LISTING_CURSOR_SECRET"]
            == smoke_values["GPU_MARKETPLACE_JWT_SECRET"]
        ):
            raise RuntimeError("API did not receive a separate Listing cursor secret")
        if (
            api_environment["GPU_MARKETPLACE_JOBS_CURSOR_SECRET"]
            != smoke_values["GPU_MARKETPLACE_JOBS_CURSOR_SECRET"]
            or smoke_values["GPU_MARKETPLACE_JOBS_CURSOR_SECRET"]
            in {
                smoke_values["GPU_MARKETPLACE_JWT_SECRET"],
                smoke_values["GPU_MARKETPLACE_LISTING_CURSOR_SECRET"],
            }
        ):
            raise RuntimeError("API did not receive a separate Jobs cursor secret")
        if (
            rendered_config["services"]["api"]["environment"]["GPU_MARKETPLACE_DATABASE_URL"]
            != smoke_values["GPU_MARKETPLACE_API_DATABASE_URL"]
        ):
            raise RuntimeError("API container did not receive its API-specific database URL")
        if (
            rendered_config["services"]["manager"]["environment"]["GPU_MARKETPLACE_DATABASE_URL"]
            != smoke_values["GPU_MARKETPLACE_MANAGER_DATABASE_URL"]
        ):
            raise RuntimeError("Manager container did not receive its Manager-specific database URL")
        for service_name, target, host_port in (
            ("frontend", 5173, ports["FRONTEND_HOST_PORT"]),
            ("api", 8000, ports["API_HOST_PORT"]),
            ("postgres", 5432, ports["POSTGRES_HOST_PORT"]),
        ):
            mappings = rendered_config["services"][service_name].get("ports", [])
            mapping = next((item for item in mappings if int(item["target"]) == target), None)
            if (
                mapping is None
                or int(mapping.get("published", -1)) != host_port
                or mapping.get("host_ip") != "127.0.0.1"
            ):
                raise RuntimeError(
                    f"Compose {service_name} port mapping is not the requested isolated loopback port: {mappings}"
                )

        # A UUID project name plus an all-resource emptiness check prevents cleanup
        # from targeting any pre-existing containers, networks, or named volumes.
        if any(docker_resource_ids(PROJECT)):
            raise RuntimeError(f"Refusing to reuse non-empty smoke project {PROJECT}")

        smoke_project_created = True
        require_compose_success(
            compose(smoke_env, PROJECT, "up", "--detach", "--wait", "--wait-timeout", "120", "postgres"),
            "PostgreSQL startup",
        )
        bootstrap_environment = {
            "GPU_MARKETPLACE_MIGRATION_DATABASE_URL": owner_database_url,
            "GPU_MARKETPLACE_API_DB_PASSWORD": api_password,
            "GPU_MARKETPLACE_MANAGER_DB_PASSWORD": manager_password,
        }
        require_compose_success(
            compose(
                smoke_env,
                PROJECT,
                "run",
                "--rm",
                "--no-deps",
                "--env",
                "GPU_MARKETPLACE_MIGRATION_DATABASE_URL",
                "--env",
                "GPU_MARKETPLACE_API_DB_PASSWORD",
                "--env",
                "GPU_MARKETPLACE_MANAGER_DB_PASSWORD",
                "api",
                "python",
                "-m",
                "gpu_marketplace.common.db_roles",
                process_env=bootstrap_environment,
            ),
            "disposable D1 role bootstrap",
        )

        # Bring up only the API before migrations. It must stay unready and return a
        # sanitized dependency error until the Auth tables exist.
        require_compose_success(
            compose(smoke_env, PROJECT, "up", "--build", "--detach", "api"),
            "API startup before schema provisioning",
        )
        api_url = f"http://127.0.0.1:{ports['API_HOST_PORT']}"
        _, unready_body = expect_http_status(f"{api_url}/health/ready", 503)
        unready = json.loads(unready_body)
        if unready != {
            "status": "not_ready",
            "components": {"database": "ok", "auth_schema": "unavailable"},
        }:
            raise RuntimeError(f"API readiness did not identify the missing Auth schema: {unready}")
        _, missing_schema_login = expect_http_status(
            f"{api_url}/api/v1/auth/login",
            503,
            method="POST",
            body=json.dumps({"login_name": "smoke-no-account", "password": "smoke-only-password"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        if json.loads(missing_schema_login).get("error", {}).get("code") != "DEPENDENCY_UNAVAILABLE":
            raise RuntimeError("Auth route did not fail closed while its schema was missing")

        require_compose_success(
            compose(
                smoke_env,
                PROJECT,
                "run",
                "--rm",
                "--no-deps",
                "--env",
                "GPU_MARKETPLACE_DATABASE_URL",
                "api",
                "python",
                "-m",
                "alembic",
                "upgrade",
                "head",
                process_env={"GPU_MARKETPLACE_DATABASE_URL": owner_database_url},
            ),
            "disposable schema migrations",
        )

        require_compose_success(
            compose(
                smoke_env,
                PROJECT,
                "up",
                "--build",
                "--detach",
                "--wait",
                "--wait-timeout",
                "240",
            ),
            "five-service Compose startup after disposable migrations",
        )

        state_result = compose(smoke_env, PROJECT, "ps", "--format", "json")
        if state_result.returncode:
            raise RuntimeError(f"Could not read smoke service health: {state_result.stderr.strip()}")
        state = parse_services(state_result.stdout)
        observed = {
            str(service.get("Service") or str(service.get("Name", "")).removeprefix(f"{PROJECT}-"))
            for service in state
        }
        if observed != EXPECTED_SERVICES or any(
            service.get("State") != "running" or service.get("Health") != "healthy"
            for service in state
        ):
            raise RuntimeError(f"Compose services did not all become healthy: {state}")

        frontend_port = published_host_port(state, "frontend", 5173, PROJECT)
        api_port = published_host_port(state, "api", 8000, PROJECT)
        postgres_port = published_host_port(state, "postgres", 5432, PROJECT)
        if (
            frontend_port != ports["FRONTEND_HOST_PORT"]
            or api_port != ports["API_HOST_PORT"]
            or postgres_port != ports["POSTGRES_HOST_PORT"]
        ):
            raise RuntimeError(
                "Compose host-port mapping differs from the isolated build configuration: "
                f"frontend={frontend_port}, API={api_port}, PostgreSQL={postgres_port}, requested={ports}"
            )
        check_postgres_from_host(postgres_port, smoke_env)
        frontend_url = f"http://127.0.0.1:{frontend_port}"
        api_url = f"http://127.0.0.1:{api_port}"
        html = check_http(f"{frontend_url}/").decode("utf-8")
        if '<div id="root"></div>' not in html:
            raise RuntimeError("Frontend root did not serve the generated production index.html")

        # A client-side path must return the same built shell; fetch the referenced
        # bundle too so this cannot pass with a Vite error page or empty placeholder.
        spa_html = check_http(f"{frontend_url}/smoke/spa-route").decode("utf-8")
        if spa_html != html:
            raise RuntimeError("Frontend SPA route did not fall back to the production index.html")
        script = re.search(r'<script[^>]+src="([^"]+\.js)"', html)
        if not script:
            raise RuntimeError("Production index.html does not reference a built JavaScript asset")
        bundle_path = script.group(1)
        if bundle_path.startswith("/"):
            bundle_url = f"{frontend_url}{bundle_path}"
        else:
            bundle_url = f"{frontend_url}/{bundle_path}"
        bundle = check_http(bundle_url).decode("utf-8")
        if "GPU Resource Marketplace" not in bundle:
            raise RuntimeError("Frontend JavaScript response does not contain the production UI bundle")

        api = json.loads(check_http(f"{api_url}/health/live"))
        if api != {"status": "ok"}:
            raise RuntimeError(f"Backend API returned unexpected liveness response: {api}")
        readiness = json.loads(check_http(f"{api_url}/health/ready"))
        if readiness != {"status": "ready", "components": {"database": "ok"}}:
            raise RuntimeError(f"Backend API database readiness returned an unexpected response: {readiness}")

        origin = f"http://localhost:{ports['FRONTEND_HOST_PORT']}"
        auth_headers, auth_body = expect_http_status(
            f"{api_url}/api/v1/auth/login",
            401,
            method="POST",
            body=json.dumps({"login_name": "smoke-no-account", "password": "smoke-only-password"}).encode(),
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        if json.loads(auth_body).get("error", {}).get("code") != "INVALID_CREDENTIALS":
            raise RuntimeError("Mounted Auth router did not return the generic invalid-credentials response")
        if auth_headers.get("access-control-allow-origin") != origin:
            raise RuntimeError("Mounted Auth route did not return the configured CORS origin")

        verify_runtime_role(smoke_env, "api", "gpm_api_app")
        verify_runtime_role(smoke_env, "manager", "gpm_manager_app")
        verify_runtime_roles_from_host(postgres_port, smoke_env)

        manager_db = compose(
            smoke_env, PROJECT, "exec", "--no-TTY", "manager",
            "python", "-m", "gpu_marketplace.manager.healthcheck",
        )
        if manager_db.returncode:
            raise RuntimeError(f"Manager PostgreSQL readiness check failed: {manager_db.stderr.strip()}")

        run_result = compose(
            smoke_env, PROJECT, "exec", "--no-TTY", "simulator", "python", "-c",
            "import urllib.request; urllib.request.urlopen('http://api:8000/health/live', timeout=3)",
        )
        if run_result.returncode:
            raise RuntimeError(f"Simulator-to-API network check failed: {run_result.stderr.strip()}")

        probe = compose(
            smoke_env, PROJECT, "exec", "--no-TTY", "simulator", "python", "-c",
            "import socket\ntry:\n s=socket.create_connection(('postgres',5432),timeout=2)\nexcept OSError:\n print('db_network_isolated')\nelse:\n s.close()\n raise SystemExit('Simulator reached PostgreSQL')",
        )
        if probe.returncode or "db_network_isolated" not in probe.stdout:
            raise RuntimeError(f"Simulator database-isolation check failed: {probe.stderr.strip()}")

        restart_marker = create_restart_persistence_marker(postgres_port, smoke_env)
        require_compose_success(
            compose(smoke_env, PROJECT, "down", "--remove-orphans"),
            "smoke stack shutdown before persistence verification",
        )
        require_compose_success(
            compose(
                smoke_env,
                PROJECT,
                "up",
                "--build",
                "--detach",
                "--wait",
                "--wait-timeout",
                "240",
            ),
            "smoke stack recreation with its existing PostgreSQL volume",
        )
        restarted_state_result = compose(smoke_env, PROJECT, "ps", "--format", "json")
        if restarted_state_result.returncode:
            raise RuntimeError("Could not read service health after Compose recreation")
        restarted_state = parse_services(restarted_state_result.stdout)
        restarted_services = {
            str(service.get("Service") or str(service.get("Name", "")).removeprefix(f"{PROJECT}-"))
            for service in restarted_state
        }
        if restarted_services != EXPECTED_SERVICES or any(
            service.get("State") != "running" or service.get("Health") != "healthy"
            for service in restarted_state
        ):
            raise RuntimeError("Compose services did not become healthy after recreation")
        verify_runtime_role(smoke_env, "api", "gpm_api_app")
        verify_runtime_role(smoke_env, "manager", "gpm_manager_app")
        verify_runtime_roles_from_host(postgres_port, smoke_env)
        check_postgres_from_host(postgres_port, smoke_env)
        verify_restart_persistence(postgres_port, smoke_env, restart_marker)
        if json.loads(check_http(f"{api_url}/health/live")) != {"status": "ok"}:
            raise RuntimeError("Backend API was not available after Compose recreation")

        print("PASS: exactly five Compose services are running and healthy")
        print("PASS: host can fetch the production frontend index and built JavaScript bundle")
        print("PASS: frontend SPA route falls back to the production index")
        print(f"PASS: frontend image build received API host URL {expected_api_url}")
        print(f"PASS: host TCP and PostgreSQL SELECT 1 via loopback port {postgres_port}")
        print("PASS: API /health/ready and Manager healthcheck can query PostgreSQL")
        print("PASS: fresh Compose API remains unready and Auth fails closed before schema provisioning")
        print("PASS: disposable migrations enable the mounted Auth route with the approved generic 401")
        print("PASS: API and Manager connect as gpm_api_app and gpm_manager_app without CREATE privileges")
        print("PASS: host verifies native API/Manager session_user values through the loopback PostgreSQL port")
        print("PASS: host can access Backend API /health/live")
        print("PASS: Simulator can reach API but cannot resolve/connect to PostgreSQL")
        print("PASS: native API/Manager session_user values remain restricted after restart")
        print("PASS: committed Client data survives Compose down/up with its PostgreSQL volume")
        exit_code = 0
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
    finally:
        if smoke_project_created and smoke_env is not None:
            try:
                cleanup = compose(smoke_env, PROJECT, "down", "--volumes", "--remove-orphans")
                if cleanup.returncode:
                    print(f"Smoke-project cleanup failed: {cleanup.stderr.strip()}", file=sys.stderr)
                    exit_code = 1
                elif not any(docker_resource_ids(PROJECT)):
                    print("PASS: cleanup removed only smoke-project containers, networks and volumes")
                else:
                    print("FAIL: smoke-project Docker resources remain after cleanup", file=sys.stderr)
                    exit_code = 1
            except OSError as exc:
                print(f"Smoke-project cleanup unavailable: {exc}", file=sys.stderr)
                exit_code = 1
            except RuntimeError as exc:
                print(f"Smoke-project cleanup verification failed: {exc}", file=sys.stderr)
                exit_code = 1
            if local_resources_before is not None:
                try:
                    local_resources_after = docker_resource_ids(LOCAL_PROJECT)
                    if local_resources_after != local_resources_before:
                        print("FAIL: smoke cleanup changed local-stack Docker resources", file=sys.stderr)
                        exit_code = 1
                    else:
                        print("PASS: local-stack containers, networks and volumes are unchanged")
                except (OSError, RuntimeError) as exc:
                    print(f"Local-stack cleanup verification failed: {exc}", file=sys.stderr)
                    exit_code = 1
        if smoke_env is not None:
            try:
                smoke_env.unlink(missing_ok=True)
            except OSError as exc:
                print(f"Could not remove temporary smoke env file: {exc}", file=sys.stderr)
        if inspect_env is not None:
            try:
                inspect_env.unlink(missing_ok=True)
            except OSError as exc:
                print(f"Could not remove temporary Compose inspection env file: {exc}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
