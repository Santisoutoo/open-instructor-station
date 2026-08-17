"""``/api/fuel-payload/*`` — exercised against ``FakeSimAdapter``.

No navdata fixture is needed here (D17 of docs/designs/fuel-payload.md): this
manager reads no ``NavdataProvider``, so the tests build their own
``TestClient`` directly rather than reusing ``tests/server/conftest.py``'s
navdata-backed one.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.fuel_payload.limits import AIRCRAFT_MASS_LIMITS_TABLE
from core.models import AirframeInfo, LoadoutState, PayloadStation, TankFuel
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter

#: A current loadout shaped like the §7.1 C172 table: two tanks, three
#: stations, all known indices present (even at 0 kg) — what a real
#: ``get_loadout()`` would report for this airframe.
C172_LOADOUT = LoadoutState(
    tanks=[
        TankFuel(tank_index=0, fuel_kg=0.0),
        TankFuel(tank_index=1, fuel_kg=0.0),
    ],
    stations=[
        PayloadStation(station_index=0, kind="crew", label="Pilot", weight_kg=0.0),
        PayloadStation(station_index=1, kind="passenger", label="Rear seats", weight_kg=0.0),
        PayloadStation(station_index=2, kind="cargo", label="Baggage", weight_kg=0.0),
    ],
)


class _NoFuelPayloadAdapter(FakeSimAdapter):
    """A fake that declares every capability except fuel/payload."""

    @property
    def name(self) -> str:
        return "no-fuel-payload"

    @property
    def capabilities(self) -> Capabilities:
        base = super().capabilities.model_dump()
        base["can_set_fuel_payload"] = False
        return Capabilities(**base)


def _client_for(adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: adapter)
    reset_adapter()
    return TestClient(create_app())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The default fake: every capability, the honest all-``None`` airframe."""
    yield _client_for(FakeSimAdapter(), monkeypatch)
    reset_adapter()


@pytest.fixture
def c172_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A fake reporting a C172 — the §7.1 table resolves through the fallback."""
    adapter = FakeSimAdapter(
        airframe=AirframeInfo(icao_type="C172"), loadout=C172_LOADOUT.model_copy(deep=True)
    )
    yield _client_for(adapter, monkeypatch)
    reset_adapter()


@pytest.fixture
def no_capability_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An adapter that declares every capability except ``can_set_fuel_payload``."""
    yield _client_for(_NoFuelPayloadAdapter(), monkeypatch)
    reset_adapter()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_lists_the_four_presets(client: TestClient) -> None:
    with client:
        response = client.get("/api/fuel-payload/manifest")
    assert response.status_code == 200
    body = response.json()
    assert {preset["id"] for preset in body["presets"]} == {"ferry", "training", "full", "empty"}


def test_manifest_reports_unknown_limits_for_the_default_fake(client: TestClient) -> None:
    with client:
        response = client.get("/api/fuel-payload/manifest")
    body = response.json()
    assert body["limits_source"] == "unknown"
    assert body["limits_note"] is None
    assert body["tank_count"] == 0
    assert body["station_count"] == 0
    assert body["supported"] is True
    assert body["reason"] is None


def test_manifest_reports_the_table_source_and_disclaimer_for_a_c172(
    c172_client: TestClient,
) -> None:
    with c172_client:
        response = c172_client.get("/api/fuel-payload/manifest")
    body = response.json()
    assert body["icao_type"] == "C172"
    assert body["limits_source"] == "table"
    assert body["limits_note"] == AIRCRAFT_MASS_LIMITS_TABLE["C172"].source_note
    assert body["tank_count"] == 2
    assert body["station_count"] == 3


def test_manifest_is_always_200_even_without_the_capability(
    no_capability_client: TestClient,
) -> None:
    with no_capability_client:
        response = no_capability_client.get("/api/fuel-payload/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False
    assert "can_set_fuel_payload" in body["reason"]


# ---------------------------------------------------------------------------
# GET /api/fuel-payload
# ---------------------------------------------------------------------------


def test_get_fuel_payload_returns_the_current_loadout_and_mass_and_balance(
    c172_client: TestClient,
) -> None:
    with c172_client:
        response = c172_client.get("/api/fuel-payload")
    assert response.status_code == 200
    body = response.json()
    assert len(body["loadout"]["tanks"]) == 2
    assert body["mass_and_balance"]["limits_source"] == "table"
    assert body["mass_and_balance"]["gross_weight_kg"] == pytest.approx(743.0, abs=0.01)


def test_get_fuel_payload_refuses_without_the_capability(
    no_capability_client: TestClient,
) -> None:
    with no_capability_client:
        response = no_capability_client.get("/api/fuel-payload")
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "no-fuel-payload" in detail
    assert "can_set_fuel_payload" in detail


# ---------------------------------------------------------------------------
# §2.2 error rows
# ---------------------------------------------------------------------------


def test_neither_preset_nor_loadout_is_refused(c172_client: TestClient) -> None:
    with c172_client:
        response = c172_client.post("/api/fuel-payload/preview", json={})
    assert response.status_code == 422
    assert "must carry a preset, a loadout, or both" in response.text


def test_preset_against_unknown_capacities_is_refused(client: TestClient) -> None:
    """The default fake's airframe has no icao_type, so nothing resolves the fractions."""
    with client:
        response = client.post("/api/fuel-payload/preview", json={"preset": "full"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "'full'" in detail
    assert "capacities" in detail


def test_unknown_preset_id_is_refused_by_request_validation(c172_client: TestClient) -> None:
    with c172_client:
        response = c172_client.post("/api/fuel-payload/preview", json={"preset": "bogus"})
    assert response.status_code == 422


def test_overlay_tank_index_outside_the_current_loadout_is_refused(
    c172_client: TestClient,
) -> None:
    with c172_client:
        response = c172_client.post(
            "/api/fuel-payload/preview",
            json={"loadout": {"tanks": [{"tank_index": 3, "fuel_kg": 1.0}]}},
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Tank index 3" in detail
    assert "2 known tanks" in detail


def test_apply_refuses_without_the_capability(no_capability_client: TestClient) -> None:
    with no_capability_client:
        response = no_capability_client.post("/api/fuel-payload/apply", json={"preset": "training"})
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "no-fuel-payload" in detail
    assert "can_set_fuel_payload" in detail


def test_preview_refuses_without_the_capability(no_capability_client: TestClient) -> None:
    with no_capability_client:
        response = no_capability_client.post(
            "/api/fuel-payload/preview", json={"preset": "training"}
        )
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# Preview is side-effect free
# ---------------------------------------------------------------------------


def test_preview_never_writes(c172_client: TestClient) -> None:
    with c172_client:
        before = c172_client.get("/api/fuel-payload").json()
        response = c172_client.post("/api/fuel-payload/preview", json={"preset": "full"})
        after = c172_client.get("/api/fuel-payload").json()
    assert response.status_code == 200
    assert before == after


# ---------------------------------------------------------------------------
# The §7.1 worked table, end to end
# ---------------------------------------------------------------------------


def test_apply_on_the_full_preset_is_refused_with_the_aft_cg_sentence(
    c172_client: TestClient,
) -> None:
    with c172_client:
        response = c172_client.post("/api/fuel-payload/apply", json={"preset": "full"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "4.80 in" in detail
    assert "aft" in detail


def test_apply_on_the_full_preset_succeeds_with_the_override(c172_client: TestClient) -> None:
    with c172_client:
        response = c172_client.post(
            "/api/fuel-payload/apply",
            json={"preset": "full", "override_envelope": True},
        )
    assert response.status_code == 200
    body = response.json()
    mb = body["state"]["mass_and_balance"]
    assert mb["gross_weight_kg"] == pytest.approx(1110.0, abs=0.01)
    assert mb["cg_arm_in"] == pytest.approx(44.95, abs=0.01)
    assert mb["within_envelope"] is False


def test_apply_on_training_succeeds_and_reports_the_read_back(c172_client: TestClient) -> None:
    with c172_client:
        response = c172_client.post("/api/fuel-payload/apply", json={"preset": "training"})
    assert response.status_code == 200
    body = response.json()
    mb = body["state"]["mass_and_balance"]
    assert mb["gross_weight_kg"] == pytest.approx(840.5, abs=0.01)
    assert mb["cg_arm_in"] == pytest.approx(40.44, abs=0.01)
    assert mb["within_envelope"] is True
    # `state` is the read-back, never the pre-write resolution.
    with c172_client:
        readback = c172_client.get("/api/fuel-payload").json()
    assert readback["mass_and_balance"]["gross_weight_kg"] == pytest.approx(840.5, abs=0.01)


def test_apply_is_idempotent(c172_client: TestClient) -> None:
    body = {"preset": "training"}
    with c172_client:
        first = c172_client.post("/api/fuel-payload/apply", json=body)
        second = c172_client.post("/api/fuel-payload/apply", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["applied"] == second.json()["applied"]


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_exposes_the_fuel_payload_surface(client: TestClient) -> None:
    with client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert {
        "/api/fuel-payload/manifest",
        "/api/fuel-payload",
        "/api/fuel-payload/preview",
        "/api/fuel-payload/apply",
    } <= set(paths)
