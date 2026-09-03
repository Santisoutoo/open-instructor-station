"""``/api/cockpit/*`` — exercised against ``FakeSimAdapter`` (§8.3 of
docs/designs/cockpit-control-catalog.md).

Written before the implementation exists (Wave 1 Track A of #220):
``server/cockpit_routes.py`` does not exist yet and nothing is wired into
``server.app.create_app()``, so every request below is expected to answer
FastAPI's default 404 ("Not Found") right now, and the module-level import
of ``core.cockpit.*`` is expected to fail collection outright with
``ModuleNotFoundError``. Both are the deliverable, not a bug in this file.

No navdata fixture: this manager names no airport and reads no
``NavdataProvider`` (the Fuel & Payload / Pushback routes' own precedent —
see ``tests/server/test_pushback_routes.py``), so these tests build their
own ``TestClient`` instead of reusing ``tests/server/conftest.py``'s
navdata-backed one.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NoReturn

import pytest
from core.cockpit.errors import CockpitWriteRejected
from core.cockpit.models import CockpitActuation, CockpitActuationResult
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter

#: The MCP panel's readable controls (docs/designs/cockpit-control-catalog.md
#: §4.1): the five toggles/dials, never the parked ``mcp_vs``.
MCP_READABLE_IDS = {"fd_capt", "cmd_a", "hdg_sel", "mcp_alt", "mcp_hdg"}

#: Every readable control across all four panels — MCP's five plus
#: ``battery``/``irs_l`` (overhead), ``stab_trim`` (pedestal) and
#: ``landing_lights`` (lights). ``toga`` and ``chime_test`` are presses and
#: therefore never readable.
ALL_READABLE_IDS = MCP_READABLE_IDS | {"battery", "irs_l", "stab_trim", "landing_lights"}


class _NoCockpitAdapter(FakeSimAdapter):
    """A fake that declares every capability except ``can_control_cockpit``."""

    @property
    def name(self) -> str:
        return "no-cockpit"

    @property
    def capabilities(self) -> Capabilities:
        return super().capabilities.model_copy(update={"can_control_cockpit": False})


class _WriteRejectingAdapter(FakeSimAdapter):
    """Declares ``can_control_cockpit`` but refuses every write (§2.1's 502) —
    the ``WeatherRejected``/502 precedent, reproduced for the cockpit catalog.
    """

    async def actuate_cockpit_control(self, actuation: CockpitActuation) -> NoReturn:
        raise CockpitWriteRejected(
            f"{actuation.control_id!r} rejected the write — the simulator disagreed."
        )


def _client_for(adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: adapter)
    reset_adapter()
    return TestClient(create_app())


@pytest.fixture
def fake_adapter() -> FakeSimAdapter:
    return FakeSimAdapter()


@pytest.fixture
def client(fake_adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(fake_adapter, monkeypatch)
    reset_adapter()


@pytest.fixture
def no_capability_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(_NoCockpitAdapter(), monkeypatch)
    reset_adapter()


@pytest.fixture
def write_rejecting_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield _client_for(_WriteRejectingAdapter(), monkeypatch)
    reset_adapter()


# ---------------------------------------------------------------------------
# GET /api/cockpit/catalog
# ---------------------------------------------------------------------------


def test_get_catalog_reports_the_fake_trainer_shape(client: TestClient) -> None:
    with client:
        response = client.get("/api/cockpit/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["adapter"] == "fake"
    assert body["supported"] is True
    assert body["reason"] is None
    assert len(body["controls"]) == 11
    assert len(body["parked"]) == 1
    assert len(body["panels"]) == 4
    assert body["revision"] >= 1
    # Binding-free (D3): no control in the JSON carries a "binding" key.
    assert "binding" not in response.text


def test_get_catalog_is_always_200_even_without_the_capability(
    no_capability_client: TestClient,
) -> None:
    """Capability-free (D1): the panel learns it is disabled by reading, not
    by a request that fails."""
    with no_capability_client:
        response = no_capability_client.get("/api/cockpit/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False
    assert "can_control_cockpit" in body["reason"]
    assert body["aircraft"] is None


# ---------------------------------------------------------------------------
# GET /api/cockpit/state
# ---------------------------------------------------------------------------


def test_get_state_scoped_to_the_mcp_panel(client: TestClient) -> None:
    with client:
        response = client.get("/api/cockpit/state", params={"panel": "mcp"})
    assert response.status_code == 200
    ids = {state["control_id"] for state in response.json()["states"]}
    assert ids == MCP_READABLE_IDS


def test_get_state_unscoped_reports_every_readable_control(client: TestClient) -> None:
    with client:
        response = client.get("/api/cockpit/state")
    assert response.status_code == 200
    ids = {state["control_id"] for state in response.json()["states"]}
    assert ids == ALL_READABLE_IDS


def test_get_state_an_unknown_panel_is_404(client: TestClient) -> None:
    with client:
        response = client.get("/api/cockpit/state", params={"panel": "nope"})
    assert response.status_code == 404


def test_get_state_without_the_capability_is_501(no_capability_client: TestClient) -> None:
    with no_capability_client:
        response = no_capability_client.get("/api/cockpit/state")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# POST /api/cockpit/actuate
# ---------------------------------------------------------------------------


def test_actuate_a_toggle_round_trips(client: TestClient) -> None:
    with client:
        first = client.post("/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True})
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["actions_taken"] == 1
        assert first_body["state"]["value"] is True

        second = client.post("/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True})
    assert second.status_code == 200
    assert second.json()["actions_taken"] == 0


def test_actuate_refuses_an_unmet_precondition_then_succeeds(client: TestClient) -> None:
    with client:
        refused = client.post("/api/cockpit/actuate", json={"control_id": "hdg_sel", "value": True})
        assert refused.status_code == 409
        assert "flight director" in refused.json()["detail"]

        client.post("/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True})
        satisfied = client.post(
            "/api/cockpit/actuate", json={"control_id": "hdg_sel", "value": True}
        )
    assert satisfied.status_code == 200


def test_actuate_a_dial_value_above_max_is_422(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/cockpit/actuate", json={"control_id": "mcp_alt", "value": 60000}
        )
    assert response.status_code == 422


def test_actuate_a_bool_for_a_dial_is_422(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/cockpit/actuate", json={"control_id": "mcp_alt", "value": True}
        )
    assert response.status_code == 422


def test_actuate_an_encoder_delta_moves_the_value(client: TestClient) -> None:
    """``stab_trim`` starts at 4.0 with ``step: 0.5``; ``delta: 2`` moves it
    by ``2 * 0.5 = 1.0`` (docs/designs/cockpit-control-catalog.md §4.1)."""
    with client:
        response = client.post("/api/cockpit/actuate", json={"control_id": "stab_trim", "delta": 2})
    assert response.status_code == 200
    assert response.json()["state"]["value"] == pytest.approx(5.0)


def test_actuate_a_bare_press_reports_no_value(client: TestClient) -> None:
    with client:
        response = client.post("/api/cockpit/actuate", json={"control_id": "toga"})
    assert response.status_code == 200
    body = response.json()
    assert body["actions_taken"] == 1
    assert body["state"]["value"] is None


def test_actuate_a_parked_control_is_404_naming_the_reason(client: TestClient) -> None:
    with client:
        response = client.post("/api/cockpit/actuate", json={"control_id": "mcp_vs", "value": True})
    assert response.status_code == 404
    assert "parked" in response.json()["detail"]


def test_actuate_an_unknown_control_is_404(client: TestClient) -> None:
    with client:
        response = client.post("/api/cockpit/actuate", json={"control_id": "ghost", "value": True})
    assert response.status_code == 404


def test_actuate_without_the_capability_is_501(no_capability_client: TestClient) -> None:
    with no_capability_client:
        response = no_capability_client.post(
            "/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True}
        )
    assert response.status_code == 501


def test_actuate_a_rejected_write_is_502(write_rejecting_client: TestClient) -> None:
    with write_rejecting_client:
        response = write_rejecting_client.post(
            "/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True}
        )
    assert response.status_code == 502
    assert "rejected the write" in response.json()["detail"]


# ---------------------------------------------------------------------------
# No active catalog (aircraft=None)
# ---------------------------------------------------------------------------


def test_no_active_catalog_answers_honestly_across_all_three_routes(
    fake_adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_adapter.load_cockpit_catalog(None)
    client = _client_for(fake_adapter, monkeypatch)
    try:
        with client:
            catalog_response = client.get("/api/cockpit/catalog")
            assert catalog_response.status_code == 200
            catalog_body = catalog_response.json()
            assert catalog_body["aircraft"] is None
            assert catalog_body["reason"]

            state_response = client.get("/api/cockpit/state")
            assert state_response.status_code == 200
            assert state_response.json()["states"] == []

            actuate_response = client.post(
                "/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True}
            )
            assert actuate_response.status_code == 409
    finally:
        reset_adapter()


# ---------------------------------------------------------------------------
# POST /api/cockpit/catalog/refresh
# ---------------------------------------------------------------------------


def test_refresh_bumps_the_revision(client: TestClient) -> None:
    with client:
        before = client.get("/api/cockpit/catalog").json()["revision"]
        response = client.post("/api/cockpit/catalog/refresh")
    assert response.status_code == 200
    assert response.json()["revision"] > before


def test_refresh_without_the_capability_is_501(no_capability_client: TestClient) -> None:
    with no_capability_client:
        response = no_capability_client.post("/api/cockpit/catalog/refresh")
    assert response.status_code == 501


# ---------------------------------------------------------------------------
# 422 — request shape (§2.2), independent of the active catalog
# ---------------------------------------------------------------------------


def test_actuate_both_value_and_delta_is_422(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/cockpit/actuate",
            json={"control_id": "fd_capt", "value": True, "delta": 1},
        )
    assert response.status_code == 422


#: A response body shaped like ``CockpitActuationResult`` — asserted for its
#: field names only, never constructed by re-running the implementation
#: (the design's own reasoning against re-deriving the oracle from the code
#: under test).
_ACTUATION_RESULT_FIELDS = set(CockpitActuationResult.model_fields)


def test_actuate_result_shape_matches_the_model(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/cockpit/actuate", json={"control_id": "fd_capt", "value": True}
        )
    assert set(response.json()) == _ACTUATION_RESULT_FIELDS
