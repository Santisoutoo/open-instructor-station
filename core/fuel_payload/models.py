"""The instructor-facing fuel/payload vocabulary: presets, request, result.

Lives beside ``core/models.py``'s ``Loadout``/``LoadoutState`` (docs/designs/
fuel-payload.md §3.1) rather than importing them the other way round, for the
same reason ``Ils`` lives beside ``Runway``: ``AircraftSetup`` needs
``Loadout`` directly.

Everything here is frozen (the Weather/Failures convention, D of
fuel-payload.md §3): a resolved preset or request is a fact about one moment,
never mutated in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import Loadout

__all__ = [
    "FUEL_PAYLOAD_PRESETS",
    "FuelPayloadPreset",
    "FuelPayloadPresetId",
    "FuelPayloadRequest",
    "MassAndBalanceResult",
]

#: The four presets the feature spec names. A closed union so an unknown
#: preset id is refused by FastAPI's own request validation (docs/designs/
#: fuel-payload.md §2.2) rather than reaching core/ at all.
FuelPayloadPresetId = Literal["ferry", "training", "full", "empty"]


class FuelPayloadPreset(BaseModel):
    """One preset: two capacity fractions, applied uniformly (D9).

    Phase 2 does not model named seats, crew or a loading order between
    stations — ``fuel_fraction``/``station_fraction`` apply to *every* known
    tank/station alike, which is why a preset can resolve outside the
    envelope (the ``full`` preset, §7.1) and is validated exactly like any
    other loadout rather than being exempt.
    """

    model_config = ConfigDict(frozen=True)

    id: FuelPayloadPresetId
    label: str
    description: str
    fuel_fraction: float = Field(
        ge=0.0, le=1.0, description="Fraction of each tank's known capacity."
    )
    station_fraction: float = Field(
        ge=0.0, le=1.0, description="Fraction of each station's known capacity."
    )


#: The preset catalogue — pure data (docs/designs/fuel-payload.md §4).
#:
#: ``empty`` is ramp weight, nobody aboard. ``ferry`` is the classic
#: max-range, min-weight configuration: full tanks, no payload. ``training``
#: is a light, safe, middle-of-the-envelope loadout for a normal lesson.
#: ``full`` is deliberately "everything to its stated maximum" and is *not*
#: guaranteed to resolve inside the envelope (§7.1's worked table) — that is
#: the disclosed point of it, not a bug.
FUEL_PAYLOAD_PRESETS: Mapping[FuelPayloadPresetId, FuelPayloadPreset] = MappingProxyType(
    {
        "empty": FuelPayloadPreset(
            id="empty",
            label="Empty",
            description="Ramp weight — no fuel, no payload.",
            fuel_fraction=0.0,
            station_fraction=0.0,
        ),
        "training": FuelPayloadPreset(
            id="training",
            label="Training",
            description="A light, middle-of-the-envelope loadout for a normal lesson.",
            fuel_fraction=0.5,
            station_fraction=0.10,
        ),
        "ferry": FuelPayloadPreset(
            id="ferry",
            label="Ferry",
            description="Full tanks, no payload — maximum range, minimum weight.",
            fuel_fraction=1.0,
            station_fraction=0.0,
        ),
        "full": FuelPayloadPreset(
            id="full",
            label="Full",
            description=(
                "Every tank and every station filled to its stated maximum. Not "
                "guaranteed to resolve inside the CG envelope — that is disclosed, "
                "not hidden."
            ),
            fuel_fraction=1.0,
            station_fraction=1.0,
        ),
    }
)


class FuelPayloadRequest(BaseModel):
    """One fuel/payload instruction: a preset, a manual loadout, or both.

    Lives in ``core/`` (D12), not the router — the Scenario Generator's YAML
    fuel/payload block validates against this exact model, same as
    ``core.weather.models.WeatherRequest`` and ``core.failures.ArmFailureRequest``.

    ``loadout`` is an overlay: when both ``preset`` and ``loadout`` are given,
    the preset resolves first and ``loadout`` is applied on top, list by list
    (``core.models.Loadout``'s own "None untouched / list replaces the whole
    set" semantics — D10).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    preset: FuelPayloadPresetId | None = None
    loadout: Loadout | None = None
    override_envelope: bool = Field(
        default=False,
        description="Ignored by preview; enforced by apply (D8). An explicit, named opt-in "
        "past a verifiably out-of-envelope loadout, never the default.",
    )

    @model_validator(mode="after")
    def _preset_or_loadout(self) -> FuelPayloadRequest:
        if self.preset is None and self.loadout is None:
            raise ValueError("A fuel/payload request must carry a preset, a loadout, or both.")
        return self


class MassAndBalanceResult(BaseModel):
    """The computed mass-and-balance verdict for one loadout.

    ``limits_source`` and ``within_envelope`` are how D7 is expressed:
    ``within_envelope`` is ``None`` (never ``False``) exactly when
    ``limits_source == "unknown"`` — "unverifiable" is disclosed, never
    invented as either a pass or a fail.
    """

    model_config = ConfigDict(frozen=True)

    gross_weight_kg: float
    fuel_kg: float
    payload_kg: float
    cg_arm_in: float | None = Field(default=None, description="None when limits are unknown.")
    limits_source: Literal["adapter", "table", "unknown"]
    within_envelope: bool | None = Field(
        default=None, description="None only when limits_source == 'unknown'."
    )
    violations: tuple[str, ...] = Field(
        default=(), description="Human sentences. Empty unless within_envelope is False."
    )
