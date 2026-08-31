"""Resolve one preset against an airframe's known capacities."""

from __future__ import annotations

from core.fuel_payload.limits import ResolvedMassLimits
from core.fuel_payload.models import FuelPayloadPreset
from core.models import LoadoutState, PayloadStation, TankFuel

__all__ = ["resolve_preset"]


def resolve_preset(
    preset: FuelPayloadPreset,
    *,
    current: LoadoutState,
    limits: ResolvedMassLimits,
) -> LoadoutState:
    """Every known tank/station, filled to ``preset``'s fractions of its capacity.

    ``tank.fuel_kg = preset.fuel_fraction * limits.fuel_tank_capacities_kg[i]``
    for every tank ``limits`` knows about; ``station.weight_kg =
    preset.station_fraction * limits.payload_station_capacities_kg[i]`` for
    every station ``limits`` knows about. The universe of tanks/stations is
    the airframe's known capacities, not ``current``'s — a preset can fill a
    tank the aircraft is not currently carrying fuel in.

    A station's ``kind``/``label`` are carried over from ``current`` when that
    index is already reported (so relabelling a seat "Rear seats" is not lost
    by selecting a preset); a station index the current loadout does not
    report yet defaults to ``kind="other"``, ``label=""`` — the same "unknown
    is honest" posture as everywhere else in this manager.
    """
    mass_limits = limits.limits
    current_stations = {station.station_index: station for station in current.stations}

    tanks = [
        TankFuel(tank_index=index, fuel_kg=preset.fuel_fraction * capacity_kg)
        for index, capacity_kg in enumerate(mass_limits.fuel_tank_capacities_kg)
    ]
    stations = []
    for index, capacity_kg in enumerate(mass_limits.payload_station_capacities_kg):
        existing = current_stations.get(index)
        stations.append(
            PayloadStation(
                station_index=index,
                kind=existing.kind if existing is not None else "other",
                label=existing.label if existing is not None else "",
                weight_kg=preset.station_fraction * capacity_kg,
            )
        )
    return LoadoutState(tanks=tanks, stations=stations)
