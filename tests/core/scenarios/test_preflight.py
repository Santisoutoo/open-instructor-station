"""Unit tests for ``core.scenarios.preflight`` -- the capability pre-flight
check (docs/designs/scenario-generator.md §3.2, §6.2, §8.1).

``missing_capabilities`` is pure: ``(document, Capabilities)`` in, flags out,
no adapter instance, no I/O. Every case here constructs a ``Capabilities``
directly rather than reaching for an adapter.
"""

from __future__ import annotations

from core.failures import ArmFailureRequest, DelayTrigger, InjectFailureRequest
from core.models import AircraftSetup, GeoPosition
from core.placements import CoordinatePlacementRequest
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock, ScenarioTrafficBlock
from core.scenarios.preflight import missing_capabilities
from core.sim_adapter import Capabilities
from core.weather.models import WeatherRequest

_NO_CAPABILITIES = Capabilities()
_ALL_CAPABILITIES = Capabilities(
    can_set_position=True,
    can_set_aircraft_state=True,
    can_set_weather=True,
    can_inject_failures=True,
    can_spawn_traffic=True,
    can_control_autopilot=True,
    can_set_fuel_payload=True,
    can_control_camera=True,
    can_pushback=True,
)

_PLACEMENT = CoordinatePlacementRequest(
    type="coordinate",
    position=GeoPosition(latitude=40.4, longitude=-3.5, altitude_ft=2000.0),
    ias_kt=90.0,
)


class TestMissingCapabilities:
    def test_weather_only_document_needs_can_set_weather(self) -> None:
        doc = ScenarioDocument(
            name="Weather",
            description="A bare weather instruction.",
            weather=WeatherRequest(preset="cavok"),
        )
        assert missing_capabilities(doc, _NO_CAPABILITIES) == ("can_set_weather",)

    def test_position_bearing_document_needs_position_then_aircraft_state_in_order(self) -> None:
        doc = ScenarioDocument(
            name="Position",
            description="A bare placement.",
            position=_PLACEMENT,
        )
        assert missing_capabilities(doc, _NO_CAPABILITIES) == (
            "can_set_position",
            "can_set_aircraft_state",
        )

    def test_autopilot_field_needs_can_control_autopilot_in_addition(self) -> None:
        doc = ScenarioDocument(
            name="Autopilot",
            description="Arms the autopilot master.",
            aircraft_state=AircraftSetup(autopilot_master=True),
        )
        assert missing_capabilities(doc, Capabilities(can_set_aircraft_state=True)) == (
            "can_control_autopilot",
        )

    def test_fuel_payload_field_needs_can_set_fuel_payload_in_addition(self) -> None:
        doc = ScenarioDocument(
            name="Fuel",
            description="Sets gross weight.",
            aircraft_state=AircraftSetup(gross_weight_kg=1000.0),
        )
        assert missing_capabilities(doc, Capabilities(can_set_aircraft_state=True)) == (
            "can_set_fuel_payload",
        )

    def test_failures_document_needs_can_inject_failures(self) -> None:
        doc = ScenarioDocument(
            name="Failures",
            description="A bare failure.",
            failures=ScenarioFailuresBlock(
                immediate=(),
                armed=(
                    ArmFailureRequest(
                        failure_id="hydraulics.system",
                        trigger=DelayTrigger(type="delay", delay_s=5.0),
                    ),
                ),
            ),
        )
        assert missing_capabilities(doc, _NO_CAPABILITIES) == ("can_inject_failures",)

    def test_traffic_document_needs_can_spawn_traffic(self) -> None:
        doc = ScenarioDocument(
            name="Traffic",
            description="Declares the need for traffic.",
            traffic=ScenarioTrafficBlock(description="One aircraft on a converging path."),
        )
        assert missing_capabilities(doc, _NO_CAPABILITIES) == ("can_spawn_traffic",)

    def test_every_flag_true_leaves_nothing_missing_for_every_shipped_scenario(self) -> None:
        """Once the 14 YAML scenarios exist (Track B), this should be re-run against
        ``load_all_scenarios()``'s full output rather than a hand-built document —
        left as a single representative document here since the shipped catalogue
        does not exist on this branch yet."""
        doc = ScenarioDocument(
            name="Everything",
            description="One of each block.",
            position=_PLACEMENT,
            aircraft_state=AircraftSetup(autopilot_master=True, gross_weight_kg=1000.0),
            weather=WeatherRequest(preset="cavok"),
            failures=ScenarioFailuresBlock(
                immediate=(InjectFailureRequest(failure_id="airframe.bird_strike"),),
            ),
            traffic=ScenarioTrafficBlock(description="One aircraft."),
        )
        assert missing_capabilities(doc, _ALL_CAPABILITIES) == ()

    def test_duplicate_flags_are_not_repeated(self) -> None:
        """position + aircraft_state both requiring can_set_aircraft_state appears once."""
        doc = ScenarioDocument(
            name="Overlap",
            description="Position and state both need can_set_aircraft_state.",
            position=_PLACEMENT,
            aircraft_state=AircraftSetup(flaps_ratio=0.2),
        )
        result = missing_capabilities(doc, _NO_CAPABILITIES)
        assert result.count("can_set_aircraft_state") == 1
