"""``ScenarioDocument`` — the validated shape of one scenario YAML file.

Per ``docs/designs/scenario-generator.md`` §4.2 (D3): reuses every other
manager's own request/setup model **verbatim** — nothing scenario-specific is
reinvented, so a typo'd field fails validation exactly as it would over that
manager's own REST endpoint.

``core/``-only: no HTTP, no dataref, no adapter import, no ``SimAdapter``
instance held anywhere near it (D6).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.failures import ArmFailureRequest, InjectFailureRequest
from core.models import AircraftSetup
from core.placements import PlacementRequest
from core.weather.models import WeatherRequest

__all__ = [
    "ScenarioDocument",
    "ScenarioFailuresBlock",
    "ScenarioTrafficBlock",
]


class ScenarioFailuresBlock(BaseModel):
    """Reuses core.failures' own request models verbatim — no re-derivation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    immediate: tuple[InjectFailureRequest, ...] = ()
    armed: tuple[ArmFailureRequest, ...] = ()

    @model_validator(mode="after")
    def _not_empty(self) -> ScenarioFailuresBlock:
        if not self.immediate and not self.armed:
            raise ValueError(
                "A scenario's failures block must list at least one immediate or armed failure."
            )
        return self


class ScenarioTrafficBlock(BaseModel):
    """Declares that this scenario needs traffic. No spawn geometry here — that
    is manager 13's model (Phase 3); this lets a scenario state the need today
    and be greyed out honestly until the capability exists anywhere."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: str = Field(min_length=1)


class ScenarioDocument(BaseModel):
    """The validated shape of one scenario YAML file. core/-only: no HTTP, no
    dataref, no adapter import, no SimAdapter instance held anywhere near it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: tuple[str, ...] = ()

    position: PlacementRequest | None = None
    aircraft_state: AircraftSetup | None = None
    weather: WeatherRequest | None = None
    failures: ScenarioFailuresBlock | None = None
    traffic: ScenarioTrafficBlock | None = None

    @model_validator(mode="after")
    def _at_least_one_block(self) -> ScenarioDocument:
        if not any((self.position, self.aircraft_state, self.weather, self.failures, self.traffic)):
            raise ValueError(
                "A scenario must declare at least one of: position, aircraft_state, "
                "weather, failures, traffic."
            )
        return self
