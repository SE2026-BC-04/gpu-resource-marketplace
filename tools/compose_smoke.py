"""Run an isolated five-service smoke project and verify public boundaries."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

import psycopg


ROOT = Path(__file__).resolve().parents[1]
PROJECT = f"gpu-marketplace-smoke-{uuid.uuid4().hex}"
LOCAL_PROJECT = "gpu-resource-marketplace"
EXPECTED_SERVICES = {"frontend", "api", "manager", "simulator", "postgres"}


def compose(env_file: Path, project: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker", "compose", "--env-file", str(env_file),
            "-p", project, "-f", "compose.yaml", *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
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
    smoke_project_created = False
    local_resources_before: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None = None
    exit_code = 1
    try:
        # Inspect the normal local project first. It is never started, stopped, or cleaned here.
        local = compose(ROOT / ".env.example", LOCAL_PROJECT, "ps", "--all", "--format", "json")
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
        smoke_env = make_smoke_env_file(
            {
                **ports,
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
        result = compose(
            smoke_env, PROJECT, "up", "--build", "--detach", "--wait", "--wait-timeout", "240"
        )
        if result.returncode:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            raise RuntimeError(f"Compose smoke project did not become healthy (exit {result.returncode})")

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

        print("PASS: exactly five Compose services are running and healthy")
        print("PASS: host can fetch the production frontend index and built JavaScript bundle")
        print("PASS: frontend SPA route falls back to the production index")
        print(f"PASS: frontend image build received API host URL {expected_api_url}")
        print(f"PASS: host TCP and PostgreSQL SELECT 1 via loopback port {postgres_port}")
        print("PASS: API /health/ready and Manager healthcheck can query PostgreSQL")
        print("PASS: host can access Backend API /health/live")
        print("PASS: Simulator can reach API but cannot resolve/connect to PostgreSQL")
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

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
