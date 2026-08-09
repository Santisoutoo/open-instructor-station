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
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import server.deps
from adapters.fake import FakeSimAdapter
from core.geodesy import APPROACH_CATEGORY_CIRCLING_IAS_KT, APPROACH_CATEGORY_VAT_KT
from core.models import AircraftSetup, GeoPosition
from core.sim_adapter import Capabilities
from server.app import create_app
from server.deps import reset_adapter, reset_navdata
from server.position_routes import CAPABILITY_UNAVAILABLE_STATUS, UNPOSITIONABLE_STATUS
from tests.server.conftest import build_provider

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
        notes = " ".join(preview(client, {**FINAL_10NM, "ias_kt": 137.0})["notes"])
        assert "as requested" in notes


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
        assert body["placement"]["ias_kt"] == 250.0
        notes = " ".join(body["notes"])
        assert "published constraint" in notes

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
    def test_it_uses_the_published_minimum_altitude(self, client: TestClient) -> None:
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        assert body["placement"]["position"]["altitude_ft"] == 7000.0

    def test_the_published_speed_is_a_ceiling_and_not_a_target(self, client: TestClient) -> None:
        """The hold is placarded at 210 kt; a category B aeroplane still flies 135.

        Flying the placard would put a light aircraft 75 kt above its
        manoeuvring speed. ``core.geodesy`` clamps rather than adopts, and the
        note has to say which of the two produced the number.
        """
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        assert body["placement"]["ias_kt"] == APPROACH_CATEGORY_CIRCLING_IAS_KT["B"]
        notes = " ".join(body["notes"])
        assert "210 kt" in notes
        assert "ceiling" in notes

    def test_an_explicit_speed_beats_the_placard_and_the_category(self, client: TestClient) -> None:
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL", "ias_kt": 200.0})
        assert body["placement"]["ias_kt"] == 200.0

    def test_the_magnetic_course_is_converted_and_the_note_says_so(
        self, client: TestClient
    ) -> None:
        """The airport publishes -2° variation, so 180° magnetic is 178° true."""
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        assert body["placement"]["heading_deg"] == pytest.approx(178.0)
        notes = " ".join(body["notes"])
        assert "magnetic" in notes
        assert "variation" in notes

    def test_it_places_over_the_fix(self, client: TestClient) -> None:
        """The default point of a hold is its fix — the one point on a chart."""
        body = preview(client, {"type": "hold", "fix_ident": "GOXOL"})
        position = body["placement"]["position"]
        assert position["latitude"] == pytest.approx(40.5)
        assert position["longitude"] == pytest.approx(-3.0)

    def test_a_hold_with_no_published_altitude_is_refused_rather_than_invented(
        self, client: TestClient
    ) -> None:
        with client:
            response = client.post(
                "/api/position/preview", json={"type": "hold", "fix_ident": "NOALTHOLD"}
            )
        assert response.status_code == UNPOSITIONABLE_STATUS
        assert "altitude" in response.json()["detail"]

    def test_an_unknown_hold_is_404(self, client: TestClient) -> None:
        with client:
            response = client.post(
                "/api/position/preview", json={"type": "hold", "fix_ident": "NOSUCH"}
            )
        assert response.status_code == 404


class TestApplyOrdersTheWrites:
    """The setup goes in before the teleport, always."""

    @pytest.fixture
    def recording_client(self, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[str]]:
        calls: list[str] = []

        class RecordingAdapter(FakeSimAdapter):
            async def apply_setup(self, setup: AircraftSetup) -> None:
                calls.append("apply_setup")
                await super().apply_setup(setup)

            async def set_position(self, position: GeoPosition, heading_deg: float) -> None:
                calls.append("set_position")
                await super().set_position(position, heading_deg)

        provider = build_provider()
        monkeypatch.setattr(server.deps, "_build_navdata", lambda _settings: provider)
        monkeypatch.setattr(server.deps, "_build_adapter", lambda _settings: RecordingAdapter())
        reset_adapter()
        reset_navdata()
        return TestClient(create_app()), calls

    def test_setup_is_written_before_the_teleport(
        self, recording_client: tuple[TestClient, list[str]]
    ) -> None:
        client, calls = recording_client
        with client:
            response = client.post("/api/position/apply", json={"placement": FINAL_10NM})
        assert response.status_code == 200, response.text
        assert calls == ["apply_setup", "set_position"]

    def test_the_aircraft_ends_up_where_the_placement_said(
        self, recording_client: tuple[TestClient, list[str]]
    ) -> None:
        client, _calls = recording_client
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
