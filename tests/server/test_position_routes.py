"""``/api/position/*`` — staging and committing a placement.

Two things here are worth more than the rest of the file.

**``preview`` must not touch the simulator.** The whole staging design collapses
if looking at a placement moves the aeroplane, so that is asserted directly
rather than assumed from reading the route.

**``apply`` must write the setup before the teleport.** A parked aircraft placed
on a 10 NM final with no speed arrives below stall and flies into terrain — the
defect behind issue #39, measured against a live X-Plane. The order is asserted
by recording the calls, not by inspecting the response, because a response that
looks right is exactly what the buggy order produced.

**A speed of zero is that same defect, whoever asked for it.** ``ias_kt: 0`` on
an airborne placement is accepted — a stationary aircraft in the air is a
legitimate demonstration and refusing would overrule the instructor — but it is
never *affirmed*: the notes warn, and the assertions below are written against
the **resolved** speed rather than against a substring that reads the same at
137 kt and at 0.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.geodesy import (
    APPROACH_CATEGORY_CIRCLING_IAS_KT,
    APPROACH_CATEGORY_VAT_KT,
    DEFAULT_GLIDESLOPE_DEG,
    FEET_PER_MINUTE_PER_KNOT,
    glideslope_altitude_ft,
)
from core.models import AircraftSetup, GeoPosition, Ils, LightsSetup, Runway
from core.navdata.in_memory import InMemoryNavdataProvider
from core.navdata.models import (
    Airport,
    AltitudeConstraint,
    Hold,
    Procedure,
    ProcedureLeg,
    SpeedConstraint,
    Waypoint,
)
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter, reset_navdata
from server.position_routes import (
    CAPABILITY_UNAVAILABLE_STATUS,
    UNPOSITIONABLE_STATUS,
    _merge_setup,
)
from tests.server.conftest import AIRPORT, FIX_GOXOL, RUNWAY_18, RUNWAY_36, build_provider

#: 3° glidepath, 10 NM out, threshold at 1000 ft:
#: 1000 + tan(3°) x 10 x 6076.115486 = 4184.4 ft.
TEN_NM_FINAL_ALTITUDE_FT = 4184.4

FINAL_10NM = {
    "type": "runway",
    "airport_icao": "ZZZZ",
    "runway_ident": "36",
    "placement": "final_10nm",
}


def preview(client: TestClient, request: dict[str, Any]) -> dict[str, Any]:
    """POST a placement request and return the preview, failing loudly on an error."""
    with client:
        response = client.post("/api/position/preview", json=request)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _has_running_loop() -> bool:
    """Whether this call is executing **on** the event loop.

    True inside the body of an ``async def`` route, false inside a threadpool
    worker — which is the whole question when asking whether a blocking navdata
    read is stalling the telemetry push.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class TestPreviewGeometry:
    def test_a_ten_mile_final_lands_on_the_glidepath(self, client: TestClient) -> None:
        body = preview(client, FINAL_10NM)
        placement = body["placement"]
        assert placement["position"]["altitude_ft"] == pytest.approx(
            TEN_NM_FINAL_ALTITUDE_FT, abs=0.1
        )
        # Runway 36 points due true north, so the final lies due south of it.
        assert placement["position"]["latitude"] < 40.0
        assert placement["position"]["longitude"] == pytest.approx(-3.0, abs=1e-6)
        assert placement["heading_deg"] == pytest.approx(0.0)

    def test_a_final_is_never_placed_at_zero_knots(self, client: TestClient) -> None:
        body = preview(client, FINAL_10NM)
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_VAT_KT["B"]
        assert body["setup"]["ias_kt"] > 0.0

    def test_a_circuit_leg_uses_circling_speed_not_threshold_speed(
        self, client: TestClient
    ) -> None:
        body = preview(client, {**FINAL_10NM, "placement": "left_downwind"})
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_CIRCLING_IAS_KT["B"]

    def test_an_explicit_speed_wins_over_the_category(self, client: TestClient) -> None:
        body = preview(client, {**FINAL_10NM, "ias_kt": 137.0, "category": "A"})
        assert body["placement"]["ias_kt"] == 137.0

    def test_the_setup_is_what_gets_applied_before_the_teleport(self, client: TestClient) -> None:
        body = preview(client, FINAL_10NM)
        setup = body["setup"]
        assert setup["altitude_ft"] == pytest.approx(TEN_NM_FINAL_ALTITUDE_FT, abs=0.1)
        assert setup["heading_deg"] == pytest.approx(0.0)


class TestPreviewIsSideEffectFree:
    def test_previewing_does_not_move_the_aircraft(self, client: TestClient) -> None:
        with client:
            before = client.get("/api/state").json()
            client.post("/api/position/preview", json=FINAL_10NM)
            after = client.get("/api/state").json()
        assert before == after


class TestSchematic:
    def test_the_runway_is_projected_into_its_own_frame(self, client: TestClient) -> None:
        schematic = preview(client, FINAL_10NM)["schematic"]
        assert schematic["runway_ident"] == "36"
        assert schematic["glidepath_deg"] == 3.0
        by_role = {point["role"]: point for point in schematic["points"]}
        assert by_role["threshold"]["x_nm"] == pytest.approx(0.0)
        assert by_role["threshold"]["y_nm"] == pytest.approx(0.0)
        # 10 NM before the threshold is 10 NM *behind* it along the centreline.
        assert by_role["placement"]["x_nm"] == pytest.approx(-10.0, abs=0.01)
        assert by_role["placement"]["y_nm"] == pytest.approx(0.0, abs=0.01)

    def test_a_downwind_leg_is_offset_to_the_correct_side(self, client: TestClient) -> None:
        schematic = preview(client, {**FINAL_10NM, "placement": "left_downwind"})["schematic"]
        placement = next(p for p in schematic["points"] if p["role"] == "placement")
        # A left-hand circuit on runway 36 lies to the west: negative "across".
        assert placement["y_nm"] < 0.0

    def test_a_circuit_leg_carries_no_glidepath(self, client: TestClient) -> None:
        schematic = preview(client, {**FINAL_10NM, "placement": "left_base"})["schematic"]
        assert schematic["glidepath_deg"] is None


class TestNotes:
    def test_a_glidepath_altitude_states_where_it_came_from(self, client: TestClient) -> None:
        notes = " ".join(preview(client, FINAL_10NM)["notes"])
        assert "glidepath" in notes
        assert "10 NM" in notes

    def test_a_category_default_says_it_is_a_guess(self, client: TestClient) -> None:
        notes = " ".join(preview(client, FINAL_10NM)["notes"])
        assert "category default" in notes

    def test_an_explicit_speed_is_not_dressed_up_as_a_computation(self, client: TestClient) -> None:
        """Assert on the **resolved** number, not on a substring.

        The previous version of this test asserted only that the notes contained
        ``"as requested"``, which reads identically at 137 kt and at 0 kt — and a
        0 kt final is issue #39's measured crash. A note that names a speed has
        to be checked against the speed that was actually resolved.
        """
        body = preview(client, {**FINAL_10NM, "ias_kt": 137.0})
        assert body["placement"]["ias_kt"] == 137.0
        notes = " ".join(body["notes"])
        assert "137 kt, exactly as requested." in notes
        # The instructor named the number, so it must not be attributed to a chart.
        assert "category default" not in notes


class TestTheProfileConfigurationIsStagedAndDisclosed:
    """``to_setup()`` emits the full pre-teleport configuration (#8), and the
    preview both carries it in ``setup`` — where the staging bar's edits merge
    over it — and discloses it in the notes, verbatim, because the numbers
    are airframe-generic hand-off constants and the instructor is the one who
    knows the airframe."""

    def test_a_final_arrives_configured(self, client: TestClient) -> None:
        setup = preview(client, FINAL_10NM)["setup"]
        assert setup["gear_down"] is True
        assert setup["flaps_ratio"] == 0.5
        assert setup["throttle_ratio"] == 0.30
        assert setup["elevator_trim_ratio"] == 0.10
        assert setup["roll_deg"] == 0.0
        assert setup["lights"]["landing"] is True

    def test_a_final_descends_at_the_glidepath_rate(self, client: TestClient) -> None:
        """120 kt on the 3° path: 120 · 101.2686 · tan 3° = 637 fpm down."""
        setup = preview(client, FINAL_10NM)["setup"]
        expected = -120.0 * FEET_PER_MINUTE_PER_KNOT * math.tan(math.radians(3.0))
        assert setup["vertical_speed_fpm"] == pytest.approx(expected)

    def test_a_runway_final_is_tuned_to_the_published_ils(self, client: TestClient) -> None:
        """Runway 36 publishes 110.30 with a 002° magnetic front course, and the
        radios arrive with the geometry — NAV1 the frequency, the OBS the
        MAGNETIC course, because an OBS is magnetic on the aeroplane."""
        setup = preview(client, FINAL_10NM)["setup"]
        assert setup["nav1_freq_khz"] == 110300
        assert setup["obs1_deg"] == 2.0

    def test_the_notes_disclose_the_configuration(self, client: TestClient) -> None:
        notes = " ".join(preview(client, FINAL_10NM)["notes"])
        assert "Configured for a final: gear down, flaps 50%, throttle 30%, trim +0.10" in notes
        assert "descending 637 fpm on the 3.0° slope" in notes

    def test_the_notes_disclose_the_ils(self, client: TestClient) -> None:
        notes = " ".join(preview(client, FINAL_10NM)["notes"])
        assert "NAV1 110.30 / OBS 2° — the published ILS for 36." in notes

    def test_a_runway_without_an_ils_stages_no_radios(self, client: TestClient) -> None:
        body = preview(client, {**FINAL_10NM, "runway_ident": "18"})
        assert body["setup"]["nav1_freq_khz"] is None
        assert body["setup"]["obs1_deg"] is None
        assert "NAV1" not in " ".join(body["notes"])

    def test_a_base_leg_is_configured_per_leg(self, client: TestClient) -> None:
        body = preview(client, {**FINAL_10NM, "placement": "left_base"})
        assert body["setup"]["gear_down"] is True
        assert body["setup"]["flaps_ratio"] == 0.25
        notes = " ".join(body["notes"])
        assert "Configured for the base leg: gear down, flaps 25%, throttle 50%." in notes

    def test_a_crosswind_leg_is_still_clean(self, client: TestClient) -> None:
        body = preview(client, {**FINAL_10NM, "placement": "left_crosswind"})
        assert body["setup"]["gear_down"] is False
        assert body["setup"]["flaps_ratio"] == 0.0

    def test_a_stand_is_configured_for_the_ground(self, client: TestClient) -> None:
        body = preview(client, {"type": "parking", "airport_icao": "ZZZZ", "stand_name": "R32"})
        setup = body["setup"]
        assert setup["gear_down"] is True
        assert setup["throttle_ratio"] == 0.0
        # Roll and vertical speed belong to the terrain, not the placement.
        assert setup["vertical_speed_fpm"] is None
        assert setup["roll_deg"] is None
        notes = " ".join(body["notes"])
        assert "Configured for the ground: gear down, flaps up, throttle idle." in notes

    def test_a_hold_is_clean_and_level(self, client: TestClient) -> None:
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        setup = body["setup"]
        assert setup["gear_down"] is False
        assert setup["flaps_ratio"] == 0.0
        assert setup["throttle_ratio"] == 0.60
        assert setup["vertical_speed_fpm"] == 0.0
        notes = " ".join(body["notes"])
        assert "Configured for level flight: gear up, flaps up, throttle 60%." in notes


class TestTheInstructorOverridesTheProfile:
    """The sparse edits merge OVER the profile's output — profile first, the
    request second — so the instructor's word is final on any field, and the
    rest of the configuration survives around the edit."""

    def test_an_edited_field_wins_over_the_profile(self, client: TestClient) -> None:
        """Full flap on a final, against the profile's 0.5."""
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"flaps_ratio": 1.0}},
            )
        assert response.status_code == 200, response.text
        applied = response.json()["applied"]
        assert applied["flaps_ratio"] == 1.0
        assert applied["gear_down"] is True
        assert applied["throttle_ratio"] == 0.30


#: Every placement type that is airborne by construction, each asking for 0 kt.
#: A final, a circuit leg, a fix, a procedure leg and a hold are all *flown*;
#: only a stand and a sea-level coordinate are not.
AIRBORNE_AT_ZERO_KNOTS: dict[str, dict[str, Any]] = {
    "final": {**FINAL_10NM, "ias_kt": 0},
    "circuit_leg": {**FINAL_10NM, "placement": "left_downwind", "ias_kt": 0},
    "waypoint": {"type": "waypoint", "ident": "GOXOL", "altitude_ft": 9000.0, "ias_kt": 0},
    "procedure_leg": {
        "type": "procedure_leg",
        "airport_icao": "ZZZZ",
        "kind": "sid",
        "ident": "TEST1A",
        "sequence": 20,
        "ias_kt": 0,
    },
    "hold": {"type": "hold", "fix_ident": "GOXOL", "ias_kt": 0},
    "coordinate": {
        "type": "coordinate",
        "position": {"latitude": 40.5, "longitude": -3.5, "altitude_ft": 7000.0},
        "ias_kt": 0,
    },
}


class TestAZeroSpeedIsWarnedAboutWhoeverAskedForIt:
    """Issue #39, from the other direction.

    ``ias_kt`` is validated ``ge=0.0`` and ``core.geodesy`` returns an explicit
    value untouched, so ``0`` reaches the placement intact — a perfect 10 NM
    final at 4,184 ft with the aircraft below stall speed, which is the exact
    geometry that flew into terrain at LEMD. The guard existed only on the
    coordinate branch; these cases prove it now covers every placement that is
    not on the ground, and that it keys on the **resolved** speed rather than on
    who chose it.
    """

    @pytest.mark.parametrize(
        "request_body", AIRBORNE_AT_ZERO_KNOTS.values(), ids=list(AIRBORNE_AT_ZERO_KNOTS)
    )
    def test_zero_knots_in_the_air_is_warned_about(
        self, client: TestClient, request_body: dict[str, Any]
    ) -> None:
        body = preview(client, request_body)
        assert body["placement"]["ias_kt"] == 0.0
        assert body["placement"]["position"]["altitude_ft"] > 0.0
        notes = " ".join(body["notes"])
        assert "stall" in notes
        # The old note affirmed the number instead: "0 kt, as requested."
        assert "as requested" not in notes

    def test_the_warning_is_not_a_refusal(self, client: TestClient) -> None:
        """A stationary aircraft in the air is a legitimate demonstration."""
        with client:
            response = client.post(
                "/api/position/apply", json={"placement": {**FINAL_10NM, "ias_kt": 0}}
            )
        assert response.status_code == 200, response.text
        assert response.json()["applied"]["ias_kt"] == 0.0

    def test_a_stand_at_zero_knots_is_not_warned_about(self, client: TestClient) -> None:
        body = preview(client, {"type": "parking", "airport_icao": "ZZZZ", "stand_name": "R32"})
        assert body["placement"]["ias_kt"] == 0.0
        assert "stall" not in " ".join(body["notes"])

    def test_a_ground_level_coordinate_at_zero_knots_is_not_warned_about(
        self, client: TestClient
    ) -> None:
        body = preview(
            client,
            {
                "type": "coordinate",
                "position": {"latitude": 40.5, "longitude": -3.5, "altitude_ft": 0.0},
                "ias_kt": 0,
            },
        )
        notes = " ".join(body["notes"])
        assert "stall" not in notes
        assert "on the ground" in notes


class TestOtherPlacementTypes:
    def test_a_stand_is_on_the_ground_at_zero_knots(self, client: TestClient) -> None:
        body = preview(client, {"type": "parking", "airport_icao": "ZZZZ", "stand_name": "R32"})
        assert body["placement"]["ias_kt"] == 0.0
        assert body["placement"]["heading_deg"] == pytest.approx(270.0)

    def test_a_stand_name_is_matched_case_insensitively(self, client: TestClient) -> None:
        body = preview(client, {"type": "parking", "airport_icao": "ZZZZ", "stand_name": "r32"})
        assert body["placement"]["ias_kt"] == 0.0

    def test_an_unknown_stand_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview",
                json={"type": "parking", "airport_icao": "ZZZZ", "stand_name": "Z99"},
            )
        assert response.status_code == 404

    def test_a_coordinate_is_taken_verbatim(self, client: TestClient) -> None:
        body = preview(
            client,
            {
                "type": "coordinate",
                "position": {"latitude": 40.5, "longitude": -3.5, "altitude_ft": 7000.0},
                "heading_deg": 90.0,
                "ias_kt": 250.0,
            },
        )
        assert body["placement"]["position"]["latitude"] == 40.5
        assert body["placement"]["ias_kt"] == 250.0

    def test_an_airborne_coordinate_at_zero_knots_is_called_out(self, client: TestClient) -> None:
        """The one placement whose default is 0 kt has to say so when it is wrong."""
        body = preview(
            client,
            {
                "type": "coordinate",
                "position": {"latitude": 40.5, "longitude": -3.5, "altitude_ft": 7000.0},
            },
        )
        assert any("below" in note and "stall" in note for note in body["notes"])

    def test_a_waypoint(self, client: TestClient) -> None:
        body = preview(client, {"type": "waypoint", "ident": "GOXOL", "altitude_ft": 9000.0})
        assert body["placement"]["position"]["altitude_ft"] == 9000.0
        assert body["placement"]["ias_kt"] > 0.0

    def test_an_unknown_waypoint_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview",
                json={"type": "waypoint", "ident": "NOSUCH", "altitude_ft": 9000.0},
            )
        assert response.status_code == 404


class TestProcedureLegs:
    def test_a_positionable_leg_takes_its_published_constraints(self, client: TestClient) -> None:
        body = preview(
            client,
            {
                "type": "procedure_leg",
                "airport_icao": "ZZZZ",
                "kind": "sid",
                "ident": "TEST1A",
                "sequence": 20,
            },
        )
        assert body["placement"]["position"]["altitude_ft"] == 6000.0
        # The leg is placarded at 250 kt, and a placard is a **ceiling**: the aircraft
        # flies its own category speed clamped to it, never the placard itself. Flying
        # 250 kt because a chart says "250" would put a trainer 100 kt over its
        # manoeuvring speed.
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_CIRCLING_IAS_KT["B"]
        notes = " ".join(body["notes"])
        assert "published constraint" in notes.lower()
        assert "250" in notes

    def test_an_unpositionable_leg_is_refused_with_its_reason(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview",
                json={
                    "type": "procedure_leg",
                    "airport_icao": "ZZZZ",
                    "kind": "sid",
                    "ident": "TEST1A",
                    "sequence": 10,
                },
            )
        assert response.status_code == UNPOSITIONABLE_STATUS
        assert "no defensible coordinate" in response.json()["detail"]

    def test_a_leg_with_no_published_altitude_needs_one_given(self, client: TestClient) -> None:
        request = {
            "type": "procedure_leg",
            "airport_icao": "ZZZZ",
            "kind": "sid",
            "ident": "TEST1A",
            "sequence": 30,
        }
        with client:
            without = client.post("/api/position/preview", json=request)
            with_altitude = client.post(
                "/api/position/preview", json={**request, "altitude_ft": 8000.0}
            )
        assert without.status_code == UNPOSITIONABLE_STATUS
        assert with_altitude.status_code == 200

    def test_an_unknown_leg_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview",
                json={
                    "type": "procedure_leg",
                    "airport_icao": "ZZZZ",
                    "kind": "sid",
                    "ident": "TEST1A",
                    "sequence": 999,
                },
            )
        assert response.status_code == 404


class TestHoldPlacement:
    def test_it_uses_the_published_minimum_and_clamps_to_the_placard(
        self, client: TestClient
    ) -> None:
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        assert body["placement"]["position"]["altitude_ft"] == 7000.0
        # Placarded at 210 kt, which is a ceiling a category B aircraft never reaches.
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_CIRCLING_IAS_KT["B"]
        assert "at or below 210 kt" in " ".join(body["notes"])

    def test_the_magnetic_course_is_converted_and_the_note_says_so(
        self, client: TestClient
    ) -> None:
        """The airport publishes -2° variation, so 180° magnetic is 178° true."""
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        assert body["placement"]["heading_deg"] == pytest.approx(178.0)
        notes = " ".join(body["notes"])
        assert "magnetic" in notes
        assert "variation" in notes

    def test_an_unknown_hold_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview", json={"type": "hold", "fix_ident": "NOSUCH"}
            )
        assert response.status_code == 404


#: What the recording fixture hands a test: the client, the call order, the
#: speeds and the vertical speeds ``set_position`` was told.
RecordingClient = tuple[TestClient, list[str], list[float | None], list[float | None]]


class TestApplyOrdersTheWrites:
    """The setup goes in before the teleport, always."""

    @pytest.fixture
    def recording_client(self, monkeypatch: pytest.MonkeyPatch) -> RecordingClient:
        calls: list[str] = []
        speeds: list[float | None] = []
        verticals: list[float | None] = []

        class RecordingAdapter(FakeSimAdapter):
            async def apply_setup(self, setup: AircraftSetup) -> None:
                calls.append("apply_setup")
                await super().apply_setup(setup)

            async def set_position(
                self,
                position: GeoPosition,
                heading_deg: float,
                *,
                ias_kt: float | None = None,
                vertical_speed_fpm: float | None = None,
            ) -> None:
                calls.append("set_position")
                speeds.append(ias_kt)
                verticals.append(vertical_speed_fpm)
                await super().set_position(
                    position,
                    heading_deg,
                    ias_kt=ias_kt,
                    vertical_speed_fpm=vertical_speed_fpm,
                )

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: RecordingAdapter())
        reset_adapter()
        reset_navdata()
        return TestClient(create_app()), calls, speeds, verticals

    def test_setup_is_written_before_the_teleport(self, recording_client: RecordingClient) -> None:
        client, calls, _speeds, _verticals = recording_client
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == 200, response.text
        assert calls == ["apply_setup", "set_position"]

    def test_the_teleport_is_told_the_speed_as_well(
        self, recording_client: RecordingClient
    ) -> None:
        """Writing the speed once, into the setup, is not enough.

        ``apply_setup`` releases the flight model when it finishes and the aircraft
        decelerates while it settles, so an adapter left to read the speed for itself
        carries the decayed value onto the new heading — 120 kt commanded, 83 kt
        measured at LEMD (issue #39). The route must hand the speed to the teleport
        too, and only the call itself shows whether it did.
        """
        client, _calls, speeds, _verticals = recording_client
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == 200, response.text
        assert speeds == [APPROACH_CATEGORY_VAT_KT["B"]]

    def test_the_teleport_is_told_the_descent_as_well(
        self, recording_client: RecordingClient
    ) -> None:
        """Issue #39's lesson, repeated on the vertical axis (#8, #81).

        The teleport writes the whole velocity vector, so a descent rate left
        only in the setup arrives level — the adapter used to zero ``local_vy``
        outright. The route must re-deliver it beside the speed, and only the
        call itself shows whether it did.
        """
        client, _calls, _speeds, verticals = recording_client
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == 200, response.text
        expected = (
            -APPROACH_CATEGORY_VAT_KT["B"] * FEET_PER_MINUTE_PER_KNOT * math.tan(math.radians(3.0))
        )
        assert verticals == [pytest.approx(expected)]

    def test_the_aircraft_ends_up_where_the_placement_said(
        self, recording_client: RecordingClient
    ) -> None:
        client, _calls, _speeds, _verticals = recording_client
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        body = response.json()
        assert body["state"]["latitude"] == pytest.approx(
            body["placement"]["position"]["latitude"], abs=1e-6
        )
        assert body["applied"]["ias_kt"] == APPROACH_CATEGORY_VAT_KT["B"]


class TestApplyMergesTheStagingBarsEdits:
    def test_an_edited_field_wins(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"ias_kt": 95.0}},
            )
        assert response.status_code == 200, response.text
        assert response.json()["applied"]["ias_kt"] == 95.0

    def test_an_omitted_field_keeps_the_geometrys_value(self, client: TestClient) -> None:
        """A client that sends only a speed must not silently drop the altitude."""
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"ias_kt": 95.0}},
            )
        applied = response.json()["applied"]
        assert applied["altitude_ft"] == pytest.approx(TEN_NM_FINAL_ALTITUDE_FT, abs=0.1)

    def test_an_edit_can_add_a_field_the_geometry_never_sets(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"gear_down": True}},
            )
        assert response.json()["applied"]["gear_down"] is True


class TestAnEditedGeometryFieldActuallyTakes:
    """``altitude_ft`` and ``heading_deg`` are geometry, not setup.

    ``set_position`` writes both, and it runs **after** ``apply_setup``, so an
    edit handed to the setup was overwritten a moment later: an altitude edited
    to 1234 ft arrived as 4184.36 and a heading edited to 99° arrived as 0°.
    Two of the staging bar's four editable controls did nothing — and
    ``applied`` echoed the request back as though they had, which is the worse
    half of the defect.

    **Every assertion here is against the read-back ``state``.** The previous
    tests trusted the echo, which is exactly how this survived.
    """

    def test_an_edited_altitude_reaches_the_aircraft(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"altitude_ft": 1234.0}},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"]["altitude_ft"] == pytest.approx(1234.0)
        # And the placement reported back is the one that was flown to.
        assert body["placement"]["position"]["altitude_ft"] == pytest.approx(1234.0)

    def test_an_edited_heading_reaches_the_aircraft(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"heading_deg": 99.0}},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"]["heading_deg"] == pytest.approx(99.0)
        assert body["placement"]["heading_deg"] == pytest.approx(99.0)

    def test_applied_describes_the_outcome_and_not_the_request(self, client: TestClient) -> None:
        """The echo and the read-back have to agree, or the echo is a lie."""
        with client:
            response = client.post(
                "/api/position/apply",
                json={
                    "placement": FINAL_10NM,
                    "setup": {"altitude_ft": 1234.0, "heading_deg": 99.0},
                },
            )
        body = response.json()
        assert body["applied"]["altitude_ft"] == pytest.approx(body["state"]["altitude_ft"])
        assert body["applied"]["heading_deg"] == pytest.approx(body["state"]["heading_deg"])

    def test_the_lateral_geometry_is_still_the_placement_s(self, client: TestClient) -> None:
        """Editing the altitude must not move the aircraft off the centreline."""
        with client:
            staged = client.post("/api/position/preview", json=FINAL_10NM).json()
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"altitude_ft": 1234.0}},
            )
        state = response.json()["state"]
        assert state["latitude"] == pytest.approx(staged["placement"]["position"]["latitude"])
        assert state["longitude"] == pytest.approx(staged["placement"]["position"]["longitude"])

    def test_an_unedited_placement_keeps_its_computed_geometry(self, client: TestClient) -> None:
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        state = response.json()["state"]
        assert state["altitude_ft"] == pytest.approx(TEN_NM_FINAL_ALTITUDE_FT, abs=0.1)
        assert state["heading_deg"] == pytest.approx(0.0)


class TestTheMergedSetupIsValidated:
    """A merged setup must be an ``AircraftSetup``, sub-models included.

    ``model_dump`` is recursive and ``model_copy(update=...)`` does not validate,
    so the pair produced an ``AircraftSetup`` whose ``lights`` was a plain
    ``dict``. It type checks, it serialises identically, and then the X-Plane
    adapter does ``getattr(setup.lights, "landing")`` on it and the request dies
    as a 500 — **after** ``apply_setup`` has started writing to a live aircraft.
    """

    @pytest.mark.parametrize(
        "edit", [{"landing": True}, {}], ids=["a_switch_set", "an_empty_object"]
    )
    def test_a_nested_edit_survives_the_merge_as_a_model(self, edit: dict[str, Any]) -> None:
        merged = _merge_setup(
            AircraftSetup(altitude_ft=4184.4, ias_kt=120.0),
            AircraftSetup.model_validate({"lights": edit}),
        )
        # Before the fix this was a plain ``dict`` — the type says otherwise, so
        # only a runtime check can catch it.
        assert isinstance(merged.lights, LightsSetup)
        # The geometry's fields are still there.
        assert merged.altitude_ft == 4184.4

    def test_an_empty_nested_object_is_not_none(self) -> None:
        """``exclude_none`` empties the sub-object but keeps the key.

        So ``{"lights": {}}`` merges as ``{}`` rather than as ``None``, and every
        adapter that gates on ``setup.lights is not None`` walks straight into
        it. It has to arrive as a model with nothing switched.
        """
        merged = _merge_setup(AircraftSetup(), AircraftSetup(lights=LightsSetup()))
        assert merged.lights is not None
        assert merged.lights.landing is None

    @pytest.mark.parametrize(
        "lights", [{"landing": True}, {}], ids=["a_switch_set", "an_empty_object"]
    )
    def test_the_adapter_receives_a_model_and_not_a_dict(
        self, monkeypatch: pytest.MonkeyPatch, lights: dict[str, Any]
    ) -> None:
        """End to end, reading the setup exactly as ``XPlaneSimAdapter`` does."""
        received: list[object] = []
        switches: list[bool | None] = []

        class LightReadingAdapter(FakeSimAdapter):
            async def apply_setup(self, setup: AircraftSetup) -> None:
                received.append(setup.lights)
                if setup.lights is not None:
                    # The attribute access from adapters/xplane/xplane_adapter.py.
                    # On a dict it raises AttributeError and takes the request
                    # down as a 500, mid-write.
                    switches.append(setup.lights.landing)
                await super().apply_setup(setup)

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _s: LightReadingAdapter())
        reset_adapter()
        reset_navdata()

        with TestClient(create_app()) as client:
            response = client.post(
                "/api/position/apply",
                json={"placement": FINAL_10NM, "setup": {"lights": lights}},
            )
        assert response.status_code == 200, response.text
        assert isinstance(received[0], LightsSetup)
        assert switches == [lights.get("landing")]


class TestApplyResolvesNavdataOffTheEventLoop:
    """``apply`` is ``async def``, and navdata is blocking SQLite.

    Resolving inline blocks the loop that also serves ``/ws/state``, so the
    ~4 Hz telemetry feed to the tablet stalls during the one operation where the
    instructor is watching the aircraft move. ``asyncio.get_running_loop()``
    raises in a worker thread and succeeds on the loop, which is the difference
    stated directly rather than timed.
    """

    @staticmethod
    def _watch(provider: InMemoryNavdataProvider, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
        on_the_loop: list[bool] = []
        original = provider.get_runway

        def watched(icao: str, ident: str) -> Runway | None:
            on_the_loop.append(_has_running_loop())
            return original(icao, ident)

        monkeypatch.setattr(provider, "get_runway", watched)
        return on_the_loop

    def test_apply_resolves_in_the_threadpool(
        self,
        client: TestClient,
        navdata: InMemoryNavdataProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        on_the_loop = self._watch(navdata, monkeypatch)
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == 200, response.text
        assert on_the_loop == [False]

    def test_preview_resolves_in_the_threadpool_too(
        self,
        client: TestClient,
        navdata: InMemoryNavdataProvider,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A regression guard: ``preview`` is ``def`` and must stay ``def``."""
        on_the_loop = self._watch(navdata, monkeypatch)
        preview(client, FINAL_10NM)
        assert on_the_loop == [False]


class TestCapabilityGating:
    @pytest.fixture
    def incapable_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        class NoPositionAdapter(FakeSimAdapter):
            @property
            def capabilities(self) -> Capabilities:
                return super().capabilities.model_copy(update={"can_set_position": False})

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _s: NoPositionAdapter())
        reset_adapter()
        reset_navdata()
        return TestClient(create_app())

    def test_apply_is_501_when_the_adapter_cannot_reposition(
        self, incapable_client: TestClient
    ) -> None:
        with incapable_client:
            response = incapable_client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == CAPABILITY_UNAVAILABLE_STATUS
        assert "can_set_position" in response.json()["detail"]

    def test_preview_still_works_without_the_capability(self, incapable_client: TestClient) -> None:
        """Staging is navdata and arithmetic: it does not need a simulator at all."""
        with incapable_client:
            response = incapable_client.post("/api/position/preview", json=FINAL_10NM)
        assert response.status_code == 200


#: A second hand-written world, for the two things the shared one cannot show:
#: a runway whose published ILS glidepath is **not** the 3° standard, and
#: published speed bands that actually bite a category B aircraft (V_AT 120 kt,
#: circling 135 kt). Nothing here comes from a navdata file either — hard rule 4.
STEEP_ILS = Ils(
    airport_icao="ZZZZ",
    runway_ident="09",
    localizer_ident="IZZS",
    frequency_khz=110500,
    localizer_position=GeoPosition(latitude=40.0, longitude=-2.96, altitude_ft=1000.0),
    localizer_true_deg=90.0,
    localizer_mag_deg=92.0,
    glideslope_deg=3.8,
)

#: Runway 09 with a steep published path — London City flies 5.5°, so 3.8° is
#: nothing exotic. On a 10 NM final the difference from the 3° standard is
#: 851 ft, and it is 851 ft on the wrong side of the glideslope.
STEEP_RUNWAY = Runway(
    airport_icao="ZZZZ",
    ident="09",
    threshold=GeoPosition(latitude=40.0, longitude=-3.0, altitude_ft=1000.0),
    true_bearing_deg=90.0,
    length_m=3000.0,
    elevation_ft=1000.0,
    opposite_ident="27",
    ils=STEEP_ILS,
)


def _leg(sequence: int, ident: str, latitude: float, speed: SpeedConstraint) -> ProcedureLeg:
    return ProcedureLeg(
        sequence=sequence,
        path_terminator="TF",
        is_positionable=True,
        fix=Waypoint(
            ident=ident,
            kind="fix",
            position=GeoPosition(latitude=latitude, longitude=-3.0),
            region_code="ZZ",
        ),
        altitude=AltitudeConstraint(descriptor="+", min_ft=6000.0),
        speed=speed,
    )


#: One procedure, three published speed bands, one category: a ceiling that bites
#: (130 < 135 circling), a floor that bites (160 > 135), and a ceiling so low it
#: would stall the aeroplane (100 < 120 V_AT) and is therefore overridden.
BANDED_SID = Procedure(
    airport_icao="ZZZZ",
    kind="sid",
    ident="BAND1A",
    runway_idents=("09",),
    legs=(
        _leg(10, "CAPPD", 40.2, SpeedConstraint(descriptor="-", max_kt=130.0)),
        _leg(20, "FLOOR", 40.3, SpeedConstraint(descriptor="+", min_kt=160.0)),
        _leg(30, "TOOLO", 40.4, SpeedConstraint(descriptor="-", max_kt=100.0)),
    ),
)

#: A hold placarded below the category's circling speed, so the placard binds.
SLOW_HOLD = Hold(
    fix=Waypoint(ident="SLOWH", kind="fix", position=FIX_GOXOL.position, region_code="ZZ"),
    inbound_course_mag_deg=180.0,
    turn_direction="R",
    leg_time_min=1.0,
    min_altitude_ft=7000.0,
    speed_kt=130.0,
    airport_icao="ZZZZ",
)


#: An airport below mean sea level. Bar Yehuda, by the Dead Sea, sits at about
#: -1,266 ft and Schiphol at -11 ft, so "altitude above zero means airborne" is
#: not a simplification — it is wrong about real places, and wrong in the
#: direction that withholds a stall warning.
DEEP_AIRPORT = Airport(
    icao="ZZZB",
    name="Testfield Below Sea Level",
    position=GeoPosition(latitude=31.3, longitude=35.4, altitude_ft=-1266.0),
    elevation_ft=-1266.0,
    runway_count=1,
    longest_runway_m=1800.0,
    has_procedures=False,
)


@pytest.fixture
def charted_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client over the steep-ILS runway, the banded SID and the slow hold."""
    provider = InMemoryNavdataProvider(
        airports=[AIRPORT, DEEP_AIRPORT],
        runways=[RUNWAY_36, RUNWAY_18, STEEP_RUNWAY],
        fixes=[FIX_GOXOL],
        holds=[SLOW_HOLD],
        procedures=[BANDED_SID],
    )
    monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
    reset_navdata()
    yield TestClient(create_app())
    reset_navdata()


def _banded_leg(sequence: int) -> dict[str, Any]:
    return {
        "type": "procedure_leg",
        "airport_icao": "ZZZZ",
        "kind": "sid",
        "ident": "BAND1A",
        "sequence": sequence,
    }


class TestTheSpeedNoteNamesTheRightSource:
    """The provenance comes from the branch taken, not from a table lookup.

    ``_constrained_ias_kt`` can return a value that is neither the category's
    circling speed nor its threshold speed, and inferring the source by
    comparing its output against those two tables labelled a **charted** number
    "ICAO category B threshold speed (V_AT). This is a category default, not
    this airframe's number" — the exact inversion of the distinction the notes
    exist to make.
    """

    def test_a_published_ceiling_is_not_credited_to_the_category_chart(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, _banded_leg(10))
        assert body["placement"]["ias_kt"] == 130.0
        notes = " ".join(body["notes"])
        assert "published restriction of at or below 130 kt" in notes
        assert "threshold speed" not in notes
        assert "category default" not in notes

    def test_a_published_floor_is_not_credited_to_the_category_chart(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, _banded_leg(20))
        assert body["placement"]["ias_kt"] == 160.0
        notes = " ".join(body["notes"])
        assert "published minimum of 160 kt" in notes
        assert "threshold speed" not in notes

    def test_a_ceiling_below_the_category_floor_says_why_it_was_overridden(
        self, charted_client: TestClient
    ) -> None:
        """100 kt would stall a category B aeroplane, so V_AT wins — and says so."""
        body = preview(charted_client, _banded_leg(30))
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_VAT_KT["B"]
        notes = " ".join(body["notes"])
        assert "threshold speed (V_AT)" in notes
        assert "no chart may hand an aeroplane a stall" in notes

    def test_a_hold_placard_below_the_circling_speed_is_named_as_the_placard(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, {"type": "hold", "fix_ident": "SLOWH"})
        assert body["placement"]["ias_kt"] == 130.0
        notes = " ".join(body["notes"])
        assert "published restriction of at or below 130 kt" in notes
        assert "threshold speed" not in notes

    def test_an_unclamped_leg_still_names_the_category(self, charted_client: TestClient) -> None:
        """The shared world's 250 kt placard never bites, and must read that way."""
        body = preview(charted_client, {**FINAL_10NM, "runway_ident": "36"})
        notes = " ".join(body["notes"])
        assert "ICAO category B threshold speed (V_AT)" in notes
        assert "category default" in notes


class TestZeroKnotsIsMeasuredAgainstTheGroundAndNotAgainstZero:
    """Sea level is not the ground, and the difference withholds the warning.

    Gating the stall warning on ``altitude_ft > 0`` gives an airborne point over
    the Dead Sea — a real place, 1,410 ft below sea level — the reassuring
    sentence. The station has no terrain service but it does have every airport
    in the index, and the nearest one is a far better reference than zero.
    """

    def test_an_airborne_point_below_sea_level_is_still_warned_about(
        self, charted_client: TestClient
    ) -> None:
        body = preview(
            charted_client,
            {
                "type": "coordinate",
                "position": {"latitude": 31.3, "longitude": 35.4, "altitude_ft": -500.0},
            },
        )
        # 766 ft above the field, and below sea level: flying, by any reading.
        assert body["placement"]["ias_kt"] == 0.0
        assert "stall" in " ".join(body["notes"])

    def test_a_point_on_a_below_sea_level_field_is_not_warned_about(
        self, charted_client: TestClient
    ) -> None:
        body = preview(
            charted_client,
            {
                "type": "coordinate",
                "position": {"latitude": 31.3, "longitude": 35.4, "altitude_ft": -1266.0},
            },
        )
        assert "stall" not in " ".join(body["notes"])

    def test_a_default_speed_is_never_reported_as_requested(
        self, charted_client: TestClient
    ) -> None:
        """Nothing was requested, so nothing may be credited to the instructor."""
        body = preview(
            charted_client,
            {
                "type": "coordinate",
                "position": {"latitude": 31.3, "longitude": 35.4, "altitude_ft": -1266.0},
            },
        )
        notes = " ".join(body["notes"])
        assert "as requested" not in notes
        assert "no speed was given" in notes


class TestTheGlidepathComesFromThePublishedIls:
    """``glideslope_deg = None`` means "the one that is published here".

    ``Runway`` carries its ``Ils`` so this is a single lookup. Reaching for the
    3° standard instead puts a 10 NM final at a 3.8° field 851 ft **below** the
    glideslope the student is about to intercept — converging on it from
    underneath, which is not the exercise.
    """

    def test_the_published_angle_is_used_when_none_is_requested(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, {**FINAL_10NM, "runway_ident": "09"})
        assert body["schematic"]["glidepath_deg"] == 3.8
        assert body["placement"]["position"]["altitude_ft"] == pytest.approx(
            glideslope_altitude_ft(1000.0, 10.0, 3.8), abs=0.1
        )
        assert "published ILS glidepath" in " ".join(body["notes"])

    def test_the_published_angle_is_not_the_standard_one(self, charted_client: TestClient) -> None:
        """The difference is the point: 851 ft at 10 NM, and the wrong way.

        ``(tan 3.8° - tan 3°) x 10 x 6076.115486 = 851.39``. Placed on the
        standard 3°, the aircraft is that far *below* the path it is about to
        intercept.
        """
        published = preview(charted_client, {**FINAL_10NM, "runway_ident": "09"})
        standard = preview(
            charted_client, {**FINAL_10NM, "runway_ident": "09", "glideslope_deg": 3.0}
        )
        assert published["placement"]["position"]["altitude_ft"] - standard["placement"][
            "position"
        ]["altitude_ft"] == pytest.approx(851.4, abs=0.1)

    def test_a_runway_without_an_ils_falls_back_to_the_icao_standard(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, {**FINAL_10NM, "runway_ident": "18"})
        assert body["schematic"]["glidepath_deg"] == DEFAULT_GLIDESLOPE_DEG
        assert body["placement"]["position"]["altitude_ft"] == pytest.approx(
            TEN_NM_FINAL_ALTITUDE_FT, abs=0.1
        )
        assert "no ILS glidepath is published" in " ".join(body["notes"])

    def test_an_explicit_angle_wins_over_the_published_one(
        self, charted_client: TestClient
    ) -> None:
        body = preview(charted_client, {**FINAL_10NM, "runway_ident": "09", "glideslope_deg": 5.5})
        assert body["schematic"]["glidepath_deg"] == 5.5
        assert "as requested" in " ".join(body["notes"])


class TestRequestValidation:
    def test_an_unknown_placement_type_is_rejected(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview", json={"type": "teleport", "airport_icao": "ZZZZ"}
            )
        assert response.status_code == 422

    def test_an_unknown_runway_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview", json={**FINAL_10NM, "runway_ident": "09"}
            )
        assert response.status_code == 404
