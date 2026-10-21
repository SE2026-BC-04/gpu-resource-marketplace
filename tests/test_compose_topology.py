from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_exactly_five_expected_services_and_isolated_networks() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"frontend", "api", "manager", "simulator", "postgres"}
    assert set(services["simulator"]["networks"]) == {"app"}
    assert set(services["postgres"]["networks"]) == {"database"}
    assert set(services["frontend"]["networks"]) == {"frontend"}
    assert set(services["api"]["networks"]) == {"app", "database"}
    assert set(services["manager"]["networks"]) == {"app", "database"}
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
