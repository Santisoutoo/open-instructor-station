"""Unit tests for ``core.fuel_payload.limits`` — the fallback table and its resolver.

No simulator, no adapter: every case here is pure Python over pydantic models.
"""

from __future__ import annotations

from core.fuel_payload.limits import AIRCRAFT_MASS_LIMITS_TABLE, resolve_mass_limits
from core.models import AirframeInfo, AirframeMassLimits, CgEnvelope, CgEnvelopePoint


def _bespoke_limits() -> AirframeMassLimits:
    """A limits model that is NOT the C172 table entry, so "adapter wins" is provable."""
    return AirframeMassLimits(
        empty_weight_kg=1000.0,
        empty_cg_arm_in=50.0,
        max_takeoff_weight_kg=1500.0,
        max_fuel_kg=200.0,
        fuel_tank_capacities_kg=(100.0,),
        fuel_tank_arms_in=(50.0,),
        payload_station_capacities_kg=(100.0,),
        payload_station_arms_in=(50.0,),
        cg_envelope=CgEnvelope(
            points=(
                CgEnvelopePoint(weight_kg=1000.0, fwd_limit_in=45.0, aft_limit_in=55.0),
                CgEnvelopePoint(weight_kg=1500.0, fwd_limit_in=46.0, aft_limit_in=54.0),
            )
        ),
    )


class TestResolveMassLimits:
    def test_adapter_supplied_limits_win_over_the_table(self) -> None:
        bespoke = _bespoke_limits()
        airframe = AirframeInfo(icao_type="C172", mass_limits=bespoke)

        resolved = resolve_mass_limits(airframe)

        assert resolved is not None
        assert resolved.source == "adapter"
        assert resolved.limits == bespoke

    def test_known_icao_type_without_adapter_limits_falls_back_to_the_table(self) -> None:
        airframe = AirframeInfo(icao_type="C172", mass_limits=None)

        resolved = resolve_mass_limits(airframe)

        assert resolved is not None
        assert resolved.source == "table"
        assert resolved.limits == AIRCRAFT_MASS_LIMITS_TABLE["C172"].limits

    def test_unknown_icao_type_and_no_adapter_limits_is_none(self) -> None:
        airframe = AirframeInfo(icao_type="PA46", mass_limits=None)

        assert resolve_mass_limits(airframe) is None

    def test_no_icao_type_and_no_adapter_limits_is_none(self) -> None:
        assert resolve_mass_limits(AirframeInfo()) is None


class TestAircraftMassLimitsTable:
    def test_c172_entry_matches_the_design_7_1_worked_table(self) -> None:
        """Pinned exactly — every downstream preset assertion depends on these numbers."""
        limits = AIRCRAFT_MASS_LIMITS_TABLE["C172"].limits
        assert limits.empty_weight_kg == 743.0
        assert limits.empty_cg_arm_in == 39.0
        assert limits.max_takeoff_weight_kg == 1157.0
        assert limits.max_zero_fuel_weight_kg is None
        assert limits.max_fuel_kg == 152.0
        assert limits.fuel_tank_capacities_kg == (76.0, 76.0)
        assert limits.fuel_tank_arms_in == (48.0, 48.0)
        assert limits.payload_station_capacities_kg == (85.0, 85.0, 45.0)
        assert limits.payload_station_arms_in == (37.0, 73.0, 95.0)
        points = limits.cg_envelope.points
        assert [(p.weight_kg, p.fwd_limit_in, p.aft_limit_in) for p in points] == [
            (700.0, 34.0, 41.0),
            (1000.0, 35.0, 40.5),
            (1157.0, 35.5, 40.0),
        ]

    def test_c172_entry_carries_a_disclaimer(self) -> None:
        note = AIRCRAFT_MASS_LIMITS_TABLE["C172"].source_note
        assert "Illustrative" in note
        assert "POH" in note
