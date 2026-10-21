"""Run the five-service foundation and prove the Simulator cannot reach PostgreSQL."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = f"gpu-marketplace-smoke-{uuid.uuid4().hex}"
COMPOSE = ["docker", "compose", "--env-file", ".env.example", "-p", PROJECT, "-f", "compose.yaml"]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, text=True, capture_output=True, check=check
    )


def main() -> int:
    created = False
    try:
        # This project name is unique to this run, so even a partially failed `up`
        # can be cleaned without touching a developer's normal Compose project.
        created = True
        result = run("up", "--build", "--detach", "--wait", "--wait-timeout", "240", check=False)
        if result.returncode:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode

        raw_state = run("ps", "--format", "json").stdout.strip()
        state = json.loads(raw_state) if raw_state.startswith("[") else [
            json.loads(line) for line in raw_state.splitlines() if line.strip()
        ]
        expected = {"frontend", "api", "manager", "simulator", "postgres"}
        observed = {item.get("Service") or item.get("Name", "").removeprefix(f"{PROJECT}-") for item in state}
        if observed != expected or any(item.get("State") != "running" or item.get("Health") != "healthy" for item in state):
            raise RuntimeError(f"Compose services did not all become healthy: {state}")

        run(
            "exec", "--no-TTY", "simulator", "python", "-c",
            "import urllib.request; urllib.request.urlopen('http://api:8000/health/live', timeout=3)",
        )
        probe = run(
            "exec", "--no-TTY", "simulator", "python", "-c",
            "import socket\ntry:\n s=socket.create_connection(('postgres',5432),timeout=2)\nexcept OSError:\n print('db_network_isolated')\nelse:\n s.close()\n raise SystemExit('Simulator reached PostgreSQL')",
        )
        if "db_network_isolated" not in probe.stdout:
            raise RuntimeError("Simulator database-isolation probe did not complete")
        print("PASS: all five Compose services are healthy")
        print("PASS: Simulator can reach the API on the application network")
        print("PASS: Simulator cannot resolve/connect to PostgreSQL")
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stdout or "", end="")
            print(exc.stderr or "", end="", file=sys.stderr)
        return 1
    finally:
        if created:
            try:
                cleanup = run("down", "--volumes", "--remove-orphans", check=False)
                if cleanup.returncode:
                    print(cleanup.stderr, end="", file=sys.stderr)
            except OSError as exc:
                print(f"Cleanup unavailable: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
