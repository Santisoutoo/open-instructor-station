"""The FastAPI surface, exercised against ``FakeSimAdapter``.

These tests also guard something easy to break: the server must start whether
or not ``ui/dist`` has been built.
"""

import json

import pytest
from fastapi.testclient import TestClient

import server.app
import server.deps
from adapters.fake import FakeSimAdapter
from core.models import AircraftState
from core.sim_adapter import Capabilities
from server.app import (
    CONTROL_IDS,
    AircraftControlManifest,
    AircraftSetupResult,
    create_app,
)
from server.deps import Settings, get_settings, reset_adapter


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


# ---------------------------------------------------------------------------
# Aircraft Control panel (issue #7)
# ---------------------------------------------------------------------------


class _NoWriteAdapter(FakeSimAdapter):
    """A fake that declares nothing. Stands in for a read-only simulator link."""

    @property
    def name(self) -> str:
        return "read-only"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities()


@pytest.fixture
def read_only_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client whose adapter declares no capabilities at all."""
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoWriteAdapter())
    reset_adapter()
    return TestClient(create_app())


def _controls(client: TestClient) -> dict[str, dict[str, object]]:
    with client:
        response = client.get("/api/aircraft/controls")
    assert response.status_code == 200
    manifest = AircraftControlManifest(**response.json())
    return {entry.control: entry.model_dump() for entry in manifest.controls}


def test_control_manifest_lists_every_panel_control(client: TestClient) -> None:
    """The panel renders straight from this list, so nothing may be missing."""
    with client:
        response = client.get("/api/aircraft/controls")
    assert response.status_code == 200
    manifest = AircraftControlManifest(**response.json())
    assert manifest.adapter == "fake"
    assert [entry.control for entry in manifest.controls] == list(CONTROL_IDS)


def test_controls_backed_by_an_aircraft_setup_field_are_supported(client: TestClient) -> None:
    """``FakeSimAdapter`` declares every capability, so every control must now be writable.

    The trim and the whole autopilot block joined this list with issue #41. Until
    then they were the live example of the "declared but not modelled" gap; the
    branch that reports it is pinned by
    :func:`test_a_control_with_no_aircraft_setup_field_is_disabled_with_a_reason`.
    """
    controls = _controls(client)
    assert [control for control, entry in controls.items() if not entry["supported"]] == []
    assert all(entry["reason"] is None for entry in controls.values())


def test_a_control_with_no_aircraft_setup_field_is_disabled_with_a_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A control the server offers but ``AircraftSetup`` cannot carry fails closed.

    Every real control has its field today, so the gap is staged rather than
    waited for: this is the branch that keeps a panel honest during the window
    between adding a control identifier and adding the field behind it.
    """
    staged = dict(server.app._CONTROL_FIELDS)
    staged["flaps"] = ("not_a_field_on_aircraft_setup", "can_set_aircraft_state")
    monkeypatch.setattr(server.app, "_CONTROL_FIELDS", staged)

    controls = _controls(client)
    assert controls["flaps"]["supported"] is False
    reason = controls["flaps"]["reason"]
    assert isinstance(reason, str) and "AircraftSetup has no" in reason


def test_an_undeclared_capability_disables_its_controls(read_only_client: TestClient) -> None:
    """Hard rule 3: unsupported means *disabled with a reason*, never a runtime throw."""
    controls = _controls(read_only_client)
    assert all(entry["supported"] is False for entry in controls.values())
    reason = controls["flaps"]["reason"]
    assert isinstance(reason, str)
    assert "does not declare can_set_aircraft_state" in reason


def test_apply_setup_writes_the_configuration_and_returns_the_new_state(
    client: TestClient,
) -> None:
    body = {"flaps_ratio": 0.5, "gear_down": True, "lights": {"landing": True}}
    with client:
        response = client.post("/api/aircraft/setup", json=body)
    assert response.status_code == 200
    result = AircraftSetupResult(**response.json())
    # `applied` is echoed because AircraftState carries no configuration at all.
    assert result.applied.flaps_ratio == 0.5
    assert result.applied.gear_down is True
    assert result.applied.lights is not None
    assert result.applied.lights.landing is True
    assert result.state.on_ground is False


def test_apply_setup_moves_the_flight_state(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/aircraft/setup",
            json={"altitude_ft": 8000.0, "ias_kt": 180.0, "heading_deg": 270.0},
        )
    assert response.status_code == 200
    state = AircraftSetupResult(**response.json()).state
    assert state.altitude_ft == pytest.approx(8000.0)
    assert state.ias_kt == pytest.approx(180.0)
    assert state.heading_deg == pytest.approx(270.0)


def test_apply_setup_is_idempotent(client: TestClient) -> None:
    """Writes state target values, not deltas — replaying a body changes nothing."""
    body = {"flaps_ratio": 0.25, "autobrake_level": 3}
    with client:
        first = client.post("/api/aircraft/setup", json=body)
        second = client.post("/api/aircraft/setup", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["applied"] == second.json()["applied"]


def test_apply_setup_accepts_an_empty_body(client: TestClient) -> None:
    with client:
        response = client.post("/api/aircraft/setup", json={})
    assert response.status_code == 200
    assert AircraftSetupResult(**response.json()).applied.flaps_ratio is None


def test_apply_setup_validates_field_ranges(client: TestClient) -> None:
    """Range checking stays in ``AircraftSetup``; the endpoint adds no parallel rules."""
    with client:
        response = client.post("/api/aircraft/setup", json={"flaps_ratio": 1.5})
    assert response.status_code == 422


def test_apply_setup_refuses_an_undeclared_capability(read_only_client: TestClient) -> None:
    """A caller that ignored the manifest gets a stated reason, not a 500."""
    with read_only_client:
        response = read_only_client.post("/api/aircraft/setup", json={"flaps_ratio": 0.5})
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "flaps_ratio" in detail
    assert "does not declare can_set_aircraft_state" in detail


def test_apply_setup_refuses_the_whole_body_rather_than_applying_it_partially(
    read_only_client: TestClient,
) -> None:
    with read_only_client:
        before = read_only_client.get("/api/state").json()
        response = read_only_client.post(
            "/api/aircraft/setup", json={"altitude_ft": 9999.0, "gear_down": True}
        )
        after = read_only_client.get("/api/state").json()
    assert response.status_code == 501
    assert after["altitude_ft"] == before["altitude_ft"]


def test_health_is_a_declared_model_not_a_bare_dict(client: TestClient) -> None:
    """An untyped dict generates as ``unknown`` in the UI client — see CLAUDE.md."""
    with client:
        response = client.get("/openapi.json")
    schemas = response.json()["components"]["schemas"]
    assert set(schemas["HealthResponse"]["properties"]) == {"status", "adapter", "connected"}


def test_openapi_exposes_the_aircraft_control_surface(client: TestClient) -> None:
    """`npm run generate:api` reads this; the panel's types come from nowhere else."""
    with client:
        response = client.get("/openapi.json")
    body = response.json()
    assert {"/api/aircraft/controls", "/api/aircraft/setup"} <= set(body["paths"])
    control_enum = body["components"]["schemas"]["AircraftControlSupport"]["properties"]["control"]
    assert control_enum["enum"] == list(CONTROL_IDS)
