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
