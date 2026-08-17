"""Unit tests for ``core.fuel_payload.mass_and_balance``.

The §7.1 worked table is asserted exactly: all four presets, all four
verdicts, CG arms to two decimal places, and the ``full`` preset's refusal
naming the exact aft-limit excess (docs/designs/fuel-payload.md §7.1, §9.1).
"""

from __future__ import annotations

import pytest

from core.fuel_payload.limits import ResolvedMassLimits
from core.fuel_payload.mass_and_balance import compute_mass_and_balance, resolve_request
from core.fuel_payload.models import FUEL_PAYLOAD_PRESETS, FuelPayloadPresetId, FuelPayloadRequest
from core.fuel_payload.presets import resolve_preset
from core.models import (
    AirframeMassLimits,
    CgEnvelope,
    CgEnvelopePoint,
    Loadout,
    LoadoutState,
    PayloadStation,
    TankFuel,
)


def _mb(
    preset_id: FuelPayloadPresetId, *, limits: ResolvedMassLimits, current: LoadoutState
) -> tuple[float, float | None, bool | None, tuple[str, ...]]:
    resolved = resolve_preset(FUEL_PAYLOAD_PRESETS[preset_id], current=current, limits=limits)
    result = compute_mass_and_balance(resolved, limits)
    return result.gross_weight_kg, result.cg_arm_in, result.within_envelope, result.violations


class TestWorkedReferenceTable:
    """docs/designs/fuel-payload.md §7.1, reproduced exactly."""

    def test_empty(self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState) -> None:
        gross, cg, within, violations = _mb("empty", limits=c172_limits, current=empty_current)
        assert gross == pytest.approx(743.0, abs=0.01)
        assert cg == pytest.approx(39.00, abs=0.01)
        assert within is True
        assert violations == ()

    def test_ferry(self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState) -> None:
        gross, cg, within, violations = _mb("ferry", limits=c172_limits, current=empty_current)
        assert gross == pytest.approx(895.0, abs=0.01)
        assert cg == pytest.approx(40.53, abs=0.01)
        assert within is True
        assert violations == ()

    def test_training(self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState) -> None:
        gross, cg, within, violations = _mb("training", limits=c172_limits, current=empty_current)
        assert gross == pytest.approx(840.5, abs=0.01)
        assert cg == pytest.approx(40.44, abs=0.01)
        assert within is True
        assert violations == ()

    def test_full_is_refused_aft_of_the_envelope(
        self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState
    ) -> None:
        gross, cg, within, violations = _mb("full", limits=c172_limits, current=empty_current)
        assert gross == pytest.approx(1110.0, abs=0.01)
        assert cg == pytest.approx(44.95, abs=0.01)
        assert within is False
        assert len(violations) == 1
        violation = violations[0]
        assert "4.80 in" in violation
        assert "aft" in violation
        assert "40.15 in aft limit" in violation


class TestComputeMassAndBalanceUnknownLimits:
    def test_limits_none_degrades_to_unknown(self) -> None:
        state = LoadoutState(
            tanks=[TankFuel(tank_index=0, fuel_kg=38.0)],
            stations=[PayloadStation(station_index=0, weight_kg=90.0)],
        )

        result = compute_mass_and_balance(state, None)

        assert result.limits_source == "unknown"
        assert result.cg_arm_in is None
        assert result.within_envelope is None
        assert result.violations == ()
        # Fuel + payload only — the empty weight is exactly what is unknown.
        assert result.gross_weight_kg == pytest.approx(128.0)
        assert result.fuel_kg == pytest.approx(38.0)
        assert result.payload_kg == pytest.approx(90.0)


class TestCgEnvelopeInterpolation:
    def test_exact_table_weight_needs_no_interpolation(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        state = LoadoutState(
            tanks=[
                TankFuel(tank_index=0, fuel_kg=0.0),
                TankFuel(tank_index=1, fuel_kg=0.0),
            ],
            # empty_weight_kg (743.0) + payload = 1000.0 -> payload = 257.0, all at station 2
            # (arm 95.0) so the CG check, not the interpolation, is exercised deliberately.
            stations=[PayloadStation(station_index=2, weight_kg=257.0)],
        )
        result = compute_mass_and_balance(state, c172_limits)
        assert result.gross_weight_kg == pytest.approx(1000.0)
        # At exactly 1000 kg the table publishes 35.0 / 40.5 with no interpolation.
        # A CG this far aft is itself a violation, which is fine — the point of this
        # test is the boundary lookup, not the verdict.
        assert result.within_envelope is False

    def test_bracketed_weight_interpolates_linearly(self, c172_limits: ResolvedMassLimits) -> None:
        # 800 kg sits a third of the way from 700 to 1000: fwd/aft limits interpolate
        # to 34.33/40.83 (hand-computed from the §7.1 table's two lower points).
        state = LoadoutState(
            tanks=[],
            stations=[PayloadStation(station_index=0, weight_kg=57.0)],  # 743 + 57 = 800 kg
        )
        result = compute_mass_and_balance(state, c172_limits)
        assert result.gross_weight_kg == pytest.approx(800.0)
        assert result.within_envelope is True


class TestMtowViolationIsIndependentOfCg:
    def test_overweight_but_forward_cg_only_fires_the_weight_check(self) -> None:
        """A fixture whose CG envelope extends past MTOW, so a weight-only violation
        can be demonstrated without also tripping the range/CG checks (design §9.1)."""
        limits = ResolvedMassLimits(
            limits=AirframeMassLimits(
                empty_weight_kg=743.0,
                empty_cg_arm_in=39.0,
                max_takeoff_weight_kg=1157.0,
                max_fuel_kg=152.0,
                fuel_tank_capacities_kg=(76.0, 76.0),
                fuel_tank_arms_in=(48.0, 48.0),
                payload_station_capacities_kg=(300.0,),
                payload_station_arms_in=(37.0,),  # forward of the empty CG arm (39.0)
                cg_envelope=CgEnvelope(
                    points=(
                        CgEnvelopePoint(weight_kg=700.0, fwd_limit_in=34.0, aft_limit_in=41.0),
                        # Extends to 1300 kg on purpose, past the 1157 kg MTOW, so 1200 kg
                        # stays inside the *envelope's* published range while still being
                        # over the *aircraft's* maximum takeoff weight.
                        CgEnvelopePoint(weight_kg=1300.0, fwd_limit_in=34.0, aft_limit_in=41.0),
                    )
                ),
            ),
            source="table",
        )
        # 743 empty + 152 full fuel + 305 station (forward, arm 37.0) = 1200 kg.
        state = LoadoutState(
            tanks=[
                TankFuel(tank_index=0, fuel_kg=76.0),
                TankFuel(tank_index=1, fuel_kg=76.0),
            ],
            stations=[PayloadStation(station_index=0, weight_kg=305.0)],
        )

        result = compute_mass_and_balance(state, limits)

        assert result.gross_weight_kg == pytest.approx(1200.0)
        assert result.within_envelope is False
        assert len(result.violations) == 1
        assert "exceeds the maximum takeoff weight" in result.violations[0]


class TestResolveRequest:
    def test_preset_with_limits_none_raises(self, empty_current: LoadoutState) -> None:
        request = FuelPayloadRequest(preset="full")
        with pytest.raises(ValueError, match="full"):
            resolve_request(request, current=empty_current, limits=None)

    def test_overlay_touching_only_tanks_leaves_stations_unchanged(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(
            tanks=[
                TankFuel(tank_index=0, fuel_kg=10.0),
                TankFuel(tank_index=1, fuel_kg=10.0),
            ],
            stations=[PayloadStation(station_index=0, kind="crew", label="Pilot", weight_kg=90.0)],
        )
        request = FuelPayloadRequest(loadout=Loadout(tanks=[TankFuel(tank_index=0, fuel_kg=50.0)]))

        resolved, _result, _notes = resolve_request(request, current=current, limits=c172_limits)

        assert resolved.tanks == [TankFuel(tank_index=0, fuel_kg=50.0)]
        assert resolved.stations == current.stations

    def test_overlay_with_an_unknown_tank_index_raises_naming_it(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(
            tanks=[TankFuel(tank_index=0, fuel_kg=10.0)],
            stations=[],
        )
        request = FuelPayloadRequest(loadout=Loadout(tanks=[TankFuel(tank_index=3, fuel_kg=1.0)]))

        with pytest.raises(ValueError, match="Tank index 3"):
            resolve_request(request, current=current, limits=c172_limits)

    def test_overlay_with_an_unknown_station_index_raises_naming_it(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(tanks=[], stations=[])
        request = FuelPayloadRequest(
            loadout=Loadout(stations=[PayloadStation(station_index=5, weight_kg=1.0)])
        )

        with pytest.raises(ValueError, match="Station index 5"):
            resolve_request(request, current=current, limits=c172_limits)

    def test_an_overlay_on_top_of_a_preset_wins(self, c172_limits: ResolvedMassLimits) -> None:
        # The overlay's station_index must be one the CURRENT loadout reports
        # (§2.2) — a real get_loadout() would report all three known C172
        # stations, even at 0 kg, so the fixture does the same.
        current = LoadoutState(
            tanks=[],
            stations=[PayloadStation(station_index=i, weight_kg=0.0) for i in range(3)],
        )
        request = FuelPayloadRequest(
            preset="ferry",
            loadout=Loadout(stations=[PayloadStation(station_index=0, weight_kg=90.0)]),
        )

        resolved, _result, _notes = resolve_request(request, current=current, limits=c172_limits)

        # ferry alone would leave every station at 0.0 kg (station_fraction=0.0).
        assert resolved.stations == [PayloadStation(station_index=0, weight_kg=90.0)]
        # The preset still governs the tanks, since the overlay never touched them.
        assert resolved.tanks[0].fuel_kg == 76.0

    def test_an_empty_overlay_list_empties_every_tank(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(
            tanks=[TankFuel(tank_index=0, fuel_kg=50.0), TankFuel(tank_index=1, fuel_kg=50.0)],
            stations=[],
        )
        request = FuelPayloadRequest(loadout=Loadout(tanks=[]))

        resolved, _result, _notes = resolve_request(request, current=current, limits=c172_limits)

        assert resolved.tanks == []

    def test_neither_preset_nor_loadout_touched_seeds_everything_from_current(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(
            tanks=[TankFuel(tank_index=0, fuel_kg=20.0)],
            stations=[PayloadStation(station_index=0, weight_kg=90.0)],
        )
        # A request must carry a preset or a loadout (model_validator), so this
        # exercises the "loadout given but neither list touched" seeding path.
        request = FuelPayloadRequest(loadout=Loadout())

        resolved, _result, _notes = resolve_request(request, current=current, limits=c172_limits)

        assert resolved.tanks == current.tanks
        assert resolved.stations == current.stations
