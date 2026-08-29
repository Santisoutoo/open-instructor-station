"""The mass/CG limits fallback table, and its resolver.

Generalises the same "the airframe arrives as an input" philosophy as
``core.geodesy.APPROACH_CATEGORY_VAT_KT`` to authored per-type mass-and-balance
constants (D6): an adapter that cannot supply
:class:`~core.models.AirframeMassLimits` is not a dead end, because this table
plausibly can, keyed by ICAO type.

Per §6.2 of the design, the X-Plane adapter is expected, in practice, to
report ``mass_limits=None`` for most or all installs in Phase 2 — this table's
fallback is therefore expected to be the *primary* path, not a rare one.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.models import AirframeInfo, AirframeMassLimits, CgEnvelope, CgEnvelopePoint

__all__ = [
    "AIRCRAFT_MASS_LIMITS_TABLE",
    "AircraftMassLimitsEntry",
    "ResolvedMassLimits",
    "resolve_mass_limits",
]


class AircraftMassLimitsEntry(BaseModel):
    """One table entry: the limits themselves, plus the disclaimer the UI shows verbatim."""

    model_config = ConfigDict(frozen=True)

    icao_type: str
    limits: AirframeMassLimits
    source_note: str


#: Illustrative, hand-authored mass/CG limits for common trainer types this
#: station has no other way to learn (D6). Every entry carries a
#: ``source_note`` disclaimer because these are illustrative POH-derived
#: numbers, not certified data — the manifest surfaces it verbatim.
#:
#: The C172 entry's exact numbers are the §7.1 worked-table fixture: the four
#: presets' resolved gross weight, CG arm and envelope verdict are computed by
#: hand from these values in the design and pinned exactly by the test suite.
AIRCRAFT_MASS_LIMITS_TABLE: Mapping[str, AircraftMassLimitsEntry] = MappingProxyType(
    {
        "C172": AircraftMassLimitsEntry(
            icao_type="C172",
            limits=AirframeMassLimits(
                empty_weight_kg=743.0,
                empty_cg_arm_in=39.0,
                max_takeoff_weight_kg=1157.0,
                max_zero_fuel_weight_kg=None,
                max_fuel_kg=152.0,
                fuel_tank_capacities_kg=(76.0, 76.0),
                fuel_tank_arms_in=(48.0, 48.0),
                payload_station_capacities_kg=(85.0, 85.0, 45.0),
                payload_station_arms_in=(37.0, 73.0, 95.0),
                cg_envelope=CgEnvelope(
                    points=(
                        CgEnvelopePoint(weight_kg=700.0, fwd_limit_in=34.0, aft_limit_in=41.0),
                        CgEnvelopePoint(weight_kg=1000.0, fwd_limit_in=35.0, aft_limit_in=40.5),
                        CgEnvelopePoint(weight_kg=1157.0, fwd_limit_in=35.5, aft_limit_in=40.0),
                    )
                ),
            ),
            source_note=(
                "Illustrative C172S figures — verify against your aircraft's POH before a "
                "lesson depends on them."
            ),
        ),
    }
)


class ResolvedMassLimits(BaseModel):
    """The mass/CG limits this request will be validated against, and where they came from."""

    model_config = ConfigDict(frozen=True)

    limits: AirframeMassLimits
    source: Literal["adapter", "table"]


def resolve_mass_limits(airframe: AirframeInfo) -> ResolvedMassLimits | None:
    """The limits to validate a loadout against, and their provenance.

    Prefers the adapter's own numbers, falls back to :data:`AIRCRAFT_MASS_LIMITS_TABLE`
    keyed by ``airframe.icao_type``, and returns ``None`` — "unverifiable," never
    invented — when neither knows (D6). Pure, no I/O.
    """
    if airframe.mass_limits is not None:
        return ResolvedMassLimits(limits=airframe.mass_limits, source="adapter")
    if airframe.icao_type is not None:
        entry = AIRCRAFT_MASS_LIMITS_TABLE.get(airframe.icao_type)
        if entry is not None:
            return ResolvedMassLimits(limits=entry.limits, source="table")
    return None
