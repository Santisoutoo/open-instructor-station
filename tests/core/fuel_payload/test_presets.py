"""Unit tests for ``core.fuel_payload.presets.resolve_preset``."""

from __future__ import annotations

from core.fuel_payload.limits import ResolvedMassLimits
from core.fuel_payload.models import FUEL_PAYLOAD_PRESETS
from core.fuel_payload.presets import resolve_preset
from core.models import LoadoutState, PayloadStation


class TestResolvePreset:
    def test_full_preset_fills_every_tank_and_station_to_capacity(
        self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState
    ) -> None:
        """§9.1's pinned case: tank 0 -> exactly 76.0 kg, station 2 (baggage) -> exactly 45.0 kg."""
        resolved = resolve_preset(
            FUEL_PAYLOAD_PRESETS["full"], current=empty_current, limits=c172_limits
        )

        assert resolved.tanks[0].tank_index == 0
        assert resolved.tanks[0].fuel_kg == 76.0
        assert resolved.stations[2].station_index == 2
        assert resolved.stations[2].weight_kg == 45.0

    def test_empty_preset_zeroes_every_tank_and_station(
        self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState
    ) -> None:
        resolved = resolve_preset(
            FUEL_PAYLOAD_PRESETS["empty"], current=empty_current, limits=c172_limits
        )

        assert all(tank.fuel_kg == 0.0 for tank in resolved.tanks)
        assert all(station.weight_kg == 0.0 for station in resolved.stations)

    def test_covers_every_known_tank_and_station_regardless_of_current(
        self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState
    ) -> None:
        """The preset's universe is the airframe's known capacities, not what is loaded now."""
        resolved = resolve_preset(
            FUEL_PAYLOAD_PRESETS["ferry"], current=empty_current, limits=c172_limits
        )

        assert [tank.tank_index for tank in resolved.tanks] == [0, 1]
        assert [station.station_index for station in resolved.stations] == [0, 1, 2]

    def test_preserves_kind_and_label_from_the_current_loadout(
        self, c172_limits: ResolvedMassLimits
    ) -> None:
        current = LoadoutState(
            tanks=[],
            stations=[PayloadStation(station_index=0, kind="crew", label="Pilot", weight_kg=90.0)],
        )

        resolved = resolve_preset(
            FUEL_PAYLOAD_PRESETS["training"], current=current, limits=c172_limits
        )

        assert resolved.stations[0].kind == "crew"
        assert resolved.stations[0].label == "Pilot"
        # The mass is still the preset's fraction of capacity, not the current mass.
        assert resolved.stations[0].weight_kg == 8.5

    def test_a_station_not_reported_by_the_current_loadout_defaults_to_other(
        self, c172_limits: ResolvedMassLimits, empty_current: LoadoutState
    ) -> None:
        resolved = resolve_preset(
            FUEL_PAYLOAD_PRESETS["training"], current=empty_current, limits=c172_limits
        )

        assert all(station.kind == "other" and station.label == "" for station in resolved.stations)
