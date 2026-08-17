"""Unit tests for the fuel/payload additions to ``core.models``.

Covers the validators ``core/models.py`` gained for the Fuel & Payload
manager's contract vocabulary: CG envelope ordering, tank/station capacity-
arm length matching, and the sparse ``Loadout`` / full ``LoadoutState`` split.
No simulator, no adapter.
"""

import pytest
from pydantic import ValidationError

from core.models import (
    AircraftSetup,
    AirframeInfo,
    AirframeMassLimits,
    CgEnvelope,
    CgEnvelopePoint,
    Loadout,
    LoadoutState,
    PayloadStation,
    TankFuel,
)


def _cg_point(weight_kg: float, fwd_limit_in: float, aft_limit_in: float) -> CgEnvelopePoint:
    return CgEnvelopePoint(
        weight_kg=weight_kg, fwd_limit_in=fwd_limit_in, aft_limit_in=aft_limit_in
    )


def _limits(**overrides: object) -> AirframeMassLimits:
    defaults: dict[str, object] = {
        "empty_weight_kg": 743.0,
        "empty_cg_arm_in": 39.0,
        "max_takeoff_weight_kg": 1157.0,
        "max_fuel_kg": 152.0,
        "fuel_tank_capacities_kg": (76.0, 76.0),
        "fuel_tank_arms_in": (48.0, 48.0),
        "payload_station_capacities_kg": (85.0, 85.0, 45.0),
        "payload_station_arms_in": (37.0, 73.0, 95.0),
        "cg_envelope": CgEnvelope(
            points=(
                _cg_point(700.0, 34.0, 41.0),
                _cg_point(1157.0, 35.5, 40.0),
            )
        ),
    }
    defaults.update(overrides)
    return AirframeMassLimits.model_validate(defaults)


class TestCgEnvelopePoint:
    def test_aft_below_fwd_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="aft_limit_in"):
            CgEnvelopePoint(weight_kg=1000.0, fwd_limit_in=40.0, aft_limit_in=35.0)

    def test_aft_equal_to_fwd_is_accepted(self) -> None:
        point = _cg_point(1000.0, 38.0, 38.0)
        assert point.aft_limit_in == pytest.approx(38.0)

    def test_is_frozen(self) -> None:
        point = _cg_point(1000.0, 34.0, 41.0)
        with pytest.raises(ValidationError):
            point.weight_kg = 500.0


class TestCgEnvelope:
    def test_requires_at_least_two_points(self) -> None:
        with pytest.raises(ValidationError):
            CgEnvelope(points=(_cg_point(1000.0, 34.0, 41.0),))

    def test_points_must_ascend_by_weight(self) -> None:
        with pytest.raises(ValidationError, match="ascending"):
            CgEnvelope(points=(_cg_point(1000.0, 34.0, 41.0), _cg_point(700.0, 34.0, 41.0)))

    def test_valid_envelope_constructs(self) -> None:
        envelope = CgEnvelope(points=(_cg_point(700.0, 34.0, 41.0), _cg_point(1157.0, 35.5, 40.0)))
        assert len(envelope.points) == 2


class TestAirframeMassLimits:
    def test_valid_limits_construct(self) -> None:
        limits = _limits()
        assert limits.max_takeoff_weight_kg == pytest.approx(1157.0)

    def test_mismatched_tank_capacity_and_arm_lengths_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="fuel_tank"):
            _limits(fuel_tank_capacities_kg=(76.0, 76.0, 76.0))

    def test_mismatched_station_capacity_and_arm_lengths_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="payload_station"):
            _limits(payload_station_arms_in=(37.0, 73.0))

    def test_max_zero_fuel_weight_defaults_to_none(self) -> None:
        limits = _limits()
        assert limits.max_zero_fuel_weight_kg is None

    def test_is_frozen(self) -> None:
        limits = _limits()
        with pytest.raises(ValidationError):
            limits.max_fuel_kg = 999.0


class TestTankFuelAndPayloadStation:
    def test_tank_fuel_defaults(self) -> None:
        tank = TankFuel(tank_index=0, fuel_kg=50.0)
        assert tank.fuel_kg == pytest.approx(50.0)

    def test_negative_fuel_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            TankFuel(tank_index=0, fuel_kg=-1.0)

    def test_payload_station_kind_defaults_to_other(self) -> None:
        station = PayloadStation(station_index=0, weight_kg=10.0)
        assert station.kind == "other"
        assert station.label == ""

    def test_station_index_out_of_range_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            PayloadStation(station_index=99, weight_kg=10.0)


class TestLoadoutSparseSemantics:
    def test_everything_defaults_to_none(self) -> None:
        loadout = Loadout()
        assert loadout.tanks is None
        assert loadout.stations is None

    def test_empty_list_survives_exclude_none(self) -> None:
        loadout = Loadout(tanks=[])
        assert loadout.model_dump(exclude_none=True)["tanks"] == []

    def test_is_not_frozen(self) -> None:
        """Mirrors LightsSetup: AircraftSetup itself is not frozen, so its
        nested sparse-write models are not either."""
        loadout = Loadout()
        loadout.tanks = [TankFuel(tank_index=0, fuel_kg=1.0)]
        assert loadout.tanks[0].fuel_kg == pytest.approx(1.0)


class TestLoadoutState:
    def test_fully_populated_state_constructs(self) -> None:
        state = LoadoutState(
            tanks=[TankFuel(tank_index=0, fuel_kg=38.0)],
            stations=[PayloadStation(station_index=0, kind="crew", weight_kg=90.0)],
        )
        assert len(state.tanks) == 1
        assert len(state.stations) == 1

    def test_empty_state_is_valid(self) -> None:
        state = LoadoutState(tanks=[], stations=[])
        assert state.tanks == []
        assert state.stations == []


class TestAircraftSetupAndAirframeInfoAdditions:
    def test_aircraft_setup_loadout_defaults_to_none(self) -> None:
        setup = AircraftSetup()
        assert setup.loadout is None

    def test_aircraft_setup_carries_a_loadout(self) -> None:
        setup = AircraftSetup(loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=10.0)]))
        assert setup.loadout is not None
        assert setup.loadout.tanks is not None
        assert setup.loadout.tanks[0].fuel_kg == pytest.approx(10.0)

    def test_airframe_info_mass_limits_defaults_to_none(self) -> None:
        assert AirframeInfo().mass_limits is None

    def test_airframe_info_carries_mass_limits(self) -> None:
        airframe = AirframeInfo(icao_type="C172", mass_limits=_limits())
        assert airframe.mass_limits is not None
        assert airframe.mass_limits.empty_weight_kg == pytest.approx(743.0)
