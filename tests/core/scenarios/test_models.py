"""Unit tests for ``core.scenarios.models`` — the validated shape of one
scenario YAML file (docs/designs/scenario-generator.md §4.2, §8.1).

Every case below asserts reuse, not reinvention: a scenario-specific rule
(``_at_least_one_block``, ``_not_empty``) is tested directly, and every other
rule is tested only to confirm it is delegated to the manager that already
owns it (``WeatherRequest``, ``FailureRef``) — never re-implemented here.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from core.failures import ArmFailureRequest, InjectFailureRequest, SpeedAboveTrigger
from core.models import AircraftSetup, GeoPosition
from core.placements import (
    CoordinatePlacementRequest,
    PlacementRequest,
    RunwayThresholdPlacementRequest,
)
from core.scenarios.models import ScenarioDocument, ScenarioFailuresBlock, ScenarioTrafficBlock
from core.weather.models import WeatherRequest


def _coordinate_placement() -> CoordinatePlacementRequest:
    return CoordinatePlacementRequest(
        type="coordinate",
        position=GeoPosition(latitude=40.4, longitude=-3.5, altitude_ft=2000.0),
        ias_kt=90.0,
    )


class TestScenarioDocumentBlocks:
    """A minimal one-block document validates for each of the five block types."""

    def test_position_only(self) -> None:
        doc = ScenarioDocument(
            name="Position only",
            description="A bare placement.",
            position=_coordinate_placement(),
        )
        assert doc.position is not None
        assert doc.aircraft_state is None

    def test_aircraft_state_only(self) -> None:
        doc = ScenarioDocument(
            name="State only",
            description="A bare aircraft state.",
            aircraft_state=AircraftSetup(flaps_ratio=0.2),
        )
        assert doc.aircraft_state == AircraftSetup(flaps_ratio=0.2)

    def test_weather_only(self) -> None:
        doc = ScenarioDocument(
            name="Weather only",
            description="A bare weather instruction.",
            weather=WeatherRequest(preset="cavok"),
        )
        assert doc.weather is not None

    def test_failures_only(self) -> None:
        doc = ScenarioDocument(
            name="Failures only",
            description="A bare failure.",
            failures=ScenarioFailuresBlock(
                immediate=(InjectFailureRequest(failure_id="airframe.bird_strike"),)
            ),
        )
        assert doc.failures is not None

    def test_traffic_only(self) -> None:
        doc = ScenarioDocument(
            name="Traffic only",
            description="A bare traffic declaration.",
            traffic=ScenarioTrafficBlock(description="One aircraft on a converging path."),
        )
        assert doc.traffic is not None


class TestScenarioDocumentValidation:
    def test_no_blocks_at_all_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must declare at least one of"):
            ScenarioDocument(name="Empty", description="Nothing declared.")

    def test_unknown_top_level_key_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioDocument.model_validate(
                {
                    "name": "Typo",
                    "description": "A typo'd field.",
                    "postion": _coordinate_placement().model_dump(),
                }
            )

    def test_weather_block_delegates_to_weather_requests_own_validator(self) -> None:
        """Neither ``preset`` nor ``setup`` on the weather block -- WeatherRequest's
        own rule, not re-implemented here."""
        with pytest.raises(ValidationError, match="must carry a preset, a setup, or both"):
            ScenarioDocument(
                name="Bad weather",
                description="Neither preset nor setup.",
                weather=WeatherRequest.model_construct(preset=None, setup=None),
            )

    def test_failures_block_with_both_lists_empty_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least one immediate or armed failure"):
            ScenarioFailuresBlock()

    def test_armed_entry_with_mismatched_engine_index_delegates_to_failure_ref(self) -> None:
        """engine.failure takes an engine index -- FailureRef's own validator,
        not re-implemented here."""
        with pytest.raises(ValidationError, match="takes an engine index"):
            ArmFailureRequest(
                failure_id="engine.failure",
                engine_index=None,
                trigger=SpeedAboveTrigger(type="speed_above", ias_kt=135.0),
            )

    def test_runway_threshold_placement_round_trips_through_the_discriminated_union(self) -> None:
        threshold = RunwayThresholdPlacementRequest(
            type="runway_threshold", airport_icao="ZZZZ", runway_ident="36"
        )
        doc = ScenarioDocument(
            name="Threshold",
            description="On the centreline at the threshold.",
            position=threshold,
        )
        assert isinstance(doc.position, RunwayThresholdPlacementRequest)
        # And it validates through the union itself, not only the field it sits in.
        revalidated: PlacementRequest = TypeAdapter(PlacementRequest).validate_python(
            doc.position.model_dump()
        )
        assert revalidated == threshold
