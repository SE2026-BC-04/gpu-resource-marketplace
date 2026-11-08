import importlib.util
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
_SMOKE_SPEC = importlib.util.spec_from_file_location(
    "gpu_marketplace_compose_smoke", ROOT / "tools" / "compose_smoke.py"
)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
compose_smoke = importlib.util.module_from_spec(_SMOKE_SPEC)
_SMOKE_SPEC.loader.exec_module(compose_smoke)


def test_compose_has_exactly_five_expected_services_and_isolated_networks() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"frontend", "api", "manager", "simulator", "postgres"}
    assert set(services["simulator"]["networks"]) == {"app"}
    assert set(services["postgres"]["networks"]) == {"database", "postgres-host"}
    assert set(services["frontend"]["networks"]) == {"frontend"}
    assert set(services["api"]["networks"]) == {"app", "database", "api-host"}
    assert set(services["manager"]["networks"]) == {"app", "database"}
    assert services["postgres"]["ports"] == ["127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432"]
    networks = compose["networks"]
    assert networks["frontend"].get("internal", False) is False
    assert networks["api-host"].get("internal", False) is False
    assert networks["postgres-host"].get("internal", False) is False
    assert networks["app"]["internal"] is True
    assert networks["database"]["internal"] is True
    assert {name for name, config in services.items() if "postgres-host" in config["networks"]} == {"postgres"}
    assert "ports" not in services["simulator"]
    assert "volumes" not in services["simulator"]
    assert "env_file" not in services["simulator"]
    simulator_env = str(services["simulator"].get("environment", {})).lower()
    assert not any(word in simulator_env for word in ("database", "postgres", "password", "oracle"))


def test_simulator_has_no_database_driver_or_access_configuration() -> None:
    pyproject = (ROOT / "simulator" / "pyproject.toml").read_text(encoding="utf-8").lower()
    source = "\n".join(
        file.read_text(encoding="utf-8")
        for file in (ROOT / "simulator" / "src").rglob("*.py")
    ).lower()
    assert "sqlalchemy" not in pyproject and "psycopg" not in pyproject and "alembic" not in pyproject
    assert "database_url" not in source and "postgres" not in source


def test_frontend_compose_builds_production_bundle_for_selected_api_host_port() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    frontend = compose["services"]["frontend"]
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    production_server = (ROOT / "frontend" / "server.mjs").read_text(encoding="utf-8")

    assert frontend["build"]["args"]["VITE_API_BASE_URL"] == "http://localhost:${API_HOST_PORT:-8000}"
    assert frontend["ports"] == ["127.0.0.1:${FRONTEND_HOST_PORT:-5173}:5173"]
    assert "AS build" in dockerfile and "AS runtime" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert 'CMD ["node", "server.mjs"]' in dockerfile
    assert 'CMD ["npm", "run", "dev"' not in dockerfile
    assert "VITE_API_BASE_URL=${VITE_API_BASE_URL}" in dockerfile
    assert "file = indexFile;" in production_server


def test_readme_local_setup_fails_fast_uses_root_alembic_config_and_syncs_runtime_dsns() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert ". .\\tools\\local_setup.ps1" in readme
    assert "Invoke-LocalSetupNativeCommand -Step 'Runtime role bootstrap'" in readme
    assert "Invoke-LocalSetupNativeCommand -Step 'Alembic migration to head'" in readme
    assert "alembic -c backend/alembic.ini upgrade head" in readme
    migration_readme = (ROOT / "backend" / "migrations" / "README.md").read_text(encoding="utf-8")
    assert "--project backend --locked alembic -c backend/alembic.ini upgrade head" in migration_readme
    assert "Set-LocalRuntimeDatabaseUrls -EnvPath .env" in readme
    assert "docker compose --env-file .env config --format json" in readme
    assert "gpm_api_app" in readme and "gpm_manager_app" in readme


def test_compose_smoke_verifies_native_session_users_owner_and_restart_persistence() -> None:
    smoke = (ROOT / "tools" / "compose_smoke.py").read_text(encoding="utf-8")

    assert "SELECT current_user, session_user" in smoke
    assert "pg_get_userbyid(datdba)" in smoke
    assert "has_database_privilege(current_user,current_database(),'CREATE')" in smoke
    assert "has_schema_privilege(current_user,'public','CREATE')" in smoke
    assert "verify_runtime_roles_from_host" in smoke
    assert '"down", "--remove-orphans"' in smoke
    assert "verify_restart_persistence" in smoke


def test_smoke_env_file_is_not_overridden_by_ambient_process_values(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / "smoke.env"
    env_file.write_text(
        "GPU_MARKETPLACE_LISTING_CURSOR_SECRET=smoke-cursor-key\n"
        "POSTGRES_HOST_PORT=45678\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GPU_MARKETPLACE_LISTING_CURSOR_SECRET", "ambient-ci-key")
    monkeypatch.setenv("POSTGRES_HOST_PORT", "5432")
    captured: dict[str, object] = {}

    def capture_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(compose_smoke.subprocess, "run", capture_run)
    compose_smoke.compose(env_file, "isolated-smoke", "config")

    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert "GPU_MARKETPLACE_LISTING_CURSOR_SECRET" not in child_env
    assert "POSTGRES_HOST_PORT" not in child_env
