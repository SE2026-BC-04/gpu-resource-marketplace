from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from gpu_marketplace_simulator.app import create_app
from gpu_marketplace_simulator.config import Settings


def test_simulator_has_operational_health_endpoints_only() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        assert client.get("/docs").status_code == 404


def test_configuration_rejects_an_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=70000)
