"""The FastAPI surface, exercised against ``FakeSimAdapter``.

These tests also guard something easy to break: the server must start whether
or not ``ui/dist`` has been built.
"""

import json

import pytest
from fastapi.testclient import TestClient

from core.models import AircraftState
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import Settings, get_settings


@pytest.fixture
def client() -> TestClient:
    """A test client with the app's lifespan running."""
    return TestClient(create_app())


def test_settings_default_to_the_fake_adapter() -> None:
    settings = get_settings()
    assert settings.adapter == "fake"
    assert settings.port == 8000
    assert settings.xplane_port == 8086


def test_settings_read_the_ois_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OIS_PORT", "9123")
    monkeypatch.setenv("OIS_XPLANE_HOST", "192.168.1.20")
    settings = Settings()
    assert settings.port == 9123
    assert settings.xplane_host == "192.168.1.20"


def test_health_reports_the_adapter(client: TestClient) -> None:
    with client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "adapter": "fake", "connected": True}


def test_capabilities_endpoint_returns_the_model(client: TestClient) -> None:
    with client:
        response = client.get("/api/capabilities")
    assert response.status_code == 200
    capabilities = Capabilities(**response.json())
    assert capabilities.can_set_position is True


def test_state_endpoint_returns_an_aircraft_state(client: TestClient) -> None:
    with client:
        response = client.get("/api/state")
    assert response.status_code == 200
    state = AircraftState(**response.json())
    assert -90.0 <= state.latitude <= 90.0


def test_state_websocket_pushes_states(client: TestClient) -> None:
    with client, client.websocket_connect("/ws/state") as socket:
        payloads = [json.loads(socket.receive_text()) for _ in range(3)]
    assert len(payloads) == 3
    for payload in payloads:
        AircraftState(**payload)


def test_openapi_schema_is_generated(client: TestClient) -> None:
    """The UI's API types are generated from this schema; it must exist."""
    with client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/api/health", "/api/capabilities", "/api/state"} <= set(paths)
