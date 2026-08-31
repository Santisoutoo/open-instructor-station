"""``/api/pushback/*`` — exercised against ``FakeSimAdapter`` (§8.4 of
``docs/designs/pushback-manager.md``).

No navdata fixture: this manager names no airport and reads no
``NavdataProvider``, so — like the Fuel & Payload routes — these tests build
their own ``TestClient`` instead of reusing ``tests/server/conftest.py``'s
navdata-backed one.

The geometry is asserted against numbers computed here with ``math``, not
against a second call to :func:`core.pushback.pushback_target`: a test that
re-runs the implementation cannot tell you the implementation is right. §8.1's
worked example (heading 090°, right, 30 m, 90°) is hand-checkable — the final
heading is 180° with no trig at all, and the chord is
``2 · (30 / (π/2)) · sin(45°) ≈ 27.01 m`` on a true bearing of 315°.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.geodesy import METRES_PER_NAUTICAL_MILE, distance_and_bearing
from core.models import AircraftState, GeoPosition
from core.pushback import (
    PUSHBACK_MAX_ANGLE_DEG,
    PUSHBACK_MAX_DISTANCE_M,
    PUSHBACK_PATH_PREVIEW_POINTS,
)
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter

#: A parked aircraft on a round-numbered spot, heading due east: the back
#: bearing is 270°, so "20 m straight back" is "20 m due west" and every
#: assertion below reads by eye.
PARKED = AircraftState(
    latitude=40.0,
    longitude=-3.0,
    altitude_ft=1000.0,
    heading_deg=90.0,
    ias_kt=0.0,
    vertical_speed_fpm=0.0,
    pitch_deg=0.0,
    roll_deg=0.0,
    on_ground=True,
)

#: The same aircraft, airborne — the 409 precondition, not a capability.
AIRBORNE = PARKED.model_copy(update={"altitude_ft": 3000.0, "ias_kt": 120.0, "on_ground": False})

#: 1 mm, in nautical miles: the tolerance §8.1 asks for on every distance.
MILLIMETRE_NM = 0.001 / METRES_PER_NAUTICAL_MILE


class _NoPushbackAdapter(FakeSimAdapter):
    """A fake that declares every capability except ``can_pushback``."""

    @property
    def name(self) -> str:
        return "no-pushback"

    @property
    def capabilities(self) -> Capabilities:
        return super().capabilities.model_copy(update={"can_pushback": False})


def _client_for(adapter: FakeSimAdapter, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: adapter)
    reset_adapter()
    return TestClient(create_app())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The default fake, parked and on the ground."""
    yield _client_for(FakeSimAdapter(initial_state=PARKED), monkeypatch)
    reset_adapter()


@pytest.fixture
def airborne_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A fake that declares ``can_pushback`` but is flying."""
    yield _client_for(FakeSimAdapter(initial_state=AIRBORNE), monkeypatch)
    reset_adapter()


@pytest.fixture
def no_capability_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A parked fake whose adapter does not declare ``can_pushback``."""
    yield _client_for(_NoPushbackAdapter(initial_state=PARKED), monkeypatch)
    reset_adapter()


def _position(body: dict[str, float]) -> GeoPosition:
    """A GeoPosition from a JSON position object, for the geodesy assertions."""
    return GeoPosition(
        latitude=body["latitude"],
        longitude=body["longitude"],
        altitude_ft=body.get("altitude_ft", 0.0),
    )


def _live_state(client: TestClient) -> dict[str, float]:
    """The live aircraft state, for "nothing moved" assertions."""
    body: dict[str, float] = client.get("/api/state").json()
    return body


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_reports_supported_with_the_exact_bounds(client: TestClient) -> None:
    """The panel's sliders read their bounds from here, never from a second copy."""
    with client:
        response = client.get("/api/pushback/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["adapter"] == "fake"
    assert body["supported"] is True
    assert body["reason"] is None
    assert body["max_distance_m"] == PUSHBACK_MAX_DISTANCE_M
    assert body["max_angle_deg"] == PUSHBACK_MAX_ANGLE_DEG


def test_manifest_is_always_200_even_without_the_capability(
    no_capability_client: TestClient,
) -> None:
    """Never gated: the panel learns it is disabled by *reading*, not by failing."""
    with no_capability_client:
        response = no_capability_client.get("/api/pushback/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False
    assert body["reason"] == "The 'no-pushback' adapter does not declare can_pushback."


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def test_preview_straight_pushes_due_west_at_an_unchanged_heading(client: TestClient) -> None:
    """§8.1's straight case, through HTTP: 20 m at the back bearing, heading held."""
    with client:
        response = client.post(
            "/api/pushback/preview", json={"direction": "straight", "distance_m": 20.0}
        )
    assert response.status_code == 200
    body = response.json()

    assert body["current_heading_deg"] == pytest.approx(90.0)
    assert body["target"]["heading_deg"] == pytest.approx(90.0)
    distance_nm, bearing_deg = distance_and_bearing(
        _position(body["current_position"]), _position(body["target"]["position"])
    )
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(20.0, abs=0.001)
    assert bearing_deg == pytest.approx(270.0, abs=0.01)


def test_preview_right_arc_matches_the_worked_example(client: TestClient) -> None:
    """§3's worked example: heading 090° + right 90° over 30 m of arc.

    The chord and its bearing are computed here from the radius identity, so
    the assertion is independent of ``core.pushback``'s own arithmetic.
    """
    with client:
        response = client.post(
            "/api/pushback/preview",
            json={"direction": "right", "distance_m": 30.0, "angle_deg": 90.0},
        )
    assert response.status_code == 200
    body = response.json()

    assert body["target"]["heading_deg"] == pytest.approx(180.0)
    expected_chord_m = 2.0 * (30.0 / (math.pi / 2.0)) * math.sin(math.pi / 4.0)
    distance_nm, bearing_deg = distance_and_bearing(
        _position(body["current_position"]), _position(body["target"]["position"])
    )
    assert distance_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(expected_chord_m, abs=0.001)
    assert bearing_deg == pytest.approx(315.0, abs=0.01)


def test_preview_left_arc_mirrors_the_right_one(client: TestClient) -> None:
    """D5's sign convention, the other way: the nose ends up counter-clockwise."""
    with client:
        response = client.post(
            "/api/pushback/preview",
            json={"direction": "left", "distance_m": 30.0, "angle_deg": 90.0},
        )
    body = response.json()

    assert body["target"]["heading_deg"] == pytest.approx(0.0)
    _distance_nm, bearing_deg = distance_and_bearing(
        _position(body["current_position"]), _position(body["target"]["position"])
    )
    assert bearing_deg == pytest.approx(225.0, abs=0.01)


def test_preview_returns_the_whole_path(client: TestClient) -> None:
    """The panel draws ``path_preview`` verbatim: origin first, target last."""
    with client:
        response = client.post(
            "/api/pushback/preview",
            json={"direction": "right", "distance_m": 30.0, "angle_deg": 90.0},
        )
    body = response.json()
    path = body["target"]["path_preview"]

    assert len(path) == PUSHBACK_PATH_PREVIEW_POINTS + 1
    start_nm, _bearing = distance_and_bearing(
        _position(body["current_position"]), _position(path[0])
    )
    assert start_nm == pytest.approx(0.0, abs=MILLIMETRE_NM)
    assert path[-1] == body["target"]["position"]


def test_preview_needs_no_capability(no_capability_client: TestClient) -> None:
    """D6: preview reads state and is otherwise ungated — an adapter that cannot
    push back still answers what a push back *would* look like."""
    with no_capability_client:
        response = no_capability_client.post(
            "/api/pushback/preview", json={"direction": "straight", "distance_m": 20.0}
        )
    assert response.status_code == 200
    assert response.json()["target"]["heading_deg"] == pytest.approx(90.0)


def test_preview_refuses_an_airborne_aircraft_with_409(airborne_client: TestClient) -> None:
    """The precondition is enforced on preview too: drawing a path that execute
    would refuse is a lie. Still 409, never 501 — the adapter can push back."""
    with airborne_client:
        response = airborne_client.post(
            "/api/pushback/preview", json={"direction": "straight", "distance_m": 20.0}
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot push back — the aircraft is airborne."


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_execute_moves_the_aircraft_to_the_previewed_target(client: TestClient) -> None:
    """The read-back is the honest verdict, and it agrees with the preview."""
    request = {"direction": "straight", "distance_m": 20.0}
    with client:
        previewed = client.post("/api/pushback/preview", json=request).json()
        response = client.post("/api/pushback/execute", json=request)
    assert response.status_code == 200
    body = response.json()

    assert body["request"] == {"direction": "straight", "distance_m": 20.0, "angle_deg": 0.0}
    assert body["target"] == previewed["target"]
    # The fake writes the target verbatim, so the read-back is exact.
    assert body["state"]["latitude"] == pytest.approx(body["target"]["position"]["latitude"])
    assert body["state"]["longitude"] == pytest.approx(body["target"]["position"]["longitude"])
    assert body["state"]["heading_deg"] == pytest.approx(90.0)
    assert body["state"]["ias_kt"] == pytest.approx(0.0)
    assert body["state"]["on_ground"] is True


def test_execute_rotates_the_nose_by_the_full_angle(client: TestClient) -> None:
    """§3's worked example again, this time actually written to the adapter."""
    with client:
        response = client.post(
            "/api/pushback/execute",
            json={"direction": "right", "distance_m": 30.0, "angle_deg": 90.0},
        )
    assert response.status_code == 200
    assert response.json()["state"]["heading_deg"] == pytest.approx(180.0)


def test_execute_twice_pushes_twice_as_far(client: TestClient) -> None:
    """A relative command, not an absolute target: replaying it pushes again."""
    request = {"direction": "straight", "distance_m": 20.0}
    with client:
        once = client.post("/api/pushback/execute", json=request).json()
        twice = client.post("/api/pushback/execute", json=request).json()

    home = GeoPosition(latitude=PARKED.latitude, longitude=PARKED.longitude)
    once_nm, _b1 = distance_and_bearing(home, _position(once["state"]))
    twice_nm, _b2 = distance_and_bearing(home, _position(twice["state"]))
    assert once_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(20.0, abs=0.001)
    assert twice_nm * METRES_PER_NAUTICAL_MILE == pytest.approx(40.0, abs=0.001)


def test_execute_refuses_an_airborne_aircraft_with_409(airborne_client: TestClient) -> None:
    """D8: a state precondition, not a capability failure. The aircraft is left alone."""
    with airborne_client:
        response = airborne_client.post(
            "/api/pushback/execute", json={"direction": "straight", "distance_m": 20.0}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "Cannot push back — the aircraft is airborne."
        state = _live_state(airborne_client)
    assert state["latitude"] == pytest.approx(AIRBORNE.latitude)
    assert state["longitude"] == pytest.approx(AIRBORNE.longitude)


def test_execute_without_the_capability_is_501(no_capability_client: TestClient) -> None:
    """The capability answer, distinct from the 409 above: this simulator has no
    pushback at all, and the panel should have been disabled long before."""
    with no_capability_client:
        response = no_capability_client.post(
            "/api/pushback/execute", json={"direction": "straight", "distance_m": 20.0}
        )
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "does not declare can_pushback" in detail
    assert "no-pushback" in detail


# ---------------------------------------------------------------------------
# 422 — the request itself cannot be honoured (§2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"direction": "straight", "distance_m": 20.0, "angle_deg": 5.0}, "angle on a straight"),
        ({"direction": "left", "distance_m": 20.0, "angle_deg": 0.0}, "no angle on a turn"),
        ({"direction": "right", "distance_m": 20.0}, "a turn defaulting to angle 0"),
        ({"direction": "straight", "distance_m": 0.0}, "a zero-length push"),
        (
            {"direction": "straight", "distance_m": PUSHBACK_MAX_DISTANCE_M + 1.0},
            "past max_distance_m",
        ),
        (
            {"direction": "right", "distance_m": 20.0, "angle_deg": PUSHBACK_MAX_ANGLE_DEG + 1.0},
            "past max_angle_deg",
        ),
        ({"direction": "sideways", "distance_m": 20.0}, "not a direction"),
    ],
)
def test_invalid_requests_are_422_on_both_write_paths(
    client: TestClient, body: dict[str, object], why: str
) -> None:
    """The rule lives on ``PushbackRequest`` (D9), so preview and execute
    enforce it identically — and so will a scenario step, later."""
    with client:
        assert client.post("/api/pushback/preview", json=body).status_code == 422, why
        assert client.post("/api/pushback/execute", json=body).status_code == 422, why
