"""``/api/traffic/*`` and ``WS /ws/traffic`` — the AI Traffic manager's HTTP surface.

Written from ``docs/designs/ai-traffic.md`` §2, §3.5 and §8.3, against
``FakeSimAdapter`` only. The geometry's exactness lives in
``tests/core/test_traffic.py`` and the adapter behaviour in
``tests/adapters/test_contract.py`` — this file proves the *plumbing*: request
resolution, capability gating, capacity mapping, idempotent deletes and the
live WebSocket stream.

The capability-refusal tests are the HTTP half of roadmap Phase 3 exit
criterion 3 (ai-traffic.md D14): with an adapter declaring
``can_spawn_traffic=False``, every write is a 501 with a stated reason and the
reads degrade to an empty picture instead of failing.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from adapters.fake.fake_adapter import _FAKE_MAX_TRAFFIC
from core.geodesy import distance_and_bearing
from core.models import GeoPosition
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter


class _NoTrafficAdapter(FakeSimAdapter):
    """A fake declaring every capability except ``can_spawn_traffic``.

    Exit criterion 3's shape: every non-traffic feature keeps working, only
    traffic is refused with a stated reason.
    """

    @property
    def name(self) -> str:
        return "no-traffic"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_set_position=True,
            can_set_aircraft_state=True,
            can_set_weather=True,
            can_inject_failures=True,
            can_control_autopilot=True,
            can_set_fuel_payload=True,
            can_control_camera=True,
            can_pushback=True,
        )


@pytest.fixture(autouse=True)
def _fresh_adapter() -> Iterator[None]:
    """Spawned traffic lives on the process-wide adapter singleton — reset it
    around every test so no contact leaks from one test into the next."""
    reset_adapter()
    yield
    reset_adapter()


@pytest.fixture
def no_traffic_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: _NoTrafficAdapter())
    reset_adapter()
    yield TestClient(create_app())
    reset_adapter()


def _custom_track_body(callsign: str = "TFC01") -> dict[str, Any]:
    """A minimal, valid ``custom`` spawn request.

    Two waypoints 0.05° of latitude apart (~3 NM) flown in 90 s — a
    self-consistent 120 kt leg near the fake's own Madrid position.
    """
    return {
        "type": "custom",
        "track": {
            "kind": "aircraft",
            "callsign": callsign,
            "label": "server-suite custom track",
            "waypoints": [
                {
                    "position": {"latitude": 40.5, "longitude": -3.5, "altitude_ft": 4000.0},
                    "speed_kt": 120.0,
                    "t_offset_s": 0.0,
                },
                {
                    "position": {"latitude": 40.55, "longitude": -3.5, "altitude_ft": 4000.0},
                    "speed_kt": 120.0,
                    "t_offset_s": 90.0,
                },
            ],
        },
    }


def _spawn_custom(client: TestClient, callsign: str = "TFC01") -> dict[str, Any]:
    response = client.post("/api/traffic/spawn", json=_custom_track_body(callsign))
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


# ---------------------------------------------------------------------------
# Spawning (§2, §8.3)
# ---------------------------------------------------------------------------


class TestSpawn:
    def test_a_custom_track_spawns_one_contact_with_a_traffic_id(self, client: TestClient) -> None:
        with client:
            body = _spawn_custom(client)
        assert len(body["contacts"]) == 1
        contact = body["contacts"][0]
        assert contact["traffic_id"]
        assert contact["callsign"] == "TFC01"
        assert contact["scenario_shape"] == "custom"
        assert contact["kind"] == "aircraft"

    def test_spawning_twice_creates_two_contacts(self, client: TestClient) -> None:
        """Not idempotent (§2) — same posture as ``POST /api/failures/arm``."""
        with client:
            first = _spawn_custom(client, "TFC01")
            second = _spawn_custom(client, "TFC02")
            status = client.get("/api/traffic/status").json()
        assert first["contacts"][0]["traffic_id"] != second["contacts"][0]["traffic_id"]
        assert len(status["contacts"]) == 2

    def test_a_tcas_conflict_spawns_plausibly_near_the_user(self, client: TestClient) -> None:
        """A coarse sanity bound on the HTTP plumbing, not a re-check of the
        geometry (that lives in ``tests/core/test_traffic.py``).

        With the fake's default state (250 kt IAS at 3000 ft) and the default
        250 kt closure, a head-on intruder spawns
        ``(user_gs + intruder_gs) * 100 s`` ahead — roughly 15 NM. The bound
        only has to catch unit confusion (a metres/feet or kt/m-s mix-up lands
        orders of magnitude away), not pin the track.
        """
        with client:
            state = client.get("/api/state").json()
            response = client.post("/api/traffic/spawn", json={"type": "tcas_conflict"})
            assert response.status_code == 200, response.text
        contacts = response.json()["contacts"]
        assert len(contacts) == 1
        contact = contacts[0]
        user = GeoPosition(latitude=state["latitude"], longitude=state["longitude"])
        intruder = GeoPosition(latitude=contact["latitude"], longitude=contact["longitude"])
        distance_nm, _ = distance_and_bearing(user, intruder)
        assert 2.0 < distance_nm < 40.0, f"intruder spawned {distance_nm:.1f} NM from the user"
        # head_on_ra's vertical miss is 0 ft: the intruder flies the user's level.
        assert contact["altitude_ft"] == pytest.approx(state["altitude_ft"], abs=1.0)

    def test_an_unknown_runway_for_an_incursion_is_404(self, client: TestClient) -> None:
        """The same convention ``position_routes`` uses for an unresolvable runway."""
        with client:
            response = client.post(
                "/api/traffic/spawn",
                json={"type": "runway_incursion", "airport_icao": "ZZZZ", "runway_ident": "09"},
            )
        assert response.status_code == 404
        assert "09" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Status, despawn, clear (§2, §8.3)
# ---------------------------------------------------------------------------


class TestStatusAndLifecycle:
    def test_status_starts_empty(self, client: TestClient) -> None:
        with client:
            response = client.get("/api/traffic/status")
        assert response.status_code == 200
        body = response.json()
        assert body["adapter"] == "fake"
        assert body["contacts"] == []

    def test_status_reflects_a_spawn(self, client: TestClient) -> None:
        with client:
            traffic_id = _spawn_custom(client)["contacts"][0]["traffic_id"]
            status = client.get("/api/traffic/status").json()
        assert traffic_id in {c["traffic_id"] for c in status["contacts"]}

    def test_delete_removes_the_contact(self, client: TestClient) -> None:
        with client:
            traffic_id = _spawn_custom(client)["contacts"][0]["traffic_id"]
            response = client.delete(f"/api/traffic/{traffic_id}")
            assert response.status_code == 200
            status = client.get("/api/traffic/status").json()
        assert traffic_id not in {c["traffic_id"] for c in response.json()["contacts"]}
        assert traffic_id not in {c["traffic_id"] for c in status["contacts"]}

    def test_delete_of_an_already_gone_id_is_still_200(self, client: TestClient) -> None:
        """Idempotent (§2): a client racing a ``despawn_after_s`` auto-clear
        never sees an error for something it did nothing wrong to ask for."""
        with client:
            traffic_id = _spawn_custom(client)["contacts"][0]["traffic_id"]
            first = client.delete(f"/api/traffic/{traffic_id}")
            second = client.delete(f"/api/traffic/{traffic_id}")
            never_existed = client.delete("/api/traffic/no-such-id")
        assert first.status_code == 200
        assert second.status_code == 200
        assert never_existed.status_code == 200

    def test_clear_empties_everything(self, client: TestClient) -> None:
        with client:
            _spawn_custom(client, "TFC01")
            _spawn_custom(client, "TFC02")
            response = client.post("/api/traffic/clear")
            assert response.status_code == 200
            status = client.get("/api/traffic/status").json()
        assert response.json()["contacts"] == []
        assert status["contacts"] == []


# ---------------------------------------------------------------------------
# Capability refusal (§2.1, D14) — the HTTP half of Phase 3 exit criterion 3
# ---------------------------------------------------------------------------


class TestCapabilityRefusal:
    def test_spawn_is_refused_with_the_stated_reason(self, no_traffic_client: TestClient) -> None:
        with no_traffic_client:
            response = no_traffic_client.post("/api/traffic/spawn", json=_custom_track_body())
        assert response.status_code == 501
        detail = response.json()["detail"]
        assert "no-traffic" in detail
        assert "can_spawn_traffic" in detail

    def test_delete_is_refused(self, no_traffic_client: TestClient) -> None:
        with no_traffic_client:
            response = no_traffic_client.delete("/api/traffic/some-id")
        assert response.status_code == 501

    def test_clear_is_refused(self, no_traffic_client: TestClient) -> None:
        with no_traffic_client:
            response = no_traffic_client.post("/api/traffic/clear")
        assert response.status_code == 501

    def test_status_still_answers_with_an_empty_picture(
        self, no_traffic_client: TestClient
    ) -> None:
        """Reads are never gated — they degrade (§2.1), like ``/api/failures/status``."""
        with no_traffic_client:
            response = no_traffic_client.get("/api/traffic/status")
        assert response.status_code == 200
        assert response.json()["contacts"] == []

    def test_the_websocket_still_streams_an_empty_picture(
        self, no_traffic_client: TestClient
    ) -> None:
        """``WS /ws/traffic`` is never gated either (§2.1): the Instructor Map
        iterates it unconditionally, exactly as it does ``/ws/state``, and an
        adapter without ``can_spawn_traffic`` pushes ``[]`` rather than closing
        or refusing the handshake."""
        with no_traffic_client, no_traffic_client.websocket_connect("/ws/traffic") as socket:
            assert socket.receive_json() == []


# ---------------------------------------------------------------------------
# Capacity (§2.1, D6)
# ---------------------------------------------------------------------------


class TestCapacity:
    def test_the_twentieth_spawn_is_a_409_with_the_exact_sentence(self, client: TestClient) -> None:
        with client:
            for index in range(_FAKE_MAX_TRAFFIC):
                _spawn_custom(client, f"TFC{index:02d}")
            over = client.post("/api/traffic/spawn", json=_custom_track_body("TFC99"))
        assert over.status_code == 409
        assert over.json()["detail"] == (
            f"'fake' is at capacity: "
            f"{_FAKE_MAX_TRAFFIC} of {_FAKE_MAX_TRAFFIC} traffic slots in use."
        )


# ---------------------------------------------------------------------------
# WS /ws/traffic (§2, D10) — the stream_state liveness pattern
# ---------------------------------------------------------------------------


class TestTrafficWebSocket:
    def test_a_rest_spawned_contact_appears_in_a_subsequent_frame(self, client: TestClient) -> None:
        """Connect the stream, spawn via REST from a second client (§8.3), and
        require a following frame to carry the contact — proves the stream is
        live, not a snapshot taken at connect."""
        with (
            client,
            client.websocket_connect("/ws/traffic") as socket,
            TestClient(create_app()) as rest,
        ):
            traffic_id = _spawn_custom(rest)["contacts"][0]["traffic_id"]
            for _ in range(10):
                frame = socket.receive_json()
                assert isinstance(frame, list)
                if traffic_id in {contact["traffic_id"] for contact in frame}:
                    break
            else:
                pytest.fail("the spawned contact never appeared in a /ws/traffic frame")


# ---------------------------------------------------------------------------
# Validation — 422 (§2.2)
# ---------------------------------------------------------------------------


class TestValidation:
    def test_an_unknown_discriminator_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/traffic/spawn", json={"type": "meteor_shower"})
        assert response.status_code == 422

    def test_empty_distances_on_an_approach_sequence_are_refused(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/traffic/spawn",
                json={
                    "type": "approach_sequence",
                    "airport_icao": "ZZZZ",
                    "runway_ident": "36",
                    "distances_nm": [],
                },
            )
        assert response.status_code == 422

    def test_a_one_point_taxi_route_is_refused(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/traffic/spawn",
                json={
                    "type": "taxi_traffic",
                    "route": [{"latitude": 40.0, "longitude": -3.0}],
                },
            )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"type": "tcas_conflict", "closure_ias_kt": 0.0}, id="tcas-zero-closure"),
            pytest.param(
                {
                    "type": "runway_incursion",
                    "airport_icao": "ZZZZ",
                    "runway_ident": "36",
                    "vehicle_speed_kt": 0.0,
                },
                id="incursion-zero-vehicle-speed",
            ),
            pytest.param(
                {
                    "type": "approach_sequence",
                    "airport_icao": "ZZZZ",
                    "runway_ident": "36",
                    "distances_nm": [10.0],
                    "ias_kt": 0.0,
                },
                id="approach-zero-ias",
            ),
            pytest.param(
                {
                    "type": "taxi_traffic",
                    "route": [
                        {"latitude": 40.0, "longitude": -3.0},
                        {"latitude": 40.01, "longitude": -3.0},
                    ],
                    "speed_kt": 0.0,
                },
                id="taxi-zero-speed",
            ),
        ],
    )
    def test_a_zero_speed_is_refused_at_the_schema(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        """The ``gt=0.0`` refusals: zero is never a meaningful speed — ``None``
        already means "use the default", so the schema refuses the degenerate
        motionless request instead of building it."""
        with client:
            response = client.post("/api/traffic/spawn", json=body)
        assert response.status_code == 422

    def test_a_custom_track_not_starting_at_t_zero_is_refused(self, client: TestClient) -> None:
        """The model's own validator (§3.2) checks a hand-authored track exactly
        like a server-resolved one."""
        body = _custom_track_body()
        body["track"]["waypoints"][0]["t_offset_s"] = 5.0
        with client:
            response = client.post("/api/traffic/spawn", json=body)
        assert response.status_code == 422

    def test_a_builder_valueerror_maps_to_422(self, client: TestClient) -> None:
        """``runway_incursion_track`` refuses to time a crossing against a
        stationary aircraft (its arrival is undefined) — the one place a
        well-formed request reaches a ``core.traffic`` builder's own
        ``ValueError``, mapped to 422 exactly as ``position_routes._resolve``
        maps ``core.geodesy``'s (§6.3)."""
        with client:
            setup = client.post("/api/aircraft/setup", json={"ias_kt": 0.0})
            assert setup.status_code == 200, setup.text
            response = client.post(
                "/api/traffic/spawn",
                json={"type": "runway_incursion", "airport_icao": "ZZZZ", "runway_ident": "36"},
            )
        assert response.status_code == 422
        assert "stationary" in response.json()["detail"]
