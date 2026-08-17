"""Mass-and-balance arithmetic: gross weight, CG arm, envelope validation.

CG is **computed here, never read from a dataref** (docs/designs/fuel-payload.md
§6.3) — no reliable dataref for it is known to exist, and the arithmetic below
is plain masses times arms, entirely sim-agnostic and trivially unit-testable
without any adapter.
"""

from __future__ import annotations

from itertools import pairwise

from core.fuel_payload.limits import ResolvedMassLimits
from core.fuel_payload.models import FUEL_PAYLOAD_PRESETS, FuelPayloadRequest, MassAndBalanceResult
from core.fuel_payload.presets import resolve_preset
from core.models import CgEnvelopePoint, LoadoutState, PayloadStation, TankFuel

__all__ = ["compute_mass_and_balance", "resolve_request"]


def _interpolate_envelope(
    points: tuple[CgEnvelopePoint, ...], weight_kg: float
) -> tuple[float, float]:
    """The (forward, aft) CG limits at ``weight_kg``, linearly interpolated.

    ``weight_kg`` is assumed already checked to lie within
    ``[points[0].weight_kg, points[-1].weight_kg]`` — outside that range is a
    violation the caller reports itself rather than an extrapolation this
    function would otherwise have to invent.
    """
    for lower, upper in pairwise(points):
        if lower.weight_kg <= weight_kg <= upper.weight_kg:
            span = upper.weight_kg - lower.weight_kg
            fraction = 0.0 if span == 0.0 else (weight_kg - lower.weight_kg) / span
            fwd_limit_in = lower.fwd_limit_in + fraction * (upper.fwd_limit_in - lower.fwd_limit_in)
            aft_limit_in = lower.aft_limit_in + fraction * (upper.aft_limit_in - lower.aft_limit_in)
            return fwd_limit_in, aft_limit_in
    # Unreachable when the caller has already range-checked weight_kg against
    # the envelope's own bounds, which every call site here does.
    raise ValueError(f"{weight_kg} kg is outside the published CG envelope range.")


def compute_mass_and_balance(
    state: LoadoutState, limits: ResolvedMassLimits | None
) -> MassAndBalanceResult:
    """Gross weight, fuel/payload totals, CG arm and an envelope verdict for ``state``.

    ``gross_weight_kg = limits.empty_weight_kg + sum(fuel) + sum(stations)``;
    ``cg_arm_in`` is the weighted average of (mass, arm) over the empty
    airframe plus every tank plus every station, using
    ``limits.fuel_tank_arms_in``/``payload_station_arms_in`` by index.
    ``limits.cg_envelope`` is interpolated linearly between the two
    bracketing weight points — a gross weight outside the published range is
    itself a violation, never extrapolated past.

    ``limits=None`` degrades to ``limits_source == "unknown"``,
    ``cg_arm_in=None``, ``within_envelope=None``, ``violations=()`` (D7): an
    unverifiable airframe is disclosed, never invented as either a pass or a
    fail. ``gross_weight_kg`` in that case is fuel plus payload only — the
    empty weight is exactly the thing that is unknown, so it is left out
    rather than assumed to be zero *and* silently trusted.
    """
    fuel_kg = sum(tank.fuel_kg for tank in state.tanks)
    payload_kg = sum(station.weight_kg for station in state.stations)

    if limits is None:
        return MassAndBalanceResult(
            gross_weight_kg=fuel_kg + payload_kg,
            fuel_kg=fuel_kg,
            payload_kg=payload_kg,
            cg_arm_in=None,
            limits_source="unknown",
            within_envelope=None,
            violations=(),
        )

    mass_limits = limits.limits
    gross_weight_kg = mass_limits.empty_weight_kg + fuel_kg + payload_kg

    moment_kg_in = mass_limits.empty_weight_kg * mass_limits.empty_cg_arm_in
    for tank in state.tanks:
        if tank.tank_index >= len(mass_limits.fuel_tank_arms_in):
            raise ValueError(
                f"Tank index {tank.tank_index} has no published moment arm "
                f"({len(mass_limits.fuel_tank_arms_in)} known tanks)."
            )
        moment_kg_in += tank.fuel_kg * mass_limits.fuel_tank_arms_in[tank.tank_index]
    for station in state.stations:
        if station.station_index >= len(mass_limits.payload_station_arms_in):
            raise ValueError(
                f"Station index {station.station_index} has no published moment arm "
                f"({len(mass_limits.payload_station_arms_in)} known stations)."
            )
        arm_in = mass_limits.payload_station_arms_in[station.station_index]
        moment_kg_in += station.weight_kg * arm_in
    cg_arm_in = (
        moment_kg_in / gross_weight_kg if gross_weight_kg > 0.0 else mass_limits.empty_cg_arm_in
    )

    violations: list[str] = []
    if gross_weight_kg > mass_limits.max_takeoff_weight_kg:
        violations.append(
            f"Gross weight {gross_weight_kg:.1f} kg exceeds the maximum takeoff weight of "
            f"{mass_limits.max_takeoff_weight_kg:.1f} kg."
        )

    points = mass_limits.cg_envelope.points
    outside_range = gross_weight_kg < points[0].weight_kg or gross_weight_kg > points[-1].weight_kg
    if outside_range:
        violations.append(
            f"Gross weight {gross_weight_kg:.1f} kg is outside the published CG envelope "
            f"range ({points[0].weight_kg:.0f}-{points[-1].weight_kg:.0f} kg) — the envelope "
            f"is not extrapolated past its published points."
        )
    else:
        fwd_limit_in, aft_limit_in = _interpolate_envelope(points, gross_weight_kg)
        if cg_arm_in < fwd_limit_in:
            violations.append(
                f"CG at {cg_arm_in:.2f} in is {fwd_limit_in - cg_arm_in:.2f} in forward of the "
                f"{fwd_limit_in:.2f} in forward limit at {gross_weight_kg:.1f} kg."
            )
        if cg_arm_in > aft_limit_in:
            violations.append(
                f"CG at {cg_arm_in:.2f} in is {cg_arm_in - aft_limit_in:.2f} in aft of the "
                f"{aft_limit_in:.2f} in aft limit at {gross_weight_kg:.1f} kg."
            )

    return MassAndBalanceResult(
        gross_weight_kg=gross_weight_kg,
        fuel_kg=fuel_kg,
        payload_kg=payload_kg,
        cg_arm_in=cg_arm_in,
        limits_source=limits.source,
        within_envelope=not violations,
        violations=tuple(violations),
    )


def resolve_request(
    request: FuelPayloadRequest,
    *,
    current: LoadoutState,
    limits: ResolvedMassLimits | None,
) -> tuple[LoadoutState, MassAndBalanceResult, tuple[str, ...]]:
    """Resolve ``request`` into a COMPLETE :class:`~core.models.LoadoutState`.

    Unlike ``core.weather``'s resolver, this never returns a partial result:
    mass-and-balance is a whole-aircraft computation, so the result always
    carries a full tank/station picture, seeded from ``current`` and replaced
    only where the preset or the overlay states one.

    Resolution order:

    1. Start from ``current`` — every tank/station the adapter reports right now.
    2. If ``request.preset`` is set, resolve it against ``limits`` (D9) and
       replace the tank/station lists wholesale with the preset's answer.
    3. If ``request.loadout`` is set, its ``tanks``/``stations`` — when not
       ``None`` — replace the current list wholesale again (D10: no
       per-index merge; a provided list is the complete new set for that
       aspect). This is the instructor's overlay, applied *after* the preset
       so it always wins.

    Then :func:`compute_mass_and_balance` on the result.

    Raises:
        ValueError: when a preset is requested and ``limits`` is ``None``
            (nothing to resolve capacity fractions against), or when the
            overlay names a ``tank_index``/``station_index`` the current
            loadout does not report.
    """
    notes: list[str] = []
    tanks: list[TankFuel] = list(current.tanks)
    stations: list[PayloadStation] = list(current.stations)

    if request.preset is not None:
        if limits is None:
            raise ValueError(
                f"The {request.preset!r} preset needs the airframe's known tank and station "
                "capacities; none are published for this aircraft and no fallback table "
                "entry exists."
            )
        preset = FUEL_PAYLOAD_PRESETS[request.preset]
        preset_state = resolve_preset(preset, current=current, limits=limits)
        tanks = list(preset_state.tanks)
        stations = list(preset_state.stations)
        total_fuel = sum(tank.fuel_kg for tank in tanks)
        total_payload = sum(station.weight_kg for station in stations)
        notes.append(
            f"Fuel {total_fuel:.1f} kg, payload {total_payload:.1f} kg — the {preset.id!r} "
            f"preset ({preset.fuel_fraction:.0%} of known tank capacity, "
            f"{preset.station_fraction:.0%} of known station capacity)."
        )

    if request.loadout is not None:
        if request.loadout.tanks is not None:
            known_tank_indices = {tank.tank_index for tank in current.tanks}
            for tank in request.loadout.tanks:
                if tank.tank_index not in known_tank_indices:
                    raise ValueError(
                        f"Tank index {tank.tank_index} is not published for this aircraft "
                        f"({len(known_tank_indices)} known tanks)."
                    )
            tanks = list(request.loadout.tanks)
            notes.append("Tanks set from a manual overlay.")
        if request.loadout.stations is not None:
            known_station_indices = {station.station_index for station in current.stations}
            for station in request.loadout.stations:
                if station.station_index not in known_station_indices:
                    raise ValueError(
                        f"Station index {station.station_index} is not published for this "
                        f"aircraft ({len(known_station_indices)} known stations)."
                    )
            stations = list(request.loadout.stations)
            notes.append("Stations set from a manual overlay.")

    resolved = LoadoutState(
        tanks=sorted(tanks, key=lambda tank: tank.tank_index),
        stations=sorted(stations, key=lambda station: station.station_index),
    )
    result = compute_mass_and_balance(resolved, limits)
    return resolved, result, tuple(notes)
